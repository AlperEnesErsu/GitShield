import pytest

pytest.importorskip("fastapi")

from gitshield.web.activity import build_activity


def by_repo(*rows):
    return [{"repository": {"nameWithOwner": name, "isPrivate": private}, "contributions": {"totalCount": n}}
            for name, private, n in rows]


def viewer(counts, start="2026-01-05"):
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
        "commitContributionsByRepository": by_repo(("acme/app", False, 7), ("acme/lib", True, 2)),
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
