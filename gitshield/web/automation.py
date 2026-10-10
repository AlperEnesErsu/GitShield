"""Cross-repo inbox and the background auto-review watcher."""

import asyncio
import logging
from typing import Any

from gitshield.web.config import settings
from gitshield.web.db import Database, hours_ago, now
from gitshield.web.github import GitHubClient, GitHubError
from gitshield.web.insights import pr_insights
from gitshield.web.llm import get_provider
from gitshield.web.review import begin_review, run_review, submit_review

log = logging.getLogger(__name__)

# Lower number = more urgent. The UI groups by kind in this order.
PRIORITY = {"approve": 1, "failed": 2, "outdated": 3, "new": 4, "running": 5, "drafts": 6}
MAX_CONCURRENT_REPOS = 6


def _pull_item(kind: str, repo: str, p: dict[str, Any], review: dict[str, Any] | None,
               detail: dict[str, Any] | None, ci_blame: str | None = None) -> dict[str, Any]:
    return {
        **pr_insights(detail, review, ci_blame),
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


def classify(p: dict[str, Any], review: dict[str, Any] | None) -> str:
    if not review:
        return "new"
    if review["status"] == "running":
        return "running"
    if review["status"] == "failed":
        return "failed"
    if review["head_sha"] != p["head"]["sha"]:
        return "outdated"
    return "approve" if review["status"] == "ready" else "done"


async def build_inbox(db: Database, gh: GitHubClient) -> dict[str, Any]:
    """Everything that needs the user's attention across all repositories, most urgent first."""
    repos = (await gh.list_repos())["repos"]
    active = [r["nameWithOwner"] for r in repos if r["pullRequests"]["totalCount"] and not r["isArchived"]]
    sem = asyncio.Semaphore(MAX_CONCURRENT_REPOS)

    async def pulls_for(full_name: str):
        owner, name = full_name.split("/", 1)
        async with sem:
            try:
                pulls, details = await asyncio.gather(
                    gh.list_pulls(owner, name), gh.open_pulls_detail(owner, name))
                return full_name, pulls, details, None
            except GitHubError as e:
                return full_name, [], {}, e.message

    results = await asyncio.gather(*(pulls_for(r) for r in active))
    items: list[dict[str, Any]] = []
    errors = []
    for full_name, pulls, details, error in results:
        if error:
            errors.append({"repo": full_name, "error": error})
        latest = db.latest_reviews(full_name)
        for p in pulls:
            kind = classify(p, latest.get(p["number"]))
            if kind != "done":
                items.append(_pull_item(kind, full_name, p, latest.get(p["number"]), details.get(p["number"]),
                                        db.ci_verdict(full_name, p["number"], p["head"]["sha"])))

    drafts: dict[str, list[dict[str, Any]]] = {}
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

    # Most urgent kind first; within a kind, riskiest first, then the oldest waiting.
    items.sort(key=lambda i: (i["priority"], -((i.get("risk") or {}).get("score") or 0), i["updated_at"]))
    counts: dict[str, int] = {}
    for i in items:
        counts[i["kind"]] = counts.get(i["kind"], 0) + 1
    actionable = sum(n for k, n in counts.items() if k != "running")
    if actionable == 0 and not errors and active:
        db.grant_achievement("marker:inbox-zero")
    return {"items": items, "counts": counts, "actionable": actionable, "errors": errors,
            "repos_checked": len(active)}


class AutoReviewer:
    """Polls opted-in repositories and reviews PRs whose head commit has not been reviewed yet."""

    def __init__(self, db: Database, gh: GitHubClient, interval_sec: int):
        self.db = db
        self.gh = gh
        self.interval = interval_sec
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.busy = False
        self.current: str | None = None
        self.last_run_at: str | None = None
        self.next_run_at: float | None = None
        self.last_error: str | None = None
        self.started_reviews = 0
        self._inflight: set[str] = set()

    @property
    def enabled(self) -> bool:
        return self.interval > 0

    def auto_reviews_today(self) -> int:
        """Automatic reviews started in the last 24 hours (the DB is the source of truth)."""
        return self.db.count_reviews("auto", hours_ago(24))

    def auto_reviews_remaining(self) -> int | None:
        """Budget left for today; None when GITSHIELD_MAX_AUTO_REVIEWS_PER_DAY is 0 (unlimited)."""
        cap = settings.max_auto_reviews_per_day
        if cap <= 0:
            return None
        return max(0, cap - self.auto_reviews_today())

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

    def status(self) -> dict[str, Any]:
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
            "max_auto_reviews_per_day": settings.max_auto_reviews_per_day,
            "auto_reviews_remaining": self.auto_reviews_remaining(),
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
            except TimeoutError:
                pass

    async def tick(self) -> int:
        """Review every PR in opted-in repos whose current head has no review yet. Returns count."""
        if self.busy:
            return 0
        self.busy = True
        started = 0
        try:
            for repo_settings in self.db.auto_review_repos():
                full_name = repo_settings["repo"]
                owner, name = full_name.split("/", 1)
                pulls = await self.gh.list_pulls(owner, name)
                latest = self.db.latest_reviews(full_name)
                for p in pulls:
                    if p.get("draft") and not repo_settings["include_drafts"]:
                        continue
                    review = latest.get(p["number"])
                    # Skip when this exact commit was already reviewed, is running, or failed
                    # (failures are retried by the user, not in a loop).
                    if review and (review["head_sha"] == p["head"]["sha"] or review["status"] == "running"):
                        continue
                    key = f"{full_name}#{p['number']}@{p['head']['sha']}"
                    if key in self._inflight:
                        continue
                    remaining = self.auto_reviews_remaining()
                    if remaining is not None and remaining <= 0:
                        # Daily budget used up: the rest waits for the next day's window.
                        log.info("Auto-review budget for today is used up; %s waits", key)
                        return started
                    self._inflight.add(key)
                    self.current = f"{full_name} #{p['number']}"
                    try:
                        pr = await self.gh.get_pull(owner, name, p["number"])
                        provider = get_provider(self.db)
                        review_id = begin_review(self.db, pr, full_name, provider, origin="auto")
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


async def approve_dependency_batch(store: Database, client: GitHubClient, owner: str, repo: str,
                                   numbers: list[int], allow_major: bool = False) -> list[dict[str, Any]]:
    """Approve dependency-update PRs that are green on CI and clean on the static scan.

    Every guard is enforced here, not only in the UI: non-dependency PRs, failing or
    missing CI, major bumps (unless allow_major) and PRs with HIGH/CRITICAL findings
    are skipped with a reason.
    """
    full_name = f"{owner}/{repo}"
    details = await client.open_pulls_detail(owner, repo)
    results = []
    for number in numbers:
        node = details.get(number)
        info = pr_insights(node)
        dep = info["dependency"]
        skip = None
        if not node:
            skip = "PR açık değil"
        elif not dep:
            skip = "Bağımlılık güncellemesi değil"
        elif info["ci"] != "success":
            skip = {"failure": "CI başarısız", "pending": "CI henüz bitmedi"}.get(info["ci"], "CI sonucu yok")
        elif dep["change"] == "major" and not allow_major:
            skip = "Major güncelleme; ayrıca onay gerekiyor"
        if skip:
            results.append({"number": number, "status": "skipped", "reason": skip})
            continue

        pr = await client.get_pull(owner, repo, number)
        review_id = begin_review(store, pr, full_name, None, origin="batch")
        await run_review(store, client, None, review_id, owner, repo, number, notify=False)
        review = store.get_review(review_id)
        if review is None:
            results.append({"number": number, "status": "failed", "reason": "İnceleme kaydı bulunamadı",
                            "review_id": review_id})
            continue
        serious = [c for c in review["comments"] if c["severity"] in ("CRITICAL", "HIGH")]
        if review["status"] != "ready" or serious:
            reason = review["error"] or f"{len(serious)} yüksek önemli tarama bulgusu"
            results.append({"number": number, "status": "skipped", "reason": reason, "review_id": review_id})
            continue
        versions = f" ({dep['from']} → {dep['to']})" if dep["from"] else ""
        store.update_review(review_id, summary=(
            f"Bağımlılık güncellemesi: **{dep['package']}**{versions}, {dep['change']}. "
            "CI başarılı, GitShield statik taraması temiz. Toplu onayla onaylandı."
        ))
        review = store.get_review(review_id)
        if review is None:
            results.append({"number": number, "status": "failed", "reason": "İnceleme kaydı bulunamadı",
                            "review_id": review_id})
            continue
        try:
            submitted = await submit_review(store, client, review, "APPROVE")
            results.append({"number": number, "status": "approved", "url": submitted.get("html_url"),
                            "review_id": review_id})
        except GitHubError as e:
            results.append({"number": number, "status": "failed", "reason": e.message, "review_id": review_id})
    return results
