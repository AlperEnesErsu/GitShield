import re
import subprocess
from pathlib import Path

from gitshield.core.models import DiffHunk, DiffLine

HUNK_HEADER_PATTERN = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
OCTAL_ESCAPE = re.compile(r"\\([0-3][0-7]{2})")
SIMPLE_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
MAX_UNTRACKED_BYTES = 1_000_000


class GitDiffError(RuntimeError):
    """Raised when git cannot produce a diff (bad ref, not a repo, git missing)."""


def _git(cwd: Path, args: list[str], ok_codes: tuple = (0,)) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as e:
        raise GitDiffError(f"Failed to execute git: {e}") from e
    if result.returncode not in ok_codes:
        raise GitDiffError(result.stderr.strip() or f"git {args[0]} exited with {result.returncode}")
    return result


def get_git_diff(
    repo_path: Path,
    staged: bool = False,
    branch_or_commit: str | None = None,
    include_untracked: bool = True,
    all_files: bool = False,
) -> str:
    """Retrieve raw unified git diff from the local repository.

    Raises GitDiffError when git fails. In default working-tree mode, untracked
    (non-ignored) files are appended as all-added diffs when include_untracked is set.
    all_files diffs the working tree against the empty tree, so every tracked line counts as added.
    """
    cmd = ["diff", "--no-color", "-U3"]

    if all_files:
        cmd.append(EMPTY_TREE)
    elif branch_or_commit:
        # --end-of-options stops a ref like "--output=x" from being read as a git option
        cmd += ["--end-of-options", branch_or_commit]
    elif staged:
        cmd.append("--cached")
    else:
        # Default: compare HEAD, or the empty tree when the repo has no commits yet
        has_head = _git(repo_path, ["rev-parse", "--verify", "-q", "HEAD"], ok_codes=(0, 1))
        cmd.append("HEAD" if has_head.returncode == 0 else EMPTY_TREE)

    out = _git(repo_path, cmd).stdout
    if include_untracked and not staged and not branch_or_commit:
        out += _untracked_diff(repo_path)
    return out


def _untracked_diff(repo_path: Path) -> str:
    """Build all-added diffs for untracked, non-ignored files, relative to the repo root."""
    top = Path(_git(repo_path, ["rev-parse", "--show-toplevel"]).stdout.strip())
    listing = _git(top, ["ls-files", "--others", "--exclude-standard", "--full-name", "-z"]).stdout

    parts: list[str] = []
    for rel in listing.split("\0"):
        if not rel or not (top / rel).is_file():
            continue
        if (top / rel).stat().st_size > MAX_UNTRACKED_BYTES:
            continue
        # --no-index exits 1 when the files differ, which is expected here
        diff = _git(top, ["diff", "--no-index", "--no-color", "-U3", "--", "/dev/null", rel], ok_codes=(0, 1))
        if diff.stdout and "Binary files" not in diff.stdout:
            parts.append(diff.stdout if diff.stdout.endswith("\n") else diff.stdout + "\n")
    return "".join(parts)


def unquote_git_path(value: str) -> str:
    """Decode a git C-style quoted path ("a\\303\\274.py") into a normal string."""
    if len(value) < 2 or not (value.startswith('"') and value.endswith('"')):
        return value
    body = value[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        octal = OCTAL_ESCAPE.match(body, i)
        if octal:
            out.append(int(octal.group(1), 8))
            i = octal.end()
        elif body[i] == "\\" and i + 1 < len(body) and body[i + 1] in SIMPLE_ESCAPES:
            out.append(SIMPLE_ESCAPES[body[i + 1]])
            i += 2
        else:
            out += body[i].encode("utf-8")
            i += 1
    return out.decode("utf-8", errors="replace")


def _parse_new_path(value: str) -> str | None:
    """Return the new-side path from a '+++ ' line, or None for /dev/null (deleted file)."""
    if value == "/dev/null":
        return None
    path = unquote_git_path(value) if value.startswith('"') else value
    return path[2:] if path.startswith("b/") else path


def parse_unified_diff(raw_diff: str) -> list[DiffHunk]:
    """Parse unified diff text into structured DiffHunk and DiffLine objects."""
    hunks: list[DiffHunk] = []
    # split on \n only: git keeps \r and other control chars inside content
    lines = raw_diff.split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    current_file: str | None = None
    current_hunk: DiffHunk | None = None
    new_line_num = 0
    old_left = 0  # hunk body lines still expected on each side
    new_left = 0

    for line in lines:
        # Inside a hunk body, +++/--- are content, not file headers
        if old_left > 0 or new_left > 0:
            if line.startswith("\\"):
                # "\ No newline at end of file" consumes nothing
                continue
            tag = line[:1]
            if tag == "+":
                new_left -= 1
                if current_hunk is not None:
                    current_hunk.lines.append(
                        DiffLine(
                            file_path=current_hunk.file_path,
                            line_number=new_line_num,
                            content=line[1:],
                            is_added=True,
                        )
                    )
                new_line_num += 1
                continue
            if tag == "-":
                old_left -= 1
                continue
            if tag == " " or line == "":
                # Context line
                old_left -= 1
                new_left -= 1
                new_line_num += 1
                continue
            # Body ended early (malformed input): fall through and treat as a header
            old_left = new_left = 0

        if line.startswith("diff --git "):
            current_file = None
            current_hunk = None
            continue

        if line.startswith("+++ "):
            current_file = _parse_new_path(line[4:])
            continue

        hunk_match = HUNK_HEADER_PATTERN.match(line)
        if hunk_match:
            old_start, old_count = int(hunk_match.group(1)), int(hunk_match.group(2) or 1)
            new_start, new_count = int(hunk_match.group(3)), int(hunk_match.group(4) or 1)
            old_left, new_left = old_count, new_count
            new_line_num = new_start
            current_hunk = None
            if current_file:
                current_hunk = DiffHunk(
                    file_path=current_file,
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    lines=[],
                )
                hunks.append(current_hunk)

    return hunks
