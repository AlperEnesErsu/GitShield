import asyncio

import pytest

pytest.importorskip("fastapi")

from gitshield.web import notify
from gitshield.web.db import Database
from gitshield.web.review import run_review
from tests.test_web_review import FakeGitHub


@pytest.fixture()
def open_db():
    """Open databases for a test and close them afterwards, so no SQLite connection leaks."""
    opened = []

    def factory(path):
        opened.append(Database(path))
        return opened[-1]

    yield factory
    for database in opened:
        database.close()


def test_message_for_ready_and_failed(monkeypatch):
    monkeypatch.setenv("GITSHIELD_PUBLIC_URL", "http://localhost:8000/")
    ready = {"repo": "acme/app", "pr_number": 7, "pr_title": "Add config", "status": "ready",
             "verdict": "REQUEST_CHANGES", "comments": [
                 {"included": True, "severity": "HIGH"}, {"included": False, "severity": "CRITICAL"}]}
    text = notify.review_message(ready)
    assert "acme/app #7" in text and "Değişiklik iste" in text and "1 yorum, 1 yüksek" in text
    assert text.endswith("http://localhost:8000/r/acme/app/pull/7")

    failed = {**ready, "status": "failed", "error": "quota exceeded"}
    assert "quota exceeded" in notify.review_message(failed)


def test_channels_from_env(monkeypatch):
    for key in ("GITSHIELD_SLACK_WEBHOOK", "GITSHIELD_DISCORD_WEBHOOK",
                "GITSHIELD_TELEGRAM_BOT_TOKEN", "GITSHIELD_TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(key, raising=False)
    assert notify.channels() == []
    monkeypatch.setenv("GITSHIELD_TELEGRAM_BOT_TOKEN", "t")
    assert notify.channels() == [], "telegram needs both token and chat id"
    monkeypatch.setenv("GITSHIELD_TELEGRAM_CHAT_ID", "1")
    monkeypatch.setenv("GITSHIELD_SLACK_WEBHOOK", "https://hooks.example/x")
    assert notify.channels() == ["slack", "telegram"]


def test_pipeline_notifies_once_unless_disabled(tmp_path, monkeypatch, open_db):
    sent = []

    async def fake_send(text):
        sent.append(text)
        return {"slack": "ok"}

    monkeypatch.setattr(notify, "channels", lambda: ["slack"])
    monkeypatch.setattr(notify, "send", fake_send)
    db = open_db(tmp_path / "t.db")
    for flag in (True, False):
        rid = db.create_review("acme/app", 7, "Add config", "abc123", "none", "")
        asyncio.run(run_review(db, FakeGitHub(), None, rid, "acme", "app", 7, notify=flag))
    assert len(sent) == 1 and "onayını bekliyor" in sent[0]
