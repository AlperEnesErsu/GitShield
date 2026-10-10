"""Waiting-time metrics: merge lead time (GitHub), open PR age / SLA, and GitShield's own latencies."""

import asyncio
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

from gitshield.web.db import Database
from gitshield.web.github import GitHubClient, GitHubError

MAX_REPOS = 12
MAX_CONCURRENT = 6


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 2)


def week_start(ts: datetime) -> str:
    monday = (ts - timedelta(days=ts.weekday())).date()
    return monday.isoformat()


def step_seconds(review: dict[str, Any], first: str, last: str, use_finish: bool = True) -> float | None:
    steps = {s["key"]: s for s in review.get("progress") or []}
    start = parse_ts((steps.get(first) or {}).get("started_at"))
    end = parse_ts((steps.get(last) or {}).get("finished_at" if use_finish else "started_at"))
    if not start or not end:
        return None
    return max(0.0, (end - start).total_seconds())


def gitshield_metrics(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    ai = [s for r in reviews if (s := step_seconds(r, "fetch", "verify")) is not None]
    approval = [s / 60 for r in reviews if r["status"] == "submitted"
                and (s := step_seconds(r, "approve", "approve")) is not None]
    weekly: dict[str, int] = {}
    for r in reviews:
        ts = parse_ts(r["created_at"])
        if ts:
            weekly[week_start(ts)] = weekly.get(week_start(ts), 0) + 1
    return {
        "reviews": len(reviews),
        "submitted": sum(1 for r in reviews if r["status"] == "submitted"),
        "failed": sum(1 for r in reviews if r["status"] == "failed"),
        "awaiting": sum(1 for r in reviews if r["status"] == "ready"),
        "median_ai_seconds": median(ai),
        "median_approval_minutes": median(approval),
        "weekly": [{"week": w, "reviews": n} for w, n in sorted(weekly.items())],
    }


async def build_metrics(db: Database, gh: GitHubClient, days: int = 30, sla_days: float = 3) -> dict[str, Any]:
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    repos = (await gh.list_repos())["repos"]
    active = [r for r in repos if not r["isArchived"]
              and ((parse_ts(r["pushedAt"]) or since) >= since or r["pullRequests"]["totalCount"])]
    active.sort(key=lambda r: r["pushedAt"] or "", reverse=True)
    active = active[:MAX_REPOS]
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def load(repo: dict[str, Any]):
        owner, name = repo["nameWithOwner"].split("/", 1)
        async with sem:
            try:
                merged = await gh.merged_pulls(owner, name)
                pulls = await gh.list_pulls(owner, name) if repo["pullRequests"]["totalCount"] else []
                return repo["nameWithOwner"], merged, pulls, None
            except GitHubError as e:
                return repo["nameWithOwner"], [], [], e.message

    results = await asyncio.gather(*(load(r) for r in active))

    lead_hours: list[float] = []
    by_repo = []
    weekly: dict[str, list[float]] = {}
    open_rows = []
    errors = []
    for name, merged, pulls, error in results:
        if error:
            errors.append({"repo": name, "error": error})
        repo_hours = []
        for p in merged:
            created, merged_at = parse_ts(p["createdAt"]), parse_ts(p["mergedAt"])
            if not created or not merged_at or merged_at < since:
                continue
            hours = (merged_at - created).total_seconds() / 3600
            repo_hours.append(hours)
            weekly.setdefault(week_start(merged_at), []).append(hours)
        lead_hours += repo_hours
        if repo_hours:
            by_repo.append({"repo": name, "count": len(repo_hours), "median_hours": median(repo_hours)})
        for p in pulls:
            opened = parse_ts(p["created_at"])
            if p.get("draft") or opened is None:
                continue
            age = (now - opened).total_seconds() / 86400
            open_rows.append({"repo": name, "number": p["number"], "title": p["title"],
                              "author": p["user"]["login"], "age_days": round(age, 1),
                              "updated_at": p["updated_at"]})

    open_rows.sort(key=lambda r: -r["age_days"])
    ages = [r["age_days"] for r in open_rows]
    buckets = [("< 1 gün", 1), ("1–3 gün", 3), ("3–7 gün", 7), ("1–4 hafta", 28), ("4 hafta +", float("inf"))]
    counts = [0] * len(buckets)
    for a in ages:
        counts[next(i for i, (_, limit) in enumerate(buckets) if a <= limit)] += 1

    by_repo.sort(key=lambda r: -(r["median_hours"] or 0))
    return {
        "days": days,
        "sla_days": sla_days,
        "repos_checked": len(active),
        "errors": errors,
        "merge": {
            "count": len(lead_hours),
            "median_hours": median(lead_hours),
            "p75_hours": percentile(lead_hours, 0.75),
            "by_repo": by_repo,
            "weekly": [{"week": w, "merged": len(h), "median_hours": median(h)} for w, h in sorted(weekly.items())],
        },
        "open": {
            "count": len(open_rows),
            "median_age_days": median(ages),
            "over_sla": [r for r in open_rows if r["age_days"] > sla_days],
            "buckets": [{"label": label, "count": n} for (label, _), n in zip(buckets, counts, strict=True)],
        },
        "gitshield": gitshield_metrics(db.reviews_since(since.isoformat(timespec="seconds"))),
    }
