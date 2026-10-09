"""SQLite persistence for reviews, review comments and draft issues."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    pr_title TEXT NOT NULL DEFAULT '',
    head_sha TEXT NOT NULL,
    status TEXT NOT NULL,              -- running | ready | failed | submitted
    error TEXT,
    summary TEXT NOT NULL DEFAULT '',
    verdict TEXT NOT NULL DEFAULT 'COMMENT',
    recommended_verdict TEXT,
    verifier_notes TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT 'none',
    model TEXT NOT NULL DEFAULT '',
    skipped_files TEXT NOT NULL DEFAULT '[]',
    stats TEXT NOT NULL DEFAULT '{}',
    github_review_url TEXT,
    progress TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    submitted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reviews_pr ON reviews(repo, pr_number);

CREATE TABLE IF NOT EXISTS review_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    source TEXT NOT NULL,              -- scanner | llm
    path TEXT NOT NULL,
    line INTEGER,
    in_diff INTEGER NOT NULL DEFAULT 0,
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    suggestion TEXT,
    rule_id TEXT,
    verification TEXT NOT NULL DEFAULT 'unverified',  -- confirmed | rejected | uncertain | unverified
    verification_note TEXT NOT NULL DEFAULT '',
    included INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS draft_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    review_id INTEGER REFERENCES reviews(id) ON DELETE SET NULL,
    comment_id INTEGER REFERENCES review_comments(id) ON DELETE SET NULL,
    fingerprint TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',  -- draft | opened | dismissed
    github_issue_number INTEGER,
    github_issue_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(repo, fingerprint)
);

CREATE TABLE IF NOT EXISTS followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    prev_comment_id INTEGER REFERENCES review_comments(id) ON DELETE SET NULL,
    path TEXT NOT NULL,
    old_line INTEGER,
    new_line INTEGER,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,            -- fixed | still_open | unclear
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    kind TEXT NOT NULL,              -- suppress (do not raise again) | rule (instruction for the reviewer)
    text TEXT NOT NULL,
    rule_id TEXT,                    -- scanner rule a suppression applies to
    path TEXT,                       -- NULL = whole repository
    source_comment_id INTEGER REFERENCES review_comments(id) ON DELETE SET NULL,
    active INTEGER NOT NULL DEFAULT 1,
    hits INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_repo ON memory(repo);

CREATE TABLE IF NOT EXISTS repo_settings (
    repo TEXT PRIMARY KEY,
    auto_review INTEGER NOT NULL DEFAULT 0,
    include_drafts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""

DEFAULT_REPO_SETTINGS = {"auto_review": False, "include_drafts": False}

REVIEW_COLUMNS = {"status", "error", "summary", "verdict", "recommended_verdict", "verifier_notes",
                  "provider", "model", "skipped_files", "stats", "github_review_url", "submitted_at",
                  "progress", "mode", "base_sha"}
COMMENT_COLUMNS = {"body", "title", "included", "verification", "verification_note"}
ISSUE_COLUMNS = {"title", "body", "status", "github_issue_number", "github_issue_url"}
JSON_COLUMNS = {"skipped_files", "stats", "progress"}

# Columns added after the first release; created on startup for older databases.
MIGRATIONS = {
    "reviews": {
        "progress": "TEXT NOT NULL DEFAULT '[]'",
        "mode": "TEXT NOT NULL DEFAULT 'full'",
        "base_sha": "TEXT",
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _encode(key: str, value: Any) -> Any:
    if key in JSON_COLUMNS:
        return json.dumps(value)
    if isinstance(value, bool):
        return int(value)
    return value


def _review_row(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    for key in JSON_COLUMNS:
        data[key] = json.loads(data[key])
    return data


def _comment_row(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    data["in_diff"] = bool(data["in_diff"])
    data["included"] = bool(data["included"])
    return data


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        for table, columns in MIGRATIONS.items():
            existing = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            for name, ddl in columns.items():
                if name not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        self._conn.commit()
        self._lock = threading.Lock()

    def _exec(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def _update(self, table: str, row_id: int, allowed: set, fields: Dict[str, Any]) -> None:
        fields = {k: v for k, v in fields.items() if k in allowed}
        if table != "review_comments":
            fields["updated_at"] = now()
        if not fields:
            return
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self._exec(
            f"UPDATE {table} SET {assignments} WHERE id = ?",
            [_encode(k, v) for k, v in fields.items()] + [row_id],
        )

    # ---- Reviews ---------------------------------------------------------------

    def create_review(self, repo: str, pr_number: int, pr_title: str, head_sha: str,
                      provider: str, model: str) -> int:
        ts = now()
        cur = self._exec(
            "INSERT INTO reviews (repo, pr_number, pr_title, head_sha, status, provider, model,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?)",
            (repo, pr_number, pr_title, head_sha, provider, model, ts, ts),
        )
        return int(cur.lastrowid)

    def update_review(self, review_id: int, **fields: Any) -> None:
        self._update("reviews", review_id, REVIEW_COLUMNS, fields)

    def get_review(self, review_id: int) -> Optional[Dict[str, Any]]:
        row = self._exec("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
        if not row:
            return None
        review = _review_row(row)
        review["comments"] = self.list_comments(review_id)
        review["followups"] = self.list_followups(review_id)
        return review

    def latest_reviews(self, repo: str) -> Dict[int, Dict[str, Any]]:
        """Latest review per PR number for a repository."""
        rows = self._exec(
            "SELECT r.*, "
            " (SELECT COUNT(*) FROM review_comments c WHERE c.review_id = r.id"
            "   AND c.verification != 'rejected') AS open_comments,"
            " (SELECT COUNT(*) FROM review_comments c WHERE c.review_id = r.id"
            "   AND c.verification != 'rejected' AND c.severity = 'CRITICAL') AS critical_findings,"
            " (SELECT COUNT(*) FROM review_comments c WHERE c.review_id = r.id"
            "   AND c.verification != 'rejected' AND c.severity = 'HIGH') AS high_findings"
            " FROM reviews r WHERE r.repo = ? AND r.id IN"
            " (SELECT MAX(id) FROM reviews WHERE repo = ? GROUP BY pr_number)",
            (repo, repo),
        ).fetchall()
        return {row["pr_number"]: _review_row(row) for row in rows}

    def list_pr_reviews(self, repo: str, pr_number: int) -> List[Dict[str, Any]]:
        rows = self._exec(
            "SELECT * FROM reviews WHERE repo = ? AND pr_number = ? ORDER BY id DESC",
            (repo, pr_number),
        ).fetchall()
        return [_review_row(r) for r in rows]

    def repo_stats(self) -> Dict[str, Dict[str, Any]]:
        rows = self._exec(
            "SELECT repo, COUNT(*) AS reviews, MAX(created_at) AS last_review_at,"
            " SUM(status = 'submitted') AS submitted"
            " FROM reviews GROUP BY repo"
        ).fetchall()
        stats = {r["repo"]: dict(r) for r in rows}
        for r in self._exec(
            "SELECT repo, COUNT(*) AS drafts FROM draft_issues WHERE status = 'draft' GROUP BY repo"
        ).fetchall():
            stats.setdefault(r["repo"], {"repo": r["repo"], "reviews": 0})["draft_issues"] = r["drafts"]
        return stats

    # ---- Comments --------------------------------------------------------------

    def add_comment(self, review_id: int, **fields: Any) -> int:
        cols = ["review_id"] + list(fields)
        cur = self._exec(
            f"INSERT INTO review_comments ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [review_id] + [_encode(k, v) for k, v in fields.items()],
        )
        return int(cur.lastrowid)

    def list_comments(self, review_id: int) -> List[Dict[str, Any]]:
        rows = self._exec(
            "SELECT * FROM review_comments WHERE review_id = ? ORDER BY id", (review_id,)
        ).fetchall()
        return [_comment_row(r) for r in rows]

    def get_comment(self, comment_id: int) -> Optional[Dict[str, Any]]:
        row = self._exec("SELECT * FROM review_comments WHERE id = ?", (comment_id,)).fetchone()
        return _comment_row(row) if row else None

    def update_comment(self, comment_id: int, **fields: Any) -> None:
        self._update("review_comments", comment_id, COMMENT_COLUMNS, fields)

    # ---- Draft issues ----------------------------------------------------------

    def add_draft_issue(self, repo: str, review_id: Optional[int], comment_id: Optional[int],
                        fingerprint: str, title: str, body: str, severity: str) -> Optional[int]:
        """Insert a draft issue; returns None if the same finding already has one."""
        ts = now()
        cur = self._exec(
            "INSERT OR IGNORE INTO draft_issues (repo, review_id, comment_id, fingerprint, title,"
            " body, severity, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (repo, review_id, comment_id, fingerprint, title, body, severity, ts, ts),
        )
        return int(cur.lastrowid) if cur.rowcount else None

    def list_draft_issues(self, repo: str, include_closed: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM draft_issues WHERE repo = ?"
        if not include_closed:
            sql += " AND status = 'draft'"
        rows = self._exec(sql + " ORDER BY id DESC", (repo,)).fetchall()
        return [dict(r) for r in rows]

    def get_draft_issue(self, issue_id: int) -> Optional[Dict[str, Any]]:
        row = self._exec("SELECT * FROM draft_issues WHERE id = ?", (issue_id,)).fetchone()
        return dict(row) if row else None

    def update_draft_issue(self, issue_id: int, **fields: Any) -> None:
        self._update("draft_issues", issue_id, ISSUE_COLUMNS, fields)

    def list_pending_drafts(self) -> List[Dict[str, Any]]:
        rows = self._exec(
            "SELECT * FROM draft_issues WHERE status = 'draft' ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- Repo settings ---------------------------------------------------------

    def get_repo_settings(self, repo: str) -> Dict[str, Any]:
        row = self._exec("SELECT * FROM repo_settings WHERE repo = ?", (repo,)).fetchone()
        if not row:
            return {"repo": repo, **DEFAULT_REPO_SETTINGS}
        return {"repo": repo, "auto_review": bool(row["auto_review"]),
                "include_drafts": bool(row["include_drafts"])}

    def set_repo_settings(self, repo: str, **fields: Any) -> Dict[str, Any]:
        merged = {**self.get_repo_settings(repo), **{k: v for k, v in fields.items()
                                                       if k in DEFAULT_REPO_SETTINGS and v is not None}}
        self._exec(
            "INSERT INTO repo_settings (repo, auto_review, include_drafts, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(repo) DO UPDATE SET auto_review = excluded.auto_review,"
            " include_drafts = excluded.include_drafts, updated_at = excluded.updated_at",
            (repo, int(merged["auto_review"]), int(merged["include_drafts"]), now()),
        )
        return self.get_repo_settings(repo)

    def auto_review_repos(self) -> List[Dict[str, Any]]:
        rows = self._exec("SELECT repo FROM repo_settings WHERE auto_review = 1 ORDER BY repo").fetchall()
        return [self.get_repo_settings(r["repo"]) for r in rows]

    # ---- Follow-ups (did the previous review's comments get fixed?) -------------

    def add_followup(self, review_id: int, **fields: Any) -> None:
        cols = ["review_id"] + list(fields)
        self._exec(
            f"INSERT INTO followups ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [review_id] + list(fields.values()),
        )

    def list_followups(self, review_id: int) -> List[Dict[str, Any]]:
        rows = self._exec("SELECT * FROM followups WHERE review_id = ? ORDER BY id", (review_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---- Repo memory ---------------------------------------------------------------

    def add_memory(self, repo: str, kind: str, text: str, rule_id: Optional[str] = None,
                   path: Optional[str] = None, source_comment_id: Optional[int] = None) -> Dict[str, Any]:
        cur = self._exec(
            "INSERT INTO memory (repo, kind, text, rule_id, path, source_comment_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (repo, kind, text, rule_id, path, source_comment_id, now()),
        )
        return self.get_memory(int(cur.lastrowid))

    def get_memory(self, memory_id: int) -> Optional[Dict[str, Any]]:
        row = self._exec("SELECT * FROM memory WHERE id = ?", (memory_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["active"] = bool(data["active"])
        return data

    def list_memory(self, repo: str, active_only: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT id FROM memory WHERE repo = ?" + (" AND active = 1" if active_only else "")
        return [self.get_memory(r["id"]) for r in self._exec(sql + " ORDER BY id DESC", (repo,)).fetchall()]

    def update_memory(self, memory_id: int, **fields: Any) -> None:
        fields = {k: v for k, v in fields.items() if k in ("text", "active") and v is not None}
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            self._exec(f"UPDATE memory SET {sets} WHERE id = ?",
                       [_encode(k, v) for k, v in fields.items()] + [memory_id])

    def delete_memory(self, memory_id: int) -> None:
        self._exec("DELETE FROM memory WHERE id = ?", (memory_id,))

    def bump_memory_hits(self, memory_ids: Iterable[int]) -> None:
        for mid in set(memory_ids):
            self._exec("UPDATE memory SET hits = hits + 1 WHERE id = ?", (mid,))
