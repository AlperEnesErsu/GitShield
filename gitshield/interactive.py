"""`gitshield scan --interactive`: walk the findings one by one and apply, skip or baseline each.

For every finding the LLM proposes a replacement for the lines around it. The proposal is shown
as a diff (secrets masked) and is written to the file only when the user accepts it. Applied
fixes are not tested; the summary asks for a rescan.
"""

import difflib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.prompt import Prompt

from gitshield.ai.remediator import AIRemediator, FixProposal, redact_secrets
from gitshield.core.baseline import write_baseline
from gitshield.core.models import Finding, RuleType, Severity
from gitshield.formatters.console import SEVERITY_COLORS

SECRET_TYPES = (RuleType.SECRET, RuleType.ENTROPY)
BLOCKING = (Severity.CRITICAL, Severity.HIGH)

# ask(prompt, choices, default) -> one of choices
Ask = Callable[[str, list[str], str], str]


def prompt_ask(console: Console) -> Ask:
    def ask(prompt: str, choices: list[str], default: str) -> str:
        return Prompt.ask(prompt, choices=choices, default=default, console=console)

    return ask


@dataclass
class _Edit:
    """An applied replacement, in the file's line numbers at the time it was applied (1-based)."""

    start: int
    original: list[str]
    replacement: list[str]


@dataclass
class InteractiveResult:
    applied: list[Finding] = field(default_factory=list)
    baselined: list[Finding] = field(default_factory=list)
    skipped: list[Finding] = field(default_factory=list)
    # Line was rewritten by an earlier fix in this session; a rescan tells whether it is gone
    covered: list[Finding] = field(default_factory=list)
    unreviewed: list[Finding] = field(default_factory=list)

    @property
    def has_blocking(self) -> bool:
        """True when a HIGH/CRITICAL finding was left as it is (skipped or not reached)."""
        return any(f.severity in BLOCKING for f in self.skipped + self.unreviewed)


def map_line(line: int, edits: list[_Edit]) -> int | None:
    """Follow an original line number through the edits; None if an edit rewrote that line."""
    for edit in edits:
        end = edit.start + len(edit.original)
        if line < edit.start:
            continue
        if line >= end:
            line += len(edit.replacement) - len(edit.original)
            continue
        offset = line - edit.start
        matcher = difflib.SequenceMatcher(a=edit.original, b=edit.replacement, autojunk=False)
        for tag, a1, a2, b1, _ in matcher.get_opcodes():
            if tag == "equal" and a1 <= offset < a2:
                line = edit.start + b1 + (offset - a1)
                break
        else:
            return None
    return line


def apply_proposal(repo_path: Path, file_path: str, proposal: FixProposal) -> str | None:
    """Write the proposal into the file, keeping its line endings. Returns an error or None."""
    root = repo_path.resolve()
    target = (root / file_path).resolve()
    try:
        target.relative_to(root)
        with open(target, encoding="utf-8", newline="") as fh:
            text = fh.read()
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return f"cannot read {file_path}: {e}"

    lines = text.splitlines(keepends=True)
    idx = proposal.start - 1
    window = lines[idx : idx + len(proposal.original)]
    if "".join(window).splitlines() != proposal.original:
        return f"{file_path} changed since the suggestion was made"

    eol = "\n"
    for line in window:
        if line.endswith("\r\n"):
            eol = "\r\n"
            break
    last_has_eol = bool(window) and window[-1] != window[-1].rstrip("\r\n")
    new = [line + eol for line in proposal.replacement]
    if new and not last_has_eol:
        new[-1] = new[-1].removesuffix(eol)
    lines[idx : idx + len(proposal.original)] = new
    try:
        with open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write("".join(lines))
    except OSError as e:
        return f"cannot write {file_path}: {e}"
    return None


def _mask(line: str, finding: Finding) -> str:
    """Never show a secret: redact detected secrets and the finding's own match."""
    safe = redact_secrets(line)
    if finding.rule_type in SECRET_TYPES and finding.matched_text:
        safe = safe.replace(finding.matched_text, finding.mask_secret())
    return safe


def _print_proposal(console: Console, finding: Finding, proposal: FixProposal) -> None:
    if proposal.explanation:
        console.print(escape(_mask(proposal.explanation, finding)))
    end = proposal.start + len(proposal.original) - 1
    diff = difflib.unified_diff(
        proposal.original,
        proposal.replacement,
        fromfile=f"a/{finding.file_path}",
        tofile=f"b/{finding.file_path}",
        lineterm="",
        n=2,
    )
    console.print(f"[dim]Proposed change to lines {proposal.start}-{end}:[/dim]")
    for line in diff:
        style = "green" if line.startswith("+") else "red" if line.startswith("-") else "cyan" if line.startswith("@@") else "dim"
        console.print(f"[{style}]{escape(_mask(line, finding))}[/{style}]", highlight=False)
    removed = len(proposal.original) - len(proposal.replacement)
    if removed > len(proposal.original) // 2:
        console.print(f"[bold yellow]⚠ The suggestion removes {removed} of {len(proposal.original)} lines; check it before applying.[/bold yellow]")


def review_findings(
    findings: list[Finding],
    fingerprints: list[str],
    repo_path: Path,
    baseline_path: Path,
    remediator: AIRemediator,
    console: Console,
    ask: Ask | None = None,
) -> InteractiveResult:
    """Interactive loop over findings (in report order). Baseline choices are written at the end."""
    ask = ask or prompt_ask(console)
    result = InteractiveResult()
    baseline_prints: list[str] = []
    edits: dict[str, list[_Edit]] = {}

    for i, finding in enumerate(findings):
        color = SEVERITY_COLORS.get(finding.severity, "white")
        console.rule(f"[{color}]{finding.severity.value}[/{color}] {i + 1}/{len(findings)}")
        console.print(
            f"[bold]{escape(finding.rule_id)}[/bold] {escape(finding.title)}  "
            f"[yellow]{escape(finding.file_path)}:{finding.line_number}[/yellow]"
        )
        if finding.context:
            console.print(f"[dim]{escape(_mask(finding.context, finding))}[/dim]", highlight=False)

        file_edits = edits.setdefault(finding.file_path, [])
        current_line = map_line(finding.line_number, file_edits)
        if current_line is None:
            console.print("[cyan]An earlier fix in this session rewrote this line; rescan to check it.[/cyan]")
            result.covered.append(finding)
            continue

        with console.status(f"Asking the LLM for a fix for [cyan]{escape(finding.rule_id)}[/cyan]..."):
            proposal = remediator.propose_patch(
                finding.model_copy(update={"line_number": current_line}), repo_path
            )

        choices = ["s", "b", "q"]
        if isinstance(proposal, FixProposal) and proposal.replacement != proposal.original:
            _print_proposal(console, finding, proposal)
            choices.insert(0, "a")
            label = "[a]pply, [s]kip, add to [b]aseline, [q]uit"
        else:
            reason = proposal if isinstance(proposal, str) else "the suggestion does not change the code"
            console.print(f"[yellow]No applicable fix: {escape(_mask(reason, finding))}[/yellow]")
            if finding.suggested_fix:
                console.print(f"[dim]Advice: {escape(_mask(finding.suggested_fix, finding))}[/dim]")
            label = "[s]kip, add to [b]aseline, [q]uit"

        choice = ask(label, choices, "s")
        if choice == "q":
            result.unreviewed.extend(findings[i:])
            break
        if choice == "b":
            result.baselined.append(finding)
            baseline_prints.append(fingerprints[i])
        elif choice == "a" and isinstance(proposal, FixProposal):
            error = apply_proposal(repo_path, finding.file_path, proposal)
            if error:
                console.print(f"[bold red]Not applied:[/bold red] {escape(error)}")
                result.skipped.append(finding)
            else:
                file_edits.append(_Edit(proposal.start, proposal.original, proposal.replacement))
                result.applied.append(finding)
                console.print("[green]✔ Applied.[/green]")
        else:
            result.skipped.append(finding)

    if result.baselined:
        added, total = write_baseline(baseline_path, result.baselined, repo_path, fingerprints=baseline_prints)
        console.print(f"[green]✔ Baseline {escape(str(baseline_path))}: {added} added, {total} total.[/green]")

    console.rule("Summary")
    console.print(
        f"Applied: {len(result.applied)}  Baselined: {len(result.baselined)}  "
        f"Skipped: {len(result.skipped)}  Rewritten by an earlier fix: {len(result.covered)}  "
        f"Not reviewed: {len(result.unreviewed)}"
    )
    if result.applied or result.covered:
        console.print("[bold]Applied fixes are untested suggestions: review the diff and run `gitshield scan` again.[/bold]")
    return result
