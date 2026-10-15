from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from gitshield.web.fixes import FixError, create_fix_pr, preview_fix
from gitshield.web.llm import get_provider
from gitshield.web.routes.deps import db, gh

router = APIRouter()


class FixBody(BaseModel):
    start_line: int
    end_line: int
    replacement: str


def _comment_or_404(request: Request, comment_id: int) -> dict[str, Any]:
    comment = db(request).get_comment(comment_id)
    if not comment:
        raise HTTPException(404, "Comment not found")
    return comment


@router.post("/api/comments/{comment_id}/fix/preview")
async def fix_preview(request: Request, comment_id: int):
    try:
        return await preview_fix(db(request), gh(request), get_provider(db(request)),
                                 _comment_or_404(request, comment_id))
    except FixError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/api/comments/{comment_id}/fix", status_code=201)
async def fix_create(request: Request, comment_id: int, body: FixBody):
    try:
        return await create_fix_pr(db(request), gh(request), _comment_or_404(request, comment_id),
                                   body.start_line, body.end_line, body.replacement)
    except FixError as e:
        raise HTTPException(422, str(e)) from e
