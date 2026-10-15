
from fastapi import APIRouter, Request
from pydantic import BaseModel

from gitshield.web.automation import approve_dependency_batch
from gitshield.web.routes.deps import db, gh

router = APIRouter()


class BatchBody(BaseModel):
    numbers: list[int]
    allow_major: bool = False


@router.post("/api/repos/{owner}/{repo}/dependency-batch")
async def dependency_batch(request: Request, owner: str, repo: str, body: BatchBody):
    results = await approve_dependency_batch(db(request), gh(request), owner, repo,
                                             body.numbers, body.allow_major)
    return {"results": results}
