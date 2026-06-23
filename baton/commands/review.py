"""
review.py -- ``baton review``: interactive walkthrough of pending scan entries.

Displays each ``status: pending_review`` entry one at a time in descending
confidence order (high → medium → low), offering four actions:

    [a] Accept   -- flip status to "active", save
    [e] Edit     -- open the whole BATON.md in $EDITOR, reparse on close,
                    then mark entry as accepted (editing IS approving)
    [d] Delete   -- remove the entry from the BATON.md list entirely
    [s] Skip     -- leave as pending_review, move to next

Empty queue prints a clear message rather than silently exiting.

Public API:
    run_review(repo_root) -> int  (exit code: 0=ok, 1=error)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..core.document import BatonDocument, BatonDocumentError
from ..core.schema import CONFIDENCE_LEVELS, PENDING_REVIEW, SUPERSEDABLE_TYPES

_console = Console(highlight=False)

# Confidence sort order: high=0, medium=1, low=2, unknown=3
_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}

# All entry types that may carry pending_review status
_ALL_ENTRY_TYPES = list(SUPERSEDABLE_TYPES.keys()) + ["open_questions"]

# Primary text field for each type (used for display)
_PRIMARY_FIELD = {
    "decisions":      "what",
    "anti_decisions": "rejected",
    "landmines":      "actually",
    "open_questions": "question",
}


def run_review(repo_root: Path) -> int:
    """Interactive walkthrough of pending scan entries.

    Args:
        repo_root: Project root (where BATON.md lives).

    Returns:
        0 on success, 1 on error loading BATON.md.
    """
    baton_path = repo_root / "BATON.md"

    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        _console.print(f"[red]Error:[/red] {exc}", markup=True)
        return 1

    # Collect all pending entries with their type key
    pending = _collect_pending(doc.data)

    if not pending:
        _console.print()
        _console.print("[green]Nothing to review.[/green] No pending_review entries in BATON.md.", markup=True)
        _console.print("Run [bold cyan]baton init --scan[/bold cyan] to populate entries from your codebase.", markup=True)
        _console.print()
        return 0

    total = len(pending)
    reviewed = 0

    _console.print()
    _console.print(f"[bold]baton review[/bold] -- {total} pending {'entry' if total == 1 else 'entries'}", markup=True)
    _console.print("Press Ctrl-C at any time to stop (skips remaining entries).\n", markup=False)

    i = 0
    while i < len(pending):
        # Reload doc each iteration (user may have edited the file)
        try:
            doc = BatonDocument.load(baton_path)
        except BatonDocumentError as exc:
            _console.print(f"[red]Error reloading BATON.md:[/red] {exc}", markup=True)
            return 1

        # Re-collect pending entries (user may have accepted some via edit)
        pending = _collect_pending(doc.data)
        if i >= len(pending):
            break

        type_key, entry = pending[i]
        reviewed += 1

        _display_entry(type_key, entry, reviewed, len(pending))

        try:
            action = _prompt_action()
        except (typer.Abort, KeyboardInterrupt):
            _console.print("\nStopped. Remaining entries stay as pending_review.", markup=False)
            return 0

        if action == "a":
            _accept_entry(doc, type_key, entry)
            doc.save()
            _console.print("[green]Accepted.[/green]\n", markup=True)
            # Don't advance i — list shrinks and next entry shifts to same index

        elif action == "e":
            _console.print("Opening BATON.md in your editor...", markup=False)
            click.edit(filename=str(baton_path))
            # After edit, reload and reparse — the user may have accepted, edited,
            # or deleted the entry manually. Advance i conservatively.
            _console.print("[green]Saved.[/green] Re-reading BATON.md...\n", markup=True)
            i += 1  # advance past this entry regardless

        elif action == "d":
            _delete_entry(doc, type_key, entry)
            doc.save()
            _console.print("[yellow]Deleted.[/yellow]\n", markup=True)
            # Don't advance i — list shrinks

        elif action == "s":
            _console.print("Skipped.\n", markup=False)
            i += 1

    # Final tally
    remaining = len(_collect_pending(doc.data if 'doc' in dir() else BatonDocument.load(baton_path).data))
    _console.print(f"[bold]Done.[/bold] {remaining} pending {'entry' if remaining == 1 else 'entries'} remaining.", markup=True)
    if remaining > 0:
        _console.print("Run [bold cyan]baton review[/bold cyan] again to continue, or edit BATON.md directly.", markup=True)
    _console.print()
    return 0


# ── Internal helpers ──────────────────────────────────────────────────────────


def _collect_pending(data: dict) -> list[tuple[str, dict]]:
    """Return all pending_review entries sorted high→low confidence.

    Returns list of (type_key, entry_dict) tuples.
    """
    pending: list[tuple[str, dict, int]] = []
    for type_key in _ALL_ENTRY_TYPES:
        entries = data.get(type_key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("status") == PENDING_REVIEW:
                rank = _CONFIDENCE_RANK.get(str(entry.get("confidence", "")), 3)
                pending.append((type_key, entry, rank))

    pending.sort(key=lambda t: t[2])
    return [(type_key, entry) for type_key, entry, _ in pending]


def _display_entry(type_key: str, entry: dict, current: int, total: int) -> None:
    """Print a rich panel showing the entry to review."""
    confidence = entry.get("confidence", "unknown")
    source = entry.get("source", "unknown")
    entry_id = entry.get("id", "?")
    primary_field = _PRIMARY_FIELD.get(type_key, "text")
    primary_val = str(entry.get(primary_field, ""))

    # Colour confidence
    conf_color = {"high": "green", "medium": "yellow", "low": "red"}.get(confidence, "dim")

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("field", style="dim", width=14)
    table.add_column("value")

    table.add_row("type", type_key.replace("_", " "))
    table.add_row("source", source)
    table.add_row("confidence", f"[{conf_color}]{confidence}[/{conf_color}]")
    table.add_row(primary_field, primary_val)

    # Extra fields worth showing
    if type_key == "decisions":
        why = str(entry.get("why") or "")
        if why:
            table.add_row("why", why)
        ev = entry.get("evidence")
        if isinstance(ev, dict):
            table.add_row("evidence", f'{ev.get("type", "?")}:{ev.get("value", "?")}')

    elif type_key == "anti_decisions":
        why = str(entry.get("why") or "")
        if why:
            table.add_row("why", why)

    elif type_key == "landmines":
        location = str(entry.get("location") or "")
        if location:
            table.add_row("location", location)

    elif type_key == "open_questions":
        context = str(entry.get("context") or "")
        if context:
            table.add_row("context", context)

    _console.print(
        Panel(table, title=f"[{current} of {total} pending]  id: {entry_id}", expand=False),
    )


def _prompt_action() -> str:
    """Prompt the user for an action; return one of 'a','e','d','s'."""
    while True:
        raw = typer.prompt(
            "  [a]ccept  [e]dit  [d]elete  [s]kip",
            default="s",
            prompt_suffix=" > ",
        ).strip().lower()
        if raw in ("a", "e", "d", "s"):
            return raw
        _console.print("  Please enter a, e, d, or s.", markup=False)


def _accept_entry(doc: BatonDocument, type_key: str, entry: dict) -> None:
    """Flip the entry's status from pending_review to active in-place."""
    entries = doc.data.get(type_key)
    if not isinstance(entries, list):
        return
    for e in entries:
        if isinstance(e, dict) and e is entry:
            e["status"] = "active"
            return
    # Fallback: match by id
    entry_id = entry.get("id")
    if entry_id:
        for e in entries:
            if isinstance(e, dict) and e.get("id") == entry_id:
                e["status"] = "active"
                return


def _delete_entry(doc: BatonDocument, type_key: str, entry: dict) -> None:
    """Remove the entry from its list in the BATON.md data dict."""
    entries = doc.data.get(type_key)
    if not isinstance(entries, list):
        return
    entry_id = entry.get("id")
    # Try identity match first, then id match
    for idx, e in enumerate(entries):
        if e is entry or (entry_id and isinstance(e, dict) and e.get("id") == entry_id):
            del entries[idx]
            return
