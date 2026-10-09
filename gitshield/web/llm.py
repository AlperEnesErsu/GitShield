"""Provider-agnostic structured LLM calls (Anthropic, Gemini, OpenAI).

Every provider exposes ``complete(system, user, schema)`` and returns a validated
instance of ``schema`` (a Pydantic model).
"""

import json
import os
import re
from typing import Optional, Protocol, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from gitshield.web.config import settings

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(self, system: str, user: str, schema: Type[T]) -> T: ...


def _parse_json(text: str, schema: Type[T]) -> T:
    """Validate model output, tolerating a surrounding ```json fence."""
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    try:
        return schema.model_validate_json(cleaned)
    except ValidationError as e:
        raise LLMError(f"Model returned JSON that does not match the schema: {e}") from e


def _schema_instruction(schema: Type[BaseModel]) -> str:
    return (
        "\n\nRespond with a single JSON object (no prose, no code fence) that matches this "
        f"JSON Schema:\n{json.dumps(schema.model_json_schema())}"
    )


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str):
        import anthropic

        self.model = model
        self._anthropic = anthropic
        self._client = anthropic.AsyncAnthropic()

    async def complete(self, system: str, user: str, schema: Type[T]) -> T:
        anthropic = self._anthropic
        try:
            response = await self._client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                output_config={"effort": "high"},
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

    def __init__(self, model: str):
        self.model = model
        self._key = os.getenv("GEMINI_API_KEY", "")

    async def complete(self, system: str, user: str, schema: Type[T]) -> T:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system + _schema_instruction(schema)}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(url, json=payload, headers={"x-goog-api-key": self._key})
        if resp.status_code != 200:
            raise LLMError(f"Gemini API error ({resp.status_code}): {resp.text[:300]}")
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

    async def complete(self, system: str, user: str, schema: Type[T]) -> T:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system + _schema_instruction(schema)},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self._key}"},
            )
        if resp.status_code != 200:
            raise LLMError(f"OpenAI API error ({resp.status_code}): {resp.text[:300]}")
        try:
            text = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError("OpenAI returned no content.") from e
        return _parse_json(text, schema)


def get_provider() -> Optional[LLMProvider]:
    """Return the configured provider, or None when running scanner-only."""
    provider = settings.llm_provider
    model = settings.llm_model
    if provider == "anthropic":
        return AnthropicProvider(model)
    if provider == "gemini":
        return GeminiProvider(model)
    if provider == "openai":
        return OpenAIProvider(model)
    return None
