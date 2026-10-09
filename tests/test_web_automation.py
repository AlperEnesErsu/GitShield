import asyncio
import copy

import pytest

pytest.importorskip("fastapi")

from gitshield.web import automation
from gitshield.web.automation import AutoReviewer, build_inbox, classify
from gitshield.web.db import Database
from tests.test_web_review import FILES, PR


def make_pull(number, sha, draft=False):
    p = copy.deepcopy(PR)
    p.update({
        "number": number, "title": f"PR {number}", "draft": draft,
        "user": {"login": "dev", "avatar_url": "https://example.com/a.png"},
        "created_at": "2026-10-01T00:00:00Z", "updated_at": f"2026-10-0{number}T00:00:00Z",
    })
    p["head"]["sha"] = sha
    return p


class InboxGitHub:
    def __init__(self, pulls):
        self.pulls = pulls
        self.reviews = []

    async def list_repos(self, refresh=False):
        return {"login": "me", "repos": [
            {"nameWithOwner": "acme/app", "isArchived": False, "pullRequests": {"totalCount": len(self.pulls)}},
            {"nameWithOwner": "acme/quiet", "isArchived": False, "pullRequests": {"totalCount": 0}},
        ]}

    async def list_pulls(self, owner, repo, state="open"):
        assert repo == "app", "repos without open PRs must not be queried"
        return self.pulls

    async def get_pull(self, owner, repo, number):
        return next(p for p in self.pulls if p["number"] == number)

    async def list_pull_files(self, owner, repo, number):
        return FILES

    async def open_pulls_detail(self, owner, repo):
        return {}


def test_classify_states():
    p = make_pull(1, "new-sha")
    assert classify(p, None) == "new"
    assert classify(p, {"status": "running", "head_sha": "x"}) == "running"
    assert classify(p, {"status": "ready", "head_sha": "old-sha"}) == "outdated"
    assert classify(p, {"status": "ready", "head_sha": "new-sha"}) == "approve"
    assert classify(p, {"status": "submitted", "head_sha": "new-sha"}) == "done"


def test_inbox_orders_by_urgency(tmp_path):
    db = Database(tmp_path / "t.db")
    pulls = [make_pull(1, "a"), make_pull(2, "b"), make_pull(3, "c")]
    ready = db.create_review("acme/app", 2, "PR 2", "b", "none", "")
    db.update_review(ready, status="ready")
    done = db.create_review("acme/app", 3, "PR 3", "c", "none", "")
    db.update_review(done, status="submitted")
    db.add_draft_issue("acme/app", ready, None, "fp", "[HIGH] x", "body", "HIGH")

    inbox = asyncio.run(build_inbox(db, InboxGitHub(pulls)))

    kinds = [(i["kind"], i.get("pr_number")) for i in inbox["items"]]
    assert kinds == [("approve", 2), ("new", 1), ("drafts", None)]
    assert inbox["actionable"] == 3 and inbox["repos_checked"] == 1


def test_auto_reviewer_reviews_each_head_once(tmp_path, monkeypatch):
    monkeypatch.setattr(automation, "get_provider", lambda: None)
    db = Database(tmp_path / "t.db")
    gh = InboxGitHub([make_pull(1, "a"), make_pull(2, "b", draft=True)])
    watcher = AutoReviewer(db, gh, interval_sec=60)

    assert asyncio.run(watcher.tick()) == 0, "repo is not opted in yet"

    db.set_repo_settings("acme/app", auto_review=True)
    assert asyncio.run(watcher.tick()) == 1, "draft PRs are skipped by default"
    assert db.latest_reviews("acme/app")[1]["status"] == "ready"
    assert asyncio.run(watcher.tick()) == 0, "same head commit must not be re-reviewed"

    gh.pulls[0]["head"]["sha"] = "a2"  # new commit pushed
    db.set_repo_settings("acme/app", include_drafts=True)
    assert asyncio.run(watcher.tick()) == 2
    assert watcher.last_error is None
