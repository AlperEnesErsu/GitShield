import time
from pathlib import Path
from typing import List, Optional

from gitshield.core.diff_parser import get_git_diff, parse_unified_diff
from gitshield.core.entropy import find_high_entropy_tokens
from gitshield.core.models import Finding, RuleType, ScanReport, Severity
from gitshield.rules.engine import RuleEngine


class Scanner:
    def __init__(self, rule_engine: Optional[RuleEngine] = None):
        self.rule_engine = rule_engine or RuleEngine()

    def scan_diff(
        self,
        repo_path: Path,
        raw_diff: Optional[str] = None,
        staged: bool = False,
        branch_or_commit: Optional[str] = None,
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

        findings: List[Finding] = []
        scanned_files = set()
        scanned_lines_count = 0

        for hunk in hunks:
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
                findings.extend(rule_findings)

                # 2. Shannon Entropy Analysis (Heuristic Secret Detection)
                if enable_entropy:
                    entropy_tokens = find_high_entropy_tokens(line.content)
                    for token, entropy_val in entropy_tokens:
                        # Avoid duplicate finding if rule already matched the exact token
                        if any(token in f.matched_text for f in rule_findings):
                            continue

                        findings.append(
                            Finding(
                                id=f"ENTROPY-{line.file_path}-{line.line_number}",
                                rule_id="ENTROPY-HIGH-001",
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

        execution_time = round(time.perf_counter() - start_time, 3)

        return ScanReport(
            repo_path=str(repo_path),
            target_ref=branch_or_commit or ("staged" if staged else "working_tree"),
            findings=findings,
            scanned_files_count=len(scanned_files),
            scanned_lines_count=scanned_lines_count,
            execution_time_sec=execution_time,
        )
