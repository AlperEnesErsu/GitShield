import json
import sys
from pathlib import Path

import typer
from dotenv import find_dotenv, load_dotenv
from rich.console import Console

from gitshield import __version__
from gitshield.ai.remediator import AIRemediator
from gitshield.core.diff_parser import get_git_diff
from gitshield.core.models import ScanReport
from gitshield.core.scanner import Scanner, load_ignore_file
from gitshield.formatters.console import print_report_to_console
from gitshield.formatters.sarif import build_sarif
from gitshield.rules.engine import RuleEngine

app = typer.Typer(
    name="gitshield",
    help="🛡️ GitShield — AI-Powered PR Security Auditor & Auto-Remediation Engine",
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

FORMATS = ("console", "sarif", "json")
EXIT_ERROR = 2  # scan could not run; findings keep exit code 1


def _redacted(report: ScanReport) -> ScanReport:
    """Copy of the report with secret values masked, safe for files and stdout."""
    return report.model_copy(update={"findings": [f.redacted() for f in report.findings]})


@app.command()
def scan(
    path: Path = typer.Argument(
        Path("."),
        help="Path to git repository to inspect.",
        exists=True,
    ),
    staged: bool = typer.Option(
        False,
        "--staged",
        "-s",
        help="Scan only staged git changes (git diff --cached).",
    ),
    branch: str | None = typer.Option(
        None,
        "--branch",
        "-b",
        help="Compare against branch or commit reference (e.g. main..HEAD).",
    ),
    no_entropy: bool = typer.Option(
        False,
        "--no-entropy",
        help="Disable Shannon entropy detection for secrets.",
    ),
    no_untracked: bool = typer.Option(
        False,
        "--no-untracked",
        help="Skip untracked (new, not yet added) files in the working-tree scan.",
    ),
    no_ignore_file: bool = typer.Option(
        False,
        "--no-ignore-file",
        help="Do not apply the repo's .gitshieldignore file.",
    ),
    rules_dir: Path | None = typer.Option(
        None,
        "--rules-dir",
        help="Load additional custom rules from this directory.",
    ),
    fix: bool = typer.Option(
        False,
        "--fix",
        "-f",
        help="Trigger AI remediation engine to generate code fixes for findings.",
    ),
    format: str = typer.Option(
        "console",
        "--format",
        help="Output format: console, sarif, or json.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save report to specified file.",
    ),
    fail_on_critical: bool = typer.Option(
        True,
        "--fail-on-critical/--no-fail",
        help="Exit with code 1 if CRITICAL or HIGH severity issues are detected (CI mode).",
    ),
):
    """Scan git diff for hardcoded secrets, OWASP vulnerabilities, and generate AI fixes.

    Exit codes: 0 clean, 1 CRITICAL/HIGH findings, 2 scan or usage error.
    """
    format = format.lower()
    if format not in FORMATS:
        err_console.print(f"[bold red]Unknown format:[/bold red] {format}. Use one of: console, sarif, json.")
        raise typer.Exit(code=EXIT_ERROR)

    # Machine-readable output without --output goes to stdout; keep status text on stderr
    stdout_report = format != "console" and output is None
    log = err_console if stdout_report else console

    repo_path = path.resolve()
    try:
        ignore_patterns = [] if no_ignore_file else load_ignore_file(repo_path)
        scanner = Scanner(RuleEngine(custom_rules_dir=rules_dir), ignore_patterns=ignore_patterns)
        raw_diff = get_git_diff(
            repo_path=repo_path,
            staged=staged,
            branch_or_commit=branch,
            include_untracked=not no_untracked,
        )
        report = scanner.scan_diff(
            repo_path=repo_path,
            raw_diff=raw_diff,
            staged=staged,
            branch_or_commit=branch,
            enable_entropy=not no_entropy,
        )
    except Exception as e:  # GitDiffError or any other failure: exit 2 so CI can tell it apart
        err_console.print(f"[bold red]Scan failed:[/bold red] {e}")
        raise typer.Exit(code=EXIT_ERROR) from e

    if fix and report.findings:
        remediator = AIRemediator()
        log.print("\n[bold magenta]🤖 Generating AI remediations...[/bold magenta]")
        for f in report.findings:
            with log.status(f"Generating fix for [cyan]{f.rule_id}[/cyan] in {f.file_path}..."):
                ai_fix = remediator.generate_fix(f, repo_path=repo_path)
                f.suggested_fix = ai_fix

    # Output formatting (files and stdout never contain unmasked secrets)
    if format == "sarif":
        text = json.dumps(build_sarif(_redacted(report)), indent=2)
    elif format == "json":
        text = _redacted(report).model_dump_json(indent=2)
    else:
        text = None

    if text is None:
        print_report_to_console(report, console=console)
    elif output:
        output.write_text(text, encoding="utf-8")
        log.print(f"[bold green]✔ {format.upper()} report saved to {output}[/bold green]")
    else:
        # JSON and SARIF are UTF-8 by spec; don't let a Windows console code page re-encode them.
        sys.stdout.flush()
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()

    if fail_on_critical and report.has_high:
        raise typer.Exit(code=1)


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", help="Interface to bind. Keep it local: the API uses your GitHub token."),
    port: int = typer.Option(8000, help="Port to listen on."),
    reload: bool = typer.Option(False, help="Auto-reload on code changes (development)."),
):
    """Start the GitShield web dashboard (PR reviews, repo tables, issues)."""
    try:
        import uvicorn
    except ImportError:
        console.print('[red]Web extras missing. Install with:[/red] uv pip install -e ".[web]"')
        raise typer.Exit(code=1) from None

    console.print(f"[bold cyan]GitShield web[/bold cyan] -> http://{host}:{port}")
    uvicorn.run("gitshield.web.app:app", host=host, port=port, reload=reload)


@app.command()
def version():
    """Show the GitShield version."""
    console.print(f"[bold cyan]GitShield[/bold cyan] version [bold green]{__version__}[/bold green]")


def main():
    # A Windows console or pipe may use a legacy code page that cannot encode the report's emoji;
    # degrade to replacement characters instead of crashing after the scan finished.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    # API keys for --fix may live in the scanned project's .env, like for `gitshield web`.
    load_dotenv(find_dotenv(usecwd=True))
    app()


if __name__ == "__main__":
    main()
