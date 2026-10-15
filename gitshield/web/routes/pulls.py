import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from gitshield.web.insights import pr_insights
from gitshield.web.llm import get_provider
from gitshield.web.review import begin_review, comment_to_issue, run_review, submit_review
from gitshield.web.routes.deps import _review_or_404, db, gh

router = APIRouter()


# Strong references so background review tasks are not garbage-collected mid-run.
_tasks: set[asyncio.Task] = set()


@router.get("/api/repos/{owner}/{repo}/pulls/{number}")
async def get_pull(request: Request, owner: str, repo: str, number: int):
    client = gh(request)
    pr, files, details = await asyncio.gather(
        client.get_pull(owner, repo, number), client.list_pull_files(owner, repo, number),
        client.open_pulls_detail(owner, repo),
    )
    reviews = db(request).list_pr_reviews(f"{owner}/{repo}", number)
    insights = pr_insights(details.get(number), db(request).latest_reviews(f"{owner}/{repo}").get(number),
                           db(request).ci_verdict(f"{owner}/{repo}", number, pr["head"]["sha"]))
    latest = db(request).get_review(reviews[0]["id"]) if reviews else None
    return {
        "number": pr["number"],
        "title": pr["title"],
        "body": pr.get("body") or "",
        "url": pr["html_url"],
        "state": pr["state"],
        "merged": pr.get("merged", False),
        "draft": pr.get("draft", False),
        "author": pr["user"]["login"],
        "head_ref": pr["head"]["ref"],
        "base_ref": pr["base"]["ref"],
        "head_sha": pr["head"]["sha"],
        "additions": pr.get("additions", 0),
        "deletions": pr.get("deletions", 0),
        "changed_files": pr.get("changed_files", len(files)),
        "files": [{
            "path": f["filename"],
            "status": f["status"],
            "additions": f["additions"],
            "deletions": f["deletions"],
            "patch": f.get("patch"),
        } for f in files],
        "reviews": [{k: r[k] for k in ("id", "status", "verdict", "created_at", "head_sha")}
                    for r in reviews],
        "latest_review": latest,
        **insights,
    }


@router.post("/api/repos/{owner}/{repo}/pulls/{number}/reviews", status_code=202)
async def start_review(request: Request, owner: str, repo: str, number: int, full: bool = False):
    running = db(request).running_review(f"{owner}/{repo}", number)
    if running:
        # A double click or the watcher already started one: do not burn LLM quota twice.
        return {"id": running["id"], "status": "running", "existing": True}
    client = gh(request)
    pr = await client.get_pull(owner, repo, number)
    provider = get_provider(db(request))
    review_id = begin_review(db(request), pr, f"{owner}/{repo}", provider)
    task = asyncio.create_task(
        run_review(db(request), client, provider, review_id, owner, repo, number, force_full=full)
    )
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"id": review_id, "status": "running"}


@router.get("/api/reviews/{review_id}")
async def get_review(request: Request, review_id: int):
    return _review_or_404(request, review_id)


class ReviewPatch(BaseModel):
    summary: str | None = None
    verdict: str | None = None


@router.patch("/api/reviews/{review_id}")
async def patch_review(request: Request, review_id: int, patch: ReviewPatch):
    review = _review_or_404(request, review_id)
    if review["status"] == "submitted":
        raise HTTPException(409, "Review already submitted")
    if patch.verdict and patch.verdict not in ("APPROVE", "REQUEST_CHANGES", "COMMENT"):
        raise HTTPException(422, "Invalid verdict")
    db(request).update_review(review_id, **patch.model_dump(exclude_none=True))
    return db(request).get_review(review_id)


class CommentPatch(BaseModel):
    included: bool | None = None
    title: str | None = None
    body: str | None = None


@router.patch("/api/comments/{comment_id}")
async def patch_comment(request: Request, comment_id: int, patch: CommentPatch):
    if not db(request).get_comment(comment_id):
        raise HTTPException(404, "Comment not found")
    db(request).update_comment(comment_id, **patch.model_dump(exclude_none=True))
    return db(request).get_comment(comment_id)


@router.post("/api/comments/{comment_id}/draft-issue")
async def comment_draft_issue(request: Request, comment_id: int):
    comment = db(request).get_comment(comment_id)
    if not comment:
        raise HTTPException(404, "Comment not found")
    review = _review_or_404(request, comment["review_id"])
    owner, repo = review["repo"].split("/", 1)
    pr = await gh(request).get_pull(owner, repo, review["pr_number"])
    issue_id = comment_to_issue(db(request), comment, review, pr)
    if issue_id is None:
        raise HTTPException(409, "Bu bulgu için zaten bir taslak issue var.")
    return db(request).get_draft_issue(issue_id)


class SubmitBody(BaseModel):
    event: str | None = None


@router.post("/api/reviews/{review_id}/submit")
async def submit(request: Request, review_id: int, body: SubmitBody):
    review = _review_or_404(request, review_id)
    if review["status"] != "ready":
        raise HTTPException(409, f"Review is {review['status']}, not ready")
    result = await submit_review(db(request), gh(request), review, body.event)
    return {"url": result.get("html_url"), "review": db(request).get_review(review_id)}
