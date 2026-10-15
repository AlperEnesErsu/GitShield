"""The API surface must not change when route modules are reorganised."""

from gitshield.web.app import app

EXPECTED = {
    ("DELETE", "/api/memory/{memory_id}"),
    ("GET", "/api/automation"),
    ("GET", "/api/gamification"),
    ("GET", "/api/inbox"),
    ("GET", "/api/metrics"),
    ("GET", "/api/notifications"),
    ("GET", "/api/repos"),
    ("GET", "/api/repos/{owner}/{repo}/draft-issues"),
    ("GET", "/api/repos/{owner}/{repo}/issues"),
    ("GET", "/api/repos/{owner}/{repo}/memory"),
    ("GET", "/api/repos/{owner}/{repo}/overview"),
    ("GET", "/api/repos/{owner}/{repo}/pulls"),
    ("GET", "/api/repos/{owner}/{repo}/pulls/{number}"),
    ("GET", "/api/repos/{owner}/{repo}/pulls/{number}/ci-diagnosis"),
    ("GET", "/api/repos/{owner}/{repo}/settings"),
    ("GET", "/api/reviews/{review_id}"),
    ("GET", "/api/status"),
    ("PATCH", "/api/comments/{comment_id}"),
    ("PATCH", "/api/draft-issues/{issue_id}"),
    ("PATCH", "/api/memory/{memory_id}"),
    ("PATCH", "/api/reviews/{review_id}"),
    ("POST", "/api/automation/run"),
    ("POST", "/api/comments/{comment_id}/draft-issue"),
    ("POST", "/api/comments/{comment_id}/fix"),
    ("POST", "/api/comments/{comment_id}/fix/preview"),
    ("POST", "/api/comments/{comment_id}/suppress"),
    ("POST", "/api/draft-issues/{issue_id}/dismiss"),
    ("POST", "/api/draft-issues/{issue_id}/open"),
    ("POST", "/api/gamification/seen"),
    ("POST", "/api/notifications/test"),
    ("POST", "/api/repos/{owner}/{repo}/actions/jobs/{job_id}/rerun"),
    ("POST", "/api/repos/{owner}/{repo}/dependency-batch"),
    ("POST", "/api/repos/{owner}/{repo}/memory"),
    ("POST", "/api/repos/{owner}/{repo}/pulls/{number}/reviews"),
    ("POST", "/api/reviews/{review_id}/submit"),
    ("PUT", "/api/gamification/goal"),
    ("PUT", "/api/repos/{owner}/{repo}/settings"),
}


def test_api_surface_is_unchanged():
    schema = app.openapi()
    actual = {(method.upper(), path) for path, item in schema["paths"].items() for method in item}
    assert actual == EXPECTED


def test_every_api_route_is_under_api_prefix():
    assert all(path.startswith("/api/") for _, path in EXPECTED)
