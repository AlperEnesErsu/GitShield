"""Outbound notifications (Slack / Discord webhooks, Telegram bot) for finished reviews."""

import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)


def channels() -> list[str]:
    found = []
    if os.getenv("GITSHIELD_SLACK_WEBHOOK"):
        found.append("slack")
    if os.getenv("GITSHIELD_DISCORD_WEBHOOK"):
        found.append("discord")
    if os.getenv("GITSHIELD_TELEGRAM_BOT_TOKEN") and os.getenv("GITSHIELD_TELEGRAM_CHAT_ID"):
        found.append("telegram")
    return found


def app_url() -> str:
    return os.getenv("GITSHIELD_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")


def review_message(review: dict[str, Any]) -> str:
    link = f"{app_url()}/r/{review['repo']}/pull/{review['pr_number']}"
    head = f"🛡️ GitShield · {review['repo']} #{review['pr_number']} — {review.get('pr_title', '')}".rstrip(" —")
    if review["status"] == "failed":
        return f"{head}\n❌ İnceleme başarısız: {review.get('error') or 'bilinmeyen hata'}\n{link}"
    comments = [c for c in review.get("comments", []) if c.get("included")]
    serious = sum(1 for c in comments if c["severity"] in ("CRITICAL", "HIGH"))
    verdict = {"APPROVE": "Onay", "REQUEST_CHANGES": "Değişiklik iste", "COMMENT": "Yorum"}.get(review["verdict"], "")
    detail = f"{len(comments)} yorum" + (f", {serious} yüksek önemli" if serious else "")
    return f"{head}\n✅ Review onayını bekliyor · önerilen karar: {verdict} · {detail}\n{link}"


async def send(text: str) -> dict[str, str]:
    """Send ``text`` to every configured channel; returns channel -> 'ok' or an error message."""
    results: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=15.0) as client:
        for channel in channels():
            try:
                if channel == "slack":
                    resp = await client.post(os.environ["GITSHIELD_SLACK_WEBHOOK"], json={"text": text})
                elif channel == "discord":
                    resp = await client.post(os.environ["GITSHIELD_DISCORD_WEBHOOK"], json={"content": text})
                else:
                    token = os.environ["GITSHIELD_TELEGRAM_BOT_TOKEN"]
                    resp = await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
                        "chat_id": os.environ["GITSHIELD_TELEGRAM_CHAT_ID"], "text": text,
                        "disable_web_page_preview": True,
                    })
                results[channel] = "ok" if resp.status_code < 300 else f"HTTP {resp.status_code}"
            except httpx.HTTPError as e:
                results[channel] = e.__class__.__name__
    for channel, result in results.items():
        if result != "ok":
            log.warning("Notification via %s failed: %s", channel, result)
    return results


async def notify_review(review: dict[str, Any]) -> None:
    """Best-effort: a notification failure must never fail the review."""
    if not channels() or review.get("status") not in ("ready", "failed"):
        return
    try:
        await send(review_message(review))
    except Exception:  # noqa: BLE001 - notifications are fire-and-forget
        log.exception("Notification failed")
