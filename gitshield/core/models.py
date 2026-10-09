from enum import Enum
from typing import List, Optional
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
    lines: List[DiffLine] = Field(default_factory=list)


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
    context: Optional[str] = None
    entropy: Optional[float] = None
    cwe: Optional[str] = None
    suggested_fix: Optional[str] = None
    diff_patch: Optional[str] = None

    def mask_secret(self) -> str:
        """Mask matched secret text for safe display."""
        if len(self.matched_text) <= 8:
            return "*" * len(self.matched_text)
        visible = self.matched_text[:4]
        return f"{visible}{'*' * (len(self.matched_text) - 4)}"


class ScanReport(BaseModel):
    repo_path: str
    target_ref: str
    findings: List[Finding] = Field(default_factory=list)
    scanned_files_count: int = 0
    scanned_lines_count: int = 0
    execution_time_sec: float = 0.0

    @property
    def has_critical(self) -> bool:
        return any(f.severity == Severity.CRITICAL for f in self.findings)

    @property
    def has_high(self) -> bool:
        return any(f.severity in (Severity.CRITICAL, Severity.HIGH) for f in self.findings)
