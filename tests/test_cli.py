import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gitshield.cli import app

runner = CliRunner()
SECRET = "AKIAIOSFODNN7EXAMPLE"


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
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_bad_ref_exits_2(repo):
    result = runner.invoke(app, ["scan", str(repo), "--branch", "no-such-ref"])
    assert result.exit_code == 2


def test_unknown_format_exits_2(repo):
    result = runner.invoke(app, ["scan", str(repo), "--format", "xml"])
    assert result.exit_code == 2


def test_clean_scan_exits_0(repo):
    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    result = runner.invoke(app, ["scan", str(repo)])
    assert result.exit_code == 0


def test_finding_exits_1(repo):
    (repo / "app.py").write_text(f'KEY = "{SECRET}"\n', encoding="utf-8")
    result = runner.invoke(app, ["scan", str(repo)])
    assert result.exit_code == 1


def test_untracked_secret_is_found_and_no_untracked_skips_it(repo):
    (repo / "new.env").write_text(f'KEY = "{SECRET}"\n', encoding="utf-8")
    assert runner.invoke(app, ["scan", str(repo)]).exit_code == 1
    assert runner.invoke(app, ["scan", str(repo), "--no-untracked"]).exit_code == 0


def test_json_stdout_is_masked(repo):
    (repo / "app.py").write_text(f'KEY = "{SECRET}"\n', encoding="utf-8")
    result = runner.invoke(app, ["scan", str(repo), "--format", "json", "--no-fail"])
    assert result.exit_code == 0
    assert SECRET not in result.stdout
    report = json.loads(result.stdout)
    assert report["findings"]
    assert all(SECRET not in f["matched_text"] for f in report["findings"])


def test_sarif_stdout_is_valid_json(repo):
    (repo / "app.py").write_text(f'KEY = "{SECRET}"\n', encoding="utf-8")
    result = runner.invoke(app, ["scan", str(repo), "--format", "sarif", "--no-fail"])
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["version"] == "2.1.0"
    assert SECRET not in result.stdout


def test_rules_dir_option_accepted(repo, tmp_path_factory):
    rules = tmp_path_factory.mktemp("rules")
    result = runner.invoke(app, ["scan", str(repo), "--rules-dir", str(rules)])
    assert result.exit_code == 0


def test_ignore_file_suppresses_findings_and_no_ignore_file_disables_it(repo):
    (repo / ".gitshieldignore").write_text("# fixtures with fake keys\nfixtures/\n", encoding="utf-8")
    (repo / "fixtures").mkdir()
    (repo / "fixtures" / "keys.py").write_text(f'KEY = "{SECRET}"\n', encoding="utf-8")
    assert runner.invoke(app, ["scan", str(repo)]).exit_code == 0
    assert runner.invoke(app, ["scan", str(repo), "--no-ignore-file"]).exit_code == 1


def test_ignore_file_does_not_hide_findings_in_other_files(repo):
    (repo / ".gitshieldignore").write_text("tests/test_*.py\n", encoding="utf-8")
    (repo / "app.py").write_text(f'KEY = "{SECRET}"\n', encoding="utf-8")
    assert runner.invoke(app, ["scan", str(repo)]).exit_code == 1
