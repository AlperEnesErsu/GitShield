import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gitshield.cli import app
from gitshield.core.baseline import (
    BASELINE_FILE_NAME,
    BaselineError,
    filter_baselined,
    fingerprint_findings,
    load_baseline,
    write_baseline,
)
from gitshield.core.models import Finding, RuleType, Severity

runner = CliRunner()
SECRET = "AKIAIOSFODNN7EXAMPLE"
OTHER_SECRET = "AKIAI44QH8DHBEXAMPLE"


def _finding(line: int = 1, context: str = f'KEY = "{SECRET}"', path: str = "app.py") -> Finding:
    return Finding(
        id=f"SEC-AWS-001-{path}-{line}",
        rule_id="SEC-AWS-001",
        title="AWS Access Key ID",
        description="",
        severity=Severity.CRITICAL,
        rule_type=RuleType.SECRET,
        file_path=path,
        line_number=line,
        matched_text=SECRET,
        context=context,
    )


def test_fingerprint_ignores_line_number_and_whitespace():
    a = fingerprint_findings([_finding(line=3)])
    b = fingerprint_findings([_finding(line=40, context=f'KEY  =  "{SECRET}"')])
    assert a == b


def test_fingerprint_depends_on_path_and_content():
    base = fingerprint_findings([_finding()])[0]
    assert fingerprint_findings([_finding(path="other.py")])[0] != base
    assert fingerprint_findings([_finding(context=f'TOKEN = "{SECRET}"')])[0] != base


def test_duplicate_line_beyond_baseline_is_new():
    prints = fingerprint_findings([_finding(line=1)])
    findings = [_finding(line=1), _finding(line=9)]
    kept, suppressed = filter_baselined(findings, set(prints))
    assert suppressed == 1
    assert [f.line_number for f in kept] == [9]


def test_write_merges_and_never_stores_secret(tmp_path):
    path = tmp_path / BASELINE_FILE_NAME
    assert write_baseline(path, [_finding()]) == (1, 1)
    assert write_baseline(path, [_finding(), _finding(path="b.py")]) == (1, 2)
    text = path.read_text(encoding="utf-8")
    assert SECRET not in text
    assert {e["file_path"] for e in json.loads(text)["findings"]} == {"app.py", "b.py"}
    assert len(load_baseline(path)) == 2


def test_missing_file_is_empty_and_bad_file_raises(tmp_path):
    assert load_baseline(tmp_path / "nope.json") == set()
    bad = tmp_path / "bad.json"
    bad.write_text('{"version": 99, "findings": []}', encoding="utf-8")
    with pytest.raises(BaselineError):
        load_baseline(bad)
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(BaselineError):
        load_baseline(bad)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "app.py").write_text(f'x = 1\nKEY = "{SECRET}"\n', encoding="utf-8")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_all_scans_committed_lines(repo):
    assert runner.invoke(app, ["scan", str(repo)]).exit_code == 0
    assert runner.invoke(app, ["scan", str(repo), "--all"]).exit_code == 1


def test_all_rejects_branch(repo):
    assert runner.invoke(app, ["scan", str(repo), "--all", "--branch", "HEAD"]).exit_code == 2


def test_baseline_accepts_existing_and_reports_new(repo):
    result = runner.invoke(app, ["scan", str(repo), "--all", "--update-baseline"])
    assert result.exit_code == 0
    assert (repo / BASELINE_FILE_NAME).is_file()

    assert runner.invoke(app, ["scan", str(repo), "--all"]).exit_code == 0
    assert runner.invoke(app, ["scan", str(repo), "--all", "--no-baseline"]).exit_code == 1

    # Shifting the accepted line down keeps it baselined; a new secret is still reported
    (repo / "app.py").write_text(f'import os\nx = 1\nKEY = "{SECRET}"\n', encoding="utf-8")
    assert runner.invoke(app, ["scan", str(repo), "--all"]).exit_code == 0
    (repo / "app.py").write_text(f'x = 1\nKEY = "{SECRET}"\nNEW = "{OTHER_SECRET}"\n', encoding="utf-8")
    assert runner.invoke(app, ["scan", str(repo), "--all"]).exit_code == 1


def test_custom_baseline_path_and_corrupt_file_exits_2(repo, tmp_path_factory):
    path = tmp_path_factory.mktemp("bl") / "accepted.json"
    assert runner.invoke(app, ["scan", str(repo), "--all", "--update-baseline", "--baseline", str(path)]).exit_code == 0
    assert runner.invoke(app, ["scan", str(repo), "--all", "--baseline", str(path)]).exit_code == 0
    path.write_text("{", encoding="utf-8")
    assert runner.invoke(app, ["scan", str(repo), "--all", "--baseline", str(path)]).exit_code == 2
