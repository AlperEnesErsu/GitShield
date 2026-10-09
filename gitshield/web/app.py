import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional, Set

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gitshield import __version__
from gitshield.web.config import settings
from gitshield.web.db import Database
from gitshield.web.github import GitHubClient, GitHubError
from gitshield.web.llm import get_provider
from gitshield.web.review import comment_to_issue, initial_progress, run_review, submit_review

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"

# Strong references so background review tasks are not garbage-collected mid-run.
_tasks: Set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = Database(settings.db_path)
    app.state.gh = GitHubClient()
    yield
    await app.state.gh.aclose()


app = FastAPI(title="GitShield", version=__version__, lifespan=lifespan)


@app.exception_handler(GitHubError)
async def github_error_handler(_: Request, exc: GitHubError) -> JSONResponse:
    status = exc.status_code if 400 <= exc.status_code < 600 else 502
    return JSONResponse({"detail": f"GitHub: {exc.message}"}, status_code=status)


def db(request: Request) -> Database:
    return request.app.state.db


def gh(request: Request) -> GitHubClient:
    return request.app.state.gh


def _review_or_404(request: Request, review_id: int) -> Dict[str, Any]:
    review = db(request).get_review(review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    return review


# ---- Status ------------------------------------------------------------------------


@app.get("/api/status")
async def status(request: Request) -> Dict[str, Any]:
    login = None
    error = None
    if settings.github_token:
        try:
            login = (await gh(request).viewer())["login"]
        except GitHubError as e:
            error = e.message
    else:
        error = "GITHUB_TOKEN tanımlı değil."
    return {
        "version": __version__,
        "github": {"login": login, "error": error},
        "llm": {"provider": settings.llm_provider, "model": settings.llm_model},
        "review_language": settings.review_language,
    }


# ---- Repositories --------------------------------------------------------------------


@app.get("/api/repos")
async def list_repos(request: Request, refresh: bool = False) -> Dict[str, Any]:
    data = await gh(request).list_repos(refresh=refresh)
    stats = db(request).repo_stats()
    repos = []
    for r in data["repos"]:
        s = stats.get(r["nameWithOwner"], {})
        repos.append({
            "full_name": r["nameWithOwner"],
            "owner": r["owner"]["login"],
            "name": r["name"],
            "description": r["description"],
            "url": r["url"],
            "private": r["isPrivate"],
            "archived": r["isArchived"],
            "fork": r["isFork"],
            "pushed_at": r["pushedAt"],
            "stars": r["stargazerCount"],
            "permission": r["viewerPermission"],
            "language": r["primaryLanguage"],
            "default_branch": (r["defaultBranchRef"] or {}).get("name"),
            "open_prs": r["pullRequests"]["totalCount"],
            "open_issues": r["issues"]["totalCount"],
            "merged_prs": r["mergedPullRequests"]["totalCount"],
            "forks": r["forkCount"],
            "languages": _languages(r["languages"]),
            "reviews": s.get("reviews", 0),
            "submitted_reviews": s.get("submitted") or 0,
            "draft_issues": s.get("draft_issues", 0),
            "last_review_at": s.get("last_review_at"),
        })
    return {"login": data["login"], "repos": repos}


def _languages(conn: Dict[str, Any]) -> list:
    total = conn.get("totalSize") or 0
    return [
        {"name": e["node"]["name"], "color": e["node"]["color"], "bytes": e["size"],
         "share": round(e["size"] / total, 4) if total else 0}
        for e in conn.get("edges", [])
    ]


@app.get("/api/repos/{owner}/{repo}/overview")
async def repo_overview(request: Request, owner: str, repo: str) -> Dict[str, Any]:
    client = gh(request)
    r, participation = await asyncio.gather(
        client.repo_overview(owner, repo), client.participation(owner, repo)
    )
    branch = r["defaultBranchRef"] or {}
    history = (branch.get("target") or {}).get("history") or {}
    full_name = f"{owner}/{repo}"
    reviews = db(request).repo_stats().get(full_name, {})
    return {
        "full_name": r["nameWithOwner"],
        "description": r["description"],
        "url": r["url"],
        "homepage": r["homepageUrl"],
        "private": r["isPrivate"],
        "archived": r["isArchived"],
        "created_at": r["createdAt"],
        "pushed_at": r["pushedAt"],
        "disk_kb": r["diskUsage"],
        "stars": r["stargazerCount"],
        "forks": r["forkCount"],
        "watchers": r["watchers"]["totalCount"],
        "license": (r["licenseInfo"] or {}).get("name"),
        "default_branch": branch.get("name"),
        "commits": history.get("totalCount"),
        "languages": _languages(r["languages"]),
        "pulls": {
            "open": r["openPullRequests"]["totalCount"],
            "merged": r["mergedPullRequests"]["totalCount"],
            "closed": r["closedPullRequests"]["totalCount"],
        },
        "issues": {"open": r["openIssues"]["totalCount"], "closed": r["closedIssues"]["totalCount"]},
        "participation": participation,
        "gitshield": {
            "reviews": reviews.get("reviews", 0),
            "submitted": reviews.get("submitted") or 0,
            "draft_issues": reviews.get("draft_issues", 0),
        },
    }


@app.get("/api/repos/{owner}/{repo}/pulls")
async def list_pulls(request: Request, owner: str, repo: str, state: str = "open"):
    pulls = await gh(request).list_pulls(owner, repo, state)
    latest = db(request).latest_reviews(f"{owner}/{repo}")
    result = []
    for p in pulls:
        review = latest.get(p["number"])
        result.append({
            "number": p["number"],
            "title": p["title"],
            "url": p["html_url"],
            "state": p["state"],
            "draft": p.get("draft", False),
            "author": p["user"]["login"],
            "author_avatar": p["user"]["avatar_url"],
            "created_at": p["created_at"],
            "updated_at": p["updated_at"],
            "head_ref": p["head"]["ref"],
            "base_ref": p["base"]["ref"],
            "head_sha": p["head"]["sha"],
            "labels": [{"name": label["name"], "color": label["color"]} for label in p["labels"]],
            "review": review and {
                "id": review["id"],
                "status": review["status"],
                "verdict": review["verdict"],
                "open_comments": review.get("open_comments", 0),
                "outdated": review["head_sha"] != p["head"]["sha"],
                "created_at": review["created_at"],
            },
        })
    return result


@app.get("/api/repos/{owner}/{repo}/issues")
async def list_issues(request: Request, owner: str, repo: str, state: str = "open"):
    issues = await gh(request).list_issues(owner, repo, state)
    return [{
        "number": i["number"],
        "title": i["title"],
        "url": i["html_url"],
        "state": i["state"],
        "author": i["user"]["login"],
        "comments": i["comments"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "labels": [{"name": label["name"], "color": label["color"]} for label in i["labels"]],
        "assignees": [a["login"] for a in i["assignees"]],
    } for i in issues]


@app.get("/api/repos/{owner}/{repo}/draft-issues")
async def list_draft_issues(request: Request, owner: str, repo: str, all: bool = False):
    return db(request).list_draft_issues(f"{owner}/{repo}", include_closed=all)


# ---- Pull request detail & reviews -------------------------------------------------------


@app.get("/api/repos/{owner}/{repo}/pulls/{number}")
async def get_pull(request: Request, owner: str, repo: str, number: int):
    client = gh(request)
    pr, files = await asyncio.gather(
        client.get_pull(owner, repo, number), client.list_pull_files(owner, repo, number)
    )
    reviews = db(request).list_pr_reviews(f"{owner}/{repo}", number)
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
    }


@app.post("/api/repos/{owner}/{repo}/pulls/{number}/reviews", status_code=202)
async def start_review(request: Request, owner: str, repo: str, number: int):
    client = gh(request)
    pr = await client.get_pull(owner, repo, number)
    provider = get_provider()
    review_id = db(request).create_review(
        f"{owner}/{repo}", number, pr["title"], pr["head"]["sha"],
        provider.name if provider else "none", provider.model if provider else "",
    )
    db(request).update_review(review_id, progress=initial_progress())
    task = asyncio.create_task(
        run_review(db(request), client, provider, review_id, owner, repo, number)
    )
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"id": review_id, "status": "running"}


@app.get("/api/reviews/{review_id}")
async def get_review(request: Request, review_id: int):
    return _review_or_404(request, review_id)


class ReviewPatch(BaseModel):
    summary: Optional[str] = None
    verdict: Optional[str] = None


@app.patch("/api/reviews/{review_id}")
async def patch_review(request: Request, review_id: int, patch: ReviewPatch):
    review = _review_or_404(request, review_id)
    if review["status"] == "submitted":
        raise HTTPException(409, "Review already submitted")
    if patch.verdict and patch.verdict not in ("APPROVE", "REQUEST_CHANGES", "COMMENT"):
        raise HTTPException(422, "Invalid verdict")
    db(request).update_review(review_id, **patch.model_dump(exclude_none=True))
    return db(request).get_review(review_id)


class CommentPatch(BaseModel):
    included: Optional[bool] = None
    title: Optional[str] = None
    body: Optional[str] = None


@app.patch("/api/comments/{comment_id}")
async def patch_comment(request: Request, comment_id: int, patch: CommentPatch):
    if not db(request).get_comment(comment_id):
        raise HTTPException(404, "Comment not found")
    db(request).update_comment(comment_id, **patch.model_dump(exclude_none=True))
    return db(request).get_comment(comment_id)


@app.post("/api/comments/{comment_id}/draft-issue")
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
    event: Optional[str] = None


@app.post("/api/reviews/{review_id}/submit")
async def submit(request: Request, review_id: int, body: SubmitBody):
    review = _review_or_404(request, review_id)
    if review["status"] != "ready":
        raise HTTPException(409, f"Review is {review['status']}, not ready")
    result = await submit_review(db(request), gh(request), review, body.event)
    return {"url": result.get("html_url"), "review": db(request).get_review(review_id)}


# ---- Draft issues ---------------------------------------------------------------------


class DraftIssuePatch(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None


def _draft_or_404(request: Request, issue_id: int) -> Dict[str, Any]:
    issue = db(request).get_draft_issue(issue_id)
    if not issue:
        raise HTTPException(404, "Draft issue not found")
    return issue


@app.patch("/api/draft-issues/{issue_id}")
async def patch_draft_issue(request: Request, issue_id: int, patch: DraftIssuePatch):
    _draft_or_404(request, issue_id)
    db(request).update_draft_issue(issue_id, **patch.model_dump(exclude_none=True))
    return db(request).get_draft_issue(issue_id)


@app.post("/api/draft-issues/{issue_id}/open")
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


@app.post("/api/draft-issues/{issue_id}/dismiss")
async def dismiss_draft_issue(request: Request, issue_id: int):
    _draft_or_404(request, issue_id)
    db(request).update_draft_issue(issue_id, status="dismissed")
    return db(request).get_draft_issue(issue_id)


# ---- Frontend -------------------------------------------------------------------------

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = (FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and FRONTEND_DIST in candidate.parents:
            return FileResponse(candidate)
        # index.html references hashed assets; never cache it so new builds load immediately.
        return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})
