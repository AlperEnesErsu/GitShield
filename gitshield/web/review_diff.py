"""Diff annotation and line mapping for the review pipeline."""

import logging
import re
from typing import Any

from gitshield.web.insights import LOCKFILE

log = logging.getLogger(__name__)


HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


# ---- Diff helpers ----------------------------------------------------------------


def annotate_patch(patch: str) -> tuple[str, set[int]]:
    """Prefix each patch line with its new-file line number; return commentable lines."""
    out: list[str] = []
    commentable: set[int] = set()
    new_line = 0
    for raw in patch.splitlines():
        header = HUNK_HEADER.match(raw)
        if header:
            new_line = int(header.group(1))
            out.append(raw)
            continue
        if raw.startswith(("-", "\\")):
            out.append(f"{'':>6} {raw}")
        else:
            commentable.add(new_line)
            out.append(f"{new_line:>6} {raw}")
            new_line += 1
    return "\n".join(out), commentable


def build_diff(files: list[dict[str, Any]], max_chars: int):
    """Return (raw unified diff, annotated diff for the LLM, commentable lines, skipped files)."""
    raw_parts: list[str] = []
    annotated_parts: list[str] = []
    commentable: dict[str, set[int]] = {}
    skipped: list[dict[str, str]] = []
    used = 0

    for f in files:
        path = f["filename"]
        patch = f.get("patch")
        if not patch:
            skipped.append({"path": path, "reason": "binary or too large for GitHub to render"})
            continue
        raw_parts.append(f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n{patch}")
        annotated, lines = annotate_patch(patch)
        commentable[path] = lines
        if LOCKFILE.search(path):
            # Generated churn: slows the LLM and adds nothing it can review. The static scan still sees it.
            skipped.append({"path": path, "reason": "lockfile; generated, not sent to the LLM"})
            continue
        block = f"### {path} ({f.get('status', 'modified')})\n{annotated}\n"
        if used + len(block) > max_chars:
            skipped.append({"path": path, "reason": "diff budget exceeded; not sent to the LLM"})
            continue
        annotated_parts.append(block)
        used += len(block)

    return "\n".join(raw_parts), "\n".join(annotated_parts), commentable, skipped


HUNK_FULL = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def map_old_line(patch: str, line: int, radius: int = 2) -> tuple[int | None, bool]:
    """Map ``line`` of the old file through ``patch`` to the new file.

    Returns (new_line or None if the line was deleted, touched) where ``touched`` means a
    change landed within ``radius`` lines of it.
    """
    offset = 0
    old = new = 0
    touched = False
    mapped: int | None = None
    in_hunk_hit = False
    for raw in patch.splitlines():
        header = HUNK_FULL.match(raw)
        if header:
            if in_hunk_hit:
                return mapped, touched
            if old:
                offset = new - old
            old, new = int(header.group(1)), int(header.group(2))
            if line < old:
                return line + offset, touched
            continue
        if raw.startswith("\\") or not old:
            continue
        if raw.startswith("-"):
            if abs(old - line) <= radius:
                touched = True
            if old == line:
                in_hunk_hit, mapped = True, None
            old += 1
        elif raw.startswith("+"):
            if abs(old - line) <= radius:
                touched = True
            new += 1
        else:
            if old == line:
                in_hunk_hit, mapped = True, new
            old += 1
            new += 1
    if in_hunk_hit:
        return mapped, touched
    return line + (new - old if old else 0), touched
