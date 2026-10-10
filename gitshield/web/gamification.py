"""Streaks, XP, levels and badges — all derived from what the user actually did in GitShield.

Nothing is tracked twice: reviews, fix PRs, opened issues, memory and CI diagnoses already live
in the database, so progress is recomputed from them (and earned badges are remembered so the UI
can celebrate new ones exactly once)."""

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from gitshield.web.db import Database

DEFAULT_DAILY_GOAL = 3
HEATMAP_DAYS = 182  # 26 weeks
LEVEL_TITLES = ["Çaylak", "Gözcü", "Muhafız", "Bekçi", "Kalkan Ustası", "Kod Şövalyesi", "Efsane"]
FAST_APPROVAL_MIN = 15


def local_day(ts: Optional[str]) -> Optional[date]:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date()


def level_for(xp: int) -> Dict[str, Any]:
    """Level n needs 100·n·(n+1)/2 XP in total: 100, 300, 600, 1000 …"""
    level = int((math.sqrt(1 + 8 * xp / 100) - 1) / 2) + 1
    floor = 100 * (level - 1) * level // 2
    ceil = 100 * level * (level + 1) // 2
    return {
        "level": level,
        "title": LEVEL_TITLES[min(level - 1, len(LEVEL_TITLES) - 1)],
        "xp": xp,
        "level_floor": floor,
        "next_level_xp": ceil,
        "progress": round((xp - floor) / (ceil - floor), 3),
    }


def review_xp(review: Dict[str, Any]) -> int:
    """XP for one submitted review: base + real findings + severity + speed."""
    if review["origin"] == "batch":
        return 3
    xp = 10 + min(25, 5 * (review["included"] or 0))
    if review["critical"]:
        xp += 20
    elif review["high"]:
        xp += 10
    minutes = review.get("approval_minutes")
    if minutes is not None and minutes <= 60:
        xp += 5
    return xp


def streaks(days_with_reviews: List[date], today: date) -> Dict[str, int]:
    """Current streak counts back from today (or yesterday, so today is not lost before the
    first review of the day); best is the longest run ever."""
    days = sorted(set(days_with_reviews))
    best = run = 0
    prev: Optional[date] = None
    for d in days:
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    current = 0
    present = set(days)
    cursor = today if today in present else today - timedelta(days=1)
    while cursor in present:
        current += 1
        cursor -= timedelta(days=1)
    return {"current": current, "best": best}


@dataclass
class Badge:
    id: str
    name: str
    description: str
    icon: str
    target: int
    metric: Callable[[Dict[str, Any]], int]
    tier: str = "bronze"


BADGES: List[Badge] = [
    Badge("first-review", "İlk Kan", "İlk review'unu GitHub'a gönder.", "🛡️", 1, lambda s: s["reviews"]),
    Badge("ten-reviews", "Düzenli Bekçi", "10 review gönder.", "🏅", 10, lambda s: s["reviews"], "silver"),
    Badge("fifty-reviews", "Kale Komutanı", "50 review gönder.", "🏰", 50, lambda s: s["reviews"], "gold"),
    Badge("bug-hunter", "Böcek Avcısı", "Gönderilen review'larda toplam 10 sorun yakala.", "🐞", 10,
          lambda s: s["findings"], "silver"),
    Badge("critical-catch", "Kritik Yakalayan", "Kritik önemde bir sorunu yakalayıp gönder.", "🚨", 1,
          lambda s: s["critical_reviews"], "gold"),
    Badge("lightning", "Şimşek", f"Hazır olan bir review'u {FAST_APPROVAL_MIN} dakika içinde gönder.", "⚡", 1,
          lambda s: s["fast_approvals"]),
    Badge("dependency-keeper", "Bağımlılık Bekçisi", "10 bağımlılık güncellemesini toplu onayla.", "📦", 10,
          lambda s: s["batch_approvals"], "silver"),
    Badge("fixer", "Tamirci", "Bir yorumdan düzeltme PR'ı aç.", "🔧", 1, lambda s: s["fix_prs"]),
    Badge("issue-opener", "Kayıt Tutucu", "3 taslak issue'yu GitHub'da aç.", "📌", 3, lambda s: s["issues_opened"]),
    Badge("memory-master", "Hafıza Ustası", "Repo hafızasına 5 kural ya da susturma ekle.", "🧠", 5,
          lambda s: s["memory_items"], "silver"),
    Badge("ci-detective", "CI Dedektifi", "5 PR'ın CI hatasını teşhis et.", "🔍", 5, lambda s: s["ci_diagnoses"]),
    Badge("inbox-zero", "Inbox Zero", "Bekleyenler kutusunu tamamen boşalt.", "✨", 1, lambda s: s["inbox_zero"], "gold"),
    Badge("streak-3", "Isınma Turu", "3 gün üst üste review gönder.", "🔥", 3, lambda s: s["best_streak"]),
    Badge("streak-7", "Haftalık Seri", "7 gün üst üste review gönder.", "🔥", 7, lambda s: s["best_streak"], "silver"),
    Badge("streak-30", "Durdurulamaz", "30 gün üst üste review gönder.", "☄️", 30, lambda s: s["best_streak"], "gold"),
    Badge("night-owl", "Gece Kuşu", "Gece yarısı ile 05:00 arasında bir review gönder.", "🦉", 1,
          lambda s: s["night_reviews"]),
]


def _submitted_reviews(db: Database) -> List[Dict[str, Any]]:
    rows = db.query(
        "SELECT r.id, r.origin, r.submitted_at, r.progress,"
        " (SELECT COUNT(*) FROM review_comments c WHERE c.review_id = r.id AND c.included = 1) AS included,"
        " (SELECT COUNT(*) FROM review_comments c WHERE c.review_id = r.id AND c.included = 1"
        "   AND c.severity = 'CRITICAL') AS critical,"
        " (SELECT COUNT(*) FROM review_comments c WHERE c.review_id = r.id AND c.included = 1"
        "   AND c.severity = 'HIGH') AS high"
        " FROM reviews r WHERE r.status = 'submitted' AND r.submitted_at IS NOT NULL ORDER BY r.submitted_at"
    )
    for r in rows:
        steps = {s["key"]: s for s in json.loads(r.pop("progress") or "[]")}
        approve = steps.get("approve") or {}
        start, end = approve.get("started_at"), approve.get("finished_at")
        r["approval_minutes"] = None
        if start and end:
            delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
            r["approval_minutes"] = delta.total_seconds() / 60
    return rows


def compute(db: Database, today: Optional[date] = None) -> Dict[str, Any]:
    today = today or datetime.now().astimezone().date()
    reviews = _submitted_reviews(db)
    manual = [r for r in reviews if r["origin"] != "batch"]
    days = [d for r in manual if (d := local_day(r["submitted_at"]))]
    streak = streaks(days, today)

    fix_prs = db.query("SELECT COUNT(*) AS n FROM review_comments WHERE fix_pr_url IS NOT NULL")[0]["n"]
    issues = db.query("SELECT COUNT(*) AS n FROM draft_issues WHERE status = 'opened'")[0]["n"]
    memory = db.query("SELECT COUNT(*) AS n FROM memory")[0]["n"]
    ci = db.query("SELECT COUNT(*) AS n FROM ci_diagnoses")[0]["n"]
    earned_before = db.achievements()

    stats = {
        "reviews": len(manual),
        "findings": sum(r["included"] for r in manual),
        "critical_reviews": sum(1 for r in manual if r["critical"]),
        "fast_approvals": sum(1 for r in manual if r["approval_minutes"] is not None
                              and r["approval_minutes"] <= FAST_APPROVAL_MIN),
        "batch_approvals": sum(1 for r in reviews if r["origin"] == "batch"),
        "fix_prs": fix_prs,
        "issues_opened": issues,
        "memory_items": memory,
        "ci_diagnoses": ci,
        "inbox_zero": 1 if "marker:inbox-zero" in earned_before else 0,
        "best_streak": streak["best"],
        "night_reviews": sum(1 for r in manual if datetime.fromisoformat(r["submitted_at"]).astimezone().hour < 5),
    }

    xp = sum(review_xp(r) for r in reviews) + 15 * fix_prs + 8 * issues + 2 * memory + 2 * ci
    goal = int(db.get_setting("daily_goal", str(DEFAULT_DAILY_GOAL)) or DEFAULT_DAILY_GOAL)
    per_day: Dict[date, int] = {}
    for d in days:
        per_day[d] = per_day.get(d, 0) + 1
    heatmap = [{"date": (today - timedelta(days=i)).isoformat(), "count": per_day.get(today - timedelta(days=i), 0)}
               for i in range(HEATMAP_DAYS - 1, -1, -1)]

    badges, new = [], []
    for b in BADGES:
        value = b.metric(stats)
        earned = value >= b.target
        if earned and db.grant_achievement(b.id):
            new.append(b.id)
        record = db.achievements().get(b.id) if earned else None
        badges.append({
            "id": b.id, "name": b.name, "description": b.description, "icon": b.icon, "tier": b.tier,
            "target": b.target, "value": min(value, b.target), "earned": earned,
            "earned_at": record["earned_at"] if record else None,
            "new": bool(record and not record["seen"]),
        })

    return {
        **level_for(xp),
        "streak": {**streak, "today": per_day.get(today, 0), "goal": goal,
                   "at_risk": streak["current"] > 0 and per_day.get(today, 0) == 0},
        "heatmap": heatmap,
        "stats": stats,
        "badges": badges,
        "new_badges": [b for b in badges if b["new"]],
    }
