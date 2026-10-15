from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from gitshield.web.routes.deps import _review_or_404, db

router = APIRouter()


class MemoryBody(BaseModel):
    text: str


class MemoryPatch(BaseModel):
    text: str | None = None
    active: bool | None = None


class SuppressBody(BaseModel):
    scope: Literal["file", "repo"] = "file"


@router.get("/api/repos/{owner}/{repo}/memory")
async def list_memory(request: Request, owner: str, repo: str):
    return db(request).list_memory(f"{owner}/{repo}")


@router.post("/api/repos/{owner}/{repo}/memory", status_code=201)
async def add_rule(request: Request, owner: str, repo: str, body: MemoryBody):
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "Kural metni boş olamaz.")
    return db(request).add_memory(f"{owner}/{repo}", "rule", text[:1000])


@router.patch("/api/memory/{memory_id}")
async def patch_memory(request: Request, memory_id: int, patch: MemoryPatch):
    if not db(request).get_memory(memory_id):
        raise HTTPException(404, "Memory item not found")
    db(request).update_memory(memory_id, **patch.model_dump())
    return db(request).get_memory(memory_id)


@router.delete("/api/memory/{memory_id}", status_code=204)
async def delete_memory(request: Request, memory_id: int):
    db(request).delete_memory(memory_id)


@router.post("/api/comments/{comment_id}/suppress", status_code=201)
async def suppress_comment(request: Request, comment_id: int, body: SuppressBody):
    """'Do not say this again': remember the comment for the repo and exclude it from this review."""
    store = db(request)
    comment = store.get_comment(comment_id)
    if not comment:
        raise HTTPException(404, "Comment not found")
    review = _review_or_404(request, comment["review_id"])
    excerpt = comment["body"].splitlines()[0][:200] if comment["body"] else ""
    memory = store.add_memory(
        review["repo"], "suppress", f"{comment['title']}: {excerpt}",
        rule_id=comment["rule_id"], path=comment["path"] if body.scope == "file" else None,
        source_comment_id=comment_id,
    )
    store.update_comment(comment_id, included=False)
    return {"memory": memory, "comment": store.get_comment(comment_id)}
