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
