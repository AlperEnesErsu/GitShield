import asyncio

import pytest

pytest.importorskip("fastapi")

from gitshield.web.db import Database
from gitshield.web.review import memory_prompt, run_review, suppressing_memory
from tests.test_web_review import FakeGitHub, FakeProvider


def _run(db, provider=None):
    rid = db.create_review("acme/app", 7, "Add config", "abc123", "none", "")
    asyncio.run(run_review(db, FakeGitHub(), provider, rid, "acme", "app", 7))
    return db.get_review(rid)


def test_suppressed_scanner_rule_is_rejected_next_time(tmp_path):
    db = Database(tmp_path / "t.db")
    first = _run(db)
    target = first["comments"][0]
    assert target["rule_id"], "scanner comments carry their rule id"

    db.add_memory("acme/app", "suppress", f"{target['title']}: x", rule_id=target["rule_id"],
                  path=target["path"])
    second = _run(db)

    again = next(c for c in second["comments"] if c["rule_id"] == target["rule_id"])
    assert again["verification"] == "rejected" and not again["included"]
    assert "Repo hafızası" in again["verification_note"]
    assert db.list_memory("acme/app")[0]["hits"] == 1
    assert "susturdu" in {s["key"]: s["detail"] for s in second["progress"]}["verify"]


def test_file_scoped_suppression_does_not_leak_to_other_files():
    memory = [{"id": 1, "kind": "suppress", "text": "SQL injection: ...", "rule_id": None,
               "path": "app/config.py"}]
    same = {"path": "app/config.py", "title": "SQL Injection", "rule_id": None}
    other = {"path": "app/other.py", "title": "SQL Injection", "rule_id": None}
    assert suppressing_memory(same, memory)["id"] == 1
    assert suppressing_memory(other, memory) is None


def test_memory_reaches_the_llm_prompts(tmp_path):
    db = Database(tmp_path / "t.db")
    db.add_memory("acme/app", "rule", "Bu repoda Riverpod kullanılıyor; Provider önerme.")
    db.add_memory("acme/app", "suppress", "Magic number: ...", path=None)
    provider = FakeProvider()
    review = _run(db, provider)

    assert review["status"] == "ready", review["error"]
    assert all("<repo_memory>" in p and "Riverpod" in p for p in provider.prompts)
    assert "whole repository" in memory_prompt(db.list_memory("acme/app"))


def test_inactive_memory_is_ignored(tmp_path):
    db = Database(tmp_path / "t.db")
    item = db.add_memory("acme/app", "rule", "Kural")
    db.update_memory(item["id"], active=False)
    assert memory_prompt(db.list_memory("acme/app", active_only=True)) == ""


def test_memory_api_roundtrip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from gitshield.web import app as app_module
    from gitshield.web.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "api.db")
    monkeypatch.setattr(settings, "auto_review_interval", 0)
    with TestClient(app_module.app) as client:
        store = app_module.app.state.db
        rid = store.create_review("acme/app", 7, "t", "abc", "none", "")
        cid = store.add_comment(rid, source="llm", path="a.py", line=3, in_diff=True, severity="LOW",
                                category="style", title="Magic number", body="Use a constant.",
                                suggestion=None, rule_id=None, verification="confirmed",
                                verification_note="", included=True)

        res = client.post(f"/api/comments/{cid}/suppress", json={"scope": "repo"})
        assert res.status_code == 201
        assert res.json()["memory"]["path"] is None and res.json()["comment"]["included"] is False

        rule = client.post("/api/repos/acme/app/memory", json={"text": "  Riverpod kullan  "}).json()
        assert rule["text"] == "Riverpod kullan" and rule["kind"] == "rule"
        assert client.post("/api/repos/acme/app/memory", json={"text": " "}).status_code == 422

        client.patch(f"/api/memory/{rule['id']}", json={"active": False})
        items = client.get("/api/repos/acme/app/memory").json()
        assert {(m["kind"], m["active"]) for m in items} == {("suppress", True), ("rule", False)}

        assert client.delete(f"/api/memory/{rule['id']}").status_code == 204
        assert len(client.get("/api/repos/acme/app/memory").json()) == 1
