"""The signed-in user's own GitHub activity over the last year (contribution calendar)."""

from datetime import date, timedelta
from typing import Any

# The four contribution kinds GitHub breaks down per repository.
KINDS = ("commits", "prs", "reviews", "issues")
MAX_REPOS = 10


def _streaks(days: list[dict[str, Any]]) -> dict[str, int]:
    """Current and longest run of consecutive active days.

    Today still counts as "current" while it is empty: the day is not over yet.
    """
    longest = run = 0
    for d in days:
        run = run + 1 if d["count"] else 0
        longest = max(longest, run)
    current = 0
    tail = days[:-1] if days and not days[-1]["count"] else days
    for d in reversed(tail):
        if not d["count"]:
            break
        current += 1
    return {"current": current, "longest": longest}


def _weeks(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Totals per ISO week (Monday start), including weeks without activity."""
    totals: dict[str, int] = {}
    for d in days:
        day = date.fromisoformat(d["date"])
        monday = (day - timedelta(days=day.weekday())).isoformat()
        totals[monday] = totals.get(monday, 0) + d["count"]
    return [{"week": w, "count": n} for w, n in sorted(totals.items())]


def build_activity(viewer: dict[str, Any]) -> dict[str, Any]:
    """Shape GitHub's ``viewer.contributionsCollection`` for the overview page."""
    c = viewer["contributionsCollection"]
    days = [
        {"date": d["date"], "count": d["contributionCount"]}
        for week in c["contributionCalendar"]["weeks"]
        for d in week["contributionDays"]
    ]

    repos: dict[str, dict[str, Any]] = {}
    sources = {
        "commits": c["commitContributionsByRepository"],
        "prs": c["pullRequestContributionsByRepository"],
        "reviews": c["pullRequestReviewContributionsByRepository"],
        "issues": c["issueContributionsByRepository"],
    }
    for kind, rows in sources.items():
        for row in rows:
            name = row["repository"]["nameWithOwner"]
            entry = repos.setdefault(name, {
                "repo": name, "private": row["repository"]["isPrivate"], **dict.fromkeys(KINDS, 0)})
            entry[kind] += row["contributions"]["totalCount"]
    ranked = sorted(repos.values(), key=lambda r: -sum(r[k] for k in KINDS))

    active = [d for d in days if d["count"]]
    best = max(active, key=lambda d: d["count"], default=None)
    by_weekday = [0] * 7  # Monday first
    for d in days:
        by_weekday[date.fromisoformat(d["date"]).weekday()] += d["count"]

    return {
        "login": viewer["login"],
        "from": days[0]["date"] if days else None,
        "to": days[-1]["date"] if days else None,
        "total": c["contributionCalendar"]["totalContributions"],
        "counts": {
            "commits": c["totalCommitContributions"],
            "prs": c["totalPullRequestContributions"],
            "reviews": c["totalPullRequestReviewContributions"],
            "issues": c["totalIssueContributions"],
            # Counted in the calendar but hidden from this token (e.g. another org's private repo).
            "restricted": c["restrictedContributionsCount"],
        },
        "active_days": len(active),
        "best_day": best,
        "streak": _streaks(days),
        "days": days,
        "weeks": _weeks(days),
        "by_weekday": by_weekday,
        "repos": ranked[:MAX_REPOS],
        "repo_count": len(ranked),
    }
