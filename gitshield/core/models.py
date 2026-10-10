from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class RuleType(str, Enum):
    SECRET = "SECRET"
    OWASP = "OWASP"
    ENTROPY = "ENTROPY"
    DEPENDENCY = "DEPENDENCY"


class DiffLine(BaseModel):
    file_path: str
    line_number: int
    content: str
    is_added: bool = True


class DiffHunk(BaseModel):
    file_path: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine] = Field(default_factory=list)


class Finding(BaseModel):
    id: str
    rule_id: str
    title: str
    description: str
    severity: Severity
    rule_type: RuleType
    file_path: str
    line_number: int
    matched_text: str
    context: str | None = None
    entropy: float | None = None
    cwe: str | None = None
    suggested_fix: str | None = None
    diff_patch: str | None = None

    def mask_secret(self) -> str:
        """Mask matched secret text for safe display. Reveals at most 4 chars, none if short."""
        return mask_text(self.matched_text)

    def redacted(self) -> "Finding":
        """Return a copy safe to write to reports: secrets masked in matched_text and context."""
        if self.rule_type not in (RuleType.SECRET, RuleType.ENTROPY):
            return self.model_copy()
        masked = self.mask_secret()
        update = {"matched_text": masked}
        if self.context and self.matched_text:
            update["context"] = self.context.replace(self.matched_text, masked)
        if self.diff_patch and self.matched_text:
            update["diff_patch"] = self.diff_patch.replace(self.matched_text, masked)
        return self.model_copy(update=update)


def mask_text(value: str) -> str:
    """Mask a secret: short values are fully hidden, long ones keep only a 4-char prefix."""
    if len(value) < 16:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 4)}"


class ScanReport(BaseModel):
    repo_path: str
    target_ref: str
    findings: list[Finding] = Field(default_factory=list)
    scanned_files_count: int = 0
    scanned_lines_count: int = 0
    execution_time_sec: float = 0.0

    @property
    def has_critical(self) -> bool:
        return any(f.severity == Severity.CRITICAL for f in self.findings)

    @property
    def has_high(self) -> bool:
        return any(f.severity in (Severity.CRITICAL, Severity.HIGH) for f in self.findings)
