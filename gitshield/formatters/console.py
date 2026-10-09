from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from gitshield.core.models import ScanReport, Severity


SEVERITY_COLORS = {
    Severity.CRITICAL: "bold red",
    Severity.HIGH: "red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "cyan",
    Severity.INFO: "blue",
}


def print_report_to_console(report: ScanReport, console: Console | None = None) -> None:
    if console is None:
        console = Console()

    console.print()
    banner = Text("🛡️  GitShield PR Security Audit Report", style="bold cyan")
    console.print(Panel(banner, border_style="cyan"))

    # Summary table
    summary_table = Table(show_header=False, box=None)
    summary_table.add_column("Key", style="bold dim")
    summary_table.add_column("Value")

    summary_table.add_row("Repository", report.repo_path)
    summary_table.add_row("Target Reference", report.target_ref)
    summary_table.add_row("Files Inspected", str(report.scanned_files_count))
    summary_table.add_row("Lines Scanned", str(report.scanned_lines_count))
    summary_table.add_row("Execution Time", f"{report.execution_time_sec}s")
    summary_table.add_row("Total Findings", str(len(report.findings)))

    console.print(summary_table)
    console.print()

    if not report.findings:
        console.print("[bold green]✔ All clean! No security vulnerabilities or leaked secrets detected.[/bold green]\n")
        return

    # Findings Table
    table = Table(title="[bold red]Security Findings[/bold red]", show_lines=True)
    table.add_column("Severity", justify="center", style="bold")
    table.add_column("Rule ID & Title", style="cyan")
    table.add_column("Location", style="yellow")
    table.add_column("Matched (Masked)", style="magenta")
    table.add_column("Remediation / Fix", style="green")

    for f in report.findings:
        sev_color = SEVERITY_COLORS.get(f.severity, "white")
        sev_text = f"[{sev_color}]{f.severity.value}[/{sev_color}]"

        rule_info = f"[bold]{f.rule_id}[/bold]\n[dim]{f.title}[/dim]"
        loc_info = f"{f.file_path}:{f.line_number}"
        masked = f.mask_secret() if f.entropy or "SEC" in f.rule_id else f.matched_text
        if len(masked) > 30:
            masked = masked[:27] + "..."

        fix = f.suggested_fix or "N/A"
        if len(fix) > 60:
            fix = fix[:57] + "..."

        table.add_row(sev_text, rule_info, loc_info, masked, fix)

    console.print(table)
    console.print()
