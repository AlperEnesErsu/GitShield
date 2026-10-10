from pathlib import Path

from gitshield.core.scanner import Scanner

HASH = "sha256: 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
AWS = 'key = "AKIAIOSFODNN7EXAMPLE"'


def diff(path, line):
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,0 +1,1 @@\n+{line}\n"


def test_lockfile_hashes_are_not_flagged_as_secrets():
    report = Scanner().scan_diff(Path("."), raw_diff=diff("pubspec.lock", HASH))
    assert not [f for f in report.findings if f.rule_id.startswith("ENTROPY")]


def test_entropy_still_runs_on_source_files():
    report = Scanner().scan_diff(Path("."), raw_diff=diff("app/config.py", f'token = "{HASH.split()[1]}"'))
    assert any(f.rule_id.startswith("ENTROPY") for f in report.findings)


def test_known_secret_rules_still_run_in_lockfiles():
    report = Scanner().scan_diff(Path("."), raw_diff=diff("package-lock.json", AWS))
    assert any(not f.rule_id.startswith("ENTROPY") for f in report.findings)
