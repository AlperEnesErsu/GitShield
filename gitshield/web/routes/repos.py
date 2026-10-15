import asyncio
from typing import Any

from fastapi import APIRouter, Request

from gitshield.web.insights import pr_insights
from gitshield.web.routes.deps import db, gh

router = APIRouter()


@router.get("/api/repos")
async def list_repos(request: Request, refresh: bool = False) -> dict[str, Any]:
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


def _languages(conn: dict[str, Any]) -> list:
    total = conn.get("totalSize") or 0
    return [
        {"name": e["node"]["name"], "color": e["node"]["color"], "bytes": e["size"],
         "share": round(e["size"] / total, 4) if total else 0}
        for e in conn.get("edges", [])
    ]


@router.get("/api/repos/{owner}/{repo}/overview")
async def repo_overview(request: Request, owner: str, repo: str) -> dict[str, Any]:
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


@router.get("/api/repos/{owner}/{repo}/pulls")
async def list_pulls(request: Request, owner: str, repo: str, state: str = "open"):
    client = gh(request)
    pulls, details = await asyncio.gather(
        client.list_pulls(owner, repo, state), client.open_pulls_detail(owner, repo))
    latest = db(request).latest_reviews(f"{owner}/{repo}")
    result = []
    for p in pulls:
        review = latest.get(p["number"])
        result.append({
            **pr_insights(details.get(p["number"]), review,
                          db(request).ci_verdict(f"{owner}/{repo}", p["number"], p["head"]["sha"])),
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


@router.get("/api/repos/{owner}/{repo}/issues")
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


@router.get("/api/repos/{owner}/{repo}/draft-issues")
async def list_draft_issues(request: Request, owner: str, repo: str, all: bool = False):
    return db(request).list_draft_issues(f"{owner}/{repo}", include_closed=all)
