from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from gitshield.web.routes.deps import db, gh

router = APIRouter()


class DraftIssuePatch(BaseModel):
    title: str | None = None
    body: str | None = None


def _draft_or_404(request: Request, issue_id: int) -> dict[str, Any]:
    issue = db(request).get_draft_issue(issue_id)
    if not issue:
        raise HTTPException(404, "Draft issue not found")
    return issue


@router.patch("/api/draft-issues/{issue_id}")
async def patch_draft_issue(request: Request, issue_id: int, patch: DraftIssuePatch):
    _draft_or_404(request, issue_id)
    db(request).update_draft_issue(issue_id, **patch.model_dump(exclude_none=True))
    return db(request).get_draft_issue(issue_id)


@router.post("/api/draft-issues/{issue_id}/open")
async def open_draft_issue(request: Request, issue_id: int):
    issue = _draft_or_404(request, issue_id)
    if issue["status"] != "draft":
        raise HTTPException(409, f"Draft issue is {issue['status']}")
    owner, repo = issue["repo"].split("/", 1)
    created = await gh(request).create_issue(owner, repo, issue["title"], issue["body"])
    db(request).update_draft_issue(issue_id, status="opened",
                                   github_issue_number=created["number"],
                                   github_issue_url=created["html_url"])
    return db(request).get_draft_issue(issue_id)


@router.post("/api/draft-issues/{issue_id}/dismiss")
async def dismiss_draft_issue(request: Request, issue_id: int):
    _draft_or_404(request, issue_id)
    db(request).update_draft_issue(issue_id, status="dismissed")
    return db(request).get_draft_issue(issue_id)
