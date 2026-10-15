"""Review progress tracking (steps and the persisted Progress helper)."""

import logging
from typing import Any

from gitshield.web.db import Database, now

log = logging.getLogger(__name__)


# ---- Progress tracking ------------------------------------------------------------

STEPS = [
    ("fetch", "PR alındı"),
    ("scan", "Statik tarama"),
    ("ai_review", "AI review"),
    ("verify", "Doğrulama"),
    ("approve", "Senin onayın"),
    ("submit", "GitHub'a gönderim"),
]


def initial_progress() -> list[dict[str, Any]]:
    return [{"key": k, "label": label, "status": "pending", "detail": "",
             "started_at": None, "finished_at": None} for k, label in STEPS]


class Progress:
    """Persists per-step status so the UI can draw the pipeline live."""

    def __init__(self, db: Database, review_id: int, steps: list[dict[str, Any]] | None = None):
        self.db = db
        self.review_id = review_id
        self.steps = steps if steps else initial_progress()

    def _set(self, key: str, status: str, detail: str | None) -> None:
        for step in self.steps:
            if step["key"] != key:
                continue
            if status == "running":
                step["started_at"] = now()
            elif status in ("done", "skipped", "failed"):
                step["started_at"] = step["started_at"] or now()
                step["finished_at"] = now()
            step["status"] = status
            if detail is not None:
                step["detail"] = detail
        self.db.update_review(self.review_id, progress=self.steps)

    def start(self, key: str, detail: str = "") -> None:
        self._set(key, "running", detail)

    def done(self, key: str, detail: str) -> None:
        self._set(key, "done", detail)

    def skip(self, key: str, detail: str) -> None:
        self._set(key, "skipped", detail)

    def append(self, key: str, note: str) -> None:
        """Add a note to a step's detail, closing it if it never started."""
        step = next(st for st in self.steps if st["key"] == key)
        detail = f"{step['detail']} · {note}" if step["detail"] else note[:1].upper() + note[1:]
        self._set(key, "done" if step["status"] == "pending" else step["status"], detail)

    def fail_running(self, detail: str) -> None:
        for step in self.steps:
            if step["status"] == "running":
                self._set(step["key"], "failed", detail)
