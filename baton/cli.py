"""
cli.py — Baton CLI entry point.

Registers all commands: init / sync / status / score / end / doctor / install-skill.
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from .commands.doctor import run_doctor
from .commands.end import run_end
from .commands.init import run_init
from .commands.install_skill import run_install_skill
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
    diff_only: bool = typer.Option(
        False,
        "--diff-only",
        help=(
            "Print the git diff + JSON contract for a host agent to use, then exit. "
            "No writes. Designed for use with agent skills: pipe the output to the "
            "agent, have it draft the JSON, then run `baton end --apply`."
        ),
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help=(
            "Read a pre-drafted session delta JSON from stdin and apply it. "
            "Falls back to the heuristic summarizer if stdin is empty or invalid."
        ),
    ),
    api: bool = typer.Option(
        False,
        "--api",
        help=(
            "Use the configured LLM provider to summarise the session. "
            "Requires ANTHROPIC_API_KEY (or OPENAI_API_KEY / "
            "GOOGLE_APPLICATION_CREDENTIALS for other providers)."
        ),
    ),
) -> None:
    """Capture the current session into [bold]BATON.md[/bold].

    Default (no flags): zero-cost heuristic summary from git diff + commit log.
    No API key required.

    Three-tier chain (cheapest first):
      [default]    Heuristic -- diff stats + commit subjects, no model needed.
      [bold]--apply[/bold]     Read a pre-drafted delta JSON from stdin (from a host agent skill).
      [bold]--api[/bold]       Call the configured LLM provider for a richer summary.
      [bold]--diff-only[/bold] Print context + JSON contract for a host agent; no writes.
    """
    flags = [diff_only, apply, api]
    if sum(flags) > 1:
        console.print(
            "[red]Error:[/red] --diff-only, --apply, and --api are mutually exclusive."
        )
        raise typer.Exit(1)

    if diff_only:
        mode = "diff-only"
    elif apply:
        mode = "apply"
    elif api:
        mode = "api"
    else:
        mode = "heuristic"

    ok = run_end(
        _repo_root(),
        force=force,
        since=since,
        tool=tool,
        auto_accept=yes,
        mode=mode,
    )
    if not ok:
        raise typer.Exit(1)


# ── baton install-skill ───────────────────────────────────────────────────────

@app.command("install-skill")
def install_skill(
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Overwrite the skill file even if it already exists.",
    ),
) -> None:
    """Install the baton-end Claude Code skill into [bold].claude/skills/baton-end/SKILL.md[/bold].

    The skill lets Claude Code automatically capture session context into
    BATON.md without an API key, by running [bold]baton end --diff-only[/bold] to get the
    JSON contract and then piping a drafted delta to [bold]baton end --apply[/bold].

    The installed file is a durable project artifact -- commit it to git.
    Unlike adapter outputs (CLAUDE.md, AGENTS.md, etc.) it is NOT gitignored
    and is NOT regenerated on every [bold]baton sync[/bold].
    """
    run_install_skill(_repo_root(), force=force)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Pyproject.toml entry point: ``baton = "baton.cli:main"``."""
    app()
