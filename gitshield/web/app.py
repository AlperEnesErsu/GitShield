import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gitshield import __version__
from gitshield.web.config import settings
from gitshield.web.db import Database
from gitshield.web.github import GitHubClient, GitHubError
from gitshield.web.llm import get_provider
from gitshield.web.automation import AutoReviewer, approve_dependency_batch, build_inbox
from gitshield.web.ci_diagnosis import diagnose
from gitshield.web.gamification import compute as compute_gamification
from gitshield.web.fixes import FixError, create_fix_pr, preview_fix
from gitshield.web.insights import pr_insights
from gitshield.web.metrics import build_metrics
from gitshield.web.notify import app_url, channels as notify_channels, send as send_notification
from gitshield.web.security import LocalOnlyMiddleware
from gitshield.web.review import begin_review, comment_to_issue, run_review, submit_review

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"

# Strong references so background review tasks are not garbage-collected mid-run.
_tasks: Set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = Database(settings.db_path)
    app.state.db.fail_interrupted_reviews()
    app.state.gh = GitHubClient()
    app.state.watcher = AutoReviewer(app.state.db, app.state.gh, settings.auto_review_interval)
    app.state.watcher.start()
    yield
    await app.state.watcher.stop()
    await app.state.gh.aclose()


app = FastAPI(title="GitShield", version=__version__, lifespan=lifespan)
app.add_middleware(LocalOnlyMiddleware)


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
    client = gh(request)
    pulls, details = await asyncio.gather(
        client.list_pulls(owner, repo, state), client.open_pulls_detail(owner, repo))
    latest = db(request).latest_reviews(f"{owner}/{repo}")
    result = []
    for p in pulls:
        review = latest.get(p["number"])
        result.append({
            **pr_insights(details.get(p["number"]), review),
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
    pr, files, details = await asyncio.gather(
        client.get_pull(owner, repo, number), client.list_pull_files(owner, repo, number),
        client.open_pulls_detail(owner, repo),
    )
    reviews = db(request).list_pr_reviews(f"{owner}/{repo}", number)
    insights = pr_insights(details.get(number), db(request).latest_reviews(f"{owner}/{repo}").get(number))
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


@app.post("/api/repos/{owner}/{repo}/pulls/{number}/reviews", status_code=202)
async def start_review(request: Request, owner: str, repo: str, number: int, full: bool = False):
    running = db(request).running_review(f"{owner}/{repo}", number)
    if running:
        # A double click or the watcher already started one: do not burn LLM quota twice.
        return {"id": running["id"], "status": "running", "existing": True}
    client = gh(request)
    pr = await client.get_pull(owner, repo, number)
    provider = get_provider()
    review_id = begin_review(db(request), pr, f"{owner}/{repo}", provider)
    task = asyncio.create_task(
        run_review(db(request), client, provider, review_id, owner, repo, number, force_full=full)
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


# ---- Gamification -------------------------------------------------------------------------


class GoalBody(BaseModel):
    goal: int


@app.get("/api/gamification")
async def gamification(request: Request):
    return compute_gamification(db(request))


@app.post("/api/gamification/seen", status_code=204)
async def gamification_seen(request: Request):
    db(request).mark_achievements_seen()


@app.put("/api/gamification/goal")
async def gamification_goal(request: Request, body: GoalBody):
    if not 1 <= body.goal <= 30:
        raise HTTPException(422, "Günlük hedef 1-30 arası olmalı.")
    db(request).set_setting("daily_goal", str(body.goal))
    return compute_gamification(db(request))


# ---- CI diagnosis --------------------------------------------------------------------------


@app.get("/api/repos/{owner}/{repo}/pulls/{number}/ci-diagnosis")
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
    provider = get_provider() if ai else None
    if ai and not provider:
        raise HTTPException(409, "AI ile derinleştirmek için bir LLM yapılandırılmalı.")
    result = await diagnose(client, owner, repo, pr, provider)
    if not result["pending"]:
        store.save_ci_diagnosis(full_name, number, pr["head"]["sha"], result)
    return result


@app.post("/api/repos/{owner}/{repo}/actions/jobs/{job_id}/rerun", status_code=202)
async def rerun_ci_job(request: Request, owner: str, repo: str, job_id: int):
    await gh(request).rerun_job(owner, repo, job_id)
    return {"rerun": job_id}


# ---- Fix PRs ------------------------------------------------------------------------------


class FixBody(BaseModel):
    start_line: int
    end_line: int
    replacement: str


def _comment_or_404(request: Request, comment_id: int) -> Dict[str, Any]:
    comment = db(request).get_comment(comment_id)
    if not comment:
        raise HTTPException(404, "Comment not found")
    return comment


@app.post("/api/comments/{comment_id}/fix/preview")
async def fix_preview(request: Request, comment_id: int):
    try:
        return await preview_fix(db(request), gh(request), get_provider(), _comment_or_404(request, comment_id))
    except FixError as e:
        raise HTTPException(422, str(e)) from e


@app.post("/api/comments/{comment_id}/fix", status_code=201)
async def fix_create(request: Request, comment_id: int, body: FixBody):
    try:
        return await create_fix_pr(db(request), gh(request), _comment_or_404(request, comment_id),
                                   body.start_line, body.end_line, body.replacement)
    except FixError as e:
        raise HTTPException(422, str(e)) from e


# ---- Repo memory ----------------------------------------------------------------------------


class MemoryBody(BaseModel):
    text: str


class MemoryPatch(BaseModel):
    text: Optional[str] = None
    active: Optional[bool] = None


class SuppressBody(BaseModel):
    scope: Literal["file", "repo"] = "file"


@app.get("/api/repos/{owner}/{repo}/memory")
async def list_memory(request: Request, owner: str, repo: str):
    return db(request).list_memory(f"{owner}/{repo}")


@app.post("/api/repos/{owner}/{repo}/memory", status_code=201)
async def add_rule(request: Request, owner: str, repo: str, body: MemoryBody):
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "Kural metni boş olamaz.")
    return db(request).add_memory(f"{owner}/{repo}", "rule", text[:1000])


@app.patch("/api/memory/{memory_id}")
async def patch_memory(request: Request, memory_id: int, patch: MemoryPatch):
    if not db(request).get_memory(memory_id):
        raise HTTPException(404, "Memory item not found")
    db(request).update_memory(memory_id, **patch.model_dump())
    return db(request).get_memory(memory_id)


@app.delete("/api/memory/{memory_id}", status_code=204)
async def delete_memory(request: Request, memory_id: int):
    db(request).delete_memory(memory_id)


@app.post("/api/comments/{comment_id}/suppress", status_code=201)
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


# ---- Dependency batch approval ------------------------------------------------------------


class BatchBody(BaseModel):
    numbers: List[int]
    allow_major: bool = False


@app.post("/api/repos/{owner}/{repo}/dependency-batch")
async def dependency_batch(request: Request, owner: str, repo: str, body: BatchBody):
    results = await approve_dependency_batch(db(request), gh(request), owner, repo,
                                             body.numbers, body.allow_major)
    return {"results": results}


# ---- Metrics ------------------------------------------------------------------------------


@app.get("/api/metrics")
async def metrics(request: Request, days: int = 30, sla_days: float = 3):
    if not 1 <= days <= 365 or sla_days <= 0:
        raise HTTPException(422, "days 1-365, sla_days > 0 olmalı")
    return await build_metrics(db(request), gh(request), days, sla_days)


# ---- Notifications ------------------------------------------------------------------------


@app.get("/api/notifications")
async def notifications_status():
    return {"channels": notify_channels(), "app_url": app_url()}


@app.post("/api/notifications/test")
async def notifications_test():
    if not notify_channels():
        raise HTTPException(409, "Bildirim kanalı tanımlı değil (.env: GITSHIELD_SLACK_WEBHOOK, "
                                 "GITSHIELD_DISCORD_WEBHOOK veya GITSHIELD_TELEGRAM_BOT_TOKEN + _CHAT_ID).")
    return {"results": await send_notification("🛡️ GitShield test bildirimi — kanal çalışıyor.")}


# ---- Inbox & automation ------------------------------------------------------------------


@app.get("/api/inbox")
async def inbox(request: Request) -> Dict[str, Any]:
    return await build_inbox(db(request), gh(request))


class RepoSettingsBody(BaseModel):
    auto_review: Optional[bool] = None
    include_drafts: Optional[bool] = None


@app.get("/api/repos/{owner}/{repo}/settings")
async def get_repo_settings(request: Request, owner: str, repo: str):
    return db(request).get_repo_settings(f"{owner}/{repo}")


@app.put("/api/repos/{owner}/{repo}/settings")
async def put_repo_settings(request: Request, owner: str, repo: str, body: RepoSettingsBody):
    result = db(request).set_repo_settings(f"{owner}/{repo}", **body.model_dump())
    if result["auto_review"]:
        request.app.state.watcher.trigger()
    return result


@app.get("/api/automation")
async def automation_status(request: Request):
    return request.app.state.watcher.status()


@app.post("/api/automation/run", status_code=202)
async def automation_run(request: Request):
    watcher: AutoReviewer = request.app.state.watcher
    if not watcher.enabled:
        raise HTTPException(409, "Otomatik inceleme kapalı (GITSHIELD_AUTO_REVIEW_INTERVAL=0).")
    watcher.trigger()
    return watcher.status()


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
