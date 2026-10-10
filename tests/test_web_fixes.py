import asyncio
import copy

import pytest

pytest.importorskip("fastapi")

from gitshield.web.db import Database
from gitshield.web.fixes import FixError, FixOutput, apply_edit, create_fix_pr, preview_fix
from tests.test_web_review import PR

FILE = "import os\nAPI_KEY = 'x'\nquery = 'SELECT * FROM users WHERE id = ' + user_id\nprint('done')\n"


class FixGitHub:
    def __init__(self, fork=False):
        self.pr = copy.deepcopy(PR)
        self.pr["head"].update({"ref": "feature/config", "repo": {"full_name": "dev/app" if fork else "acme/app",
                                                                  "html_url": "https://github.com/acme/app"}})
        self.pr["base"]["repo"]["full_name"] = "acme/app"
        self.calls = []

    async def get_pull(self, owner, repo, number):
        return self.pr

    async def get_file(self, owner, repo, path, ref):
        self.calls.append(("get_file", path, ref))
        return {"text": FILE, "sha": "blob1"}

    async def create_branch(self, owner, repo, branch, sha):
        self.calls.append(("branch", branch, sha))

    async def update_file(self, owner, repo, path, branch, text, blob_sha, message):
        self.calls.append(("update", path, branch, text, blob_sha))
        return {}

    async def create_pull(self, owner, repo, title, head, base, body):
        self.calls.append(("pull", head, base))
        return {"html_url": "https://github.com/acme/app/pull/8", "number": 8}


class FixProvider:
    name, model = "fake", "fake-1"

    async def complete(self, system, user, schema):
        assert schema is FixOutput and "<file_excerpt>" in user
        return FixOutput(start_line=3, end_line=3, explanation="Parametreli sorgu.",
                         replacement="query = db.execute('SELECT * FROM users WHERE id = ?', [user_id])")


def _comment(db):
    rid = db.create_review("acme/app", 7, "t", "abc123", "fake", "fake-1")
    cid = db.add_comment(rid, source="llm", path="app/config.py", line=3, in_diff=True, severity="HIGH",
                         category="security", title="SQL injection", body="Use parameters.", suggestion=None,
                         rule_id=None, verification="confirmed", verification_note="", included=True)
    return db.get_comment(cid)


def test_apply_edit_keeps_crlf_and_validates_range():
    assert apply_edit("a\r\nb\r\nc", 2, 2, "B1\nB2") == "a\r\nB1\r\nB2\r\nc"
    with pytest.raises(FixError):
        apply_edit("a\nb", 2, 5, "x")


def test_preview_then_create_fix_pr(tmp_path):
    db = Database(tmp_path / "t.db")
    gh = FixGitHub()
    comment = _comment(db)

    preview = asyncio.run(preview_fix(db, gh, FixProvider(), comment))
    assert preview["can_push"] and preview["changed"]
    assert "-query = 'SELECT * FROM users WHERE id = ' + user_id" in preview["diff"]
    assert gh.calls == [("get_file", "app/config.py", "abc123")], "preview must not write anything"

    result = asyncio.run(create_fix_pr(db, gh, comment, preview["start_line"], preview["end_line"],
                                       preview["replacement"]))
    kinds = [c[0] for c in gh.calls]
    assert kinds == ["get_file", "get_file", "branch", "update", "pull"]
    branch_call = gh.calls[2]
    assert branch_call[1] == f"gitshield/fix-7-{comment['id']}" and branch_call[2] == "abc123"
    assert gh.calls[4] == ("pull", branch_call[1], "feature/config"), "fix PR targets the reviewed branch"
    assert "db.execute" in gh.calls[3][3] and gh.calls[3][4] == "blob1"
    assert db.get_comment(comment["id"])["fix_pr_url"] == result["url"]


def test_fork_prs_cannot_get_fix_branches(tmp_path):
    db = Database(tmp_path / "t.db")
    gh = FixGitHub(fork=True)
    comment = _comment(db)
    preview = asyncio.run(preview_fix(db, gh, FixProvider(), comment))
    assert not preview["can_push"] and "fork" in preview["reason"]
    with pytest.raises(FixError):
        asyncio.run(create_fix_pr(db, gh, comment, 3, 3, "x"))
    assert not any(c[0] in ("branch", "update", "pull") for c in gh.calls)


@pytest.mark.parametrize("path", ["../../user", "/etc/passwd", "a/../b", "a//b", "a\\b", "a?x=1", "a#b", "a%2e%2e/b", ""])
def test_unsafe_paths_are_refused(tmp_path, path):
    from gitshield.web.fixes import safe_repo_path

    with pytest.raises(FixError):
        safe_repo_path(path)


def test_hostile_comment_path_never_reaches_github(tmp_path):
    db = Database(tmp_path / "t.db")
    gh = FixGitHub()
    comment = _comment(db)
    comment["path"] = "../../../user/repos"
    with pytest.raises(FixError):
        asyncio.run(preview_fix(db, gh, FixProvider(), comment))
    with pytest.raises(FixError):
        asyncio.run(create_fix_pr(db, gh, comment, 3, 3, "x"))
    assert not any(c[0] in ("get_file", "branch", "update", "pull") for c in gh.calls)
