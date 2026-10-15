"""Golden-output test for the review pipeline.

Runs `run_review` through representative scenarios and compares everything it
persists (review row, comments, progress, follow-ups, draft issues) and every
prompt it sends with a snapshot recorded from the original implementation.
Volatile fields (ids, timestamps) are dropped before comparing.

Regenerate deliberately with: GITSHIELD_UPDATE_GOLDEN=1 pytest tests/test_run_review_golden.py
"""

import asyncio
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from gitshield.web.db import Database
from gitshield.web.llm import LLMUnavailable
from gitshield.web.review import VerificationOutput, run_review
from tests.test_web_incremental import IncrementalGitHub
from tests.test_web_review import PR, FakeGitHub, FakeProvider

GOLDEN = Path(__file__).with_name("golden") / "run_review.json"
VOLATILE = {"id", "review_id", "comment_id", "prev_comment_id", "created_at", "updated_at",
            "started_at", "finished_at", "submitted_at", "at", "ts", "time"}


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in sorted(value.items()) if k not in VOLATILE}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


class FlakyVerifier(FakeProvider):
    async def complete(self, system, user, schema):
        if schema is VerificationOutput:
            raise LLMUnavailable("Gemini şu an yanıt vermiyor (503)")
        return await super().complete(system, user, schema)


def _run(db, gh, provider, head="abc123"):
    rid = db.create_review("acme/app", 7, PR["title"], head,
                           provider.name if provider else "none",
                           provider.model if provider else "")
    asyncio.run(run_review(db, gh, provider, rid, "acme", "app", 7))
    review = db.get_review(rid)
    review["followups"] = db.list_followups(rid) if hasattr(db, "list_followups") else []
    return review


def _scenarios(tmp_path):
    out = {}
    for name, provider_cls in (("llm", FakeProvider), ("scanner_only", None), ("verifier_outage", FlakyVerifier)):
        db = Database(tmp_path / f"{name}.db")
        try:
            provider = provider_cls() if provider_cls else None
            review = _run(db, FakeGitHub(), provider)
            out[name] = {
                "review": _clean(review),
                "prompts": provider.prompts if provider else [],
                "drafts": _clean(db.list_draft_issues("acme/app")),
            }
        finally:
            db.close()

    db = Database(tmp_path / "incremental.db")
    try:
        _run(db, IncrementalGitHub(head="abc123"), None)
        second = _run(db, IncrementalGitHub(head="def456"), None, head="def456")
        out["incremental"] = {"review": _clean(second), "drafts": _clean(db.list_draft_issues("acme/app"))}
    finally:
        db.close()
    return out


def test_run_review_output_matches_the_golden_snapshot(tmp_path):
    actual = json.loads(json.dumps(_scenarios(tmp_path), ensure_ascii=False, default=str))
    if os.getenv("GITSHIELD_UPDATE_GOLDEN") or not GOLDEN.exists():
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(actual, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        pytest.skip("golden snapshot written")
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert actual == expected
