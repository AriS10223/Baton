"""
trim.py -- ``baton trim``: prune stale entries from BATON.md.

Modes:
  default (interactive) -- walk each stale entry: [d]elete / [s]kip / [q]uit
  --dry-run             -- print what would change, touch nothing
  --auto                -- show summary list, single Y/n bulk delete
  --budget N            -- delete most-stale entries until under N tokens
  --compress            -- collapse deep supersession chains only

Archive strategy: git-only.
  trim edits BATON.md in place and regenerates agent configs via run_sync.
  It does NOT stage or commit; the user gets a reminder to commit.
  History is preserved in git log.

Hard rules:
  - Never delete an entry without displaying it first.
  - Never delete a superseded ancestor via non-compress modes (refer to --compress).
  - After deletions: doc.save() FIRST, then regen appendix if needed, then run_sync.
  - Check working tree is clean before proceeding (unless --force).

Public API:
    run_trim(repo_root, *, dry_run, auto, budget, compress, force, model) -> int
"""
from __future__ import annotations

import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..core.config import BatonConfig
from ..core.document import BatonDocument, BatonDocumentError
from ..core.gitdiff import GitError, working_tree_dirty
from ..core.schema import (
    HISTORY_COMPRESSED_FIELD,
    ORIGINAL_DATE_FIELD,
    SUPERSEDABLE_TYPES,
    active_entries,
)
from ..core.staleness import (
    PrunableEntry,
    chain_backward,
    chain_depth,
    chain_heads,
    collect_prunable,
    parse_date,
)
from ..core.supersede import (
    SUPERSEDED_END,
    SUPERSEDED_START,
    derive_status,
    entries_for,
    render_superseded_appendix,
)
from ..core.tokens import count_tokens

_console = Console(highlight=False)

# Primary text field for display (mirrors review.py)
_PRIMARY_FIELD = {
    "decisions":      "what",
    "anti_decisions": "rejected",
    "landmines":      "actually",
    "open_questions": "question",
}


# ── Public entry point ────────────────────────────────────────────────────────

def run_trim(
    repo_root: Path,
    *,
    dry_run: bool = False,
    auto: bool = False,
    budget: int | None = None,
    compress: bool = False,
    force: bool = False,
    model: str | None = None,
) -> int:
    """Run baton trim.

    Returns 0 on success, 1 on error or refusal.
    """
    baton_path = repo_root / "BATON.md"

    # 1. Load BATON.md
    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        _console.print(f"[trim] Error loading BATON.md: {exc}", markup=False)
        return 1

    # 2. Clean-tree gate (non-dry-run modes only)
    if not dry_run and not force:
        try:
            if working_tree_dirty(repo_root, "BATON.md"):
                _console.print(
                    "[trim] Stash or commit your current BATON.md changes "
                    "before running baton trim.",
                    markup=False,
                )
                _console.print(
                    "       Use --force to skip this check.",
                    markup=False,
                )
                return 1
        except GitError:
            # Not a git repo or git unavailable -- note and proceed
            _console.print(
                "[trim] Warning: could not check git status (not a git repo?). "
                "Proceeding -- remember to commit any changes manually.",
                markup=False,
            )

    config = BatonConfig.load(repo_root)
    today = datetime.date.today()

    # 3. Dispatch to mode
    if compress:
        return _run_compress(doc, baton_path, repo_root, config, dry_run=dry_run, model=model)
    elif auto:
        return _run_auto(doc, baton_path, repo_root, config, today, dry_run=dry_run, model=model)
    elif budget is not None:
        return _run_budget(doc, baton_path, repo_root, config, today, budget=budget, dry_run=dry_run, model=model)
    else:
        return _run_interactive(doc, baton_path, repo_root, config, today, dry_run=dry_run, model=model)


# ── Mode implementations ──────────────────────────────────────────────────────

def _run_interactive(
    doc: BatonDocument,
    baton_path: Path,
    repo_root: Path,
    config: BatonConfig,
    today: datetime.date,
    *,
    dry_run: bool = False,
    model: str | None = None,
) -> int:
    """Interactive mode: walk stale entries one at a time."""
    prunable = collect_prunable(doc.data, config, today, model=model)

    if not prunable:
        _console.print("[trim] Nothing to trim.", markup=False)
        return 0

    total = len(prunable)
    _console.print(
        f"[trim] {total} stale {'entry' if total == 1 else 'entries'} found.",
        markup=False,
    )
    if dry_run:
        _console.print("[trim] --dry-run: no changes will be made.", markup=False)

    _console.print("Press Ctrl-C at any time to stop.\n", markup=False)

    deleted_count = 0
    i = 0
    while i < len(prunable):
        # Reload doc and re-collect each iteration (like review.py)
        try:
            doc = BatonDocument.load(baton_path)
        except BatonDocumentError as exc:
            _console.print(f"[trim] Error reloading BATON.md: {exc}", markup=False)
            return 1

        prunable = collect_prunable(doc.data, config, today, model=model)
        if i >= len(prunable):
            break

        pe = prunable[i]

        # Refuse superseded ancestors (only --compress removes those)
        eid = pe.entry.get("id", "")
        if eid and derive_status(doc.data, eid) == "superseded":
            _console.print(
                f"[trim] Skipping {eid}: superseded ancestors can only be "
                "removed with --compress.",
                markup=False,
            )
            i += 1
            continue

        _display_prunable(pe, i + 1, len(prunable))

        if dry_run:
            _console.print("  [dry-run] would delete\n", markup=False)
            i += 1
            continue

        try:
            action = _prompt_trim_action()
        except (typer.Abort, KeyboardInterrupt):
            _console.print("\n[trim] Stopped.", markup=False)
            break

        if action == "d":
            _delete_entry_from_doc(doc, pe.type_key, pe.entry)
            doc.save()
            deleted_count += 1
            _console.print("[trim] Deleted.\n", markup=False)
            # Don't advance i -- list shrinks, next entry shifts to same index
        elif action == "q":
            _console.print("[trim] Quit.\n", markup=False)
            break
        else:  # "s"
            _console.print("[trim] Skipped.\n", markup=False)
            i += 1

    if deleted_count > 0 and not dry_run:
        _post_trim_sync(repo_root, doc)

    _print_summary(deleted_count, dry_run)
    return 0


def _run_auto(
    doc: BatonDocument,
    baton_path: Path,
    repo_root: Path,
    config: BatonConfig,
    today: datetime.date,
    *,
    dry_run: bool = False,
    model: str | None = None,
) -> int:
    """Auto mode: show summary list + single Y/n."""
    prunable = collect_prunable(doc.data, config, today, model=model)

    # Filter out superseded ancestors (--compress only)
    prunable = [
        pe for pe in prunable
        if not (pe.entry.get("id") and derive_status(doc.data, pe.entry.get("id", "")) == "superseded")
    ]

    if not prunable:
        _console.print("[trim] Nothing to trim.", markup=False)
        return 0

    # Show summary list
    _console.print(
        f"[trim] --auto: {len(prunable)} stale {'entry' if len(prunable) == 1 else 'entries'} "
        "to delete:",
        markup=False,
    )
    total_cost = 0
    for pe in prunable:
        eid = pe.entry.get("id", "(no id)")
        primary_field = _PRIMARY_FIELD.get(pe.type_key, "text")
        text = str(pe.entry.get(primary_field, ""))[:60]
        _console.print(
            f"  [{pe.type_key}] {eid}  {text}  ({pe.reason}, ~{pe.token_cost} tokens)",
            markup=False,
        )
        total_cost += pe.token_cost

    _console.print(
        f"\n  Total token savings: ~{total_cost} tokens",
        markup=False,
    )

    if dry_run:
        _console.print("[trim] --dry-run: no changes made.", markup=False)
        return 0

    # Single confirmation
    try:
        confirmed = typer.confirm("\nDelete all of the above?", default=False)
    except (typer.Abort, KeyboardInterrupt):
        _console.print("\n[trim] Aborted.", markup=False)
        return 0

    if not confirmed:
        _console.print("[trim] Aborted. No changes made.", markup=False)
        return 0

    # Reload + delete all
    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        _console.print(f"[trim] Error reloading BATON.md: {exc}", markup=False)
        return 1

    deleted_count = 0
    for pe in prunable:
        _delete_entry_from_doc(doc, pe.type_key, pe.entry)
        deleted_count += 1

    doc.save()
    _post_trim_sync(repo_root, doc)
    _print_summary(deleted_count, dry_run)
    return 0


def _run_budget(
    doc: BatonDocument,
    baton_path: Path,
    repo_root: Path,
    config: BatonConfig,
    today: datetime.date,
    *,
    budget: int,
    dry_run: bool = False,
    model: str | None = None,
) -> int:
    """Budget mode: delete stale entries until BATON.md is under *budget* tokens."""
    raw_text = baton_path.read_text(encoding="utf-8")
    total, _ = count_tokens(raw_text, model=model)

    if total <= budget:
        _console.print(
            f"[trim] BATON.md is already under {budget} tokens ({total} tokens). "
            "Nothing to trim.",
            markup=False,
        )
        return 0

    prunable = collect_prunable(doc.data, config, today, model=model)
    # Filter out superseded ancestors
    prunable = [
        pe for pe in prunable
        if not (pe.entry.get("id") and derive_status(doc.data, pe.entry.get("id", "")) == "superseded")
    ]

    if not prunable:
        _console.print(
            f"[trim] No stale entries found. Cannot reduce below {budget} tokens "
            f"(currently {total} tokens).",
            markup=False,
        )
        return 1

    # Select entries in priority order until budget is projected to be reached
    selected: list[PrunableEntry] = []
    projected = total
    for pe in prunable:
        if projected <= budget:
            break
        selected.append(pe)
        projected -= pe.token_cost

    if not selected:
        _console.print(
            f"[trim] Budget already met ({total} <= {budget} tokens).",
            markup=False,
        )
        return 0

    # Check if target is reachable
    best_possible = total - sum(pe.token_cost for pe in prunable)
    if best_possible > budget:
        _console.print(
            f"[trim] Cannot reach {budget} tokens by pruning stale entries alone "
            f"(best ~{best_possible} tokens). "
            "Refusing to delete active entries. "
            "Consider 'baton trim --compress' or manual editing.",
            markup=False,
        )
        return 1

    # Show selected entries
    _console.print(
        f"[trim] --budget {budget}: selecting {len(selected)} stale "
        f"{'entry' if len(selected) == 1 else 'entries'} to delete:",
        markup=False,
    )
    for pe in selected:
        eid = pe.entry.get("id", "(no id)")
        primary_field = _PRIMARY_FIELD.get(pe.type_key, "text")
        text = str(pe.entry.get(primary_field, ""))[:60]
        _console.print(
            f"  [{pe.type_key}] {eid}  {text}  ({pe.reason}, ~{pe.token_cost} tokens)",
            markup=False,
        )
        _display_prunable(pe, 0, 0)

    _console.print(
        f"  Projected total after trim: ~{projected} tokens (budget: {budget})",
        markup=False,
    )

    if dry_run:
        _console.print("[trim] --dry-run: no changes made.", markup=False)
        return 0

    # Reload + delete
    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        _console.print(f"[trim] Error reloading BATON.md: {exc}", markup=False)
        return 1

    deleted_count = 0
    for pe in selected:
        _delete_entry_from_doc(doc, pe.type_key, pe.entry)
        deleted_count += 1

    doc.save()

    # Re-measure after actual save
    new_raw = baton_path.read_text(encoding="utf-8")
    new_total, _ = count_tokens(new_raw, model=model)

    _post_trim_sync(repo_root, doc)
    _console.print(
        f"[trim] Deleted {deleted_count} {'entry' if deleted_count == 1 else 'entries'}. "
        f"New total: ~{new_total} tokens.",
        markup=False,
    )
    _print_commit_reminder()
    return 0


def _run_compress(
    doc: BatonDocument,
    baton_path: Path,
    repo_root: Path,
    config: BatonConfig,
    *,
    dry_run: bool = False,
    model: str | None = None,
) -> int:
    """Compress mode: collapse supersession chains with depth >= compress_min_depth."""
    min_depth = config.compress_min_depth
    heads = chain_heads(doc.data)

    compressible = [h for h in heads if chain_depth(doc.data, h) >= min_depth]

    if not compressible:
        _console.print(
            f"[trim] No supersession chains with depth >= {min_depth} found.",
            markup=False,
        )
        return 0

    _console.print(
        f"[trim] --compress: {len(compressible)} chain(s) with depth >= {min_depth}:",
        markup=False,
    )

    # Describe what will happen
    chain_info: list[dict] = []
    for head_id in compressible:
        branches = chain_backward(doc.data, head_id)
        # Collect unique ancestor entries
        ancestors: list[dict] = []
        seen_ids: set[str] = set()
        for branch in branches:
            for entry in branch:
                eid = entry.get("id") if isinstance(entry, dict) else None
                if eid and eid not in seen_ids:
                    seen_ids.add(eid)
                    ancestors.append(entry)

        # Find oldest date across dated ancestors
        result = doc.data  # use current doc.data
        from ..core.schema import SUPERSEDABLE_TYPES as _ST
        head_type = None
        for tk in _ST:
            for e in entries_for(result, tk):
                if isinstance(e, dict) and e.get("id") == head_id:
                    head_type = tk
                    break
            if head_type:
                break

        date_field = _ST.get(head_type or "", {}).get("date") if head_type else None
        oldest_date = None
        if date_field:
            dates = [
                parse_date(a.get(date_field))
                for a in ancestors
                if isinstance(a, dict) and parse_date(a.get(date_field))
            ]
            if dates:
                oldest_date = min(dates)

        ancestor_ids = [a.get("id", "?") for a in ancestors]
        depth = chain_depth(doc.data, head_id)
        _console.print(
            f"  {head_id} (depth={depth}): remove ancestors [{', '.join(ancestor_ids)}], "
            f"set history_compressed=true"
            + (f", original_date={oldest_date.isoformat()}" if oldest_date else ""),
            markup=False,
        )
        chain_info.append({
            "head_id": head_id,
            "head_type": head_type,
            "ancestors": ancestors,
            "oldest_date": oldest_date,
            "date_field": date_field,
        })

    if dry_run:
        _console.print("[trim] --dry-run: no changes made.", markup=False)
        return 0

    # Confirm
    try:
        confirmed = typer.confirm(
            f"\nCompress {len(compressible)} chain(s)? (Ancestors will be deleted)",
            default=False,
        )
    except (typer.Abort, KeyboardInterrupt):
        _console.print("\n[trim] Aborted.", markup=False)
        return 0

    if not confirmed:
        _console.print("[trim] Aborted. No changes made.", markup=False)
        return 0

    # Reload
    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        _console.print(f"[trim] Error reloading BATON.md: {exc}", markup=False)
        return 1

    compressed_count = 0
    for info in chain_info:
        head_id    = info["head_id"]
        head_type  = info["head_type"]
        ancestors  = info["ancestors"]
        oldest_date = info["oldest_date"]

        if head_type is None:
            continue

        # Delete ancestor entries
        for anc in ancestors:
            _delete_entry_from_doc(doc, head_type, anc)

        # Update head entry in place
        head_entries = doc.data.get(head_type)
        if isinstance(head_entries, list):
            for e in head_entries:
                if isinstance(e, dict) and e.get("id") == head_id:
                    # Remove supersedes list
                    if "supersedes" in e:
                        del e["supersedes"]
                    if "reason" in e and not e.get("reason"):
                        del e["reason"]
                    # Set compression fields
                    e[HISTORY_COMPRESSED_FIELD] = True
                    if oldest_date:
                        e[ORIGINAL_DATE_FIELD] = oldest_date.isoformat()
                    break

        compressed_count += 1

    # Save FIRST
    doc.save()

    # Regenerate superseded appendix (after compression, affected chains have no bullets)
    doc2 = BatonDocument.load(baton_path)
    appendix_inner = render_superseded_appendix(doc2.data)
    doc2.upsert_markdown_region(SUPERSEDED_START, SUPERSEDED_END, appendix_inner)

    _post_trim_sync(repo_root, doc2)
    _console.print(
        f"[trim] Compressed {compressed_count} supersession "
        f"{'chain' if compressed_count == 1 else 'chains'}.",
        markup=False,
    )
    _print_commit_reminder()
    return 0


# ── Display helpers ───────────────────────────────────────────────────────────

def _display_prunable(pe: PrunableEntry, current: int, total: int) -> None:
    """Print a Rich panel showing the stale entry."""
    entry = pe.entry
    eid = entry.get("id", "(no id)")
    primary_field = _PRIMARY_FIELD.get(pe.type_key, "text")
    primary_val = str(entry.get(primary_field, ""))

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("field", style="dim", width=14)
    table.add_column("value")

    table.add_row("type", pe.type_key.replace("_", " "))
    table.add_row("reason", pe.reason)
    table.add_row(primary_field, primary_val)

    if pe.type_key == "decisions":
        why = str(entry.get("why") or "")
        if why:
            table.add_row("why", why)
        made = str(entry.get("made") or "")
        if made:
            table.add_row("made", made)

    elif pe.type_key == "anti_decisions":
        why = str(entry.get("why") or "")
        if why:
            table.add_row("why", why)

    elif pe.type_key == "landmines":
        location = str(entry.get("location") or "")
        if location:
            table.add_row("location", location)

    elif pe.type_key == "open_questions":
        raised = str(entry.get("raised") or "")
        if raised:
            table.add_row("raised", raised)
        status = str(entry.get("status") or "")
        if status:
            table.add_row("status", status)

    title_str = f"id: {eid}"
    if current and total:
        title_str = f"[{current} of {total}]  {title_str}"
    if pe.token_cost:
        title_str += f"  (~{pe.token_cost} tokens)"

    _console.print(Panel(table, title=title_str, expand=False))


def _prompt_trim_action() -> str:
    """Prompt for [d]elete / [s]kip / [q]uit. Returns one of 'd', 's', 'q'."""
    while True:
        raw = typer.prompt(
            "  [d]elete  [s]kip  [q]uit",
            default="s",
            prompt_suffix=" > ",
        ).strip().lower()
        if raw in ("d", "s", "q"):
            return raw
        _console.print("  Please enter d, s, or q.", markup=False)


# ── Delete helper ─────────────────────────────────────────────────────────────

def _delete_entry_from_doc(
    doc: BatonDocument,
    type_key: str,
    entry: dict,
) -> bool:
    """Remove *entry* from the live doc. Returns True if found and deleted.

    Uses identity match first (live ref), then id match as fallback.
    Mirrors review.py:_delete_entry exactly.
    """
    entries = doc.data.get(type_key)
    if not isinstance(entries, list):
        return False
    entry_id = entry.get("id")
    for idx, e in enumerate(entries):
        if e is entry or (entry_id and isinstance(e, dict) and e.get("id") == entry_id):
            del entries[idx]
            return True
    return False


# ── Post-trim pipeline ────────────────────────────────────────────────────────

def _post_trim_sync(repo_root: Path, doc: BatonDocument) -> None:
    """Regenerate per-agent config files after BATON.md was modified.

    doc.save() must have been called before this function.
    """
    from ..commands.sync import run_sync
    run_sync(repo_root, quiet=True)


def _print_summary(deleted_count: int, dry_run: bool) -> None:
    if dry_run:
        return
    if deleted_count:
        _console.print(
            f"[trim] Deleted {deleted_count} {'entry' if deleted_count == 1 else 'entries'}.",
            markup=False,
        )
        _print_commit_reminder()
    else:
        _console.print("[trim] No entries deleted.", markup=False)


def _print_commit_reminder() -> None:
    _console.print(
        "[trim] Remember to commit the changes: git add BATON.md && git commit",
        markup=False,
    )
