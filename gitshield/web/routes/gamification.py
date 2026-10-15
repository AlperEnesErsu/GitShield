
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from gitshield.web.config import settings
from gitshield.web.gamification import compute as compute_gamification
from gitshield.web.routes.deps import db

router = APIRouter()


class GoalBody(BaseModel):
    goal: int


@router.get("/api/gamification")
async def gamification(request: Request):
    if not settings.gamification_enabled:
        return {"enabled": False}
    return compute_gamification(db(request))


@router.post("/api/gamification/seen", status_code=204)
async def gamification_seen(request: Request):
    db(request).mark_achievements_seen()


@router.put("/api/gamification/goal")
async def gamification_goal(request: Request, body: GoalBody):
    if not 1 <= body.goal <= 30:
        raise HTTPException(422, "Günlük hedef 1-30 arası olmalı.")
    if not settings.gamification_enabled:
        return {"enabled": False}
    db(request).set_setting("daily_goal", str(body.goal))
    return compute_gamification(db(request))
