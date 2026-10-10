"""Provider-agnostic structured LLM calls (Anthropic, Gemini, OpenAI).

Every provider exposes ``complete(system, user, schema)`` and returns a validated
instance of ``schema`` (a Pydantic model).
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Literal, Protocol, TypeVar, cast

import httpx
from pydantic import BaseModel, ValidationError

from gitshield.web.config import settings
from gitshield.web.db import Database

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class LLMUnavailable(LLMError):
    """The provider did not answer (timeout, dropped connection, 5xx): worth trying another model."""


class LLMProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def complete(self, system: str, user: str, schema: type[T]) -> T: ...


def _parse_json(text: str, schema: type[T]) -> T:
    """Validate model output, tolerating a surrounding ```json fence."""
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    try:
        return schema.model_validate_json(cleaned)
    except ValidationError as e:
        raise LLMError(f"Model returned JSON that does not match the schema: {e}") from e


LLM_TIMEOUT_SEC = 150
LLM_ATTEMPTS = 2
RETRY_DELAY_SEC = 5


async def post_with_retry(vendor: str, url: str, **kwargs: Any) -> httpx.Response:
    """POST to an LLM API, retrying once on a timeout, a dropped connection or a 5xx answer.
    A single slow or flaky call should not fail a whole (possibly unattended) review."""
    last: Exception | None = None
    for attempt in range(LLM_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SEC) as client:
                resp = await client.post(url, **kwargs)
            if resp.status_code < 500 or attempt == LLM_ATTEMPTS - 1:
                return resp
        except httpx.TimeoutException as e:
            last = e
        except httpx.TransportError as e:
            last = e
        await asyncio.sleep(RETRY_DELAY_SEC)
    if isinstance(last, httpx.TimeoutException):
        raise LLMUnavailable(f"{vendor} {LLM_ATTEMPTS} denemede de {LLM_TIMEOUT_SEC} sn içinde yanıt vermedi; "
                       "servis yavaş olabilir, birazdan yeniden incele.") from last
    raise LLMUnavailable(f"{vendor} API'sine bağlanılamadı ({last.__class__.__name__}); ağ bağlantını kontrol et.") from last


def http_error_message(vendor: str, model: str, resp: httpx.Response) -> str:
    """Readable, actionable text for the common provider failures; raw detail otherwise."""
    try:
        detail = resp.json().get("error", {}).get("message", "")
    except ValueError:
        detail = resp.text
    first_line = (detail or resp.text).strip().splitlines()[0][:200] if (detail or resp.text).strip() else ""
    code = resp.status_code
    if code == 429:
        retry = re.search(r"retry in ([\d.]+)s", detail or "", re.I)
        wait = f" ~{round(float(retry.group(1)))} sn sonra tekrar dene." if retry else " Biraz bekleyip tekrar dene."
        hint = ""
        if vendor == "Gemini" and "free_tier" in (detail or "") and "pro" in model:
            hint = " Ücretsiz katmanda Pro modellerin kotası yok; LLM_MODEL=gemini-flash-latest kullan."
        return f"{vendor} kotası ya da hız limiti doldu ({model}).{wait}{hint}"
    if code in (401, 403):
        return f"{vendor} API anahtarı geçersiz ya da bu modele erişimi yok ({model}). .env'deki anahtarı kontrol et."
    if code == 404:
        return f"{vendor} modeli bulunamadı ya da kullanımdan kalktı: {model}. LLM_MODEL ile başka bir model seç."
    if code >= 500:
        return f"{vendor} şu an yanıt vermiyor ({code}); birazdan tekrar dene."
    return f"{vendor} API hatası ({code}): {first_line}"


def _schema_instruction(schema: type[BaseModel]) -> str:
    return (
        "\n\nRespond with a single JSON object (no prose, no code fence) that matches this "
        f"JSON Schema:\n{json.dumps(schema.model_json_schema())}"
    )


EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]
EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, effort: str = "medium"):
        import anthropic

        self.model = model
        if effort not in EFFORT_LEVELS:
            log.warning("LLM_EFFORT=%r is not one of %s; using medium", effort, ", ".join(EFFORT_LEVELS))
            effort = "medium"
        self.effort = cast(EffortLevel, effort)
        self._anthropic = anthropic
        self._client = anthropic.AsyncAnthropic()

    async def complete(self, system: str, user: str, schema: type[T]) -> T:
        anthropic = self._anthropic
        try:
            response = await self._client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                output_config={"effort": self.effort},
                # Re-run on Anthropic's recommended model if a safety classifier declines.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as e:
            raise LLMError("Anthropic API key is invalid.") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Anthropic rate limit reached; retry shortly.") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Anthropic API error ({e.status_code}): {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Could not reach the Anthropic API.") from e

        if response.stop_reason == "refusal":
            raise LLMError("The model declined to review this content.")
        if response.stop_reason == "max_tokens":
            raise LLMError("Model output hit max_tokens before finishing the review.")
        if response.parsed_output is None:
            raise LLMError("Model returned no structured output.")
        return response.parsed_output


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: str, fallback: str | None = None):
        self.model = model
        self.fallback = fallback if fallback and fallback != model else None
        self._key = os.getenv("GEMINI_API_KEY", "")

    async def complete(self, system: str, user: str, schema: type[T]) -> T:
        try:
            return await self._complete(self.model, system, user, schema)
        except LLMUnavailable:
            if not self.fallback:
                raise
            # The primary model hangs or is down (a "-latest" alias can point at an overloaded
            # model); the same request on the fallback model keeps the review going.
            log.warning("Gemini %s unavailable, retrying on %s", self.model, self.fallback)
            self.model, self.fallback = self.fallback, None
            return await self._complete(self.model, system, user, schema)

    async def _complete(self, model: str, system: str, user: str, schema: type[T]) -> T:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system + _schema_instruction(schema)}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        resp = await post_with_retry("Gemini", url, json=payload, headers={"x-goog-api-key": self._key})
        if resp.status_code >= 500:
            raise LLMUnavailable(http_error_message("Gemini", model, resp))
        if resp.status_code != 200:
            raise LLMError(http_error_message("Gemini", model, resp))
        try:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise LLMError("Gemini returned no content.") from e
        return _parse_json(text, schema)


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str):
        self.model = model
        self._key = os.getenv("OPENAI_API_KEY", "")

    async def complete(self, system: str, user: str, schema: type[T]) -> T:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system + _schema_instruction(schema)},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        resp = await post_with_retry("OpenAI", "https://api.openai.com/v1/chat/completions",
                                     json=payload, headers={"Authorization": f"Bearer {self._key}"})
        if resp.status_code != 200:
            raise LLMError(http_error_message("OpenAI", self.model, resp))
        try:
            text = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError("OpenAI returned no content.") from e
        return _parse_json(text, schema)


class BudgetedProvider:
    """Every LLM request goes through here first: a daily cap (GITSHIELD_MAX_LLM_CALLS_PER_DAY)
    stops runaway spend from unattended auto-reviews, retries and repeated clicks."""

    def __init__(self, inner: LLMProvider, db: Database, daily_limit: int):
        self._inner = inner
        self._db = db
        self._limit = daily_limit

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def model(self) -> str:
        return self._inner.model

    async def complete(self, system: str, user: str, schema: type[T]) -> T:
        if not self._db.reserve_llm_call(self._limit):
            raise LLMError(
                f"Günlük LLM çağrı limiti doldu ({self._limit} çağrı / 24 sa). "
                "Yarın tekrar dene ya da GITSHIELD_MAX_LLM_CALLS_PER_DAY ile limiti artır."
            )
        return await self._inner.complete(system, user, schema)


def _make_provider() -> LLMProvider | None:
    provider = settings.llm_provider
    model = settings.llm_model
    if provider == "anthropic":
        return AnthropicProvider(model, settings.llm_effort)
    if provider == "gemini":
        return GeminiProvider(model, settings.llm_fallback_model)
    if provider == "openai":
        return OpenAIProvider(model)
    return None


def get_provider(db: Database) -> LLMProvider | None:
    """Return the configured provider (metered against the daily budget), or None when running
    scanner-only."""
    provider = _make_provider()
    if provider is None:
        return None
    return BudgetedProvider(provider, db, settings.max_llm_calls_per_day)
