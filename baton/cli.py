"""
cli.py — Baton CLI entry point.

Registers all commands: init / sync / status / score / end / doctor /
install-skill / check / supersede / history / hooks / review.
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from .commands.doctor import run_doctor
from .commands.end import run_end
from .commands.init import run_init
from .commands.install_skill import run_install_skill
from .commands.review import run_review
from .commands.score import run_score
from .commands.status import run_status
from .commands.history import run_history
from .commands.supersede import run_supersede
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
    scan: bool = typer.Option(
        False,
        "--scan",
        help=(
            "Scan the codebase for decisions, landmines, and anti-decisions "
            "and append them as pending_review draft entries to BATON.md. "
            "Works on existing BATON.md without --force."
        ),
    ),
    exhaustive: bool = typer.Option(
        False,
        "--exhaustive",
        help="Include medium- and low-confidence scan entries (default: high only).",
    ),
    skip_pr_history: bool = typer.Option(
        False,
        "--skip-pr-history",
        help="Skip the GitHub PR history scan (no gh CLI calls).",
    ),
    skip_docs: bool = typer.Option(
        False,
        "--skip-docs",
        help="Skip README/ADR documentation scanning.",
    ),
) -> None:
    """Scaffold [bold]BATON.md[/bold], [bold].baton.toml[/bold], and a git pre-commit reminder hook.

    With [bold]--scan[/bold]: scan the codebase and populate draft entries from manifests,
    code comments, docs, and PR history.  No API key required.
    """
    run_init(
        _repo_root(),
        force=force,
        scan=scan,
        exhaustive=exhaustive,
        skip_pr_history=skip_pr_history,
        skip_docs=skip_docs,
    )


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


# ── baton check ───────────────────────────────────────────────────────────────

@app.command()
def check(
    drift: bool = typer.Option(
        False,
        "--drift",
        help="Check whether the codebase still matches BATON.md claims.",
    ),
    since: str | None = typer.Option(None, "--since", help="Override base git ref."),
    staged: bool = typer.Option(False, "--staged", help="Check staged changes only (git diff --cached)."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="[Deprecated] Alias for --format json."),
    fmt: str = typer.Option("human", "--format", help="Output format: human, json, or github."),
    fail_on: str = typer.Option("warn", "--fail-on", help="Exit non-zero threshold: warn or block."),
    acknowledge: str | None = typer.Option(None, "--acknowledge", help="Acknowledge an alert by its id."),
    reason: str | None = typer.Option(None, "--reason", help="Reason for acknowledging (required with --acknowledge)."),
) -> None:
    """Check whether the codebase still matches BATON.md claims (reality drift)."""
    if not drift:
        console.print("[drift] Use --drift flag: baton check --drift", markup=False)
        raise typer.Exit(1)
    from .commands.check import run_check
    code = run_check(
        _repo_root(),
        since=since,
        staged=staged,
        quiet=quiet,
        fmt=fmt,
        fail_on=fail_on,
        acknowledge=acknowledge,
        reason=reason,
    )
    raise typer.Exit(code)


# ── baton supersede ───────────────────────────────────────────────────────────

@app.command()
def supersede(
    old_id: str = typer.Argument(..., help="ID of the entry being superseded (e.g. d001, a002)."),
    with_id: str = typer.Option(..., "--with", help="ID of the new entry that supersedes it."),
    reason: str = typer.Option("", "--reason", help="Why this entry is superseded (required)."),
) -> None:
    """Record that an existing entry has been replaced by a newer one.

    Appends [italic]old_id[/italic] to [italic]with_id[/italic]'s supersedes list in BATON.md.
    The old entry is NEVER modified.
    """
    code = run_supersede(_repo_root(), old_id, with_id, reason)
    raise typer.Exit(code)


# ── baton history ─────────────────────────────────────────────────────────────

@app.command()
def history(
    entry_id: str = typer.Argument(..., help="Entry ID to show history for (e.g. d001, a002, l003)."),
) -> None:
    """Show the full supersession timeline for a BATON.md entry."""
    code = run_history(_repo_root(), entry_id)
    raise typer.Exit(code)


# ── baton review ─────────────────────────────────────────────────────────────

@app.command()
def review() -> None:
    """Interactively review pending scan entries in [bold]BATON.md[/bold].

    Walks through entries added by [bold]baton init --scan[/bold] one at a time,
    sorted by confidence (high → medium → low).

    For each entry:
      [bold][a][/bold]ccept  -- mark as active (included in sync / drift)
      [bold][e][/bold]dit    -- open BATON.md in \\$EDITOR, then advance
      [bold][d][/bold]elete  -- remove the entry from BATON.md
      [bold][s][/bold]kip    -- leave as pending_review for the next run

    You can also approve entries by hand-editing the [bold]status[/bold] field in
    BATON.md from [italic]pending_review[/italic] to [italic]active[/italic].
    """
    code = run_review(_repo_root())
    raise typer.Exit(code)


# ── baton scope ───────────────────────────────────────────────────────────────

@app.command()
def scope(
    task: str | None = typer.Argument(None, help="Task description to scope context for"),
    clear: bool = typer.Option(False, "--clear", help="Clear active scope and restore full context"),
) -> None:
    """Focus context on a task (token-minimised view).

    Writes a task-scoped subset of BATON.md entries to [bold].baton/scope.md[/bold]
    and syncs SCOPED managed blocks to all agent config files.

    Run [bold]baton scope --clear[/bold] to restore full context.
    """
    from .commands.scope import run_scope
    ok = run_scope(_repo_root(), task=task, clear=clear)
    if not ok:
        raise typer.Exit(1)


# ── baton hooks ───────────────────────────────────────────────────────────────

hooks_app = typer.Typer(name="hooks", help="Manage Baton git hooks.", no_args_is_help=True)
app.add_typer(hooks_app, name="hooks")


@hooks_app.command("install")
def hooks_install(
    strict: bool = typer.Option(False, "--strict", help="Also install a blocking pre-commit hook."),
) -> None:
    """Install Baton drift-detection git hooks."""
    from .commands.hooks import run_hooks_install
    run_hooks_install(_repo_root(), strict=strict)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Pyproject.toml entry point: ``baton = "baton.cli:main"``."""
    app()
