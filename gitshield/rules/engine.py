import re
from pathlib import Path
from typing import Any, Dict, List
import yaml
from gitshield.core.models import Finding, RuleType, Severity


class CompiledRule:
    def __init__(self, raw: Dict[str, Any]):
        self.id = raw["id"]
        self.title = raw["title"]
        self.description = raw["description"]
        self.severity = Severity(raw["severity"])
        self.rule_type = RuleType(raw["rule_type"])
        self.pattern_str = raw["pattern"]
        self.compiled_pattern = re.compile(self.pattern_str)
        self.cwe = raw.get("cwe")
        self.remediation = raw.get("remediation")


class RuleEngine:
    def __init__(self, custom_rules_dir: Path | None = None):
        self.rules: List[CompiledRule] = []
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
            with open(path, "r", encoding="utf-8") as f:
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

    def scan_line(self, file_path: str, line_number: int, content: str) -> List[Finding]:
        findings: List[Finding] = []
        for rule in self.rules:
            match = rule.compiled_pattern.search(content)
            if match:
                matched_text = match.group(0)
                findings.append(
                    Finding(
                        id=f"{rule.id}-{file_path}-{line_number}",
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
        return findings
