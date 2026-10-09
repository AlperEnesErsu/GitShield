import asyncio
import copy

import pytest

pytest.importorskip("fastapi")

from gitshield.web.db import Database
from gitshield.web.review import map_old_line, run_review, submit_review
from tests.test_web_review import PR, FakeGitHub

# Old file lines 1..10; the new commit deletes line 3, rewrites line 6 and adds a line after 8.
DELTA_PATCH = """@@ -2,3 +2,2 @@
 line2
-line3
 line4
@@ -5,5 +4,6 @@
 line5
-line6
+line6 fixed
 line7
 line8
+inserted
 line9"""


@pytest.mark.parametrize("old,expected", [
    (1, (1, False)),    # before every hunk
    (3, (None, True)),  # deleted
    (4, (3, True)),     # shifted up by the deletion, next to it
    (6, (None, True)),  # rewritten line counts as deleted
    (8, (7, True)),     # insertion right after it
    (10, (10, True)),   # after the last hunk (net offset 0), but the insertion is within 2 lines
    (12, (12, False)),  # far from every change
])
def test_map_old_line(old, expected):
    assert map_old_line(DELTA_PATCH, old) == expected


class IncrementalGitHub(FakeGitHub):
    """PR head moves from abc123 to def456; the new commit fixes the SQL line only."""

    def __init__(self, head="abc123", compare_status="ahead"):
        super().__init__()
        self.head = head
        self.compare_status = compare_status

    async def get_pull(self, owner, repo, number):
        pr = copy.deepcopy(PR)
        pr["head"]["sha"] = self.head
        return pr

    async def compare(self, owner, repo, base, head):
        patch = ("@@ -2,3 +2,3 @@\n API_KEY = \"AKIAIOSFODNN7EXAMPLE\"\n"
                 "-query = \"SELECT * FROM users WHERE id = \" + user_id\n"
                 "+query = db.execute(\"SELECT * FROM users WHERE id = ?\", [user_id])\n print(\"done\")")
        return {"status": self.compare_status, "commits": [{"sha": head}],
                "files": [{"filename": "app/config.py", "status": "modified", "patch": patch}]}


def _review(db, gh):
    rid = db.create_review("acme/app", 7, "Add config", gh.head, "none", "")
    asyncio.run(run_review(db, gh, None, rid, "acme", "app", 7))
    return db.get_review(rid)


def test_incremental_review_tracks_fixes_and_carries_open_comments(tmp_path):
    db = Database(tmp_path / "t.db")
    first = _review(db, IncrementalGitHub("abc123"))
    assert first["mode"] == "full" and first["comments"]
    first_titles = {c["title"] for c in first["comments"]}

    second = _review(db, IncrementalGitHub("def456"))
    assert second["mode"] == "incremental" and second["base_sha"] == "abc123"
    steps = {s["key"]: s["detail"] for s in second["progress"]}
    assert "Artımlı" in steps["fetch"] and "düzeltildi" in steps["verify"]

    statuses = {f["title"]: f["status"] for f in second["followups"]}
    assert set(statuses) == first_titles
    # Line 2 (the AWS key) sits next to the changed line, so it is "unclear" without an LLM,
    # never silently marked fixed.
    assert all(v in ("still_open", "unclear") for v in statuses.values())

    # The first review never reached GitHub, so its open comments are carried over.
    carried = [c for c in second["comments"] if c["source"] == "carried"]
    assert carried and all("taşındı" in c["verification_note"] for c in carried)


def test_diverged_history_falls_back_to_full_review(tmp_path):
    db = Database(tmp_path / "t.db")
    _review(db, IncrementalGitHub("abc123"))
    again = _review(db, IncrementalGitHub("def456", compare_status="diverged"))
    assert again["mode"] == "full" and again["followups"] == []


def test_submission_reports_followups(tmp_path):
    db = Database(tmp_path / "t.db")
    _review(db, IncrementalGitHub("abc123"))
    second = _review(db, IncrementalGitHub("def456"))
    gh = IncrementalGitHub("def456")
    asyncio.run(submit_review(db, gh, second))
    assert "Önceki review'a göre" in gh.reviews[0]["body"]
