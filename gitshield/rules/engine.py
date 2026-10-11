import fnmatch
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from gitshield.core.models import Finding, RuleType, Severity

SEVERITY_RANK = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
    Severity.INFO: 0,
}

# Values that are obviously not real credentials (docs, examples, env-var references)
PLACEHOLDER_VALUES = {
    "changeme", "changeit", "change_me", "password", "passwd", "pass", "secret",
    "yourpassword", "your_password", "your-password", "placeholder", "redacted",
    "example", "dummy", "todo", "none", "null", "xxxxxxxx", "********",
}
PLACEHOLDER_PATTERNS = [
    re.compile(r"([^\d])\1+"),  # xxxxxxxx, ********, aaaaaaaa
    re.compile(r"<[^>]*>"),  # <your-password>
    re.compile(r"\$\{[^}]*\}"),  # ${DB_PASSWORD}
    re.compile(r"\{\{.*\}\}"),  # {{ password }}
    re.compile(r"%\([^)]*\)s"),  # %(password)s
]
PLACEHOLDER_MARKERS = ("os.getenv", "os.environ", "process.env", "getenv(", "System.getenv")


def is_placeholder(value: str) -> bool:
    """True when a captured secret value is a placeholder rather than a real credential."""
    stripped = value.strip()
    lowered = stripped.lower()
    if lowered in PLACEHOLDER_VALUES or lowered.startswith(("your", "changeme", "example")):
        return True
    if any(marker in stripped for marker in PLACEHOLDER_MARKERS):
        return True
    return any(p.fullmatch(stripped) for p in PLACEHOLDER_PATTERNS)


def dedupe_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Keep one finding per (file, line, matched text), preferring the highest severity."""
    best: dict[tuple, Finding] = {}
    order: list[tuple] = []
    for finding in findings:
        key = (finding.file_path, finding.line_number, finding.matched_text)
        if key not in best:
            best[key] = finding
            order.append(key)
        elif SEVERITY_RANK[finding.severity] > SEVERITY_RANK[best[key].severity]:
            best[key] = finding
    return [best[key] for key in order]


def _as_pattern_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [p.strip() for p in value.split(",") if p.strip()]
    return [str(p) for p in value]


class CompiledRule:
    def __init__(self, raw: dict[str, Any]):
        self.id = raw["id"]
        self.title = raw["title"]
        self.description = raw["description"]
        self.severity = Severity(raw["severity"])
        self.rule_type = RuleType(raw["rule_type"])
        self.pattern_str = raw["pattern"]
        self.compiled_pattern = re.compile(self.pattern_str)
        self.cwe = raw.get("cwe")
        self.remediation = raw.get("remediation")
        # Optional scoping: glob patterns matched against the file path or its basename
        self.file_patterns = _as_pattern_list(raw.get("file_patterns"))
        self.exclude_patterns = _as_pattern_list(raw.get("exclude_patterns"))
        # When True, a named group "value" in the pattern must not be a placeholder
        self.skip_placeholders = bool(raw.get("skip_placeholders", False))

    def _matches_any(self, file_path: str, patterns: list[str]) -> bool:
        normalized = file_path.replace("\\", "/")
        name = normalized.rsplit("/", 1)[-1]
        return any(fnmatch.fnmatch(normalized, p) or fnmatch.fnmatch(name, p) for p in patterns)

    def applies_to(self, file_path: str) -> bool:
        if self.file_patterns and not self._matches_any(file_path, self.file_patterns):
            return False
        if self.exclude_patterns and self._matches_any(file_path, self.exclude_patterns):
            return False
        return True


class RuleEngine:
    def __init__(self, custom_rules_dir: Path | None = None):
        self.rules: list[CompiledRule] = []
        self._load_builtin_rules()
        if custom_rules_dir and custom_rules_dir.exists():
            self._load_rules_from_dir(custom_rules_dir)

    def _load_builtin_rules(self) -> None:
        builtin_dir = Path(__file__).parent
        for yaml_file in builtin_dir.glob("*.yaml"):
            self._load_yaml_file(yaml_file)

    def _load_rules_from_dir(self, directory: Path) -> None:
        for yaml_file in directory.glob("*.yaml"):
            self._load_yaml_file(yaml_file)

    def _load_yaml_file(self, path: Path) -> None:
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if not data or "rules" not in data:
                    return
                for rule_dict in data["rules"]:
                    try:
                        self.rules.append(CompiledRule(rule_dict))
                    except Exception as e:
                        print(f"Warning: Failed to compile rule in {path.name}: {e}")
        except Exception as e:
            print(f"Warning: Failed to read rule file {path}: {e}")

    def scan_line(self, file_path: str, line_number: int, content: str) -> list[Finding]:
        findings: list[Finding] = []
        for rule in self.rules:
            if not rule.applies_to(file_path):
                continue

            seen_texts = set()
            for match in rule.compiled_pattern.finditer(content):
                matched_text = match.group(0)
                if not matched_text or matched_text in seen_texts:
                    continue
                if rule.skip_placeholders:
                    value = match.groupdict().get("value")
                    if value is not None and is_placeholder(value):
                        continue
                seen_texts.add(matched_text)

                findings.append(
                    Finding(
                        id=f"{rule.id}-{file_path}-{line_number}-{match.start()}",
                        rule_id=rule.id,
                        title=rule.title,
                        description=rule.description,
                        severity=rule.severity,
                        rule_type=rule.rule_type,
                        file_path=file_path,
                        line_number=line_number,
                        matched_text=matched_text,
                        context=content.strip(),
                        cwe=rule.cwe,
                        suggested_fix=rule.remediation,
                    )
                )
        return dedupe_findings(findings)
