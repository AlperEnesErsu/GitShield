
from fastapi import APIRouter, HTTPException, Request

from gitshield.web.metrics import build_metrics
from gitshield.web.routes.deps import db, gh

router = APIRouter()


@router.get("/api/metrics")
async def metrics(request: Request, days: int = 30, sla_days: float = 3):
    if not 1 <= days <= 365 or sla_days <= 0:
        raise HTTPException(422, "days 1-365, sla_days > 0 olmalı")
    return await build_metrics(db(request), gh(request), days, sla_days)
