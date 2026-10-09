from gitshield.core.diff_parser import parse_unified_diff

SAMPLE_DIFF = """diff --git a/app/main.py b/app/main.py
index e69de29..d95f3ad 100644
--- a/app/main.py
+++ b/app/main.py
@@ -1,3 +1,5 @@
 import os
+AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
+cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
 def run():
     pass
"""


def test_parse_unified_diff():
    hunks = parse_unified_diff(SAMPLE_DIFF)
    assert len(hunks) == 1
    hunk = hunks[0]
    assert hunk.file_path == "app/main.py"
    assert len(hunk.lines) == 2
    assert hunk.lines[0].line_number == 2
    assert "AKIAIOSFODNN7EXAMPLE" in hunk.lines[0].content
    assert hunk.lines[1].line_number == 3
    assert "SELECT * FROM users" in hunk.lines[1].content
