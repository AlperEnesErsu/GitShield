import asyncio

import httpx
import pytest

pytest.importorskip("fastapi")

from gitshield.web import llm
from gitshield.web.llm import LLMError, post_with_retry


@pytest.fixture()
def fake_http(monkeypatch):
    """Route post_with_retry's httpx client through a scripted handler; no real network, no waiting."""
    script = []
    calls = []

    def handler(request):
        calls.append(request.url.path)
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    real_client = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(llm, "RETRY_DELAY_SEC", 0)
    return script, calls


def run(coro):
    return asyncio.run(coro)


def test_retries_once_after_a_timeout(fake_http):
    script, calls = fake_http
    script += [httpx.ReadTimeout("slow"), httpx.Response(200, json={"ok": True})]
    resp = run(post_with_retry("Gemini", "https://llm.test/v1/generate", json={}))
    assert resp.status_code == 200 and len(calls) == 2


def test_retries_once_after_a_server_error(fake_http):
    script, calls = fake_http
    script += [httpx.Response(503), httpx.Response(200, json={"ok": True})]
    assert run(post_with_retry("Gemini", "https://llm.test/v1/generate", json={})).status_code == 200


def test_client_errors_are_not_retried(fake_http):
    script, calls = fake_http
    script += [httpx.Response(429, json={"error": {"message": "quota"}})]
    assert run(post_with_retry("Gemini", "https://llm.test/v1/generate", json={})).status_code == 429
    assert len(calls) == 1


def test_gemini_falls_back_to_another_model_when_the_primary_hangs(fake_http):
    from pydantic import BaseModel

    class Ping(BaseModel):
        ok: bool

    script, calls = fake_http
    answer = {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}
    script += [httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"), httpx.Response(200, json=answer)]
    provider = llm.GeminiProvider("gemini-flash-latest", fallback="gemini-3.5-flash")
    result = run(provider.complete("sys", "user", Ping))
    assert result.ok is True
    assert calls[-1].endswith("/models/gemini-3.5-flash:generateContent")
    assert provider.model == "gemini-3.5-flash", "later calls of the same review stay on the working model"


def test_quota_errors_do_not_trigger_the_fallback(fake_http):
    from pydantic import BaseModel

    class Ping(BaseModel):
        ok: bool

    script, calls = fake_http
    script += [httpx.Response(429, json={"error": {"message": "quota"}})]
    provider = llm.GeminiProvider("gemini-flash-latest", fallback="gemini-3.5-flash")
    with pytest.raises(LLMError):
        run(provider.complete("sys", "user", Ping))
    assert len(calls) == 1


def test_gives_a_readable_error_after_repeated_timeouts(fake_http):
    script, calls = fake_http
    script += [httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow")]
    with pytest.raises(LLMError) as err:
        run(post_with_retry("Gemini", "https://llm.test/v1/generate", json={}))
    assert "yanıt vermedi" in str(err.value) and "ReadTimeout" not in str(err.value)
