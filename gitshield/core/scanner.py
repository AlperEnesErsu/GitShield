import re
import time
from fnmatch import fnmatch
from pathlib import Path

from gitshield.core.diff_parser import get_git_diff, parse_unified_diff
from gitshield.core.entropy import find_high_entropy_tokens
from gitshield.core.models import Finding, RuleType, ScanReport, Severity
from gitshield.rules.engine import RuleEngine, dedupe_findings

LOCKFILE = re.compile(
    r"(^|/)(package-lock\.json|npm-shrinkwrap\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|uv\.lock|"
    r"Pipfile\.lock|pubspec\.lock|go\.sum|Cargo\.lock|Gemfile\.lock|composer\.lock|packages\.lock\.json)$"
)

ENTROPY_RULE_ID = "ENTROPY-HIGH-001"
# "gitshield: ignore" suppresses every finding on the line; "gitshield: ignore[ID,ID2]" only those rules
SUPPRESSION = re.compile(r"gitshield:\s*ignore\b(?:\[([^\]]*)\])?", re.IGNORECASE)


def is_suppressed(content: str, rule_id: str) -> bool:
    """True when an inline gitshield: ignore comment on the line covers this rule id."""
    for match in SUPPRESSION.finditer(content):
        ids = match.group(1)
        if ids is None:
            return True
        wanted = {item.strip().upper() for item in ids.split(",") if item.strip()}
        if rule_id.upper() in wanted:
            return True
    return False


IGNORE_FILE_NAME = ".gitshieldignore"


def load_ignore_file(repo_path: Path) -> list[str]:
    """Read gitignore-like glob patterns from <repo_path>/.gitshieldignore (blank lines and # comments skipped)."""
    path = Path(repo_path) / IGNORE_FILE_NAME
    if not path.is_file():
        return []
    patterns = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _normalize_path(file_path: str) -> str:
    normalized = file_path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def is_ignored_path(file_path: str, patterns: list[str]) -> bool:
    """True when the repo-relative path matches an ignore pattern.

    Patterns are fnmatch globs against the POSIX path. A trailing "/" means a directory prefix
    (tests/fixtures/). A leading "**/" also matches at the repo root. Patterns without a "/" match the basename.
    """
    path = _normalize_path(file_path)
    basename = path.rsplit("/", 1)[-1]
    for raw in patterns:
        pattern = raw.strip().lstrip("/")
        if not pattern:
            continue
        is_dir = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        candidates = {pattern}
        while pattern.startswith("**/"):
            pattern = pattern[3:]
            candidates.add(pattern)
        for candidate in candidates:
            if is_dir:
                if fnmatch(path, f"{candidate}/*"):
                    return True
            elif fnmatch(path, candidate):
                return True
            elif "/" not in candidate and fnmatch(basename, candidate):
                return True
    return False


class Scanner:
    def __init__(self, rule_engine: RuleEngine | None = None, ignore_patterns: list[str] | None = None):
        self.rule_engine = rule_engine or RuleEngine()
        self.ignore_patterns = list(ignore_patterns or [])

    def scan_diff(
        self,
        repo_path: Path,
        raw_diff: str | None = None,
        staged: bool = False,
        branch_or_commit: str | None = None,
        enable_entropy: bool = True,
    ) -> ScanReport:
        start_time = time.perf_counter()

        if raw_diff is None:
            raw_diff = get_git_diff(
                repo_path=repo_path,
                staged=staged,
                branch_or_commit=branch_or_commit,
            )

        hunks = parse_unified_diff(raw_diff)

        findings: list[Finding] = []
        scanned_files = set()
        scanned_lines_count = 0

        for hunk in hunks:
            if self.ignore_patterns and is_ignored_path(hunk.file_path, self.ignore_patterns):
                continue
            scanned_files.add(hunk.file_path)

            for line in hunk.lines:
                if not line.is_added:
                    continue

                scanned_lines_count += 1

                # 1. Deterministic Pattern Matching (Secrets & OWASP rules)
                rule_findings = self.rule_engine.scan_line(
                    file_path=line.file_path,
                    line_number=line.line_number,
                    content=line.content,
                )
                line_findings = [f for f in rule_findings if not is_suppressed(line.content, f.rule_id)]

                # 2. Shannon Entropy Analysis (Heuristic Secret Detection)
                # Lockfiles are full of integrity hashes that look random by design; skip the
                # heuristic there (the deterministic secret rules above still run).
                if enable_entropy and not LOCKFILE.search(line.file_path):
                    entropy_tokens = find_high_entropy_tokens(line.content)
                    for token, entropy_val in entropy_tokens:
                        # Avoid duplicate finding if rule already matched the exact token
                        if any(token in f.matched_text for f in rule_findings):
                            continue
                        if is_suppressed(line.content, ENTROPY_RULE_ID):
                            continue

                        line_findings.append(
                            Finding(
                                id=f"{ENTROPY_RULE_ID}-{line.file_path}-{line.line_number}-{line.content.find(token)}",
                                rule_id=ENTROPY_RULE_ID,
                                title="Suspicious High-Entropy String (Potential Secret)",
                                description=f"Detected string with high Shannon randomness (entropy: {entropy_val:.2f}).",
                                severity=Severity.HIGH,
                                rule_type=RuleType.ENTROPY,
                                file_path=line.file_path,
                                line_number=line.line_number,
                                matched_text=token,
                                context=line.content.strip(),
                                entropy=entropy_val,
                                cwe="CWE-798",
                                suggested_fix="Ensure this random token is loaded from environment variables or a secret vault.",
                            )
                        )

                findings.extend(dedupe_findings(line_findings))

        execution_time = round(time.perf_counter() - start_time, 3)

        return ScanReport(
            repo_path=str(repo_path),
            target_ref=branch_or_commit or ("staged" if staged else "working_tree"),
            findings=findings,
            scanned_files_count=len(scanned_files),
            scanned_lines_count=scanned_lines_count,
            execution_time_sec=execution_time,
        )
