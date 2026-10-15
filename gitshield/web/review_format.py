"""Markdown formatting of comments and draft-issue bodies."""

import logging
from typing import Any

from gitshield.web.review_schemas import SEVERITY_ICON

log = logging.getLogger(__name__)


def format_comment_markdown(c: dict[str, Any]) -> str:
    text = f"**{SEVERITY_ICON.get(c['severity'], '')} [{c['severity']}] {c['title']}**\n\n{c['body']}"
    if c.get("suggestion"):
        text += f"\n\n**Öneri:**\n```\n{c['suggestion']}\n```"
    return text


def draft_issue_body(c: dict[str, Any], pr: dict[str, Any], html_base: str) -> str:
    location = f"{html_base}/blob/{pr['head']['sha']}/{c['path']}#L{c['line']}"
    body = (
        f"GitShield, PR [#{pr['number']} {pr['title']}]({pr['html_url']}) incelemesinde bu sorunu "
        f"tespit etti.\n\n"
        f"- **Önem:** {c['severity']}\n- **Kategori:** {c['category']}\n"
        f"- **Konum:** [`{c['path']}:{c['line']}`]({location})\n"
    )
    if c.get("rule_id"):
        body += f"- **Kural:** `{c['rule_id']}`\n"
    body += f"\n{c['body']}\n"
    if c.get("suggestion"):
        body += f"\n**Önerilen düzeltme:**\n```\n{c['suggestion']}\n```\n"
    if c.get("verification_note"):
        body += f"\n> Doğrulayıcı notu: {c['verification_note']}\n"
    return body
