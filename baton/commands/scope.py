"""
scope.py -- ``baton scope``: focus context on a specific task.

Normal path (task provided):
  1. Load BATON.md (active_entries only -- never pending_review).
  2. Call build_scope(task, data) -> ScopeResult (keyword + path-token matching).
  3. Save .baton/scope.json state (task, keywords, entry_ids, generated_at).
  4. Write .baton/scope.md (committable rendered artifact).
  5. Update .gitignore so scope.md is NOT ignored.
  6. Call run_sync(quiet=True) -- sync now writes SCOPED blocks.
  7. Print summary (ASCII-only, CP1252-safe).

--clear path:
  1. If no scope active, no-op.
  2. clear_scope(), run_sync(quiet=True), print confirmation.
"""
from __future__ import annotations

import datetime
from pathlib import Path

from rich.console import Console

from ..core.document import BatonDocument, BatonDocumentError
from ..core.gitignore import ensure_scope_committable
from ..core.schema import active_entries
from ..core.scope_io import clear_scope, load_scope, save_scope, scope_active
from ..core.scope_match import build_scope, apply_scope
from ..core.scope_render import render_scope_md

console = Console()


def _render_data(data: dict) -> dict:
    """Return a shallow copy of data with pending_review entries removed.

    Mirrors sync.py._render_data exactly so the snapshot scope.py builds
    matches what run_sync later filters against.
    """
    filtered = dict(data)
    for key in ("decisions", "anti_decisions", "landmines", "open_questions"):
        raw = data.get(key)
        if isinstance(raw, list):
            filtered[key] = active_entries(raw)
    return filtered


def run_scope(
    repo_root: Path,
    task: str | None = None,
    clear: bool = False,
) -> bool:
    """Run baton scope.

    Args:
        repo_root: Project root (where BATON.md lives).
        task:      Task description to scope context for.
        clear:     If True, clear the active scope and restore full context.

    Returns:
        True on success or clean no-op; False on error.
    """
    # ── --clear path ──────────────────────────────────────────────────────────
    if clear:
        if not scope_active(repo_root):
            console.print("No active scope.", markup=False)
            return True
        clear_scope(repo_root)
        from ..commands.sync import run_sync
        run_sync(repo_root, quiet=True)
        console.print("Scope cleared. Full context restored.", markup=False)
        return True

    # ── Normal path: task is required ─────────────────────────────────────────
    if not task:
        console.print(
            "Error: a task description is required. "
            "Usage: baton scope \"<task>\" or baton scope --clear",
            markup=False,
        )
        return False

    # ── 1. Load BATON.md ──────────────────────────────────────────────────────
    baton_path = repo_root / "BATON.md"
    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        console.print(f"Error loading BATON.md: {exc}", markup=False)
        return False

    # ── 2. Filter to active entries only (never pending_review) ───────────────
    filtered_data = _render_data(doc.data)

    # ── 3. Build scope (keyword + path-token matching) ────────────────────────
    result = build_scope(task, filtered_data)

    # ── 4. Save .baton/scope.json ─────────────────────────────────────────────
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    scope_state = {
        "task": task,
        "keywords": result.keywords,
        "entry_ids": result.entry_ids,
        "generated_at": now_iso,
    }
    save_scope(repo_root, scope_state)

    # ── 5. Write .baton/scope.md ──────────────────────────────────────────────
    scope_md_text = render_scope_md(result, filtered_data)
    scope_md_path = repo_root / ".baton" / "scope.md"
    scope_md_path.write_text(scope_md_text, encoding="utf-8")

    # ── 6. Update .gitignore so scope.md is not ignored ───────────────────────
    ensure_scope_committable(repo_root)

    # ── 7. Run sync (now writes SCOPED blocks) ────────────────────────────────
    from ..commands.sync import run_sync
    run_sync(repo_root, quiet=True)

    # ── 8. Print summary (ASCII-only, CP1252-safe) ────────────────────────────
    n_matched = len(result.entry_ids)
    console.print(f"Scope set: {task}", markup=False)
    console.print(f"  {n_matched} entries matched.", markup=False)
    if result.under_threshold:
        console.print(
            "Tip: fewer than 3 entries matched. Try "
            "`baton scope --clear && baton scope \"<broader task>\"` "
            "or use the baton-end skill for semantic matching.",
            markup=False,
        )

    return True
