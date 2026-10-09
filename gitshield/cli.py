import sys
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console

from gitshield import __version__
from gitshield.ai.remediator import AIRemediator
from gitshield.core.scanner import Scanner
from gitshield.formatters.console import print_report_to_console
from gitshield.formatters.sarif import export_to_sarif


app = typer.Typer(
    name="gitshield",
    help="🛡️ GitShield — AI-Powered PR Security Auditor & Auto-Remediation Engine",
    add_completion=False,
)
console = Console()


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
    branch: Optional[str] = typer.Option(
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
    output: Optional[Path] = typer.Option(
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
    """Scan git diff for hardcoded secrets, OWASP vulnerabilities, and generate AI fixes."""
    scanner = Scanner()

    try:
        report = scanner.scan_diff(
            repo_path=path.resolve(),
            staged=staged,
            branch_or_commit=branch,
            enable_entropy=not no_entropy,
        )
    except Exception as e:
        console.print(f"[bold red]Scan failed:[/bold red] {e}")
        raise typer.Exit(code=1)

    if fix and report.findings:
        remediator = AIRemediator()
        console.print("\n[bold magenta]🤖 Generating AI remediations...[/bold magenta]")
        for f in report.findings:
            with console.status(f"Generating fix for [cyan]{f.rule_id}[/cyan] in {f.file_path}..."):
                ai_fix = remediator.generate_fix(f)
                f.suggested_fix = ai_fix

    # Output formatting
    if format == "sarif" and output:
        export_to_sarif(report, output)
        console.print(f"[bold green]✔ SARIF report saved to {output}[/bold green]")
    elif format == "json" and output:
        output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[bold green]✔ JSON report saved to {output}[/bold green]")
    else:
        print_report_to_console(report, console=console)

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
        raise typer.Exit(code=1)

    console.print(f"[bold cyan]GitShield web[/bold cyan] -> http://{host}:{port}")
    uvicorn.run("gitshield.web.app:app", host=host, port=port, reload=reload)


@app.command()
def version():
    """Show the GitShield version."""
    console.print(f"[bold cyan]GitShield[/bold cyan] version [bold green]{__version__}[/bold green]")


def main():
    app()


if __name__ == "__main__":
    main()
