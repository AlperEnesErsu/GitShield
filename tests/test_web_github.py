import asyncio
import time

import httpx
import pytest

pytest.importorskip("fastapi")

from gitshield.web.github import GitHubClient, GitHubError, rate_limit_message


def response(status, headers=None, body=""):
    return httpx.Response(status, headers=headers or {}, text=body)


def test_rate_limit_messages():
    reset = int(time.time()) + 600
    primary = rate_limit_message(response(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)}))
    assert "limiti doldu" in primary and time.strftime("%H:%M", time.localtime(reset)) in primary
    secondary = rate_limit_message(response(403, {"retry-after": "60"}, "You have exceeded a secondary rate limit"))
    assert "60 sn" in secondary
    assert rate_limit_message(response(403, {}, "Resource not accessible by integration")) is None
    assert rate_limit_message(response(404)) is None


def test_client_raises_readable_429():
    def handler(request):
        return httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"},
                              json={"message": "API rate limit exceeded"})

    gh = GitHubClient(token="t", base_url="https://api.github.test")
    gh._client = httpx.AsyncClient(base_url="https://api.github.test", transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubError) as err:
        asyncio.run(gh.viewer())
    assert err.value.status_code == 429 and "limiti doldu" in err.value.message


def test_repeated_reads_are_cached_and_writes_invalidate():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(200, json={"html_url": "https://x"})
        return httpx.Response(200, json=[{"number": 1}])

    gh = GitHubClient(token="t", base_url="https://api.github.test")
    gh._client = httpx.AsyncClient(base_url="https://api.github.test", transport=httpx.MockTransport(handler))

    async def scenario():
        await gh.list_pulls("acme", "app")
        await gh.list_pulls("acme", "app")  # served from cache
        await gh.list_pulls("acme", "other")  # different repo: fetched
        await gh.create_review("acme", "app", 1, "sha", "body", "COMMENT", [])
        await gh.list_pulls("acme", "app")  # invalidated by the write: fetched again

    asyncio.run(scenario())
    gets = [c for c in calls if c[0] == "GET"]
    assert gets == [("GET", "/repos/acme/app/pulls"), ("GET", "/repos/acme/other/pulls"),
                    ("GET", "/repos/acme/app/pulls")]
