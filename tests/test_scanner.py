from pathlib import Path

from gitshield.core.scanner import Scanner

SAMPLE_DIFF = """diff --git a/app/vulnerable.py b/app/vulnerable.py
new file mode 100644
--- /dev/null
+++ b/app/vulnerable.py
@@ -0,0 +1,5 @@
+import subprocess
+AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
+subprocess.run(user_input, shell=True)
+cursor.execute(f"SELECT * FROM secrets WHERE key = '{val}'")
+API_SECRET = "dGhpc2lzYXZlcnlsb25ncmFuZG9tc2VjcmV0dG9rZW4xMjM="
"""


def test_scanner_detects_secrets_and_owasp():
    scanner = Scanner()
    report = scanner.scan_diff(
        repo_path=Path("."),
        raw_diff=SAMPLE_DIFF,
        enable_entropy=True,
    )

    assert report.scanned_lines_count == 5
    assert len(report.findings) >= 3

    # Check for AWS finding
    aws_findings = [f for f in report.findings if f.rule_id == "SEC-AWS-001"]
    assert len(aws_findings) == 1
    assert aws_findings[0].severity.value == "CRITICAL"

    # Check for Command Injection finding
    cmdi_findings = [f for f in report.findings if f.rule_id == "OWASP-A03-CMDI-002"]
    assert len(cmdi_findings) == 1

    # Check for SQL Injection finding
    sqli_findings = [f for f in report.findings if f.rule_id == "OWASP-A03-SQLI-001"]
    assert len(sqli_findings) == 1


def _scan(path, line, enable_entropy=True):
    raw = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,0 +1,1 @@\n+{line}\n"
    return Scanner().scan_diff(Path("."), raw_diff=raw, enable_entropy=enable_entropy).findings


def test_stripe_key_caught_once_without_entropy_duplicate():
    findings = _scan("app/billing.py", 'key = "sk_live_' + '51HxQ2bLkd8sJ2mN4pQ7rT9vW1yZ3aB5cD"')
    assert [f.rule_id for f in findings] == ["SEC-STRIPE-010"]


def test_git_sha_and_uuid_are_not_flagged_by_scanner():
    assert _scan("app/meta.py", 'commit = "9fceb02d0ae598e95dc970b74767f19372d61af8"') == []
    assert _scan("app/meta.py", 'id = "123e4567-e89b-12d3-a456-426614174000"') == []


def test_literal_eval_and_regex_exec_not_flagged_by_scanner():
    assert _scan("app/parse.py", "value = ast.literal_eval(raw)") == []
    assert _scan("web/match.js", "const m = pattern.exec(text);") == []


def test_eval_call_flagged_by_scanner():
    findings = _scan("app/run.py", "result = eval(user_input)")
    assert [f.rule_id for f in findings] == ["OWASP-A03-EVAL-003"]


def test_pickle_in_readme_not_flagged_but_in_python_is_flagged():
    assert _scan("README.md", "data = pickle.loads(blob)") == []
    assert [f.rule_id for f in _scan("app/load.py", "data = pickle.loads(blob)")] == ["OWASP-A08-PICKLE-004"]


def test_inline_ignore_suppresses_all_findings_on_line():
    line = 'AWS = "AKIAIOSFODNN7EXAMPLE"  # gitshield: ignore'
    assert _scan("app/x.py", line) == []


def test_inline_ignore_with_rule_id_suppresses_only_that_rule():
    line = 'AWS = "AKIAIOSFODNN7EXAMPLE"; r = eval(x)  # gitshield: ignore[SEC-AWS-001]'
    rule_ids = {f.rule_id for f in _scan("app/x.py", line)}
    assert "SEC-AWS-001" not in rule_ids
    assert "OWASP-A03-EVAL-003" in rule_ids


def test_inline_ignore_with_other_rule_id_does_not_suppress():
    line = 'AWS = "AKIAIOSFODNN7EXAMPLE"  // gitshield: ignore[OWASP-A03-EVAL-003]'
    assert [f.rule_id for f in _scan("app/x.py", line)] == ["SEC-AWS-001"]


def test_inline_ignore_suppresses_entropy_finding():
    line = 'blob = "Xk9Lm2Pq8Rt4Vw7Yz1Ab"  # gitshield: ignore[ENTROPY-HIGH-001]'
    assert _scan("app/x.py", line) == []


def test_entropy_finding_reported_for_unmatched_secret():
    findings = _scan("app/x.py", 'blob = "Xk9Lm2Pq8Rt4Vw7Yz1"')
    assert [f.rule_id for f in findings] == ["ENTROPY-HIGH-001"]


def test_multiple_findings_on_one_line_all_reported():
    line = 'a = "AKIAIOSFODNN7EXAMPLE"; b = "AKIAIOSFODNN7EXAMPL2"'
    findings = [f for f in _scan("app/x.py", line) if f.rule_id == "SEC-AWS-001"]
    assert len(findings) == 2


def _scan_with_ignore(path, line, ignore_patterns):
    raw = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,0 +1,1 @@\n+{line}\n"
    return Scanner(ignore_patterns=ignore_patterns).scan_diff(Path("."), raw_diff=raw).findings


def test_ignore_patterns_drop_findings_in_matching_files():
    line = 'KEY = "AKIAIOSFODNN7EXAMPLE"'
    assert _scan_with_ignore("tests/test_keys.py", line, ["tests/test_*.py"]) == []
    assert _scan_with_ignore("tests/test_keys.py", line, []) != []


def test_ignore_directory_prefix_pattern():
    line = 'KEY = "AKIAIOSFODNN7EXAMPLE"'
    assert _scan_with_ignore("tests/fixtures/data.py", line, ["tests/fixtures/"]) == []
    assert _scan_with_ignore("tests/fixtures2/data.py", line, ["tests/fixtures/"]) != []


def test_ignore_double_star_pattern_matches_nested_and_root():
    line = 'KEY = "AKIAIOSFODNN7EXAMPLE"'
    assert _scan_with_ignore("web/static/app.min.js", line, ["**/*.min.js"]) == []
    assert _scan_with_ignore("app.min.js", line, ["**/*.min.js"]) == []
    assert _scan_with_ignore("web/static/app.js", line, ["**/*.min.js"]) != []


def test_scanner_default_has_no_ignore_behavior():
    line = 'KEY = "AKIAIOSFODNN7EXAMPLE"'
    raw = f"diff --git a/tests/test_x.py b/tests/test_x.py\n--- a/tests/test_x.py\n+++ b/tests/test_x.py\n@@ -1,0 +1,1 @@\n+{line}\n"
    assert Scanner().scan_diff(Path("."), raw_diff=raw).findings != []


def test_load_ignore_file_skips_comments_and_blank_lines(tmp_path):
    from gitshield.core.scanner import load_ignore_file

    (tmp_path / ".gitshieldignore").write_text("# comment\n\n tests/test_*.py \n**/*.min.js\n", encoding="utf-8")
    assert load_ignore_file(tmp_path) == ["tests/test_*.py", "**/*.min.js"]


def test_load_ignore_file_missing_returns_empty(tmp_path):
    from gitshield.core.scanner import load_ignore_file

    assert load_ignore_file(tmp_path) == []
