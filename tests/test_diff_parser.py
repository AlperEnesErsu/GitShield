import subprocess
from pathlib import Path

import pytest

from gitshield.core.diff_parser import (
    GitDiffError,
    get_git_diff,
    parse_unified_diff,
    unquote_git_path,
)

SAMPLE_DIFF = """diff --git a/app/main.py b/app/main.py
index e69de29..d95f3ad 100644
--- a/app/main.py
+++ b/app/main.py
@@ -1,3 +1,5 @@
 import os
+AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
+cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
 def run():
     pass
"""


def test_parse_unified_diff():
    hunks = parse_unified_diff(SAMPLE_DIFF)
    assert len(hunks) == 1
    hunk = hunks[0]
    assert hunk.file_path == "app/main.py"
    assert len(hunk.lines) == 2
    assert hunk.lines[0].line_number == 2
    assert "AKIAIOSFODNN7EXAMPLE" in hunk.lines[0].content
    assert hunk.lines[1].line_number == 3
    assert "SELECT * FROM users" in hunk.lines[1].content


def test_quoted_non_ascii_path_is_parsed():
    diff = (
        'diff --git "a/src/\\303\\274ser.py" "b/src/\\303\\274ser.py"\n'
        '--- "a/src/\\303\\274ser.py"\n'
        '+++ "b/src/\\303\\274ser.py"\n'
        "@@ -1 +1,2 @@\n"
        " x = 1\n"
        "+API_KEY = 'AKIAIOSFODNN7EXAMPLE'\n"
    )
    hunks = parse_unified_diff(diff)
    assert len(hunks) == 1
    assert hunks[0].file_path == "src/üser.py"
    assert hunks[0].lines[0].line_number == 2


def test_unquote_git_path_escapes():
    assert unquote_git_path(r'"a\tb\"c\\d\303\251"') == 'a\tb"c\\dé'
    assert unquote_git_path("plain/path.py") == "plain/path.py"


def test_path_with_spaces_unquoted():
    diff = (
        "diff --git a/my dir/my file.py b/my dir/my file.py\n"
        "--- a/my dir/my file.py\n"
        "+++ b/my dir/my file.py\n"
        "@@ -0,0 +1 @@\n"
        "+token = 'x'\n"
    )
    hunks = parse_unified_diff(diff)
    assert hunks[0].file_path == "my dir/my file.py"
    assert hunks[0].lines[0].content == "token = 'x'"


def test_added_line_starting_with_plus_plus_keeps_line_numbers():
    diff = (
        "diff --git a/a.c b/a.c\n"
        "--- a/a.c\n"
        "+++ b/a.c\n"
        "@@ -2,2 +1,5 @@\n"
        " int x;\n"
        "+++i;\n"
        "+--j;\n"
        " int y;\n"
        "+AWS = 'AKIAIOSFODNN7EXAMPLE'\n"
    )
    lines = parse_unified_diff(diff)[0].lines
    assert [(dl.line_number, dl.content) for dl in lines] == [
        (2, "++i;"),
        (3, "--j;"),
        (5, "AWS = 'AKIAIOSFODNN7EXAMPLE'"),
    ]


def test_no_newline_marker_does_not_shift_lines():
    diff = (
        "diff --git a/b.txt b/b.txt\n"
        "--- a/b.txt\n"
        "+++ b/b.txt\n"
        "@@ -1 +1,2 @@\n"
        "-old\n"
        "\\ No newline at end of file\n"
        "+new\n"
        "+second\n"
        "\\ No newline at end of file\n"
        "diff --git a/c.txt b/c.txt\n"
        "--- a/c.txt\n"
        "+++ b/c.txt\n"
        "@@ -0,0 +1 @@\n"
        "+third\n"
    )
    hunks = parse_unified_diff(diff)
    assert [(dl.file_path, dl.line_number, dl.content) for h in hunks for dl in h.lines] == [
        ("b.txt", 1, "new"),
        ("b.txt", 2, "second"),
        ("c.txt", 1, "third"),
    ]


def test_deleted_file_yields_no_added_lines():
    diff = (
        "diff --git a/gone.py b/gone.py\n"
        "deleted file mode 100644\n"
        "--- a/gone.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-SECRET = 'AKIAIOSFODNN7EXAMPLE'\n"
        "-print(1)\n"
        "diff --git a/next.py b/next.py\n"
        "--- a/next.py\n"
        "+++ b/next.py\n"
        "@@ -0,0 +1 @@\n"
        "+ok = 1\n"
    )
    hunks = parse_unified_diff(diff)
    added = [(dl.file_path, dl.content) for h in hunks for dl in h.lines]
    assert added == [("next.py", "ok = 1")]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


def _init_repo(path: Path) -> Path:
    _git(path, "init", "-q")
    (path / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(path, "add", "app.py")
    _git(path, "commit", "-q", "-m", "init")
    return path


def test_get_git_diff_raises_on_bad_ref(tmp_path):
    repo = _init_repo(tmp_path)
    with pytest.raises(GitDiffError):
        get_git_diff(repo_path=repo, branch_or_commit="no-such-ref")


def test_get_git_diff_raises_outside_repo(tmp_path):
    with pytest.raises(GitDiffError):
        get_git_diff(repo_path=tmp_path)


def test_get_git_diff_includes_untracked_files(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "secrets.env").write_text("KEY=abc\n", encoding="utf-8")
    raw = get_git_diff(repo_path=repo)
    hunks = parse_unified_diff(raw)
    assert [(h.file_path, dl.content) for h in hunks for dl in h.lines] == [("secrets.env", "KEY=abc")]

    raw_no_untracked = get_git_diff(repo_path=repo, include_untracked=False)
    assert parse_unified_diff(raw_no_untracked) == []


def test_get_git_diff_repo_without_commits(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "first.py").write_text("print('hi')\n", encoding="utf-8")
    raw = get_git_diff(repo_path=tmp_path)
    assert [dl.content for h in parse_unified_diff(raw) for dl in h.lines] == ["print('hi')"]
