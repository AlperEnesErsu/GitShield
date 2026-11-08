import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from gitshield.cli import app
from gitshield.hooks import BACKUP_SUFFIX, HOOK_MARKER, hook_script

runner = CliRunner()
SECRET = "AKIAIOSFODNN7EXAMPLE"
ROOT = Path(__file__).resolve().parent.parent


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=str(repo),
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def _hook(repo: Path) -> Path:
    return repo / ".git" / "hooks" / "pre-commit"


def test_install_writes_marked_hook(repo):
    result = runner.invoke(app, ["hook", "install", str(repo)])
    assert result.exit_code == 0, result.output
    text = _hook(repo).read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert HOOK_MARKER in text
    assert "scan --staged" in text
    assert "\r\n" not in text
    if os.name != "nt":
        assert os.access(_hook(repo), os.X_OK)


def test_install_is_idempotent(repo):
    assert runner.invoke(app, ["hook", "install", str(repo)]).exit_code == 0
    assert runner.invoke(app, ["hook", "install", str(repo)]).exit_code == 0
    assert not _hook(repo).with_name("pre-commit" + BACKUP_SUFFIX).exists()


def test_foreign_hook_is_kept_without_force(repo):
    _hook(repo).write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    result = runner.invoke(app, ["hook", "install", str(repo)])
    assert result.exit_code == 2
    assert "echo mine" in _hook(repo).read_text(encoding="utf-8")


def test_force_backs_up_and_uninstall_restores(repo):
    _hook(repo).write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    assert runner.invoke(app, ["hook", "install", str(repo), "--force"]).exit_code == 0
    assert HOOK_MARKER in _hook(repo).read_text(encoding="utf-8")

    assert runner.invoke(app, ["hook", "uninstall", str(repo)]).exit_code == 0
    assert _hook(repo).read_text(encoding="utf-8") == "#!/bin/sh\necho mine\n"
    assert not _hook(repo).with_name("pre-commit" + BACKUP_SUFFIX).exists()


def test_uninstall_removes_hook(repo):
    runner.invoke(app, ["hook", "install", str(repo)])
    assert runner.invoke(app, ["hook", "uninstall", str(repo)]).exit_code == 0
    assert not _hook(repo).exists()


def test_uninstall_leaves_foreign_hook(repo):
    _hook(repo).write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    assert runner.invoke(app, ["hook", "uninstall", str(repo)]).exit_code == 2
    assert _hook(repo).exists()


def test_uninstall_without_hook_exits_2(repo):
    assert runner.invoke(app, ["hook", "uninstall", str(repo)]).exit_code == 2


def test_install_outside_repo_exits_2(tmp_path):
    assert runner.invoke(app, ["hook", "install", str(tmp_path)]).exit_code == 2


def test_install_honours_core_hooks_path(repo):
    _git(repo, "config", "core.hooksPath", ".githooks")
    assert runner.invoke(app, ["hook", "install", str(repo)]).exit_code == 0
    assert HOOK_MARKER in (repo / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    assert not _hook(repo).exists()


def test_script_quotes_interpreter_path():
    script = hook_script(r"C:\it's here\python.exe")
    assert "'C:/it'\\''s here/python.exe'" in script


def test_hook_blocks_commit_with_secret_and_allows_clean_commit(repo):
    assert runner.invoke(app, ["hook", "install", str(repo)]).exit_code == 0

    (repo / "app.py").write_text(f'KEY = "{SECRET}"\n', encoding="utf-8")
    _git(repo, "add", "app.py")
    blocked = _git(repo, "commit", "-q", "-m", "leak", check=False)
    assert blocked.returncode != 0
    assert "GitShield" in blocked.stdout + blocked.stderr
    assert _git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"

    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    allowed = _git(repo, "commit", "-q", "-m", "clean", check=False)
    assert allowed.returncode == 0, allowed.stderr
    assert _git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "2"


def test_pre_commit_framework_manifest():
    hooks = yaml.safe_load((ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8"))
    (hook,) = hooks
    assert hook["id"] == "gitshield"
    assert hook["entry"] == "gitshield scan --staged"
    assert hook["language"] == "python"
    assert hook["pass_filenames"] is False


def test_hook_uses_current_interpreter():
    assert Path(sys.executable).as_posix() in hook_script()
