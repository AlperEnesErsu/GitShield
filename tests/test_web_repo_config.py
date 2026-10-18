import asyncio
import copy
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from gitshield.core.baseline import BASELINE_FILE_NAME, BASELINE_VERSION, fingerprint_findings
from gitshield.core.scanner import IGNORE_FILE_NAME, Scanner
from gitshield.web.db import Database
from gitshield.web.github import GitHubError
from gitshield.web.review import build_diff, run_review
from tests.test_web_review import FILES, PR, FakeGitHub, FakeProvider

BASE_SHA = "base000"


@pytest.fixture()
def open_db():
    opened = []

    def factory(path):
        opened.append(Database(path))
        return opened[-1]

    yield factory
    for database in opened:
        database.close()


class RepoFilesGitHub(FakeGitHub):
    """Serves repo files per ref; the PR's base commit is BASE_SHA."""

    def __init__(self, files_by_ref: dict[str, dict[str, str]], error: GitHubError | None = None):
        super().__init__()
        self.files_by_ref = files_by_ref
        self.error = error
        self.reads: list[tuple[str, str]] = []

    async def get_pull(self, owner, repo, number):
        pr = copy.deepcopy(PR)
        pr["base"]["sha"] = BASE_SHA
        return pr

    async def get_file(self, owner, repo, path, ref):
        self.reads.append((path, ref))
        if self.error:
            raise self.error
        text = self.files_by_ref.get(ref, {}).get(path)
        if text is None:
            raise GitHubError(404, "Not Found")
        return {"text": text}


def _scanner_findings():
    raw, _, _, _ = build_diff(FILES, max_chars=10_000)
    return Scanner().scan_diff(Path("."), raw_diff=raw).findings


def _baseline_of(rule_prefix: str) -> str:
    findings = _scanner_findings()
    prints = [fp for f, fp in zip(findings, fingerprint_findings(findings), strict=True)
              if f.rule_id.startswith(rule_prefix)]
    assert prints, f"fixture has no {rule_prefix} finding"
    return json.dumps({"version": BASELINE_VERSION,
                       "findings": [{"fingerprint": fp} for fp in prints]})


def _run(db, gh, provider=None):
    rid = db.create_review("acme/app", 7, PR["title"], "abc123",
                           provider.name if provider else "none", provider.model if provider else "")
    asyncio.run(run_review(db, gh, provider, rid, "acme", "app", 7))
    return db.get_review(rid)


def _scan_detail(review):
    return next(s["detail"] for s in review["progress"] if s["key"] == "scan")


def test_ignore_file_at_base_drops_scanner_findings(tmp_path, open_db):
    db = open_db(tmp_path / "t.db")
    gh = RepoFilesGitHub({BASE_SHA: {IGNORE_FILE_NAME: "# fixtures\napp/\n"}})
    review = _run(db, gh)

    assert review["status"] == "ready", review["error"]
    assert not [c for c in review["comments"] if c["source"] == "scanner"]
    assert review["stats"]["ignored_findings"] == len(_scanner_findings())
    assert ".gitshieldignore ile atlandı" in _scan_detail(review)
    assert {ref for _, ref in gh.reads} == {BASE_SHA}


def test_files_added_by_the_pr_itself_are_not_trusted(tmp_path, open_db):
    db = open_db(tmp_path / "t.db")
    gh = RepoFilesGitHub({"abc123": {IGNORE_FILE_NAME: "app/\n", BASELINE_FILE_NAME: _baseline_of("SEC-")}})
    review = _run(db, gh)

    assert len([c for c in review["comments"] if c["source"] == "scanner"]) == len(_scanner_findings())
    assert "ignored_findings" not in review["stats"] and "baselined_findings" not in review["stats"]


def test_baseline_accepts_known_findings_but_secrets_stay_redacted(tmp_path, open_db):
    db = open_db(tmp_path / "t.db")
    provider = FakeProvider()
    gh = RepoFilesGitHub({BASE_SHA: {BASELINE_FILE_NAME: _baseline_of("SEC-AWS-")}})
    review = _run(db, gh, provider)

    assert review["status"] == "ready", review["error"]
    scanner_rules = {c["rule_id"] for c in review["comments"] if c["source"] == "scanner"}
    assert scanner_rules == {"SEC-GEN-006"}, "only the baselined rule is dropped"
    assert review["stats"]["baselined_findings"] == 1
    assert "baseline'da kabul edilmiş" in _scan_detail(review)
    # The accepted AWS key is still a secret: the LLM never sees it.
    assert provider.prompts and all("AKIAIOSFODNN7EXAMPLE" not in p for p in provider.prompts)


def test_unreadable_baseline_is_reported_and_the_review_goes_on(tmp_path, open_db):
    db = open_db(tmp_path / "t.db")
    gh = RepoFilesGitHub({BASE_SHA: {BASELINE_FILE_NAME: '{"version": 99}'}})
    review = _run(db, gh)

    assert review["status"] == "ready", review["error"]
    assert len([c for c in review["comments"] if c["source"] == "scanner"]) == len(_scanner_findings())
    assert "Unsupported baseline format" in _scan_detail(review)


def test_github_error_reading_config_does_not_fail_the_review(tmp_path, open_db):
    db = open_db(tmp_path / "t.db")
    review = _run(db, RepoFilesGitHub({}, error=GitHubError(403, "Resource not accessible")))

    assert review["status"] == "ready", review["error"]
    assert "okunamadı (403)" in _scan_detail(review)
