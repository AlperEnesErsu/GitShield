"""Cross-repo inbox and the background auto-review watcher."""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set

from gitshield.web.db import Database, now
from gitshield.web.github import GitHubClient, GitHubError
from gitshield.web.llm import get_provider
from gitshield.web.review import begin_review, run_review

log = logging.getLogger(__name__)

# Lower number = more urgent. The UI groups by kind in this order.
PRIORITY = {"approve": 1, "failed": 2, "outdated": 3, "new": 4, "running": 5, "drafts": 6}
MAX_CONCURRENT_REPOS = 6


def _pull_item(kind: str, repo: str, p: Dict[str, Any], review: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "kind": kind,
        "priority": PRIORITY[kind],
        "repo": repo,
        "pr_number": p["number"],
        "title": p["title"],
        "author": p["user"]["login"],
        "author_avatar": p["user"]["avatar_url"],
        "draft": p.get("draft", False),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "review_id": review["id"] if review else None,
        "verdict": review["verdict"] if review else None,
        "open_comments": review.get("open_comments", 0) if review else 0,
        "error": review.get("error") if review else None,
    }


def classify(p: Dict[str, Any], review: Optional[Dict[str, Any]]) -> str:
    if not review:
        return "new"
    if review["status"] == "running":
        return "running"
    if review["status"] == "failed":
        return "failed"
    if review["head_sha"] != p["head"]["sha"]:
        return "outdated"
    return "approve" if review["status"] == "ready" else "done"


async def build_inbox(db: Database, gh: GitHubClient) -> Dict[str, Any]:
    """Everything that needs the user's attention across all repositories, most urgent first."""
    repos = (await gh.list_repos())["repos"]
    active = [r["nameWithOwner"] for r in repos if r["pullRequests"]["totalCount"] and not r["isArchived"]]
    sem = asyncio.Semaphore(MAX_CONCURRENT_REPOS)

    async def pulls_for(full_name: str):
        owner, name = full_name.split("/", 1)
        async with sem:
            try:
                return full_name, await gh.list_pulls(owner, name), None
            except GitHubError as e:
                return full_name, [], e.message

    results = await asyncio.gather(*(pulls_for(r) for r in active))
    items: List[Dict[str, Any]] = []
    errors = []
    for full_name, pulls, error in results:
        if error:
            errors.append({"repo": full_name, "error": error})
        latest = db.latest_reviews(full_name)
        for p in pulls:
            kind = classify(p, latest.get(p["number"]))
            if kind != "done":
                items.append(_pull_item(kind, full_name, p, latest.get(p["number"])))

    drafts: Dict[str, List[Dict[str, Any]]] = {}
    for d in db.list_pending_drafts():
        drafts.setdefault(d["repo"], []).append(d)
    for repo, ds in drafts.items():
        items.append({
            "kind": "drafts", "priority": PRIORITY["drafts"], "repo": repo,
            "title": f"{len(ds)} taslak issue açılmayı bekliyor",
            "draft_count": len(ds),
            "severities": sorted({d["severity"] for d in ds}),
            "updated_at": max(d["created_at"] for d in ds),
        })

    # Most urgent kind first; within a kind, the oldest waiting item first.
    items.sort(key=lambda i: (i["priority"], i["updated_at"]))
    counts: Dict[str, int] = {}
    for i in items:
        counts[i["kind"]] = counts.get(i["kind"], 0) + 1
    actionable = sum(n for k, n in counts.items() if k != "running")
    return {"items": items, "counts": counts, "actionable": actionable, "errors": errors,
            "repos_checked": len(active)}


class AutoReviewer:
    """Polls opted-in repositories and reviews PRs whose head commit has not been reviewed yet."""

    def __init__(self, db: Database, gh: GitHubClient, interval_sec: int):
        self.db = db
        self.gh = gh
        self.interval = interval_sec
        self._wake = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self.busy = False
        self.current: Optional[str] = None
        self.last_run_at: Optional[str] = None
        self.next_run_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self.started_reviews = 0
        self._inflight: Set[str] = set()

    @property
    def enabled(self) -> bool:
        return self.interval > 0

    def start(self) -> None:
        if self.enabled and not self._task:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def trigger(self) -> None:
        self._wake.set()

    def status(self) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        next_in = None
        if self.next_run_at is not None:
            next_in = max(0, round(self.next_run_at - loop.time()))
        return {
            "enabled": self.enabled,
            "interval_sec": self.interval,
            "busy": self.busy,
            "current": self.current,
            "last_run_at": self.last_run_at,
            "next_run_in_sec": next_in,
            "last_error": self.last_error,
            "started_reviews": self.started_reviews,
            "repos": [s["repo"] for s in self.db.auto_review_repos()],
        }

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            await self.tick()
            self.next_run_at = loop.time() + self.interval
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    async def tick(self) -> int:
        """Review every PR in opted-in repos whose current head has no review yet. Returns count."""
        if self.busy:
            return 0
        self.busy = True
        started = 0
        try:
            for settings in self.db.auto_review_repos():
                full_name = settings["repo"]
                owner, name = full_name.split("/", 1)
                pulls = await self.gh.list_pulls(owner, name)
                latest = self.db.latest_reviews(full_name)
                for p in pulls:
                    if p.get("draft") and not settings["include_drafts"]:
                        continue
                    review = latest.get(p["number"])
                    # Skip when this exact commit was already reviewed, is running, or failed
                    # (failures are retried by the user, not in a loop).
                    if review and review["head_sha"] == p["head"]["sha"]:
                        continue
                    key = f"{full_name}#{p['number']}@{p['head']['sha']}"
                    if key in self._inflight:
                        continue
                    self._inflight.add(key)
                    self.current = f"{full_name} #{p['number']}"
                    try:
                        pr = await self.gh.get_pull(owner, name, p["number"])
                        provider = get_provider()
                        review_id = begin_review(self.db, pr, full_name, provider)
                        # Sequential on purpose: keeps LLM usage within free-tier rate limits.
                        await run_review(self.db, self.gh, provider, review_id, owner, name, p["number"])
                        started += 1
                        self.started_reviews += 1
                    finally:
                        self._inflight.discard(key)
            self.last_error = None
        except Exception as e:  # keep the loop alive; surface the error in status
            log.exception("Auto-review tick failed")
            self.last_error = str(e) or e.__class__.__name__
        finally:
            self.busy = False
            self.current = None
            self.last_run_at = now()
        return started
