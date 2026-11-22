import pytest

pytest.importorskip("fastapi")

from gitshield.web.activity import build_activity


def commits_by_repo(*rows):
    """Like by_repo, plus the commit days GitHub lists for each repository."""
    return [{"repository": {"nameWithOwner": name, "isPrivate": private},
             "contributions": {"totalCount": sum(n for _, n in days),
                               "nodes": [{"occurredAt": f"{d}T08:00:00Z", "commitCount": n} for d, n in days]}}
            for name, private, days in rows]


def by_repo(*rows):
    return [{"repository": {"nameWithOwner": name, "isPrivate": private}, "contributions": {"totalCount": n}}
            for name, private, n in rows]


def viewer(counts, start="2026-01-05", commits=None):
    """A calendar starting on a Monday, split into GitHub-style weeks of seven days."""
    from datetime import date, timedelta
    first = date.fromisoformat(start)
    days = [{"date": (first + timedelta(days=i)).isoformat(), "contributionCount": n}
            for i, n in enumerate(counts)]
    weeks = [{"contributionDays": days[i:i + 7]} for i in range(0, len(days), 7)]
    return {"login": "me", "contributionsCollection": {
        "totalCommitContributions": 9, "totalPullRequestContributions": 3,
        "totalPullRequestReviewContributions": 2, "totalIssueContributions": 1,
        "restrictedContributionsCount": 4,
        "contributionCalendar": {"totalContributions": sum(counts), "weeks": weeks},
        "commitContributionsByRepository": commits if commits is not None else by_repo(
            ("acme/app", False, 7), ("acme/lib", True, 2)),
        "pullRequestContributionsByRepository": by_repo(("acme/lib", True, 3)),
        "pullRequestReviewContributionsByRepository": by_repo(("acme/app", False, 2)),
        "issueContributionsByRepository": by_repo(("acme/docs", False, 1)),
    }}


def test_build_activity_shapes_calendar_and_repos():
    #          Mon..Sun            Mon..Wed
    a = build_activity(viewer([1, 0, 2, 3, 4, 0, 0, 5, 1, 0]))

    assert a["login"] == "me" and a["total"] == 16
    assert (a["from"], a["to"]) == ("2026-01-05", "2026-01-14")
    assert a["counts"] == {"commits": 9, "prs": 3, "reviews": 2, "issues": 1, "restricted": 4}
    assert a["active_days"] == 6
    assert a["best_day"] == {"date": "2026-01-12", "count": 5}
    assert a["weeks"] == [{"week": "2026-01-05", "count": 10}, {"week": "2026-01-12", "count": 6}]
    assert a["by_weekday"] == [6, 1, 2, 3, 4, 0, 0]
    assert a["repo_count"] == 3
    assert a["repos"][0] == {"repo": "acme/app", "private": False, "commits": 7, "prs": 0, "reviews": 2, "issues": 0}
    assert a["repos"][1] == {"repo": "acme/lib", "private": True, "commits": 2, "prs": 3, "reviews": 0, "issues": 0}


@pytest.mark.parametrize("counts, current, longest", [
    ([1, 1, 1, 0, 1, 1], 2, 3),
    ([1, 1, 1, 0], 3, 3),      # today is still empty: yesterday's streak holds
    ([1, 1, 0, 0], 0, 2),      # a full missed day ends it
    ([0, 0, 0], 0, 0),
])
def test_streaks(counts, current, longest):
    assert build_activity(viewer(counts))["streak"] == {"current": current, "longest": longest}


def test_empty_calendar():
    a = build_activity(viewer([]))
    assert a["days"] == [] and a["from"] is None and a["best_day"] is None
    assert a["streak"] == {"current": 0, "longest": 0}


def test_recent_compares_the_last_30_days_with_the_30_before():
    counts = [1] * 10 + [2] * 30 + [3] * 30   # 70 days: 10 old ones, then 30, then 30
    a = build_activity(viewer(counts))
    assert a["recent"] == {"days": 30, "current": 90, "previous": 60}


def test_short_calendar_has_no_previous_period():
    a = build_activity(viewer([4, 0, 1]))
    assert a["recent"] == {"days": 30, "current": 5, "previous": 0}


def test_repo_weeks_bucket_commit_days_into_the_last_12_weeks():
    # 14 weeks from Monday 2026-01-05: the trend covers weeks 3-14 (2026-01-19 .. 2026-04-06).
    commits = commits_by_repo(
        ("acme/app", False, [("2026-04-07", 2), ("2026-04-06", 1), ("2026-01-19", 4), ("2026-01-12", 9)]),
        ("acme/lib", True, []),
    )
    a = build_activity(viewer([0] * 98, commits=commits))
    assert a["trend_weeks"][0] == "2026-01-19" and a["trend_weeks"][-1] == "2026-04-06"
    assert len(a["trend_weeks"]) == 12
    app = a["repo_weeks"]["acme/app"]
    assert app[0] == 4, "first trend week"
    assert app[-1] == 3, "two days in the last week are summed"
    assert sum(app) == 7, "a commit before the trend window is left out"
    assert a["repo_weeks"]["acme/lib"] == [0] * 12
