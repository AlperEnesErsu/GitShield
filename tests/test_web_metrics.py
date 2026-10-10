import asyncio
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fastapi")

from gitshield.web.db import Database
from gitshield.web.metrics import build_metrics, gitshield_metrics, percentile

NOW = datetime.now(UTC)


@pytest.fixture()
def open_db():
    """Open databases for a test and close them afterwards, so no SQLite connection leaks."""
    opened = []

    def factory(path):
        opened.append(Database(path))
        return opened[-1]

    yield factory
    for database in opened:
        database.close()


def iso(delta_hours: float) -> str:
    return (NOW - timedelta(hours=delta_hours)).isoformat().replace("+00:00", "Z")


class MetricsGitHub:
    async def list_repos(self, refresh=False):
        return {"repos": [
            {"nameWithOwner": "acme/app", "isArchived": False, "pushedAt": iso(5), "pullRequests": {"totalCount": 2}},
            {"nameWithOwner": "acme/old", "isArchived": True, "pushedAt": iso(5), "pullRequests": {"totalCount": 1}},
        ]}

    async def merged_pulls(self, owner, repo):
        assert repo == "app", "archived repos are skipped"
        return [
            {"number": 1, "title": "a", "createdAt": iso(50), "mergedAt": iso(40), "author": {"login": "x"}},
            {"number": 2, "title": "b", "createdAt": iso(30), "mergedAt": iso(10), "author": {"login": "x"}},
            {"number": 3, "title": "old", "createdAt": iso(24 * 90), "mergedAt": iso(24 * 80), "author": {"login": "x"}},
        ]

    async def list_pulls(self, owner, repo, state="open"):
        def pr(n, age_h, draft=False):
            return {"number": n, "title": f"PR {n}", "draft": draft, "user": {"login": "dev"},
                    "created_at": iso(age_h), "updated_at": iso(1)}
        return [pr(4, 24 * 5), pr(5, 2), pr(6, 24 * 30, draft=True)]


def test_build_metrics(tmp_path, open_db):
    db = open_db(tmp_path / "t.db")
    m = asyncio.run(build_metrics(db, MetricsGitHub(), days=30, sla_days=3))

    assert m["repos_checked"] == 1
    assert m["merge"]["count"] == 2, "merges older than the window are excluded"
    assert m["merge"]["median_hours"] == 15.0  # 10h and 20h
    assert m["open"]["count"] == 2, "draft PRs do not count as waiting"
    assert [r["number"] for r in m["open"]["over_sla"]] == [4]
    assert {b["label"]: b["count"] for b in m["open"]["buckets"]}["3–7 gün"] == 1


def test_gitshield_latencies():
    def step(key, start_min, end_min):
        return {"key": key, "started_at": (NOW + timedelta(minutes=start_min)).isoformat(),
                "finished_at": (NOW + timedelta(minutes=end_min)).isoformat() if end_min is not None else None}
    reviews = [
        {"status": "submitted", "created_at": NOW.isoformat(),
         "progress": [step("fetch", 0, 0.1), step("verify", 0.5, 1), step("approve", 1, 31)]},
        {"status": "ready", "created_at": NOW.isoformat(),
         "progress": [step("fetch", 0, 0.1), step("verify", 1, 2), step("approve", 2, None)]},
    ]
    g = gitshield_metrics(reviews)
    assert g["median_ai_seconds"] == 90.0 and g["median_approval_minutes"] == 30.0
    assert g["awaiting"] == 1 and g["weekly"][0]["reviews"] == 2


def test_percentile():
    assert percentile([1, 2, 3, 4], 0.75) == 3.25
    assert percentile([], 0.5) is None

class PullWithoutTimestampGitHub(MetricsGitHub):
    async def list_pulls(self, owner, repo, state="open"):
        pulls = await super().list_pulls(owner, repo, state)
        pulls[0]["created_at"] = None  # seen in the wild for some API responses
        return pulls


def test_open_pull_without_a_timestamp_is_skipped(tmp_path, open_db):
    db = open_db(tmp_path / "t.db")
    m = asyncio.run(build_metrics(db, PullWithoutTimestampGitHub(), days=30, sla_days=3))
    assert m["open"]["count"] == 1, "the PR with a usable timestamp still counts"
