import pytest

from gitshield.rules.engine import RuleEngine, is_placeholder

ENGINE = RuleEngine()


def ids(path, line):
    return {f.rule_id for f in ENGINE.scan_line(path, 1, line)}


def matches(path, line, rule_id):
    return [f.matched_text for f in ENGINE.scan_line(path, 1, line) if f.rule_id == rule_id]


# --- Provider secret rules: (rule id, positive line, negative line) ---
SECRET_CASES = [
    ("SEC-GH-007", "t = 'gho_" + "aB3dE5gH7jK9mN2pQ4rS6tU8vW0xY1zA2bC3" + "'", "t = 'ghp_short'"),
    ("SEC-GH-007", "t = 'ghs_" + "aB3dE5gH7jK9mN2pQ4rS6tU8vW0xY1zA2bC3" + "'", "t = 'ghx_" + "a" * 36 + "'"),
    ("SEC-SLACK-008", "SLACK = 'xoxb-1234567890-abcdefGHIJ'", "SLACK = 'xoxz-1234567890-abcdefGHIJ'"),
    ("SEC-SLACK-009", "URL = 'https://hooks.slack.com/services/T0ABCDEF12/B0ABCDEF12/aBcDeFgHiJkLmNoPqRsT12'", "URL = 'https://hooks.slack.com/docs'"),
    ("SEC-STRIPE-010", 'key = "sk_live_' + '51HxQ2bLkd8sJ2mN4pQ7rT9vW1yZ3aB5cD"', 'key = "sk_test_' + '51HxQ2bLkd8sJ2mN4pQ7rT9vW1yZ3aB5cD"'),
    ("SEC-STRIPE-010", 'key = "rk_live_' + '51HxQ2bLkd8sJ2mN4pQ7rT9vW1yZ3aB5cD"', 'key = "pk_live_' + '51HxQ2bLkd8sJ2mN4pQ7rT9vW1yZ3aB5cD"'),
    ("SEC-GCP-011", 'k = "AIzaSyD4f8Lk2Mn9Qp3Rs7Tu1Vw5Xy0Za6Bc8De"', 'k = "AIza-too-short"'),
    ("SEC-ANT-012", 'k = "sk-ant-api03-aB3dE5gH7jK9mN2pQ4rS6tU8vW0xY1zA2bC3"', 'k = "sk-ant-short"'),
    ("SEC-NPM-013", "t = npm_aB3dE5gH7jK9mN2pQ4rS6tU8vW0xY1zA2bC3", "t = npm_too_short"),
    ("SEC-PYPI-014", "t = pypi-AgEIcHlwaS5vcmcaB3dE5gH7jK9mN2pQ4rS6tU8vW0xY1zA2bC3dE5gH7jK9mN2pQ4", "t = pypi-notatoken"),
    ("SEC-AZURE-015", "CS = 'DefaultEndpointsProtocol=https;AccountKey=" + "A" * 86 + "=='", "CS = 'AccountKey=abc'"),
    ("SEC-TWILIO-016", "sid = 'SK" + "0123456789abcdef0123456789abcdef'", "sid = 'SKXYZ'"),
    ("SEC-SENDGRID-017", "k = 'SG.aB3dE5gH7jK9mN2pQ4rS6t.aB3dE5gH7jK9mN2pQ4rS6tU8vW0xY1zA2bC3dE5gH7jK'", "k = 'SG.short.short'"),
    ("SEC-DISCORD-018", "h = 'https://discord.com/api/webhooks/123456789012345678/" + "aB3dE5gH7jK9mN2pQ4rS6tU8vW0xY1zA2bC3dE5gH7jK9mN2pQ4rS6tU8vWxYz1Ab2Cd3Ef4Gh5" + "'", "h = 'https://discord.com/channels/123'"),
    ("SEC-TG-019", "bot = '123456789:AAH3dE5gH7jK9mN2pQ4rS6tU8vW0xY1zA2b'", "ratio = '12:30'"),
]


@pytest.mark.parametrize("rule_id, positive, negative", SECRET_CASES)
def test_new_secret_rules_positive_and_negative(rule_id, positive, negative):
    assert rule_id in ids("app/config.py", positive)
    assert rule_id not in ids("app/config.py", negative)


def test_openai_rule_does_not_report_anthropic_key():
    line = 'k = "sk-ant-api03-aB3dE5gH7jK9mN2pQ4rS6tU8vW0xY1zA2bC3"'
    assert "SEC-OAI-003" not in ids("app/config.py", line)
    assert "SEC-ANT-012" in ids("app/config.py", line)


def test_openai_key_still_detected():
    assert "SEC-OAI-003" in ids("app/config.py", 'k = "sk-proj-aB3dE5gH7jK9mN2pQ4rS6tU8vW0xY1zA2bC3"')


def test_openai_rule_ignores_words_containing_sk_dash():
    assert "SEC-OAI-003" not in ids("app/config.py", "run = 'task-runner-name-with-a-long-suffix-value'")


# --- Connection strings ---
def test_connection_string_with_real_password_is_flagged():
    assert "SEC-DB-020" in ids("app/db.py", 'URL = "postgres://app:s3cr3tPw@db.internal:5432/app"')
    assert "SEC-DB-020" in ids("app/db.py", "URL = 'mongodb+srv://svc:Zq8Lm2Pw@cluster0.example.net/x'")


@pytest.mark.parametrize(
    "line",
    [
        'URL = "postgres://user:password@localhost/app"',
        'URL = "mysql://user:${DB_PASS}@host/app"',
        'URL = "redis://user:<your-password>@host:6379"',
        'URL = "postgres://localhost:5432/app"',
    ],
)
def test_connection_string_placeholders_are_not_flagged(line):
    assert "SEC-DB-020" not in ids("app/db.py", line)


# --- Private keys ---
@pytest.mark.parametrize(
    "line",
    [
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN ENCRYPTED PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----BEGIN PGP PRIVATE KEY BLOCK-----",
    ],
)
def test_private_key_variants_are_flagged(line):
    assert "SEC-PRIVKEY-004" in ids("keys/server.txt", line)


def test_public_key_is_not_flagged():
    assert "SEC-PRIVKEY-004" not in ids("keys/server.txt", "-----BEGIN PUBLIC KEY-----")


# --- Generic password rule: placeholders and markdown scoping ---
@pytest.mark.parametrize(
    "value",
    ["changeme", "changeme123", "password", "xxxxxxxx", "********", "<your-password>", "${DB_PASS}", "{{ var }}",
     "os.getenv", "process.env.SECRET_VALUE"],
)
def test_placeholder_values_are_recognised(value):
    assert is_placeholder(value)


def test_real_value_is_not_placeholder():
    assert not is_placeholder("hunter2hunter2")


def test_generic_password_placeholder_not_flagged():
    assert "SEC-GEN-006" not in ids("app/settings.py", 'password = "changeme123"')
    assert "SEC-GEN-006" not in ids("app/settings.py", 'password = "xxxxxxxx"')


def test_generic_password_real_value_flagged():
    assert "SEC-GEN-006" in ids("app/settings.py", 'password = "hunter2hunter2"')


def test_generic_password_skipped_in_markdown_docs():
    assert "SEC-GEN-006" not in ids("docs/setup.md", 'password = "hunter2hunter2"')


# --- OWASP eval/exec rule ---
def test_literal_eval_is_not_flagged():
    assert "OWASP-A03-EVAL-003" not in ids("app/parse.py", "value = ast.literal_eval(raw)")


def test_regex_exec_is_not_flagged():
    assert "OWASP-A03-EVAL-003" not in ids("web/match.js", "const m = pattern.exec(text);")


@pytest.mark.parametrize(
    "line",
    ["result = eval(user_input)", "exec(code)", "builtins.eval(payload)", "value = eval(expr)"],
)
def test_eval_and_exec_calls_are_flagged(line):
    assert "OWASP-A03-EVAL-003" in ids("app/run.py", line)


# --- file_patterns / exclude_patterns scoping ---
def test_pickle_in_markdown_is_not_flagged():
    assert "OWASP-A08-PICKLE-004" not in ids("README.md", "data = pickle.loads(blob)")


def test_pickle_in_python_is_flagged():
    assert "OWASP-A08-PICKLE-004" in ids("app/load.py", "data = pickle.loads(blob)")


def test_dangerously_set_inner_html_only_in_js_family():
    line = "<div dangerouslySetInnerHTML={{ __html: html }} />"
    assert "OWASP-A03-XSS-006" in ids("ui/Card.tsx", line)
    assert "OWASP-A03-XSS-006" not in ids("notes/guide.md", line)
    assert "OWASP-A03-XSS-006" not in ids("app/render.py", line)


def test_python_rules_do_not_fire_on_markdown():
    assert "OWASP-A03-CMDI-002" not in ids("docs/x.md", "subprocess.run(cmd, shell=True)")
    assert "OWASP-A02-HASH-005" not in ids("docs/x.md", "hashlib.md5(data)")


def test_python_rules_fire_on_python():
    assert "OWASP-A03-CMDI-002" in ids("app/x.py", "subprocess.run(cmd, shell=True)")
    assert "OWASP-A02-HASH-005" in ids("app/x.py", "hashlib.md5(data)")


def test_file_pattern_matches_basename_in_nested_paths():
    rule = next(r for r in ENGINE.rules if r.id == "OWASP-A08-PICKLE-004")
    assert rule.applies_to("deep\\nested\\dir\\load.py")
    assert not rule.applies_to("deep/nested/dir/load.txt")


# --- Multiple matches per line ---
def test_every_distinct_match_on_a_line_is_reported():
    line = 'a = "AKIAIOSFODNN7EXAMPLE"; b = "AKIAIOSFODNN7EXAMPL2"'
    found = matches("app/keys.py", line, "SEC-AWS-001")
    assert found == ["AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPL2"]


def test_identical_match_reported_once_per_line():
    line = 'a = "AKIAIOSFODNN7EXAMPLE"; b = "AKIAIOSFODNN7EXAMPLE"'
    assert matches("app/keys.py", line, "SEC-AWS-001") == ["AKIAIOSFODNN7EXAMPLE"]


def test_finding_ids_are_unique_per_match():
    line = 'a = "AKIAIOSFODNN7EXAMPLE"; b = "AKIAIOSFODNN7EXAMPL2"'
    findings = ENGINE.scan_line("app/keys.py", 3, line)
    assert len({f.id for f in findings}) == len(findings)


# --- Dedupe of overlapping same-span findings ---
def test_same_span_findings_keep_highest_severity():
    from gitshield.core.models import Finding, RuleType, Severity
    from gitshield.rules.engine import dedupe_findings

    base = dict(
        title="t", description="d", rule_type=RuleType.SECRET, file_path="a.py", line_number=1,
        matched_text="same", id="x",
    )
    low = Finding(rule_id="LOW-1", severity=Severity.HIGH, **base)
    high = Finding(rule_id="HIGH-1", severity=Severity.CRITICAL, **base)
    result = dedupe_findings([low, high])
    assert len(result) == 1
    assert result[0].rule_id == "HIGH-1"
