import asyncio
import copy

import pytest

pytest.importorskip("fastapi")

from gitshield.web.automation import approve_dependency_batch
from gitshield.web.db import Database
from gitshield.web.insights import change_type, compute_risk, parse_dependency_update, pr_ci_state
from tests.test_web_review import PR

LOCK_PATCH = "@@ -1,2 +1,2 @@\n-  version: 1.0.9\n+  version: 1.0.10\n"


def node(number, title, files, ci="SUCCESS", author="dependabot[bot]", assoc="NONE", adds=1, dels=1):
    return {
        "number": number, "title": title, "additions": adds, "deletions": dels,
        "changedFiles": len(files), "authorAssociation": assoc, "author": {"login": author},
        "files": {"nodes": [{"path": f, "additions": adds, "deletions": dels} for f in files]},
        "commits": {"nodes": [{"commit": {"oid": "x", "statusCheckRollup": {"state": ci} if ci else None}}]},
    }


@pytest.mark.parametrize("old,new,expected", [
    ("1.0.9", "2.0.0", "major"), ("4.1.10", "4.2.0", "minor"), ("6.9.1", "6.9.2", "patch"),
    ("0.3.1", "0.4.0", "major"), ("v1", "v3", "major"), ("abc", "def", "unknown"),
])
def test_change_type(old, new, expected):
    assert change_type(old, new) == expected


def test_parse_dependency_update():
    dep = parse_dependency_update("chore(deps): bump cupertino_icons from 1.0.9 to 2.0.0", "dependabot[bot]")
    assert dep["package"] == "cupertino_icons" and dep["change"] == "major"
    group = parse_dependency_update("chore(deps): bump the pub-minor-patch group with 2 updates", "dependabot[bot]")
    assert group["group"] and group["change"] == "minor"
    assert parse_dependency_update("feat: add login screen", "alice") is None


def test_risk_explains_its_score():
    risky = node(1, "feat: auth refactor", ["src/auth/session.py", ".github/workflows/ci.yml"],
                 ci="FAILURE", author="newbie", assoc="FIRST_TIME_CONTRIBUTOR", adds=300, dels=50)
    r = compute_risk(risky)
    labels = " | ".join(f["label"] for f in r["factors"])
    assert r["level"] == "high" and r["score"] == min(100, sum(f["points"] for f in r["factors"]))
    for expected in ("Kimlik doğrulama", "CI/CD", "CI başarısız", "yeni katkı", "test eklenmemiş"):
        assert expected in labels

    lock_only = compute_risk(node(2, "chore: bump x from 1.0.0 to 1.0.1", ["package-lock.json"], adds=900))
    assert lock_only["level"] == "low", "lockfile churn alone must not look risky"


def test_ci_state_mapping():
    assert pr_ci_state(node(1, "t", [], ci="SUCCESS")) == "success"
    assert pr_ci_state(node(1, "t", [], ci="ERROR")) == "failure"
    assert pr_ci_state(node(1, "t", [], ci=None)) == "none"


class BatchGitHub:
    def __init__(self):
        self.nodes = {
            10: node(10, "chore(deps): bump lodash from 4.17.20 to 4.17.21", ["package.json"]),
            11: node(11, "chore(deps): bump react from 18.3.1 to 19.0.0", ["package.json"]),
            12: node(12, "chore(deps): bump vite from 5.4.0 to 5.4.11", ["package.json"], ci="FAILURE"),
            13: node(13, "feat: new screen", ["src/app.ts"], author="alice", assoc="MEMBER"),
        }
        self.submitted = []

    async def open_pulls_detail(self, owner, repo):
        return self.nodes

    async def get_pull(self, owner, repo, number):
        p = copy.deepcopy(PR)
        p.update({"number": number, "title": self.nodes[number]["title"]})
        return p

    async def list_pull_files(self, owner, repo, number):
        return [{"filename": "package.json", "status": "modified", "patch": LOCK_PATCH}]

    async def create_review(self, owner, repo, number, commit_id, body, event, comments):
        self.submitted.append((number, event))
        return {"html_url": f"https://github.com/acme/app/pull/{number}#review"}


def test_dependency_batch_enforces_guards(tmp_path):
    db = Database(tmp_path / "t.db")
    gh = BatchGitHub()
    results = asyncio.run(approve_dependency_batch(db, gh, "acme", "app", [10, 11, 12, 13, 99]))
    by_number = {r["number"]: r for r in results}

    assert by_number[10]["status"] == "approved"
    assert by_number[11]["reason"].startswith("Major")
    assert by_number[12]["reason"] == "CI başarısız"
    assert by_number[13]["reason"] == "Bağımlılık güncellemesi değil"
    assert by_number[99]["reason"] == "PR açık değil"
    assert gh.submitted == [(10, "APPROVE")]
    assert db.get_review(by_number[10]["review_id"])["status"] == "submitted"

    major = asyncio.run(approve_dependency_batch(db, gh, "acme", "app", [11], allow_major=True))
    assert major[0]["status"] == "approved"


def test_ci_failure_weighs_less_when_diagnosis_clears_the_pr():
    failing = node(3, "chore(deps): bump x from 1.0.0 to 1.1.0", ["package.json"], ci="FAILURE")
    blamed = compute_risk(failing)
    cleared = compute_risk(failing, ci_blame="environment")
    assert blamed["score"] - cleared["score"] == 15
    assert any("PR'ın suçu değil" in f["label"] for f in cleared["factors"])
    assert compute_risk(failing, ci_blame="pr")["score"] == blamed["score"]
