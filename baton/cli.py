"""
cli.py — Baton CLI entry point.

Registers the four Phase-1 commands (init / sync / status / score).
The ``baton end`` command (Increment 2, requires LLM) is a stub here.
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from .commands.init import run_init
from .commands.score import run_score
from .commands.status import run_status
from .commands.sync import run_sync

app = typer.Typer(
    name="baton",
    help=(
        "Baton — context sync for vibe coders.\n\n"
        "Maintains a single BATON.md as your source of truth and syncs it\n"
        "into every AI agent's native config file, so any agent picks up\n"
        "exactly where the last session left off."
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()


def _repo_root() -> Path:
    """Return the current working directory as the project root."""
    return Path.cwd()


# ── Commands ──────────────────────────────────────────────────────────────────

@app.command()
def init(
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Reinitialise even if BATON.md already exists.",
    ),
) -> None:
    """Scaffold [bold]BATON.md[/bold], [bold].baton.toml[/bold], and a git pre-commit reminder hook."""
    run_init(_repo_root(), force=force)


@app.command()
def sync() -> None:
    """Push [bold]BATON.md[/bold] → all enabled agent config files."""
    ok = run_sync(_repo_root())
    if not ok:
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """Show which agent files are in-sync, drifted, or missing."""
    run_status(_repo_root())


@app.command()
def score() -> None:
    """Evaluate [bold]BATON.md[/bold] completeness (no LLM — purely structural)."""
    run_score(_repo_root())


# ── Stub for Increment 2 ──────────────────────────────────────────────────────

@app.command()
def end(
    force: bool = typer.Option(
        False,
        "--force",
        help="Trigger even if the diff is below the minimum line threshold.",
    ),
) -> None:
    """Summarise the current session into BATON.md (requires LLM — Increment 2).

    [dim]Not yet implemented.  Coming in Increment 2:[/dim]
    [dim]  1. Parse git diff (Pass 1)[/dim]
    [dim]  2. Generate YAML delta via Anthropic Claude (Pass 2)[/dim]
    [dim]  3. Human review in terminal[/dim]
    [dim]  4. Update BATON.md + run baton sync[/dim]
    """
    console.print(
        "[yellow]`baton end` is not yet implemented.[/yellow]\n"
        "It is coming in Increment 2 (AI summariser + review UI).\n\n"
        "For now, update [bold]BATON.md[/bold] manually, then run "
        "[bold]baton sync[/bold]."
    )
    raise typer.Exit(0)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Pyproject.toml entry point: ``baton = "baton.cli:main"``."""
    app()
