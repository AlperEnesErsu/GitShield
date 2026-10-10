import base64
import time
from typing import Any, Dict, List, Optional

import httpx

from gitshield.web.config import settings

REPOS_QUERY = """
query($cursor: String) {
  viewer {
    login
    repositories(
      first: 50
      after: $cursor
      affiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]
      ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]
      orderBy: {field: PUSHED_AT, direction: DESC}
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        name
        owner { login }
        description
        url
        isPrivate
        isArchived
        isFork
        pushedAt
        updatedAt
        stargazerCount
        viewerPermission
        forkCount
        primaryLanguage { name color }
        defaultBranchRef { name }
        languages(first: 6, orderBy: {field: SIZE, direction: DESC}) {
          totalSize
          edges { size node { name color } }
        }
        pullRequests(states: OPEN) { totalCount }
        mergedPullRequests: pullRequests(states: MERGED) { totalCount }
        issues(states: OPEN) { totalCount }
      }
    }
  }
}
"""

REPO_OVERVIEW_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    nameWithOwner
    description
    url
    homepageUrl
    isPrivate
    isArchived
    createdAt
    pushedAt
    diskUsage
    stargazerCount
    forkCount
    watchers { totalCount }
    licenseInfo { name }
    defaultBranchRef {
      name
      target { ... on Commit { history { totalCount } } }
    }
    languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
      totalSize
      edges { size node { name color } }
    }
    openPullRequests: pullRequests(states: OPEN) { totalCount }
    mergedPullRequests: pullRequests(states: MERGED) { totalCount }
    closedPullRequests: pullRequests(states: CLOSED) { totalCount }
    openIssues: issues(states: OPEN) { totalCount }
    closedIssues: issues(states: CLOSED) { totalCount }
  }
}
"""

MAX_REPO_PAGES = 10
MAX_PR_FILES = 300
REPO_CACHE_TTL_SEC = 60

OPEN_PULLS_DETAIL_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 50, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number
        title
        additions
        deletions
        changedFiles
        authorAssociation
        author { login }
        files(first: 100) { nodes { path additions deletions } }
        commits(last: 1) { nodes { commit { oid statusCheckRollup { state } } } }
      }
    }
  }
}
"""

MERGED_PULLS_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: MERGED, first: 40, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { number title createdAt mergedAt author { login } }
    }
  }
}
"""


class GitHubError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class GitHubClient:
    def __init__(self, token: Optional[str] = None, base_url: Optional[str] = None):
        self.token = token if token is not None else settings.github_token
        self.base_url = (base_url or settings.github_api_url).rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "GitShield-Web",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            },
        )
        self._repo_cache: Optional[tuple[float, Dict[str, Any]]] = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if not self.token:
            raise GitHubError(401, "GITHUB_TOKEN is not configured.")
        resp = await self._client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("message", resp.text)
                errors = resp.json().get("errors")
                if errors:
                    detail = f"{detail}: {errors}"
            except ValueError:
                detail = resp.text
            raise GitHubError(resp.status_code, detail)
        return resp

    async def _paginate(self, path: str, params: Dict[str, Any], max_pages: int = 10) -> List[Any]:
        items: List[Any] = []
        params = {"per_page": 100, **params}
        for page in range(1, max_pages + 1):
            resp = await self._request("GET", path, params={**params, "page": page})
            batch = resp.json()
            items.extend(batch)
            if len(batch) < params["per_page"] or 'rel="next"' not in resp.headers.get("link", ""):
                break
        return items

    # ---- Viewer & repositories -------------------------------------------------

    async def viewer(self) -> Dict[str, Any]:
        resp = await self._request("GET", "/user")
        return resp.json()

    async def list_repos(self, refresh: bool = False) -> Dict[str, Any]:
        """All repositories the token can see, with open PR/issue counts (GraphQL)."""
        if not refresh and self._repo_cache and time.monotonic() - self._repo_cache[0] < REPO_CACHE_TTL_SEC:
            return self._repo_cache[1]

        repos: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        login = ""
        for _ in range(MAX_REPO_PAGES):
            viewer = (await self._graphql(REPOS_QUERY, {"cursor": cursor}))["viewer"]
            login = viewer["login"]
            conn = viewer["repositories"]
            repos.extend(conn["nodes"])
            if not conn["pageInfo"]["hasNextPage"]:
                break
            cursor = conn["pageInfo"]["endCursor"]

        result = {"login": login, "repos": repos}
        self._repo_cache = (time.monotonic(), result)
        return result

    async def _graphql(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        resp = await self._request("POST", "/graphql", json={"query": query, "variables": variables})
        payload = resp.json()
        if payload.get("errors"):
            raise GitHubError(502, str(payload["errors"]))
        return payload["data"]

    async def repo_overview(self, owner: str, repo: str) -> Dict[str, Any]:
        data = await self._graphql(REPO_OVERVIEW_QUERY, {"owner": owner, "name": repo})
        if not data.get("repository"):
            raise GitHubError(404, f"{owner}/{repo} not found")
        return data["repository"]

    async def open_pulls_detail(self, owner: str, repo: str) -> Dict[int, Dict[str, Any]]:
        """Size, files, author association and CI rollup for every open PR, keyed by number."""
        data = await self._graphql(OPEN_PULLS_DETAIL_QUERY, {"owner": owner, "name": repo})
        nodes = ((data.get("repository") or {}).get("pullRequests") or {}).get("nodes", [])
        return {n["number"]: n for n in nodes}

    async def merged_pulls(self, owner: str, repo: str) -> List[Dict[str, Any]]:
        data = await self._graphql(MERGED_PULLS_QUERY, {"owner": owner, "name": repo})
        return ((data.get("repository") or {}).get("pullRequests") or {}).get("nodes", [])

    async def participation(self, owner: str, repo: str) -> Optional[Dict[str, List[int]]]:
        """Weekly commit counts for the last 52 weeks; None while GitHub is still computing them."""
        resp = await self._request("GET", f"/repos/{owner}/{repo}/stats/participation")
        if resp.status_code == 202 or not resp.content:
            return None
        return resp.json()

    # ---- Pull requests ---------------------------------------------------------

    async def list_pulls(self, owner: str, repo: str, state: str = "open") -> List[Dict[str, Any]]:
        return await self._paginate(
            f"/repos/{owner}/{repo}/pulls", {"state": state, "sort": "updated", "direction": "desc"}, 3
        )

    async def get_pull(self, owner: str, repo: str, number: int) -> Dict[str, Any]:
        resp = await self._request("GET", f"/repos/{owner}/{repo}/pulls/{number}")
        return resp.json()

    async def list_pull_files(self, owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
        return await self._paginate(
            f"/repos/{owner}/{repo}/pulls/{number}/files", {}, max_pages=MAX_PR_FILES // 100
        )

    async def compare(self, owner: str, repo: str, base: str, head: str) -> Dict[str, Any]:
        """Commits and per-file patches between two commits (used for incremental reviews)."""
        resp = await self._request("GET", f"/repos/{owner}/{repo}/compare/{base}...{head}")
        return resp.json()

    async def create_review(
        self,
        owner: str,
        repo: str,
        number: int,
        commit_id: str,
        body: str,
        event: str,
        comments: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        resp = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{number}/reviews",
            json={"commit_id": commit_id, "body": body, "event": event, "comments": comments},
        )
        return resp.json()

    # ---- Checks & Actions (CI diagnosis) -------------------------------------------------

    async def check_runs(self, owner: str, repo: str, sha: str) -> List[Dict[str, Any]]:
        resp = await self._request("GET", f"/repos/{owner}/{repo}/commits/{sha}/check-runs",
                                   params={"per_page": 100})
        return resp.json().get("check_runs", [])

    async def actions_job(self, owner: str, repo: str, job_id: int) -> Dict[str, Any]:
        resp = await self._request("GET", f"/repos/{owner}/{repo}/actions/jobs/{job_id}")
        return resp.json()

    async def actions_run(self, owner: str, repo: str, run_id: int) -> Dict[str, Any]:
        resp = await self._request("GET", f"/repos/{owner}/{repo}/actions/runs/{run_id}")
        return resp.json()

    async def workflow_runs(self, owner: str, repo: str, workflow_id: int, branch: str,
                            limit: int = 5) -> List[Dict[str, Any]]:
        resp = await self._request(
            "GET", f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs",
            params={"branch": branch, "status": "completed", "per_page": limit})
        return resp.json().get("workflow_runs", [])

    async def run_jobs(self, owner: str, repo: str, run_id: int) -> List[Dict[str, Any]]:
        resp = await self._request("GET", f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
                                   params={"per_page": 100})
        return resp.json().get("jobs", [])

    async def job_logs(self, owner: str, repo: str, job_id: int) -> str:
        """Plain-text log of an Actions job. GitHub answers with a redirect to blob storage;
        httpx drops the Authorization header when the redirect leaves api.github.com."""
        resp = await self._request("GET", f"/repos/{owner}/{repo}/actions/jobs/{job_id}/logs",
                                   follow_redirects=True)
        return resp.text

    async def rerun_job(self, owner: str, repo: str, job_id: int) -> None:
        await self._request("POST", f"/repos/{owner}/{repo}/actions/jobs/{job_id}/rerun")

    # ---- Contents, branches & PR creation (fix PRs) ----------------------------------

    async def get_file(self, owner: str, repo: str, path: str, ref: str) -> Dict[str, Any]:
        """File metadata + decoded text at ``ref``."""
        resp = await self._request("GET", f"/repos/{owner}/{repo}/contents/{path}", params={"ref": ref})
        data = resp.json()
        if isinstance(data, list) or data.get("type") != "file":
            raise GitHubError(422, f"{path} bir dosya değil")
        data["text"] = base64.b64decode(data.get("content", "")).decode("utf-8")
        return data

    async def create_branch(self, owner: str, repo: str, branch: str, sha: str) -> None:
        await self._request("POST", f"/repos/{owner}/{repo}/git/refs",
                            json={"ref": f"refs/heads/{branch}", "sha": sha})

    async def update_file(self, owner: str, repo: str, path: str, branch: str, text: str,
                          blob_sha: str, message: str) -> Dict[str, Any]:
        resp = await self._request("PUT", f"/repos/{owner}/{repo}/contents/{path}", json={
            "message": message, "branch": branch, "sha": blob_sha,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        })
        return resp.json()

    async def create_pull(self, owner: str, repo: str, title: str, head: str, base: str,
                          body: str) -> Dict[str, Any]:
        resp = await self._request("POST", f"/repos/{owner}/{repo}/pulls",
                                   json={"title": title, "head": head, "base": base, "body": body})
        return resp.json()

    # ---- Issues ----------------------------------------------------------------

    async def list_issues(self, owner: str, repo: str, state: str = "open") -> List[Dict[str, Any]]:
        items = await self._paginate(
            f"/repos/{owner}/{repo}/issues", {"state": state, "sort": "updated"}, 3
        )
        # The issues endpoint also returns pull requests; keep real issues only.
        return [i for i in items if "pull_request" not in i]

    async def create_issue(self, owner: str, repo: str, title: str, body: str) -> Dict[str, Any]:
        resp = await self._request(
            "POST", f"/repos/{owner}/{repo}/issues", json={"title": title, "body": body}
        )
        return resp.json()
