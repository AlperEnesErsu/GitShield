import io
import json
from pathlib import Path

from rich.console import Console

from gitshield import __version__
from gitshield.core.models import Finding, RuleType, ScanReport, Severity
from gitshield.formatters.console import print_report_to_console
from gitshield.formatters.sarif import build_sarif, export_to_sarif

AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
GH_TOKEN = "ghp_aB3dE5fG7hI9jK1lM2nO4pQ6rS8tU0vW2xY4"


def _report() -> ScanReport:
    secret = Finding(
        id="SEC-AWS-001-app/config.py-3",
        rule_id="SEC-AWS-001",
        title="AWS Access Key",
        description="Hardcoded AWS access key",
        severity=Severity.CRITICAL,
        rule_type=RuleType.SECRET,
        file_path="app/config.py",
        line_number=3,
        matched_text=AWS_KEY,
        context=f'AWS_KEY = "{AWS_KEY}"',
        cwe="CWE-798",
        suggested_fix="Load the key from the environment.",
    )
    gh = Finding(
        id="SEC-GH-002-app/config.py-4",
        rule_id="SEC-GH-002",
        title="GitHub Token",
        description="Hardcoded GitHub token",
        severity=Severity.HIGH,
        rule_type=RuleType.SECRET,
        file_path="app/config.py",
        line_number=4,
        matched_text=GH_TOKEN,
        context=f'GH = "{GH_TOKEN}"',
        cwe="CWE-798",
    )
    sqli = Finding(
        id="OWASP-SQL-app/db.py-9",
        rule_id="OWASP-SQLI-001",
        title="SQL injection",
        description="String-built SQL query",
        severity=Severity.MEDIUM,
        rule_type=RuleType.OWASP,
        file_path="app/db.py",
        line_number=9,
        matched_text="execute(f\"SELECT",
        context='cur.execute(f"SELECT * FROM t WHERE id={uid}")',
        cwe="CWE-89",
    )
    return ScanReport(
        repo_path="C:/repo",
        target_ref="HEAD",
        findings=[secret, gh, sqli],
    )


def test_build_sarif_is_valid_shape() -> None:
    sarif = build_sarif(_report())

    assert sarif["version"] == "2.1.0"
    driver = sarif["runs"][0]["tool"]["driver"]
    assert driver["name"] == "GitShield"
    assert driver["version"] == __version__

    results = sarif["runs"][0]["results"]
    assert len(results) == 3
    for result in results:
        assert result["ruleId"]
        assert result["level"] in {"error", "warning", "note", "none"}
        assert "primaryLocationLineHash" in result["partialFingerprints"]
        loc = result["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uriBaseId"] == "%SRCROOT%"
        assert loc["region"]["startLine"] >= 1


def test_build_sarif_rules_carry_security_severity_and_tags() -> None:
    rules = {r["id"]: r for r in build_sarif(_report())["runs"][0]["tool"]["driver"]["rules"]}

    assert rules["SEC-AWS-001"]["properties"]["security-severity"] == "9.5"
    assert rules["SEC-GH-002"]["properties"]["security-severity"] == "7.5"
    assert rules["OWASP-SQLI-001"]["properties"]["security-severity"] == "5.0"
    assert rules["SEC-AWS-001"]["properties"]["tags"] == ["security", "CWE-798"]


def test_build_sarif_never_contains_raw_secrets() -> None:
    dumped = json.dumps(build_sarif(_report()))

    assert AWS_KEY not in dumped
    assert GH_TOKEN not in dumped
    assert AWS_KEY[:4] in dumped  # masked form is still useful for triage


def test_build_sarif_uses_relative_forward_slash_uris() -> None:
    report = _report()
    report.findings[0].file_path = "C:\\repo\\app\\config.py"
    results = build_sarif(report)["runs"][0]["results"]

    uri = results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert "\\" not in uri
    assert not uri.startswith("/")


def test_fingerprints_are_stable_across_line_shifts() -> None:
    first = build_sarif(_report())["runs"][0]["results"]
    shifted = _report()
    for f in shifted.findings:
        f.line_number += 10
    second = build_sarif(shifted)["runs"][0]["results"]

    assert [r["partialFingerprints"] for r in first] == [r["partialFingerprints"] for r in second]


def test_fingerprints_differ_for_identical_lines_in_one_file() -> None:
    report = _report()
    dup = report.findings[2].model_copy(update={"line_number": 20})
    report.findings.append(dup)

    results = build_sarif(report)["runs"][0]["results"]
    hashes = [r["partialFingerprints"]["primaryLocationLineHash"] for r in results]

    assert len(set(hashes)) == len(hashes)


def test_export_to_sarif_writes_file(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "report.sarif"

    export_to_sarif(_report(), out)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == "2.1.0"
    assert len(data["runs"][0]["results"]) == 3
    assert AWS_KEY not in out.read_text(encoding="utf-8")


def test_console_output_masks_secrets() -> None:
    buf = io.StringIO()
    console = Console(file=buf, width=200, force_terminal=False, color_system=None)

    print_report_to_console(_report(), console=console)

    text = buf.getvalue()
    assert AWS_KEY not in text
    assert GH_TOKEN not in text
    assert "AKIA" in text
    assert "ghp_" in text
    assert "execute(f" in text  # non-secret matches are still shown


def test_console_escapes_markup_in_matched_text() -> None:
    report = _report()
    report.findings[2].matched_text = "[bold]x[/bold]"
    buf = io.StringIO()
    console = Console(file=buf, width=200, force_terminal=False, color_system=None)

    print_report_to_console(report, console=console)

    assert "[bold]x[/bold]" in buf.getvalue()
