import re
import subprocess
from pathlib import Path
from typing import List, Optional
from gitshield.core.models import DiffHunk, DiffLine


HUNK_HEADER_PATTERN = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
DIFF_FILE_HEADER = re.compile(r"^diff --git a/(.*) b/(.*)")


def get_git_diff(
    repo_path: Path,
    staged: bool = False,
    branch_or_commit: Optional[str] = None,
) -> str:
    """Retrieve raw unified git diff from the local repository."""
    cmd = ["git", "diff", "--no-color", "-U3"]

    if branch_or_commit:
        cmd.append(branch_or_commit)
    elif staged:
        cmd.append("--cached")
    else:
        # Default: compare HEAD or uncommitted changes
        cmd.append("HEAD")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout
    except Exception as e:
        raise RuntimeError(f"Failed to execute git diff: {e}")


def parse_unified_diff(raw_diff: str) -> List[DiffHunk]:
    """Parse unified diff text into structured DiffHunk and DiffLine objects."""
    hunks: List[DiffHunk] = []
    lines = raw_diff.splitlines()

    current_file: Optional[str] = None
    current_hunk: Optional[DiffHunk] = None
    new_line_num = 0

    for line in lines:
        file_match = DIFF_FILE_HEADER.match(line)
        if file_match:
            current_file = file_match.group(2)
            continue

        hunk_match = HUNK_HEADER_PATTERN.match(line)
        if hunk_match and current_file:
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2) or 1)
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4) or 1)

            current_hunk = DiffHunk(
                file_path=current_file,
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                lines=[],
            )
            hunks.append(current_hunk)
            new_line_num = new_start
            continue

        if current_hunk:
            if line.startswith("+") and not line.startswith("+++"):
                content = line[1:]
                current_hunk.lines.append(
                    DiffLine(
                        file_path=current_hunk.file_path,
                        line_number=new_line_num,
                        content=content,
                        is_added=True,
                    )
                )
                new_line_num += 1
            elif line.startswith("-") and not line.startswith("---"):
                # Deleted line, do not increment new_line_num
                pass
            elif line.startswith(" "):
                # Context line
                new_line_num += 1

    return hunks
