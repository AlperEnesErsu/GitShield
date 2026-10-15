
from fastapi import APIRouter, HTTPException, Request

from gitshield.web.ci_diagnosis import diagnose
from gitshield.web.llm import get_provider
from gitshield.web.routes.deps import db, gh

router = APIRouter()


@router.get("/api/repos/{owner}/{repo}/pulls/{number}/ci-diagnosis")
async def ci_diagnosis(request: Request, owner: str, repo: str, number: int,
                       refresh: bool = False, ai: bool = False):
    """Why CI failed on the PR's current head. Cached per commit; `ai=true` adds an LLM deep-dive."""
    store, client = db(request), gh(request)
    pr = await client.get_pull(owner, repo, number)
    full_name = f"{owner}/{repo}"
    cached = store.get_ci_diagnosis(full_name, number, pr["head"]["sha"])
    if cached and not refresh and (cached.get("ai") or not ai):
        # Pending checks may have finished since; recompute until everything is settled.
        if not cached.get("pending"):
            return cached
    provider = get_provider(db(request)) if ai else None
    if ai and not provider:
        raise HTTPException(409, "AI ile derinleştirmek için bir LLM yapılandırılmalı.")
    result = await diagnose(client, owner, repo, pr, provider)
    if not result["pending"]:
        store.save_ci_diagnosis(full_name, number, pr["head"]["sha"], result)  # also feeds risk
    return result


@router.post("/api/repos/{owner}/{repo}/actions/jobs/{job_id}/rerun", status_code=202)
async def rerun_ci_job(request: Request, owner: str, repo: str, job_id: int):
    await gh(request).rerun_job(owner, repo, job_id)
    return {"rerun": job_id}
