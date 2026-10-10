import json
from datetime import date, datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")

from gitshield.web.db import Database
from gitshield.web.gamification import compute, level_for, review_xp, streaks

TODAY = date(2026, 10, 10)


def at(day_offset: int, hour: int = 14) -> str:
    """ISO timestamp `day_offset` days before TODAY at `hour` local time."""
    local = datetime.combine(TODAY - timedelta(days=day_offset), datetime.min.time()).replace(hour=hour)
    return local.astimezone().astimezone(timezone.utc).isoformat()


def submit(db, day_offset, *, origin="manual", severities=(), approval_minutes=None, hour=14):
    rid = db.create_review("acme/app", 1, "t", f"sha{day_offset}{hour}{origin}", "none", "")
    progress = []
    if approval_minutes is not None:
        end = datetime.fromisoformat(at(day_offset, hour))
        progress = [{"key": "approve", "started_at": (end - timedelta(minutes=approval_minutes)).isoformat(),
                     "finished_at": end.isoformat()}]
    db.update_review(rid, status="submitted", submitted_at=at(day_offset, hour), origin=origin, progress=progress)
    for sev in severities:
        db.add_comment(rid, source="llm", path="a.py", line=1, in_diff=True, severity=sev, category="bug",
                       title="x", body="y", suggestion=None, rule_id=None, verification="confirmed",
                       verification_note="", included=True)
    return rid


def test_levels():
    assert level_for(0)["level"] == 1 and level_for(99)["level"] == 1
    assert level_for(100)["level"] == 2 and level_for(300)["level"] == 3
    assert level_for(150)["progress"] == 0.25  # 50 of the 200 XP between level 2 and 3


def test_streaks_keep_today_alive_until_it_ends():
    days = [TODAY - timedelta(days=d) for d in (1, 2, 3, 6, 7)]
    assert streaks(days, TODAY) == {"current": 3, "best": 3}
    assert streaks(days + [TODAY], TODAY)["current"] == 4
    assert streaks([TODAY - timedelta(days=2)], TODAY)["current"] == 0, "a missed day breaks the streak"


def test_review_xp():
    base = {"origin": "manual", "included": 0, "critical": 0, "high": 0, "approval_minutes": None}
    assert review_xp(base) == 10
    assert review_xp({**base, "included": 9, "critical": 1, "approval_minutes": 5}) == 10 + 25 + 20 + 5
    assert review_xp({**base, "origin": "batch"}) == 3


def test_compute_badges_streak_and_new_flags(tmp_path):
    db = Database(tmp_path / "t.db")
    submit(db, 2)
    submit(db, 1, severities=("CRITICAL", "HIGH"), approval_minutes=4)
    submit(db, 0, hour=2)  # night owl
    for i in range(3):
        submit(db, 0, origin="batch", hour=15 + i)

    g = compute(db, today=TODAY)
    earned = {b["id"] for b in g["badges"] if b["earned"]}
    assert {"first-review", "critical-catch", "lightning", "streak-3", "night-owl"} <= earned
    assert "dependency-keeper" not in earned, "3 of 10 batch approvals"
    keeper = next(b for b in g["badges"] if b["id"] == "dependency-keeper")
    assert (keeper["value"], keeper["target"]) == (3, 10)
    assert g["stats"]["reviews"] == 3, "batch approvals are not manual reviews"
    assert g["streak"]["current"] == 3 and g["streak"]["today"] == 1 and not g["streak"]["at_risk"]
    assert sum(c["count"] for c in g["heatmap"]) == 3 and g["heatmap"][-1]["date"] == TODAY.isoformat()

    assert {b["id"] for b in g["new_badges"]} == earned
    db.mark_achievements_seen()
    assert compute(db, today=TODAY)["new_badges"] == [], "a badge is celebrated once"


def test_goal_and_inbox_zero_via_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from gitshield.web import app as app_module
    from gitshield.web.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "api.db")
    monkeypatch.setattr(settings, "auto_review_interval", 0)
    with TestClient(app_module.app) as client:
        assert client.put("/api/gamification/goal", json={"goal": 5}).json()["streak"]["goal"] == 5
        assert client.put("/api/gamification/goal", json={"goal": 0}).status_code == 422
        app_module.app.state.db.grant_achievement("marker:inbox-zero")
        badges = {b["id"]: b for b in client.get("/api/gamification").json()["badges"]}
        assert badges["inbox-zero"]["earned"] and badges["inbox-zero"]["new"]
        assert client.post("/api/gamification/seen").status_code == 204
        assert client.get("/api/gamification").json()["new_badges"] == []
        assert json.dumps(badges["inbox-zero"])  # serializable for the UI
