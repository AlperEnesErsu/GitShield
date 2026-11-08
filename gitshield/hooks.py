"""Install GitShield as a plain git pre-commit hook (no pre-commit framework needed).

The hook runs ``gitshield scan --staged`` with the interpreter that installed it, so it keeps
working from git GUIs and editors whose PATH does not include the virtualenv. If that
interpreter disappears (the venv was deleted), the hook falls back to ``gitshield`` on PATH.
"""

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from gitshield.core.diff_parser import GitDiffError, _git

HOOK_NAME = "pre-commit"
HOOK_MARKER = "# gitshield-hook"
BACKUP_SUFFIX = ".gitshield-backup"


class HookError(RuntimeError):
    """The hook could not be installed or removed (not a repo, foreign hook in the way)."""


@dataclass
class HookResult:
    path: Path
    backup: Path | None = None  # install: where a replaced hook went; uninstall: what was restored


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def hook_script(python: str | None = None) -> str:
    # Forward slashes: git runs hooks with sh on Windows too, and sh treats '\' specially.
    interpreter = Path(python or sys.executable).as_posix()
    py = _sh_quote(interpreter)
    return (
        "#!/bin/sh\n"
        f"{HOOK_MARKER}\n"
        "# Installed by `gitshield hook install`; remove with `gitshield hook uninstall`.\n"
        "# Skip once with `git commit --no-verify`.\n"
        f"if [ -x {py} ]; then\n"
        f"  exec {py} -m gitshield.cli scan --staged\n"
        "fi\n"
        "if command -v gitshield >/dev/null 2>&1; then\n"
        "  exec gitshield scan --staged\n"
        "fi\n"
        'echo "gitshield: interpreter not found; reinstall with \\`gitshield hook install --force\\`." >&2\n'
        "exit 1\n"
    )


def hooks_dir(repo_path: Path) -> Path:
    """The directory git runs hooks from (honours core.hooksPath and linked worktrees)."""
    try:
        out = _git(repo_path, ["rev-parse", "--path-format=absolute", "--git-path", "hooks"])
    except GitDiffError as e:
        raise HookError(str(e)) from e
    return Path(out.stdout.strip())


def is_gitshield_hook(path: Path) -> bool:
    try:
        return HOOK_MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def install_hook(repo_path: Path, force: bool = False, python: str | None = None) -> HookResult:
    """Write the pre-commit hook. A foreign hook is kept unless ``force``, then backed up."""
    directory = hooks_dir(repo_path)
    path = directory / HOOK_NAME
    backup: Path | None = None
    if path.exists() and not is_gitshield_hook(path):
        if not force:
            raise HookError(
                f"{path} already exists and was not installed by GitShield. "
                "Use --force to replace it (it is backed up), or call GitShield from that hook."
            )
        backup = path.with_name(HOOK_NAME + BACKUP_SUFFIX)
        os.replace(path, backup)
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(hook_script(python), encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return HookResult(path=path, backup=backup)


def uninstall_hook(repo_path: Path) -> HookResult:
    """Remove GitShield's hook and restore the hook it replaced, if any."""
    path = hooks_dir(repo_path) / HOOK_NAME
    if not path.exists():
        raise HookError(f"No pre-commit hook at {path}.")
    if not is_gitshield_hook(path):
        raise HookError(f"{path} was not installed by GitShield; leaving it alone.")
    path.unlink()
    backup = path.with_name(HOOK_NAME + BACKUP_SUFFIX)
    if backup.exists():
        os.replace(backup, path)
        return HookResult(path=path, backup=backup)
    return HookResult(path=path)
