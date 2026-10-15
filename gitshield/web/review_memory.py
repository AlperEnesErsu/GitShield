"""Repo-memory helpers: prompt text, suppression matching and fingerprints."""

import hashlib
import logging
import re
from typing import Any

log = logging.getLogger(__name__)


def memory_prompt(memory: list[dict[str, Any]]) -> str:
    """Render active repo memory for the reviewer and verifier prompts ('' when empty)."""
    rules = [m for m in memory if m["kind"] == "rule"]
    dismissed = [m for m in memory if m["kind"] == "suppress"]
    if not rules and not dismissed:
        return ""
    parts = []
    if rules:
        parts.append("Maintainer rules for this repository:\n" + "\n".join(f"- {m['text']}" for m in rules))
    if dismissed:
        parts.append("Dismissed by the maintainers, do not raise again:\n" + "\n".join(
            f"- [{m['path'] or 'whole repository'}] {m['text']}" for m in dismissed))
    return "<repo_memory>\n" + "\n\n".join(parts) + "\n</repo_memory>\n\n"


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def suppressing_memory(c: dict[str, Any], memory: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Deterministic match: same scanner rule, or the exact same title, within the memory's scope."""
    for m in memory:
        if m["kind"] != "suppress" or (m["path"] and m["path"] != c["path"]):
            continue
        if m["rule_id"] and m["rule_id"] == c.get("rule_id"):
            return m
        if not m["rule_id"] and _norm(m["text"].split(":", 1)[0]) == _norm(c["title"]):
            return m
    return None


def fingerprint(path: str, key: str) -> str:
    return hashlib.sha1(f"{path}:{key.lower().strip()}".encode()).hexdigest()[:16]
