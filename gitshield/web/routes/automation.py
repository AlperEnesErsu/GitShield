from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from gitshield.web.automation import AutoReviewer, build_inbox
from gitshield.web.routes.deps import db, gh

router = APIRouter()


@router.get("/api/inbox")
async def inbox(request: Request) -> dict[str, Any]:
    return await build_inbox(db(request), gh(request))


class RepoSettingsBody(BaseModel):
    auto_review: bool | None = None
    include_drafts: bool | None = None


@router.get("/api/repos/{owner}/{repo}/settings")
async def get_repo_settings(request: Request, owner: str, repo: str):
    return db(request).get_repo_settings(f"{owner}/{repo}")


@router.put("/api/repos/{owner}/{repo}/settings")
async def put_repo_settings(request: Request, owner: str, repo: str, body: RepoSettingsBody):
    result = db(request).set_repo_settings(f"{owner}/{repo}", **body.model_dump())
    if result["auto_review"]:
        request.app.state.watcher.trigger()
    return result


@router.get("/api/automation")
async def automation_status(request: Request):
    return request.app.state.watcher.status()


@router.post("/api/automation/run", status_code=202)
async def automation_run(request: Request):
    watcher: AutoReviewer = request.app.state.watcher
    if not watcher.enabled:
        raise HTTPException(409, "Otomatik inceleme kapalı (GITSHIELD_AUTO_REVIEW_INTERVAL=0).")
    watcher.trigger()
    return watcher.status()
