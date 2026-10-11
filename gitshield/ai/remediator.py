import functools
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from gitshield.ai.prompts import SYSTEM_REMEDIATION_PROMPT, USER_REMEDIATION_TEMPLATE
from gitshield.core.entropy import find_high_entropy_tokens
from gitshield.core.models import Finding, RuleType
from gitshield.rules.engine import RuleEngine

REDACTED = "<REDACTED_SECRET>"
SECRET_TYPES = (RuleType.SECRET, RuleType.ENTROPY)
DEFAULT_ADVICE = "Review code security according to best practices."
TIMEOUT_SEC = 60.0
CONTEXT_RADIUS = 8
MAX_OUTPUT_TOKENS = 2048

PROVIDERS = ("anthropic", "gemini", "openai")
KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}
DEFAULT_MODELS = {
    "anthropic": "claude-opus-5-5",
    "gemini": "gemini-flash-latest",
    "openai": "gpt-5",
}
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class LLMCallError(Exception):
    """A provider call failed. The message never contains the API key."""


@functools.lru_cache(maxsize=1)
def _rule_engine() -> RuleEngine:
    return RuleEngine()


def redact_secrets(text: str) -> str:
    """Replace every detected secret in text with a placeholder before it leaves the machine."""
    if not text:
        return text
    engine = _rule_engine()
    out_lines: list[str] = []
    for line in text.split("\n"):
        secrets = set()
        for finding in engine.scan_line("", 0, line):
            if finding.rule_type in SECRET_TYPES and len(finding.matched_text) >= 4:
                secrets.add(finding.matched_text)
        for token, _ in find_high_entropy_tokens(line):
            secrets.add(token)
        for secret in sorted(secrets, key=len, reverse=True):
            line = line.replace(secret, REDACTED)
        out_lines.append(line)
    return "\n".join(out_lines)


def _resolve_provider(explicit: str | None, api_key: str | None) -> str | None:
    """LLM_PROVIDER wins; otherwise the first provider whose API key is in the environment."""
    name = (explicit or os.getenv("LLM_PROVIDER") or "").strip().lower()
    if name:
        return name
    for provider in PROVIDERS:
        if os.getenv(KEY_ENV[provider]):
            return provider
    if api_key:
        return "gemini"
    return None


def _read_surrounding_lines(repo_path: Path, finding: Finding) -> str | None:
    """Return the lines around the finding from the file on disk, marking the finding line."""
    try:
        root = repo_path.resolve()
        target = (root / finding.file_path).resolve()
        target.relative_to(root)
        if not target.is_file():
            return None
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, ValueError):
        return None
    idx = finding.line_number - 1
    if not 0 <= idx < len(lines):
        return None
    start = max(0, idx - CONTEXT_RADIUS)
    end = min(len(lines), idx + CONTEXT_RADIUS + 1)
    return "\n".join((">> " if i == idx else "   ") + lines[i] for i in range(start, end))


def _text_from_parts(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str))


class AIRemediator:
    def __init__(
        self,
        api_key: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ):
        self.provider = _resolve_provider(provider, api_key)
        key_env = KEY_ENV.get(self.provider or "", "")
        self.api_key = api_key or (os.getenv(key_env) if key_env else None) or None
        self.model = model or os.getenv("LLM_MODEL") or DEFAULT_MODELS.get(self.provider or "", "")

    def generate_fix(
        self,
        finding: Finding,
        file_context: str | None = None,
        repo_path: Path | None = None,
    ) -> str:
        """Ask the configured LLM for a suggested replacement; falls back to rule advice."""
        fallback = finding.suggested_fix or DEFAULT_ADVICE
        if not self.provider:
            return fallback
        if self.provider not in PROVIDERS:
            return self._fallback(f"unsupported LLM_PROVIDER '{self.provider}'", fallback)
        if not self.api_key:
            return self._fallback(f"{KEY_ENV[self.provider]} is not set", fallback)

        user = USER_REMEDIATION_TEMPLATE.format(
            file_path=finding.file_path,
            line_number=finding.line_number,
            rule_id=finding.rule_id,
            title=finding.title,
            severity=finding.severity.value,
            cwe=finding.cwe or "N/A",
            context=self._build_context(finding, file_context, repo_path),
        )
        try:
            return self._complete(SYSTEM_REMEDIATION_PROMPT, user)
        except LLMCallError as e:
            return self._fallback(str(e), fallback)

    def _fallback(self, reason: str, fallback: str) -> str:
        reason = reason.replace(self.api_key, "<redacted>") if self.api_key else reason
        return f"LLM error ({self.provider}): {reason}. Default advice: {fallback}"

    def _build_context(
        self,
        finding: Finding,
        file_context: str | None,
        repo_path: Path | None,
    ) -> str:
        raw = file_context
        if raw is None and repo_path is not None:
            raw = _read_surrounding_lines(repo_path, finding)
        if raw is None:
            raw = finding.context or finding.matched_text
        safe = redact_secrets(raw)
        if finding.rule_type in SECRET_TYPES and finding.matched_text:
            safe = safe.replace(finding.matched_text, REDACTED)
        return safe.replace("</code>", "&lt;/code&gt;")

    def _complete(self, system: str, user: str) -> str:
        key = self.api_key or ""
        try:
            if self.provider == "anthropic":
                data = self._post(
                    ANTHROPIC_URL,
                    {"x-api-key": key, "anthropic-version": "2023-06-01"},
                    {
                        "model": self.model,
                        "max_tokens": MAX_OUTPUT_TOKENS,
                        "system": system,
                        "messages": [{"role": "user", "content": user}],
                    },
                )
                text = "".join(
                    b.get("text", "")
                    for b in data.get("content", [])
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            elif self.provider == "gemini":
                url = GEMINI_URL.format(model=quote(self.model, safe=""))
                data = self._post(
                    url,
                    {"x-goog-api-key": key},
                    {
                        "systemInstruction": {"parts": [{"text": system}]},
                        "contents": [{"role": "user", "parts": [{"text": user}]}],
                    },
                )
                candidates = data.get("candidates") or []
                text = _text_from_parts((candidates[0].get("content") or {}).get("parts")) if candidates else ""
            else:
                data = self._post(
                    OPENAI_URL,
                    {"Authorization": f"Bearer {key}"},
                    {
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    },
                )
                choices = data.get("choices") or []
                message = choices[0].get("message") or {} if choices else {}
                text = message.get("content") or ""
        except (AttributeError, TypeError, IndexError) as e:
            raise LLMCallError("unexpected response format") from e

        text = text.strip() if isinstance(text, str) else ""
        if not text:
            raise LLMCallError("the model returned an empty answer")
        return text

    def _post(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=TIMEOUT_SEC) as client:
                resp = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as e:
            raise LLMCallError(f"no response within {int(TIMEOUT_SEC)}s") from e
        except httpx.HTTPError as e:
            raise LLMCallError(f"network error ({e.__class__.__name__})") from e

        if resp.status_code != 200:
            raise LLMCallError(f"HTTP {resp.status_code}: {_error_detail(resp)}")
        try:
            data = resp.json()
        except ValueError as e:
            raise LLMCallError("response was not JSON") from e
        if not isinstance(data, dict):
            raise LLMCallError("unexpected response format")
        return data


def _error_detail(resp: httpx.Response) -> str:
    """First line of the provider's error message, without echoing the request."""
    try:
        body = resp.json()
        err = body.get("error") if isinstance(body, dict) else None
        message = err.get("message", "") if isinstance(err, dict) else str(err or "")
    except ValueError:
        message = ""
    first = message.strip().splitlines()[0][:200] if message.strip() else ""
    return first or "no details"
