"""The repository's own scanner settings (.gitshieldignore, baseline) applied to PR reviews.

Both files are read at the PR's base commit, never its head: a pull request must not be able to
silence its own findings by adding an ignore pattern or a baseline entry. Changes to either file
take effect for reviews once they are merged.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from gitshield.core.baseline import (
    BASELINE_FILE_NAME,
    BaselineError,
    filter_baselined,
    parse_baseline,
)
from gitshield.core.models import Finding
from gitshield.core.scanner import IGNORE_FILE_NAME, is_ignored_path, parse_ignore_patterns
from gitshield.web.github import GitHubClient, GitHubError

log = logging.getLogger(__name__)


@dataclass
class RepoScanConfig:
    ignore_patterns: list[str] = field(default_factory=list)
    baseline: set[str] = field(default_factory=set)
    # Files that exist but could not be used; shown in the scan step so the maintainer knows.
    problems: list[str] = field(default_factory=list)


async def _read(gh: GitHubClient, owner: str, repo: str, path: str, ref: str,
                problems: list[str]) -> str | None:
    try:
        return (await gh.get_file(owner, repo, path, ref))["text"]
    except GitHubError as e:
        if e.status_code != 404:
            log.warning("Cannot read %s at %s in %s/%s: %s", path, ref, owner, repo, e.message)
            problems.append(f"{path} okunamadı ({e.status_code})")
    except UnicodeDecodeError:
        problems.append(f"{path} UTF-8 değil")
    return None


async def load_repo_scan_config(gh: GitHubClient, owner: str, repo: str,
                                pr: dict[str, Any]) -> RepoScanConfig:
    """Read .gitshieldignore and the baseline at the PR's base commit. Missing files are empty."""
    config = RepoScanConfig()
    ref = pr.get("base", {}).get("sha")
    if not ref:
        return config
    text = await _read(gh, owner, repo, IGNORE_FILE_NAME, ref, config.problems)
    if text is not None:
        config.ignore_patterns = parse_ignore_patterns(text)
    text = await _read(gh, owner, repo, BASELINE_FILE_NAME, ref, config.problems)
    if text is not None:
        try:
            config.baseline = parse_baseline(text, BASELINE_FILE_NAME)
        except BaselineError as e:
            config.problems.append(str(e))
    return config


def apply_repo_scan_config(findings: list[Finding],
                           config: RepoScanConfig) -> tuple[list[Finding], int, int]:
    """Drop findings in ignored files, then those accepted in the baseline (the CLI's order).
    Returns (kept, ignored count, baselined count)."""
    kept = [f for f in findings if not is_ignored_path(f.file_path, config.ignore_patterns)]
    ignored = len(findings) - len(kept)
    kept, baselined = filter_baselined(kept, config.baseline)
    return kept, ignored, baselined
