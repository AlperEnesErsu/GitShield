from typing import Any

from fastapi import APIRouter, Request

from gitshield.web.activity import build_activity
from gitshield.web.routes.deps import gh

router = APIRouter()


@router.get("/api/activity")
async def activity(request: Request, refresh: bool = False) -> dict[str, Any]:
    return build_activity(await gh(request).activity(refresh=refresh))
