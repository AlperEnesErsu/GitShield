import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from gitshield.ai import remediator
from gitshield.ai.remediator import DEFAULT_ADVICE, REDACTED, AIRemediator, redact_secrets
from gitshield.core.models import Finding, RuleType, Severity

AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
GH_TOKEN = "ghp_aB3dE5fG7hI9jK1lM2nO4pQ6rS8tU0vW2xY4"
ENTROPY_TOKEN = "q7Rv2XbN9kLm4TpW8zHc3Yd6Jf1Gs5Ua"
FALLBACK = "Load the key from the environment."
PROVIDER_ENV = ("LLM_PROVIDER", "LLM_MODEL", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _finding(**overrides: Any) -> Finding:
    values: dict[str, Any] = dict(
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
        suggested_fix=FALLBACK,
    )
    values.update(overrides)
    return Finding(**values)


def _mock_http(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    """Route every httpx.Client created by the remediator through a MockTransport."""
    seen: list[httpx.Request] = []
    real_client = httpx.Client

    def recording_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(recording_handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(remediator.httpx, "Client", factory)
    return seen


def _json_response(body: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


# ---- provider selection -------------------------------------------------

def test_selects_anthropic_when_only_anthropic_key_set(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    r = AIRemediator()
    assert r.provider == "anthropic"
    assert r.api_key == "sk-ant-test"
    assert r.model == "claude-opus-5-5"


def test_selection_order_is_anthropic_gemini_openai(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPENAI_API_KEY", "o")
    clean_env.setenv("GEMINI_API_KEY", "g")
    assert AIRemediator().provider == "gemini"
    clean_env.setenv("ANTHROPIC_API_KEY", "a")
    assert AIRemediator().provider == "anthropic"


def test_selects_openai_with_default_model(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPENAI_API_KEY", "o-test")
    r = AIRemediator()
    assert r.provider == "openai"
    assert r.model == "gpt-5"


def test_llm_provider_env_overrides_detection(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("ANTHROPIC_API_KEY", "a")
    clean_env.setenv("LLM_PROVIDER", "gemini")
    r = AIRemediator()
    assert r.provider == "gemini"
    assert r.api_key is None  # no GEMINI_API_KEY, so the explicit provider has no key


def test_llm_model_env_overrides_default(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GEMINI_API_KEY", "g")
    clean_env.setenv("LLM_MODEL", "gemini-2.5-pro")
    assert AIRemediator().model == "gemini-2.5-pro"


def test_no_keys_means_no_provider(clean_env: pytest.MonkeyPatch) -> None:
    r = AIRemediator()
    assert r.provider is None
    assert r.api_key is None


# ---- request shapes -----------------------------------------------------

def test_anthropic_request_shape(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    body = {"content": [{"type": "text", "text": "Use os.getenv.\n```python\nx = os.getenv('K')\n```"}]}
    seen = _mock_http(clean_env, lambda req: _json_response(body))

    out = AIRemediator().generate_fix(_finding())

    assert out.startswith("Use os.getenv.")
    req = seen[0]
    assert str(req.url) == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == "sk-ant-test"
    assert req.headers["anthropic-version"] == "2023-06-01"
    sent = json.loads(req.content)
    assert sent["model"] == "claude-opus-5-5"
    assert "system" in sent and sent["messages"][0]["role"] == "user"


def test_gemini_key_is_sent_in_header_not_url(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GEMINI_API_KEY", "gem-secret-key")
    body = {"candidates": [{"content": {"parts": [{"text": "Fixed version"}]}}]}
    seen = _mock_http(clean_env, lambda req: _json_response(body))

    out = AIRemediator().generate_fix(_finding())

    assert out == "Fixed version"
    req = seen[0]
    assert str(req.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    )
    assert "key=" not in str(req.url)
    assert "gem-secret-key" not in str(req.url)
    assert req.headers["x-goog-api-key"] == "gem-secret-key"
    assert b"gem-secret-key" not in req.content


def test_openai_request_shape(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPENAI_API_KEY", "sk-openai-test")
    body = {"choices": [{"message": {"content": "Use env vars."}}]}
    seen = _mock_http(clean_env, lambda req: _json_response(body))

    out = AIRemediator().generate_fix(_finding())

    assert out == "Use env vars."
    req = seen[0]
    assert str(req.url) == "https://api.openai.com/v1/chat/completions"
    assert req.headers["Authorization"] == "Bearer sk-openai-test"
    sent = json.loads(req.content)
    assert sent["model"] == "gpt-5"
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]


# ---- error paths --------------------------------------------------------

def test_http_error_returns_labelled_fallback_without_key(clean_env: pytest.MonkeyPatch) -> None:
    key = "gem-secret-key-123"
    clean_env.setenv("GEMINI_API_KEY", key)
    body = {"error": {"message": f"API key not valid: {key}"}}
    _mock_http(clean_env, lambda req: _json_response(body, status=400))

    out = AIRemediator().generate_fix(_finding())

    assert out.startswith("LLM error (gemini): ")
    assert f"Default advice: {FALLBACK}" in out
    assert key not in out


def test_timeout_returns_fallback(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPENAI_API_KEY", "sk-openai-test")

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=req)

    _mock_http(clean_env, handler)

    out = AIRemediator().generate_fix(_finding())

    assert out.startswith("LLM error (openai): no response within 60s")
    assert f"Default advice: {FALLBACK}" in out


def test_missing_key_for_explicit_provider_is_reported(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("LLM_PROVIDER", "anthropic")
    out = AIRemediator().generate_fix(_finding())
    assert out == f"LLM error (anthropic): ANTHROPIC_API_KEY is not set. Default advice: {FALLBACK}"


def test_no_key_path_returns_rule_remediation(clean_env: pytest.MonkeyPatch) -> None:
    assert AIRemediator().generate_fix(_finding()) == FALLBACK
    assert AIRemediator().generate_fix(_finding(suggested_fix=None)) == DEFAULT_ADVICE


# ---- redaction and context ----------------------------------------------

def test_redact_secrets_removes_aws_github_and_entropy_tokens() -> None:
    text = "\n".join([
        "import os",
        f'AWS = "{AWS_KEY}"',
        f'GH = "{GH_TOKEN}"',
        f'TOKEN = "{ENTROPY_TOKEN}"',
        "print('hello')",
    ])

    out = redact_secrets(text)

    assert AWS_KEY not in out
    assert GH_TOKEN not in out
    assert ENTROPY_TOKEN not in out
    assert out.count(REDACTED) == 3
    assert "import os" in out and "print('hello')" in out
    assert out.count("\n") == text.count("\n")


def test_redact_secrets_leaves_plain_text_alone() -> None:
    assert redact_secrets("") == ""
    assert redact_secrets("x = 1") == "x = 1"


def test_generate_fix_sends_only_redacted_context(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clean_env.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    src = tmp_path / "app" / "config.py"
    src.parent.mkdir()
    src.write_text("\n".join([
        "import os",
        f'AWS_KEY = "{AWS_KEY}"',
        f'GH = "{GH_TOKEN}"',
        "def main():",
        "    return AWS_KEY",
    ]) + "\n", encoding="utf-8")
    seen = _mock_http(clean_env, lambda req: _json_response({"content": [{"type": "text", "text": "ok"}]}))

    AIRemediator().generate_fix(_finding(line_number=2), repo_path=tmp_path)

    sent = seen[0].content.decode("utf-8")
    assert AWS_KEY not in sent
    assert GH_TOKEN not in sent
    assert REDACTED in sent
    assert ">> AWS_KEY" in sent  # the finding line is marked
    assert "def main():" in sent  # surrounding lines are included


def test_generate_fix_uses_explicit_file_context_and_redacts_it(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPENAI_API_KEY", "sk-openai-test")
    seen = _mock_http(clean_env, lambda req: _json_response({"choices": [{"message": {"content": "ok"}}]}))

    AIRemediator().generate_fix(_finding(), file_context=f'x = "{AWS_KEY}"\ny = 2')

    sent = seen[0].content.decode("utf-8")
    assert AWS_KEY not in sent
    assert "y = 2" in sent


def test_generate_fix_redacts_entropy_match_text(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPENAI_API_KEY", "sk-openai-test")
    seen = _mock_http(clean_env, lambda req: _json_response({"choices": [{"message": {"content": "ok"}}]}))
    finding = _finding(
        rule_id="ENT-001",
        rule_type=RuleType.ENTROPY,
        matched_text=ENTROPY_TOKEN,
        context=f'token = "{ENTROPY_TOKEN}"',
    )

    AIRemediator().generate_fix(finding)

    assert ENTROPY_TOKEN not in seen[0].content.decode("utf-8")
