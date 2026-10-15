import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from typer.testing import CliRunner

from gitshield.ai.remediator import REDACTED, AIRemediator, FixProposal
from gitshield.cli import app
from gitshield.core.baseline import BASELINE_FILE_NAME, fingerprint_findings, load_baseline
from gitshield.core.models import Finding, RuleType, Severity
from gitshield.interactive import _Edit, apply_proposal, map_line, review_findings

SECRET = "AKIAIOSFODNN7EXAMPLE"
PROVIDER_ENV = ("LLM_PROVIDER", "LLM_MODEL", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _finding(line: int, path: str = "app.py", rule_type: RuleType = RuleType.OWASP, **kw: Any) -> Finding:
    values: dict[str, Any] = dict(
        id=f"R-{path}-{line}",
        rule_id="OWASP-A03-EVAL-003",
        title="eval",
        description="",
        severity=Severity.CRITICAL,
        rule_type=rule_type,
        file_path=path,
        line_number=line,
        matched_text="eval(",
        context="eval(x)",
    )
    values.update(kw)
    return Finding(**values)


# ---- map_line ------------------------------------------------------------


def test_map_line_shifts_lines_after_an_edit_and_follows_unchanged_lines_inside_it():
    edit = _Edit(start=3, original=["a", "b", "c"], replacement=["a", "b1", "b2", "c"])
    assert map_line(1, [edit]) == 1
    assert map_line(3, [edit]) == 3  # "a" unchanged
    assert map_line(5, [edit]) == 6  # "c" moved down by one
    assert map_line(4, [edit]) is None  # "b" was rewritten
    assert map_line(10, [edit]) == 11


# ---- apply_proposal ------------------------------------------------------


def test_apply_keeps_crlf_and_missing_final_newline(tmp_path: Path):
    (tmp_path / "app.py").write_bytes(b"one\r\ntwo\r\nthree")
    proposal = FixProposal(start=2, original=["two", "three"], replacement=["2", "3", "4"], explanation="")
    assert apply_proposal(tmp_path, "app.py", proposal) is None
    assert (tmp_path / "app.py").read_bytes() == b"one\r\n2\r\n3\r\n4"


def test_apply_refuses_when_file_changed(tmp_path: Path):
    (tmp_path / "app.py").write_text("one\ntwo\n", encoding="utf-8")
    proposal = FixProposal(start=1, original=["uno"], replacement=["1"], explanation="")
    assert "changed" in (apply_proposal(tmp_path, "app.py", proposal) or "")
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "one\ntwo\n"


def test_apply_refuses_paths_outside_repo(tmp_path: Path):
    proposal = FixProposal(start=1, original=["x"], replacement=["y"], explanation="")
    assert apply_proposal(tmp_path, "../outside.py", proposal) is not None


# ---- propose_patch -------------------------------------------------------


def _remediator(monkeypatch: pytest.MonkeyPatch, answer: str, prompts: list[str]) -> AIRemediator:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    r = AIRemediator()

    def fake_complete(system: str, user: str) -> str:
        prompts.append(user)
        return answer

    monkeypatch.setattr(r, "_complete", fake_complete)
    return r


def test_propose_patch_restores_unchanged_secret_lines_and_never_sends_secret(clean_env, tmp_path: Path):
    (tmp_path / "app.py").write_text(f'KEY = "{SECRET}"\nresult = eval(x)\n', encoding="utf-8")
    answer = f'Use literal_eval.\n```python\nKEY = "{REDACTED}"\nresult = ast.literal_eval(x)\n```\n'
    prompts: list[str] = []
    proposal = _remediator(clean_env, answer, prompts).propose_patch(_finding(2), tmp_path)
    assert isinstance(proposal, FixProposal)
    assert proposal.start == 1
    assert proposal.replacement == [f'KEY = "{SECRET}"', "result = ast.literal_eval(x)"]
    assert proposal.explanation == "Use literal_eval."
    assert SECRET not in prompts[0]


def test_propose_patch_refuses_to_write_a_placeholder(clean_env, tmp_path: Path):
    (tmp_path / "app.py").write_text(f'KEY = "{SECRET}"\n', encoding="utf-8")
    answer = f'```python\nKEY = os.getenv("KEY", "{REDACTED}")\n```'
    finding = _finding(1, rule_type=RuleType.SECRET, matched_text=SECRET, context=f'KEY = "{SECRET}"')
    result = _remediator(clean_env, answer, []).propose_patch(finding, tmp_path)
    assert isinstance(result, str) and "redacted" in result


def test_propose_patch_without_code_block_or_provider(clean_env, tmp_path: Path):
    (tmp_path / "app.py").write_text("eval(x)\n", encoding="utf-8")
    assert "no code block" in _remediator(clean_env, "just text", []).propose_patch(_finding(1), tmp_path)
    clean_env.delenv("ANTHROPIC_API_KEY")
    assert "no LLM provider" in AIRemediator().propose_patch(_finding(1), tmp_path)


# ---- review_findings -----------------------------------------------------


class FakeRemediator:
    """Proposes replacing the finding's line with a fixed line, read from the current file."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.seen_lines: list[int] = []

    def propose_patch(self, finding: Finding, repo_path: Path) -> FixProposal:
        self.seen_lines.append(finding.line_number)
        lines = (self.repo / finding.file_path).read_text(encoding="utf-8").splitlines()
        original = lines[finding.line_number - 1]
        return FixProposal(
            start=finding.line_number,
            original=[original],
            replacement=["# safe", original.replace("eval", "literal_eval")],
            explanation="fix",
        )


def _review(repo: Path, findings: list[Finding], answers: list[str]):
    replies = iter(answers)
    return review_findings(
        findings,
        fingerprint_findings(findings, repo),
        repo_path=repo,
        baseline_path=repo / BASELINE_FILE_NAME,
        remediator=FakeRemediator(repo),  # type: ignore[arg-type]
        console=Console(record=True, width=120),
        ask=lambda prompt, choices, default: next(replies),
    )


def test_review_applies_and_tracks_line_shifts(tmp_path: Path):
    (tmp_path / "app.py").write_text("a = eval(x)\nb = 1\nc = eval(y)\n", encoding="utf-8")
    findings = [_finding(1), _finding(3)]
    result = _review(tmp_path, findings, ["a", "a"])
    assert len(result.applied) == 2
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == (
        "# safe\na = literal_eval(x)\nb = 1\n# safe\nc = literal_eval(y)\n"
    )
    assert not result.has_blocking


def test_review_baselines_skips_and_quits(tmp_path: Path):
    (tmp_path / "app.py").write_text("eval(a)\neval(b)\neval(c)\n", encoding="utf-8")
    findings = [_finding(1, context="eval(a)"), _finding(2, context="eval(b)"), _finding(3, context="eval(c)")]
    result = _review(tmp_path, findings, ["b", "q"])
    assert [f.line_number for f in result.baselined] == [1]
    assert [f.line_number for f in result.unreviewed] == [2, 3]
    assert result.has_blocking
    assert load_baseline(tmp_path / BASELINE_FILE_NAME) == {fingerprint_findings(findings, tmp_path)[0]}
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "eval(a)\neval(b)\neval(c)\n"


# ---- CLI -----------------------------------------------------------------

runner = CliRunner()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=str(repo), check=True, capture_output=True
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_cli_interactive_rejects_machine_output(repo: Path):
    assert runner.invoke(app, ["scan", str(repo), "-i", "--format", "json"]).exit_code == 2


def test_cli_interactive_without_llm_can_baseline(clean_env, repo: Path):
    (repo / "app.py").write_text(f'KEY = "{SECRET}"\n', encoding="utf-8")
    result = runner.invoke(app, ["scan", str(repo), "--interactive"], input="b\n")
    assert result.exit_code == 0, result.output
    assert SECRET not in result.output
    data = json.loads((repo / BASELINE_FILE_NAME).read_text(encoding="utf-8"))
    assert [e["rule_id"] for e in data["findings"]] == ["SEC-AWS-001"]
    assert runner.invoke(app, ["scan", str(repo)]).exit_code == 0


def test_cli_interactive_skip_keeps_exit_1(clean_env, repo: Path):
    (repo / "app.py").write_text(f'KEY = "{SECRET}"\n', encoding="utf-8")
    assert runner.invoke(app, ["scan", str(repo), "-i"], input="s\n").exit_code == 1
