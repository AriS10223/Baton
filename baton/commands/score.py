"""
score.py — ``baton score``: structural completeness check for BATON.md.

Evaluates BATON.md quality without any LLM calls — purely structural.
Imports ``SCORE_CHECKS`` from ``core/schema.py`` (the single source of truth).
Score is out of 100 points.  Partial credit for "warn" checks.
"""
from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..core.document import BatonDocument, BatonDocumentError
from ..core.schema import SCORE_CHECKS

console = Console()

_STATUS_ICON = {
    "pass": "[bold green] OK [/bold green]",
    "warn": "[bold yellow] !! [/bold yellow]",
    "fail": "[bold red] -- [/bold red]",
}


def run_score(repo_root: Path) -> None:
    """Print a BATON.md completeness score and actionable tips."""
    baton_path = repo_root / "BATON.md"

    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    # ── Run all checks ────────────────────────────────────────────
    results: list[tuple] = []  # (check, status, detail, tip, earned)
    total_score = 0

    for check in SCORE_CHECKS:
        status, detail, tip = check.fn(doc.data)
        earned = {
            "pass": check.points,
            "warn": check.warn_points,
            "fail": 0,
        }[status]
        total_score += earned
        results.append((check, status, detail, tip, earned))

    # ── Score colour ──────────────────────────────────────────────
    if total_score >= 80:
        score_style = "bold green"
    elif total_score >= 50:
        score_style = "bold yellow"
    else:
        score_style = "bold red"

    # ── Output ────────────────────────────────────────────────────
    console.print()
    console.rule("[bold]BATON.md Quality Score[/bold]")
    console.print(f"\n  Score: [{score_style}]{total_score}/100[/{score_style}]\n")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("icon", width=6, no_wrap=True)
    table.add_column("label", style="bold", width=26, no_wrap=True)
    table.add_column("detail", style="dim")

    for check, status, detail, tip, earned in results:
        icon = _STATUS_ICON[status]
        table.add_row(icon, check.label, detail)

    console.print(table)
    console.print()

    # ── Tips ──────────────────────────────────────────────────────
    tips = [(check.label, tip) for check, status, _, tip, _ in results if tip]
    if tips:
        console.print("  [bold]Suggestions:[/bold]")
        for label, tip in tips:
            console.print(f"  - [cyan]{label}[/cyan]: {tip}")
        console.print()
    else:
        console.print("  [green]Great shape - no suggestions![/green]\n")
