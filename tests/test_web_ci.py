import asyncio
import copy

import pytest

pytest.importorskip("fastapi")

from gitshield.web.ci_diagnosis import audit_packages, classify, clean_log, diagnose, verdict
from tests.test_web_review import PR

LOGS = {
    "docker": "2026-10-09T10:00:00.0000000Z Error response from daemon: toomanyrequests: You have reached "
              "your unauthenticated pull rate limit.\n##[error]Docker pull failed with exit code 1",
    "secret": "FAILURE: Build failed with an exception.\n* What went wrong:\n"
              "Execution failed for task ':app:processDebugGoogleServices'.\n> File google-services.json is missing.",
    "peer": "npm error code ERESOLVE\nnpm error ERESOLVE could not resolve\nnpm error Found: eslint@10.11.0",
    "node": "npm warn EBADENGINE Unsupported engine {\nTypeError: webidl.util.markAsUncloneable is not a function",
    "audit": "brace-expansion  4.0.0 - 5.0.11\nSeverity: high\nsharp  <0.35.5\nSeverity: high\n"
             "fix available via `npm audit fix`\n6 vulnerabilities (2 moderate, 4 high)\n"
             "##[error]Process completed with exit code 1.",
    "unknown": "something odd happened\n##[error]Process completed with exit code 2.",
}


@pytest.mark.parametrize("log,pattern,blame", [
    ("docker", "docker-rate-limit", "environment"),
    ("secret", "missing-secret-file", "environment"),
    ("peer", "peer-conflict", "pr"),
    ("node", "node-version", "environment"),
    ("audit", "audit", "base"),
])
def test_known_patterns(log, pattern, blame):
    match = classify(clean_log(LOGS[log]), "dependabot[bot]")
    assert match["pattern"] == pattern and match["blame"] == blame and match["evidence"]


def test_clean_log_strips_timestamps_and_ansi():
    assert clean_log("2026-10-09T10:00:00.1234567Z \x1b[31mboom\x1b[0m\n##[group]x") == ["boom"]


def test_audit_packages():
    assert audit_packages(clean_log(LOGS["audit"])) == ["brace-expansion", "sharp"]


def test_verdict_summaries():
    assert verdict([{"blame": "environment"}])["blame"] == "environment"
    assert verdict([{"blame": "environment"}, {"blame": "base"}])["blame"] == "base"
    assert verdict([{"blame": "pr"}, {"blame": "environment"}])["blame"] == "pr"
    assert verdict([])["blame"] == "none"


class CiGitHub:
    """Two checks failed on the PR head; `e2e` was rerun (only the newest attempt counts)."""

    def __init__(self, base_conclusion="success", lock_patch=""):
        self.pr = copy.deepcopy(PR)
        self.pr.update({"user": {"login": "dependabot[bot]"}, "number": 7})
        self.pr["base"]["ref"] = "develop"
        self.base_conclusion = base_conclusion
        self.lock_patch = lock_patch

    async def check_runs(self, owner, repo, sha):
        gha = {"slug": "github-actions"}
        return [
            {"id": 1, "name": "e2e", "conclusion": "failure", "status": "completed", "app": gha,
             "started_at": "2026-10-09T10:00:00Z"},
            {"id": 2, "name": "e2e", "conclusion": "failure", "status": "completed", "app": gha,
             "started_at": "2026-10-09T11:00:00Z"},
            {"id": 3, "name": "dependency audit", "conclusion": "failure", "status": "completed", "app": gha,
             "started_at": "2026-10-09T10:00:00Z"},
            {"id": 4, "name": "lint", "conclusion": "success", "status": "completed", "app": gha,
             "started_at": "2026-10-09T10:00:00Z"},
        ]

    async def actions_job(self, owner, repo, job_id):
        return {"id": job_id, "run_id": 100, "name": {2: "e2e", 1: "e2e", 3: "dependency audit"}[job_id]}

    async def job_logs(self, owner, repo, job_id):
        return {1: LOGS["unknown"], 2: LOGS["docker"], 3: LOGS["audit"]}[job_id]

    async def actions_run(self, owner, repo, run_id):
        return {"id": run_id, "workflow_id": 9}

    async def workflow_runs(self, owner, repo, workflow_id, branch, limit=5):
        assert branch == "develop"
        return [{"id": 200, "html_url": "https://x/200", "updated_at": "2026-09-19T00:00:00Z", "event": "push"}]

    async def run_jobs(self, owner, repo, run_id):
        return [{"name": "e2e", "conclusion": "success"},
                {"name": "dependency audit", "conclusion": self.base_conclusion}]

    async def list_pull_files(self, owner, repo, number):
        return [{"filename": "package-lock.json", "patch": self.lock_patch}]


def _diag(gh):
    return asyncio.run(diagnose(gh, "acme", "app", gh.pr))


def test_diagnose_uses_latest_attempt_and_blames_base_for_untouched_audit_packages():
    # The lockfile diff mentions sharp only in an unchanged context line: that must not count.
    gh = CiGitHub(lock_patch='@@ -1,3 +1,3 @@\n     "node_modules/sharp": {\n-      "version": "1.0.0",\n'
                             '+      "version": "1.0.1",\n')
    d = _diag(gh)
    assert d["failed"] == 2 and d["total_checks"] == 3, "rerun attempts are de-duplicated by name"
    jobs = {j["name"]: j for j in d["jobs"]}
    assert jobs["e2e"]["pattern"] == "docker-rate-limit", "the newest e2e attempt is diagnosed"
    assert jobs["dependency audit"]["blame"] == "base"
    assert jobs["dependency audit"]["audit"]["touched_by_pr"] == []
    assert d["verdict"]["blame"] == "base"


def test_diagnose_blames_pr_when_it_changes_a_vulnerable_package():
    gh = CiGitHub(lock_patch='-      "resolved": "https://registry.npmjs.org/sharp/-/sharp-0.35.4.tgz",\n'
                             '+      "resolved": "https://registry.npmjs.org/sharp/-/sharp-0.35.3.tgz",\n')
    jobs = {j["name"]: j for j in _diag(gh)["jobs"]}
    assert jobs["dependency audit"]["blame"] == "pr"
    assert jobs["dependency audit"]["audit"]["touched_by_pr"] == ["sharp"]


def test_base_failure_overrides_unknown_pattern():
    class BaseBroken(CiGitHub):
        async def job_logs(self, owner, repo, job_id):
            return LOGS["unknown"]

        async def run_jobs(self, owner, repo, run_id):
            return [{"name": "e2e", "conclusion": "failure"}, {"name": "dependency audit", "conclusion": "failure"}]

    jobs = _diag(BaseBroken())["jobs"]
    assert all(j["blame"] == "base" and "hedef dal" in j["explanation"] for j in jobs)


def test_audit_fixed_on_base_after_the_run_means_outdated_branch():
    class Outdated(CiGitHub):
        async def actions_job(self, owner, repo, job_id):
            job = await super().actions_job(owner, repo, job_id)
            return {**job, "started_at": "2026-10-10T13:38:00Z"}

        async def workflow_runs(self, owner, repo, workflow_id, branch, limit=5):
            return [{"id": 200, "html_url": "https://x/200", "updated_at": "2026-10-10T13:45:00Z", "event": "push"}]

    d = asyncio.run(diagnose(Outdated(), "acme", "app", Outdated().pr))
    audit = next(j for j in d["jobs"] if j["name"] == "dependency audit")
    assert audit["blame"] == "outdated" and "rebase" in audit["suggestion"]
    assert d["verdict"]["blame"] == "outdated"
