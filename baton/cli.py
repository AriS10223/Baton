"""
cli.py — Baton CLI entry point.

Registers all five commands: init / sync / status / score / end.
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from .commands.doctor import run_doctor
from .commands.end import run_end
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


@app.command()
def doctor() -> None:
    """Diagnose your Baton setup: checks BATON.md, config, adapters, agent files, and API keys."""
    run_doctor(_repo_root())


# ── baton end ─────────────────────────────────────────────────────────────────

@app.command()
def end(
    force: bool = typer.Option(
        False,
        "--force",
        help="Trigger even if the diff is below the minimum line threshold.",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Override the base git ref to diff from (SHA or branch name).",
    ),
    tool: str = typer.Option(
        "",
        "--tool",
        help="Name of the AI tool used this session (e.g. claude-code, cursor).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Accept all proposed changes without interactive prompts.",
    ),
) -> None:
    """Summarise the current session into [bold]BATON.md[/bold] via LLM.

    Reads the git diff since the last ``baton end`` run, asks your configured
    LLM to propose sprint-done / sprint-next / session-log updates, lets you
    review them, then writes them back to BATON.md and re-syncs agent files.

    Requires the ANTHROPIC_API_KEY environment variable (or OPENAI_API_KEY /
    GOOGLE_APPLICATION_CREDENTIALS depending on llm_provider in .baton.toml).
    """
    ok = run_end(
        _repo_root(),
        force=force,
        since=since,
        tool=tool,
        auto_accept=yes,
    )
    if not ok:
        raise typer.Exit(1)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Pyproject.toml entry point: ``baton = "baton.cli:main"``."""
    app()
