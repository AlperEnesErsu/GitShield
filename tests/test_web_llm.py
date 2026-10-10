import httpx
import pytest

pytest.importorskip("fastapi")

from gitshield.web.llm import http_error_message


def resp(code, message):
    return httpx.Response(code, json={"error": {"message": message}})


def test_gemini_quota_message_with_retry_and_pro_hint():
    text = http_error_message("Gemini", "gemini-pro-latest", resp(
        429, "Quota exceeded for metric: generate_content_free_tier_requests, limit: 0. Please retry in 41.5s."))
    assert "kotası" in text and "~42 sn" in text and "gemini-flash-latest" in text


@pytest.mark.parametrize("code,needle", [(401, "anahtar"), (404, "kullanımdan kalktı"), (503, "yanıt vermiyor"),
                                         (400, "API hatası (400)")])
def test_other_errors(code, needle):
    assert needle in http_error_message("OpenAI", "gpt-x", resp(code, "boom"))


def test_non_json_body():
    assert "API hatası (400): plain" in http_error_message("Gemini", "m", httpx.Response(400, text="plain text"))
