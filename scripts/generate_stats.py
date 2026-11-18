#!/usr/bin/env python3
"""Generate a self-hosted Liquid Glass + Terminal Neofetch + 52-Week Work Matrix SVG."""

from __future__ import annotations

import html
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USERNAME = os.environ.get("GITHUB_USER", "Fabian131")
OUTPUT_PATH = Path(os.environ.get("OUTPUT_SVG", "assets/telemetry-glass.svg"))

def build_graphql_query(start_year: int = 2023) -> tuple[str, list[str]]:
    """Build GraphQL query dynamically across all years from start_year to current year."""
    current_year = datetime.now(timezone.utc).year
    year_keys = [f"y{y}" for y in range(start_year, current_year + 1)]
    year_blocks = "\n    ".join(
        f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y}-12-31T23:59:59Z") '
        "{ contributionCalendar { totalContributions } }"
        for y in range(start_year, current_year + 1)
    )
    query = f"""
query($login: String!, $prQuery: String!, $mergedQuery: String!, $reviewQuery: String!) {{
  user(login: $login) {{
    createdAt
    followers {{ totalCount }}
    repositories(first: 100, ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {{
      totalCount
      nodes {{
        stargazerCount
        isPrivate
        languages(first: 8, orderBy: {{field: SIZE, direction: DESC}}) {{
          edges {{
            size
            node {{
              name
              color
            }}
          }}
        }}
      }}
    }}
    contributionsCollection {{
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      restrictedContributionsCount
      contributionCalendar {{
        totalContributions
        weeks {{
          contributionDays {{
            contributionCount
            contributionLevel
            date
          }}
        }}
      }}
    }}
    {year_blocks}
  }}
  allPrs: search(query: $prQuery, type: ISSUE) {{ issueCount }}
  mergedPrs: search(query: $mergedQuery, type: ISSUE) {{ issueCount }}
  reviews: search(query: $reviewQuery, type: ISSUE) {{ issueCount }}
}}
"""
    return query, year_keys


GRAPHQL_QUERY, YEAR_KEYS = build_graphql_query()

IGNORED_LANGUAGES = {"HTML", "CSS", "Shell", "Dockerfile", "Mako", "Hack"}

LANGUAGE_COLOR_FALLBACK = {
    "Java": "#f97316",
    "PHP": "#818cf8",
    "Blade": "#fb7185",
    "JavaScript": "#facc15",
    "TypeScript": "#38bdf8",
    "C#": "#34d399",
    "Kotlin": "#a855f7",
    "Python": "#60a5fa",
    "Go": "#22d3ee",
}

LEVEL_COLORS = {
    "NONE": "#1e293b",
    "FIRST_QUARTILE": "#0e7490",
    "SECOND_QUARTILE": "#06b6d4",
    "THIRD_QUARTILE": "#38bdf8",
    "FOURTH_QUARTILE": "#34d399",
}


def fetch_github_stats(username: str, token: str) -> dict:
    """Fetch live user, PR, and contribution matrix data from GitHub GraphQL API."""
    variables = {
        "login": username,
        "prQuery": f"author:{username} is:pr",
        "mergedQuery": f"author:{username} is:pr is:merged",
        "reviewQuery": f"reviewed-by:{username} is:pr",
    }
    payload = json.dumps({"query": GRAPHQL_QUERY, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"{username}-profile-telemetry",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if "errors" in body:
        raise RuntimeError(f"GraphQL error: {body['errors']}")
    return body["data"]


def compute_metrics(data: dict) -> dict:
    """Aggregate repository, PR, yearly contribution, and 52-week matrix metrics."""
    user = data["user"]
    repos = user["repositories"]["nodes"]
    contrib = user["contributionsCollection"]

    total_stars = sum(repo.get("stargazerCount", 0) for repo in repos)
    repo_count = user["repositories"]["totalCount"]
    followers = user["followers"]["totalCount"]

    contribs_12m = contrib["contributionCalendar"]["totalContributions"]
    public_commits = contrib["totalCommitContributions"]
    private_contribs = contrib["restrictedContributionsCount"]

    yearly_totals = [
        user.get(key, {}).get("contributionCalendar", {}).get("totalContributions", 0)
        for key in YEAR_KEYS
    ]
    all_time_contribs = max(contribs_12m, sum(yearly_totals))

    prs_total = data.get("allPrs", {}).get("issueCount") or contrib["totalPullRequestContributions"]
    prs_merged = data.get("mergedPrs", {}).get("issueCount") or 0
    pr_reviews = data.get("reviews", {}).get("issueCount") or contrib["totalPullRequestReviewContributions"]

    lang_bytes: dict[str, int] = {}
    lang_colors: dict[str, str] = {}
    for repo in repos:
        for edge in repo.get("languages", {}).get("edges", []):
            name = edge["node"]["name"]
            if name in IGNORED_LANGUAGES:
                continue
            size = edge["size"]
            lang_bytes[name] = lang_bytes.get(name, 0) + size
            if name not in lang_colors:
                lang_colors[name] = LANGUAGE_COLOR_FALLBACK.get(
                    name, edge["node"].get("color") or "#38bdf8"
                )

    total_bytes = sum(lang_bytes.values()) or 1
    sorted_langs = sorted(lang_bytes.items(), key=lambda item: item[1], reverse=True)[:6]
    top_languages = [
        {
            "name": name,
            "pct": round((size / total_bytes) * 100, 1),
            "color": lang_colors.get(name, "#38bdf8"),
        }
        for name, size in sorted_langs
    ]

    created_year = int(user["createdAt"][:4])
    current_year = datetime.now(timezone.utc).year
    years_active = max(1, current_year - created_year)

    weeks = contrib["contributionCalendar"].get("weeks", [])[-52:]
    active_days = sum(
        1
        for week in weeks
        for day in week.get("contributionDays", [])
        if day.get("contributionCount", 0) > 0
    )

    return {
        "repo_count": repo_count,
        "total_stars": total_stars,
        "followers": followers,
        "contribs_12m": contribs_12m,
        "all_time_contribs": all_time_contribs,
        "public_commits": public_commits,
        "private_contribs": private_contribs,
        "prs_total": prs_total,
        "prs_merged": prs_merged,
        "pr_reviews": pr_reviews,
        "years_active": years_active,
        "top_languages": top_languages,
        "weeks": weeks,
        "active_days": active_days,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def render_pixel_bar(x: int, y: int, pct: float, color: str, segments: int = 15) -> str:
    """Render a crisp pixel-art segmented progress bar."""
    filled = max(1, round((pct / 100.0) * segments))
    blocks = []
    for idx in range(segments):
        bx = x + idx * 12
        fill = color if idx < filled else "#1e293b"
        opacity = "0.95" if idx < filled else "0.7"
        blocks.append(
            f'<rect x="{bx}" y="{y}" width="9" height="9" rx="1.5" '
            f'fill="{fill}" fill-opacity="{opacity}" />'
        )
    return "\n      ".join(blocks)


def render_work_matrix(weeks: list[dict], ox: int = 56, oy: int = 338) -> str:
    """Render a 52-week × 7-day pixel activity work matrix."""
    cells = []
    cell_size = 11
    step = 15  # 52 * 15 = 780px total width -> fits cleanly inside 812px sub-panel
    for w_idx, week in enumerate(weeks):
        days = week.get("contributionDays", [])
        for d_idx, day in enumerate(days):
            level = day.get("contributionLevel", "NONE")
            color = LEVEL_COLORS.get(level, "#1e293b")
            opacity = "0.55" if level == "NONE" else "0.95"
            cx = ox + w_idx * step
            cy = oy + d_idx * 14
            cells.append(
                f'<rect x="{cx}" y="{cy}" width="{cell_size}" height="{cell_size}" rx="2.5" '
                f'fill="{color}" fill-opacity="{opacity}" />'
            )
    return "\n    ".join(cells)


def build_svg(metrics: dict) -> str:
    """Render the complete Liquid Glass + Neofetch + Work Matrix SVG."""
    lang_rows = []
    for idx, lang in enumerate(metrics["top_languages"]):
        row_y = 104 + idx * 32
        safe_name = html.escape(lang["name"])
        color = html.escape(lang["color"])
        pct = lang["pct"]
        pixel_bar = render_pixel_bar(572, row_y - 9, min(pct * 2.2, 100.0), color)
        lang_rows.append(
            f"""    <g>
      <circle cx="472" cy="{row_y - 4}" r="4.5" fill="{color}" />
      <text x="485" y="{row_y}" class="mono" font-size="12" fill="#e2e8f0" font-weight="600">{safe_name}</text>
      {pixel_bar}
      <text x="822" y="{row_y}" text-anchor="end" class="mono" font-size="11.5" fill="#94a3b8">{pct:.1f}%</text>
    </g>"""
        )

    lang_block = "\n".join(lang_rows)
    matrix_block = render_work_matrix(metrics["weeks"])
    updated_at = html.escape(metrics["updated_at"])

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 468" width="100%" role="img" aria-label="Fabian131 Live Telemetry, Pull Requests &amp; 52-Week Work Matrix">
  <defs>
    <filter id="telemetryBlur" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="34" />
    </filter>
    <linearGradient id="tBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#050814" />
      <stop offset="50%" stop-color="#0a1022" />
      <stop offset="100%" stop-color="#060916" />
    </linearGradient>
    <linearGradient id="tGlass" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.11" />
      <stop offset="50%" stop-color="#ffffff" stop-opacity="0.04" />
      <stop offset="100%" stop-color="#ffffff" stop-opacity="0.02" />
    </linearGradient>
    <linearGradient id="tRim" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.45" />
      <stop offset="50%" stop-color="#ffffff" stop-opacity="0.22" />
      <stop offset="100%" stop-color="#a855f7" stop-opacity="0.45" />
    </linearGradient>
    <linearGradient id="subGlass" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" stop-opacity="0.64" />
      <stop offset="100%" stop-color="#0f172a" stop-opacity="0.40" />
    </linearGradient>
    <pattern id="tGrid" width="24" height="24" patternUnits="userSpaceOnUse">
      <circle cx="2" cy="2" r="0.8" fill="#94a3b8" fill-opacity="0.12" />
    </pattern>
  </defs>

  <style>
    .mono {{ font-family: 'JetBrains Mono', 'Fira Code', 'SFMono-Regular', Consolas, monospace; }}
    .pulse {{ animation: pulse 2.4s ease-in-out infinite; }}
    @keyframes pulse {{
      0%, 100% {{ opacity: 1; }}
      50% {{ opacity: 0.35; }}
    }}
  </style>

  <!-- Canvas -->
  <rect width="880" height="468" rx="24" fill="url(#tBg)" />
  <rect width="880" height="468" rx="24" fill="url(#tGrid)" />

  <!-- Liquid Orbs -->
  <g filter="url(#telemetryBlur)">
    <circle cx="170" cy="230" r="105" fill="#06b6d4" opacity="0.34" />
    <circle cx="710" cy="95" r="100" fill="#a855f7" opacity="0.32" />
    <circle cx="480" cy="390" r="110" fill="#10b981" opacity="0.24" />
  </g>

  <!-- Outer Liquid Glass Container -->
  <rect x="18" y="16" width="844" height="436" rx="20" fill="url(#tGlass)" stroke="url(#tRim)" stroke-width="1.4" />

  <!-- Top-Left Panel: Terminal Neofetch Telemetry -->
  <rect x="34" y="32" width="398" height="256" rx="14" fill="url(#subGlass)" stroke="#ffffff" stroke-opacity="0.14" stroke-width="1" />
  <circle cx="52" cy="50" r="4.5" fill="#ff5f56" />
  <circle cx="67" cy="50" r="4.5" fill="#ffbd2e" />
  <circle cx="82" cy="50" r="4.5" fill="#27c93f" />
  <text x="98" y="54" class="mono" font-size="11.5" fill="#94a3b8">neofetch --github Fabian131</text>
  <line x1="34" y1="68" x2="432" y2="68" stroke="#ffffff" stroke-opacity="0.1" stroke-width="1" />

  <text x="54" y="96" class="mono" font-size="12.2" fill="#38bdf8" font-weight="700">ENGINEER</text>
  <text x="188" y="96" class="mono" font-size="12.2" fill="#f8fafc">Fabian131 (xxTYBUxx)</text>

  <text x="54" y="124" class="mono" font-size="12.2" fill="#34d399" font-weight="700">ALL-TIME</text>
  <text x="188" y="124" class="mono" font-size="12.2" fill="#34d399" font-weight="700">{metrics['all_time_contribs']:,} contribs ({metrics['contribs_12m']:,} / 12m)</text>

  <text x="54" y="152" class="mono" font-size="12.2" fill="#c084fc" font-weight="700">PUB / PRIV</text>
  <text x="188" y="152" class="mono" font-size="12.2" fill="#cbd5e1">{metrics['public_commits']} pub · {metrics['private_contribs']:,} priv (12m)</text>

  <text x="54" y="180" class="mono" font-size="12.2" fill="#facc15" font-weight="700">PULL REQUESTS</text>
  <text x="188" y="180" class="mono" font-size="12.2" fill="#fef08a" font-weight="700">{metrics['prs_total']} authored · {metrics['prs_merged']} merged</text>

  <text x="54" y="208" class="mono" font-size="12.2" fill="#38bdf8" font-weight="700">CODE REVIEWS</text>
  <text x="188" y="208" class="mono" font-size="12.2" fill="#e2e8f0">{metrics['pr_reviews']} PR reviews · {metrics['years_active']}+ yrs</text>

  <text x="54" y="236" class="mono" font-size="12.2" fill="#38bdf8" font-weight="700">REPOSITORIES</text>
  <text x="188" y="236" class="mono" font-size="12.2" fill="#e2e8f0">{metrics['repo_count']} active · {metrics['total_stars']} stars</text>

  <circle class="pulse" cx="58" cy="264" r="3.5" fill="#22c55e" />
  <text x="70" y="268" class="mono" font-size="10.2" fill="#94a3b8">Synced: {updated_at} · Followers: {metrics['followers']}</text>

  <!-- Top-Right Panel: Pixel Language Matrix -->
  <rect x="448" y="32" width="398" height="256" rx="14" fill="url(#subGlass)" stroke="#ffffff" stroke-opacity="0.14" stroke-width="1" />
  <text x="468" y="54" class="mono" font-size="11.5" fill="#7dd3fc" font-weight="700">htop --languages (owned + collab)</text>
  <line x1="448" y1="68" x2="846" y2="68" stroke="#ffffff" stroke-opacity="0.1" stroke-width="1" />

  <g shape-rendering="crispEdges">
{lang_block}
  </g>

  <!-- Bottom Full-Width Panel: 52-Week Contribution Work Matrix -->
  <rect x="34" y="302" width="812" height="136" rx="14" fill="url(#subGlass)" stroke="#ffffff" stroke-opacity="0.14" stroke-width="1" />
  <text x="54" y="324" class="mono" font-size="11.5" fill="#a7f3d0" font-weight="700">
    cal --work-matrix 52w ({metrics['active_days']} active coding days · public + private)
  </text>

  <!-- Matrix Intensity Legend -->
  <text x="698" y="324" class="mono" font-size="10" fill="#94a3b8">Less</text>
  <g shape-rendering="crispEdges">
    <rect x="728" y="315" width="9" height="9" rx="2" fill="#1e293b" fill-opacity="0.55" />
    <rect x="741" y="315" width="9" height="9" rx="2" fill="#0e7490" />
    <rect x="754" y="315" width="9" height="9" rx="2" fill="#06b6d4" />
    <rect x="767" y="315" width="9" height="9" rx="2" fill="#38bdf8" />
    <rect x="780" y="315" width="9" height="9" rx="2" fill="#34d399" />
  </g>
  <text x="796" y="324" class="mono" font-size="10" fill="#94a3b8">More</text>

  <g shape-rendering="crispEdges">
    {matrix_block}
  </g>
</svg>
"""


def main() -> int:
    stats_json_path = os.environ.get("STATS_JSON_PATH")
    if stats_json_path:
        raw = json.loads(Path(stats_json_path).read_text(encoding="utf-8"))
        data = raw["data"]
    else:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            print("Error: set GH_TOKEN, GITHUB_TOKEN, or STATS_JSON_PATH", file=sys.stderr)
            return 1
        data = fetch_github_stats(USERNAME, token)

    metrics = compute_metrics(data)
    svg = build_svg(metrics)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(svg, encoding="utf-8")
    print(
        f"Generated {OUTPUT_PATH} for {USERNAME} "
        f"({metrics['all_time_contribs']} all-time contribs, {metrics['prs_total']} PRs)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
