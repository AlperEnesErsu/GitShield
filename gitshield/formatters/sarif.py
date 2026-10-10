import hashlib
import json
from pathlib import Path
from typing import Any

from gitshield import __version__
from gitshield.core.models import Finding, RuleType, ScanReport, Severity

SARIF_SEVERITY_MAP = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "none",
}

# GitHub Code Scanning reads this CVSS-like score to show the alert severity.
SECURITY_SEVERITY_MAP = {
    Severity.CRITICAL: "9.5",
    Severity.HIGH: "7.5",
    Severity.MEDIUM: "5.0",
    Severity.LOW: "3.0",
    Severity.INFO: "0.0",
}

SECRET_TYPES = (RuleType.SECRET, RuleType.ENTROPY)
REDACTED = "<REDACTED_SECRET>"


def _is_secret(finding: Finding) -> bool:
    return finding.rule_type in SECRET_TYPES and bool(finding.matched_text)


def _safe_text(finding: Finding, text: str) -> str:
    """Mask a secret wherever it appears in text; other findings are returned unchanged."""
    if _is_secret(finding):
        return text.replace(finding.matched_text, finding.mask_secret())
    return text


def _relative_uri(file_path: str, repo_path: str) -> str:
    """Repo-relative, forward-slash URI for SARIF artifactLocation (uriBaseId %SRCROOT%)."""
    path = Path(file_path)
    if repo_path and path.is_absolute():
        try:
            path = path.resolve().relative_to(Path(repo_path).resolve())
        except (OSError, ValueError):
            pass
    return path.as_posix().replace("\\", "/").lstrip("/")


def _line_hash(finding: Finding, uri: str, occurrence: int) -> str:
    """Stable across runs: rule, file and normalized line content, but not the line number."""
    raw = finding.context or finding.matched_text
    normalized = " ".join(raw.split())
    if _is_secret(finding):
        # Never hash the raw secret; a placeholder keeps the fingerprint stable for the same leak.
        normalized = normalized.replace(finding.matched_text, REDACTED)
    key = f"{finding.rule_id}|{uri}|{normalized}|{occurrence}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def build_sarif(report: ScanReport) -> dict[str, Any]:
    """Build an OASIS SARIF 2.1.0 document compatible with GitHub Code Scanning."""
    rules: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    rules_seen: set[str] = set()
    fingerprint_counts: dict[str, int] = {}

    for f in report.findings:
        uri = _relative_uri(f.file_path, report.repo_path)

        if f.rule_id not in rules_seen:
            rules_seen.add(f.rule_id)
            tags = ["security"]
            if f.cwe:
                tags.append(f.cwe)
            rules.append(
                {
                    "id": f.rule_id,
                    "shortDescription": {"text": f.title},
                    "fullDescription": {"text": f.description},
                    "defaultConfiguration": {
                        "level": SARIF_SEVERITY_MAP.get(f.severity, "warning")
                    },
                    "help": {"text": f.suggested_fix or f.description},
                    "properties": {
                        "security-severity": SECURITY_SEVERITY_MAP.get(f.severity, "5.0"),
                        "tags": tags,
                    },
                }
            )

        base = f"{f.rule_id}|{uri}|{' '.join((f.context or f.matched_text).split())}"
        occurrence = fingerprint_counts.get(base, 0)
        fingerprint_counts[base] = occurrence + 1

        region: dict[str, Any] = {"startLine": max(1, f.line_number), "startColumn": 1}
        if f.context:
            region["snippet"] = {"text": _safe_text(f, f.context)}

        results.append(
            {
                "ruleId": f.rule_id,
                "level": SARIF_SEVERITY_MAP.get(f.severity, "warning"),
                "message": {"text": _safe_text(f, f"{f.title}: {f.description}")},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": uri, "uriBaseId": "%SRCROOT%"},
                            "region": region,
                        }
                    }
                ],
                "partialFingerprints": {
                    "primaryLocationLineHash": _line_hash(f, uri, occurrence),
                },
            }
        )

    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "GitShield",
                        "version": __version__,
                        "informationUri": "https://github.com/AlperEnesErsu/GitShield",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


def export_to_sarif(report: ScanReport, output_file: Path) -> None:
    """Write the SARIF document for report to output_file."""
    sarif = build_sarif(report)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as out:
        json.dump(sarif, out, indent=2)
