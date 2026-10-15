
from fastapi import APIRouter, HTTPException

from gitshield.web.notify import app_url
from gitshield.web.notify import channels as notify_channels
from gitshield.web.notify import send as send_notification

router = APIRouter()


@router.get("/api/notifications")
async def notifications_status():
    return {"channels": notify_channels(), "app_url": app_url()}


@router.post("/api/notifications/test")
async def notifications_test():
    if not notify_channels():
        raise HTTPException(409, "Bildirim kanalı tanımlı değil (.env: GITSHIELD_SLACK_WEBHOOK, "
                                 "GITSHIELD_DISCORD_WEBHOOK veya GITSHIELD_TELEGRAM_BOT_TOKEN + _CHAT_ID).")
    return {"results": await send_notification("🛡️ GitShield test bildirimi — kanal çalışıyor.")}
