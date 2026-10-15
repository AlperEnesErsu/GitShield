"""Previous-review lookup and follow-up checks for incremental reviews."""

import logging
from typing import Any

from gitshield.web.config import settings
from gitshield.web.db import Database
from gitshield.web.llm import LLMProvider
from gitshield.web.review_diff import map_old_line
from gitshield.web.review_schemas import FOLLOWUP_SYSTEM, FollowupOutput

log = logging.getLogger(__name__)


def find_previous_review(db: Database, repo: str, number: int, review_id: int,
                         head_sha: str) -> dict[str, Any] | None:
    """The most recent finished review of this PR made for a different (older) commit."""
    for r in db.list_pr_reviews(repo, number):
        if r["id"] != review_id and r["status"] in ("ready", "submitted") and r["head_sha"] != head_sha:
            return db.get_review(r["id"])
    return None


async def check_followups(provider: LLMProvider | None, previous: dict[str, Any],
                          delta_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify each still-relevant comment of ``previous`` as fixed / still_open / unclear."""
    patches = {f["filename"]: f for f in delta_files}
    results: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for c in previous["comments"]:
        if not c["included"] or c["verification"] == "rejected" or c["line"] is None:
            continue
        item = {"prev": c, "path": c["path"], "old_line": c["line"], "new_line": c["line"],
                "severity": c["severity"], "title": c["title"]}
        f = patches.get(c["path"])
        if not f:
            item.update(status="still_open", note="Bu dosyaya yeni commit'lerde dokunulmadı.")
        elif f.get("status") == "removed":
            item.update(status="fixed", new_line=None, note="Dosya kaldırıldı.")
        elif not f.get("patch"):
            item.update(status="unclear", note="Değişiklik görüntülenemiyor (binary ya da çok büyük).")
        else:
            new_line, touched = map_old_line(f["patch"], c["line"])
            item["new_line"] = new_line
            if new_line is not None and not touched:
                item.update(status="still_open", note="İlgili satırlar değişmedi.")
            else:
                item.update(status="unclear", note="İlgili bölge değişti; kontrol gerekiyor.")
                candidates.append(item)
        results.append(item)

    if provider and candidates:
        numbered = "\n\n".join(
            f"[{i}] {it['path']}:{it['old_line']} [{it['severity']}] {it['prev']['title']}\n"
            f"{it['prev']['body']}\n<new_commits_diff>\n{patches[it['path']]['patch']}\n</new_commits_diff>"
            for i, it in enumerate(candidates)
        )
        out = await provider.complete(FOLLOWUP_SYSTEM.format(language=settings.review_language),
                                      numbered, FollowupOutput)
        for entry in out.items:
            if 0 <= entry.index < len(candidates):
                candidates[entry.index].update(status=entry.status, note=entry.reason)
    return results
