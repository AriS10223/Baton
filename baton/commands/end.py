"""
end.py -- ``baton end``: summarise the current session into BATON.md.

Pipeline:
  1. Load BATON.md + config.
  2. Resolve git diff (commit-aware, from last session SHA).
  3. Skip if diff is below min_diff_lines and --force is not set.
  4. Build prompt -> LLM call (via injected summarizer) -> parse delta.
  5. Review proposed changes (per-section accept/reject in the terminal).
  6. Merge accepted changes into BATON.md (ruamel round-trip-safe appends).
  7. doc.save() then run_sync() if config.auto_sync is True.

ASCII-only output throughout (Law 6: CP1252-safe console on Windows).
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from ..core.config import BatonConfig
from ..core.document import BatonDocument, BatonDocumentError
from ..core.gitdiff import GitError, count_changed_lines, get_diff, head_sha, resolve_base_ref
from ..core.summarizer import build_prompt, parse_delta
from ..core.summarizer import summarize as _default_summarizer

console = Console()

# Type alias for the injectable summarizer seam.
SummarizerFn = Callable[[str, str, BatonConfig], str]


# ── Public entry point ────────────────────────────────────────────────────────

def run_end(
    repo_root: Path,
    *,
    force: bool = False,
    since: str | None = None,
    tool: str = "",
    auto_accept: bool = False,
    summarizer: SummarizerFn | None = None,
) -> bool:
    """Run baton end.

    Args:
        repo_root:   Project root (where BATON.md lives).
        force:       Bypass the min_diff_lines threshold.
        since:       Override base ref (git SHA or branch) for the diff.
        tool:        Name of the AI tool used this session (e.g. 'claude-code').
        auto_accept: Skip interactive prompts; accept all sections (for tests).
        summarizer:  Injectable LLM seam.  Defaults to the real provider call.

    Returns:
        True on success, False if an error occurred.
    """
    if summarizer is None:
        summarizer = _default_summarizer

    # ── 1. Load BATON.md ──────────────────────────────────────────
    baton_path = repo_root / "BATON.md"
    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return False

    config = BatonConfig.load(repo_root)

    # ── 2. Resolve diff ───────────────────────────────────────────
    try:
        sha = head_sha(repo_root)
        base_ref = resolve_base_ref(doc.data, since)
        diff_text = get_diff(repo_root, base_ref)
    except GitError as exc:
        console.print(f"[red]Git error:[/red] {exc}")
        return False

    changed = count_changed_lines(diff_text)

    # ── 3. Threshold check ────────────────────────────────────────
    if changed < config.min_diff_lines and not force:
        console.print(
            f"[yellow]Skipping:[/yellow] only {changed} changed line(s) "
            f"(threshold: {config.min_diff_lines}). "
            "Use [bold]--force[/bold] to override."
        )
        return True

    console.print()
    console.print(Rule("baton end"))
    if base_ref:
        console.print(f"  Diffing from: [dim]{base_ref}[/dim]")
    console.print(f"  Changed lines: [cyan]{changed}[/cyan]")
    console.print()

    # ── 4. LLM call ───────────────────────────────────────────────
    console.print("[dim]Calling LLM to summarise session...[/dim]")
    try:
        system, user = build_prompt(diff_text, doc.data)
        raw = summarizer(system, user, config)
        delta = parse_delta(raw)
    except ValueError as exc:
        console.print(f"[red]Parse error:[/red] {exc}")
        return False
    except RuntimeError as exc:
        console.print(f"[red]LLM error:[/red] {exc}")
        return False

    # ── 5. Review ─────────────────────────────────────────────────
    accepted = _review(delta, auto_accept)
    if accepted is None:
        console.print("[yellow]Cancelled. BATON.md unchanged.[/yellow]")
        return True

    # ── 6. Merge ──────────────────────────────────────────────────
    today = datetime.date.today().isoformat()
    _merge_delta(doc.data, accepted, sha, tool, today)

    # Update metadata fields.
    doc.data["last_updated"] = today
    if tool:
        doc.data["last_session_tool"] = tool

    doc.save()
    console.print("[green]BATON.md updated.[/green]")

    # ── 7. Auto-sync ──────────────────────────────────────────────
    if config.auto_sync:
        from ..commands.sync import run_sync
        run_sync(repo_root)

    return True


# ── Review UI ─────────────────────────────────────────────────────────────────

def _review(delta: dict, auto_accept: bool) -> dict | None:
    """Display the proposed delta and return the accepted subset.

    Returns None if the user cancels entirely.
    When auto_accept is True, skips prompts and accepts everything.

    ASCII-only output (Law 6).
    """
    console.print(Rule("Proposed session update"))

    # -- Session summary
    session = delta["session"]
    console.print(f"\n[bold]Session summary:[/bold]  {session['summary']}")
    if session["highlights"]:
        console.print("[bold]Highlights:[/bold]")
        for h in session["highlights"]:
            console.print(f"  * {h}")

    # -- Sprint done
    sprint_done = delta["sprint_done"]
    console.print()
    if sprint_done:
        console.print("[bold]Sprint items proposed as DONE:[/bold]")
        for item in sprint_done:
            console.print(f"  [green]+[/green] {item}")
    else:
        console.print("[dim]No sprint items proposed as done.[/dim]")

    # -- Sprint next
    sprint_next = delta["sprint_next"]
    if sprint_next:
        console.print()
        console.print("[bold]Sprint items proposed as NEXT:[/bold]")
        for item in sprint_next:
            pri = item.get("priority", "medium")
            console.print(f"  [cyan]+[/cyan] [{pri}] {item['feature']}")

    console.print()

    if auto_accept:
        console.print("[dim]Auto-accepting all sections (--yes).[/dim]")
        return delta

    # Per-section accept/reject via typer prompts.
    import typer

    try:
        keep_session = typer.confirm("Accept session log entry?", default=True)
        keep_done = False
        if sprint_done:
            keep_done = typer.confirm("Accept sprint-done updates?", default=True)
        keep_next = False
        if sprint_next:
            keep_next = typer.confirm("Accept sprint-next additions?", default=True)
        proceed = typer.confirm("Write to BATON.md?", default=True)
    except typer.Abort:
        return None

    if not proceed:
        return None

    return {
        "session": delta["session"] if keep_session else None,
        "sprint_done": delta["sprint_done"] if keep_done else [],
        "sprint_next": delta["sprint_next"] if keep_next else [],
    }


# ── Merge ─────────────────────────────────────────────────────────────────────

def _merge_delta(
    data: dict,
    accepted: dict,
    sha: str | None,
    tool: str,
    today: str,
) -> None:
    """Apply the accepted delta to the ruamel CommentedMap *data* in-place.

    Append-only: never modifies existing entries; only appends new ones.
    Plain Python dicts/lists are safe to append into CommentedSeq --
    ruamel serialises them correctly on the next save() call.
    """
    # ── Sprint done ───────────────────────────────────────────────
    new_done = accepted.get("sprint_done") or []
    if new_done:
        sprint = data.get("current_sprint")
        if sprint is not None:
            done_list = sprint.get("done")
            if done_list is not None:
                existing_features = {
                    (item.get("feature") or str(item))
                    if isinstance(item, dict)
                    else str(item)
                    for item in done_list
                }
                for feature_str in new_done:
                    if feature_str not in existing_features:
                        done_list.append({"feature": feature_str, "confidence": "stable"})
                        existing_features.add(feature_str)

    # ── Sprint next ───────────────────────────────────────────────
    new_next = accepted.get("sprint_next") or []
    if new_next:
        sprint = data.get("current_sprint")
        if sprint is not None:
            next_list = sprint.get("next")
            if next_list is not None:
                existing_features = {
                    (item.get("feature") or str(item))
                    if isinstance(item, dict)
                    else str(item)
                    for item in next_list
                }
                for item in new_next:
                    feature = item.get("feature", "")
                    if feature not in existing_features:
                        next_list.append({
                            "feature": feature,
                            "priority": item.get("priority", "medium"),
                        })
                        existing_features.add(feature)

    # ── Session log ───────────────────────────────────────────────
    session_payload = accepted.get("session")
    if session_payload:
        sessions_list = data.get("sessions")
        if sessions_list is not None:
            entry: dict = {
                "date": today,
                "tool": tool or "",
                "summary": session_payload.get("summary") or "",
                "highlights": list(session_payload.get("highlights") or []),
                # commit SHA lets the next baton end diff from this point.
                "commit": sha or "",
            }
            sessions_list.append(entry)
