"""Baseline file: accept the findings that exist today and report only new ones.

Entries are keyed by a fingerprint of rule, repo-relative path and normalized line content, so a
baselined finding stays matched when unrelated edits shift its line number. Identical lines in
the same file get an occurrence index, so adding a second copy of a baselined line is still new.
The file stores only SHA-256 fingerprints, never the matched text.
"""

import hashlib
import json
from pathlib import Path

from gitshield import __version__
from gitshield.core.models import Finding

BASELINE_FILE_NAME = ".gitshield-baseline.json"
BASELINE_VERSION = 1


class BaselineError(ValueError):
    """Raised when a baseline file cannot be read or has an unknown format."""


def _relative_path(file_path: str, repo_path: Path | None) -> str:
    path = Path(file_path)
    if repo_path is not None and path.is_absolute():
        try:
            path = path.resolve().relative_to(Path(repo_path).resolve())
        except (OSError, ValueError):
            pass
    normalized = path.as_posix().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def fingerprint_findings(findings: list[Finding], repo_path: Path | None = None) -> list[str]:
    """Fingerprint each finding (same order). Line numbers are left out on purpose."""
    counts: dict[str, int] = {}
    prints = []
    for f in findings:
        line = " ".join((f.context or f.matched_text).split())
        base = f"{f.rule_id}|{_relative_path(f.file_path, repo_path)}|{line}"
        occurrence = counts.get(base, 0)
        counts[base] = occurrence + 1
        prints.append(hashlib.sha256(f"{base}|{occurrence}".encode()).hexdigest())
    return prints


def load_baseline(path: Path) -> set[str]:
    """Fingerprints from a baseline file. A missing file is an empty baseline."""
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BaselineError(f"Cannot read baseline {path}: {e}") from e
    if not isinstance(data, dict) or data.get("version") != BASELINE_VERSION:
        raise BaselineError(f"Unsupported baseline format in {path} (expected version {BASELINE_VERSION}).")
    entries = data.get("findings")
    if not isinstance(entries, list):
        raise BaselineError(f"Baseline {path} has no findings list.")
    return {e["fingerprint"] for e in entries if isinstance(e, dict) and isinstance(e.get("fingerprint"), str)}


def filter_baselined(
    findings: list[Finding], baseline: set[str], repo_path: Path | None = None
) -> tuple[list[Finding], int]:
    """Drop findings whose fingerprint is in the baseline; return (new findings, suppressed count)."""
    if not baseline:
        return list(findings), 0
    kept = [f for f, fp in zip(findings, fingerprint_findings(findings, repo_path), strict=True) if fp not in baseline]
    return kept, len(findings) - len(kept)


def write_baseline(path: Path, findings: list[Finding], repo_path: Path | None = None) -> tuple[int, int]:
    """Merge findings into the baseline file (existing entries are kept); return (added, total).

    Merging matters because most scans see only a diff: rewriting the file from one scan would
    drop every accepted finding outside that diff. Delete the file to start over.
    """
    entries: dict[str, dict[str, str]] = {}
    if path.is_file():
        load_baseline(path)  # validate before rewriting
        for e in json.loads(path.read_text(encoding="utf-8"))["findings"]:
            if isinstance(e, dict) and isinstance(e.get("fingerprint"), str):
                entries[e["fingerprint"]] = e
    before = len(entries)
    for f, fp in zip(findings, fingerprint_findings(findings, repo_path), strict=True):
        entries.setdefault(
            fp,
            {
                "fingerprint": fp,
                "rule_id": f.rule_id,
                "file_path": _relative_path(f.file_path, repo_path),
                "severity": f.severity.value,
            },
        )
    doc = {
        "version": BASELINE_VERSION,
        "generated_by": f"gitshield {__version__}",
        # Sorted so regenerating the file gives a readable, stable diff in review
        "findings": sorted(entries.values(), key=lambda e: (e["file_path"], e["rule_id"], e["fingerprint"])),
    }
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(entries) - before, len(entries)
