"""run_supersede() -- link an old BATON.md entry into a newer one's supersedes list."""
from __future__ import annotations

from pathlib import Path

from rich.console import Console

from ..core.document import BatonDocument, BatonDocumentError
from ..core.supersede import (
    SUPERSEDED_END,
    SUPERSEDED_START,
    derive_status,
    find_entry,
    render_superseded_appendix,
    resolve_head,
    superseded_by_map,
    validate_link,
)

console = Console()


def run_supersede(repo_root: Path, old_id: str, with_id: str, reason: str) -> int:
    """Link an old BATON.md entry into a newer entry's supersedes list.

    Returns 0 on success, non-zero on any error.
    """
    # Step 1: Load BATON.md
    baton_path = repo_root / "BATON.md"
    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        console.print(f"[supersede] Error: {exc}", markup=False)
        return 1
    data = doc.data

    # Step 2: Find both entries
    old_result = find_entry(data, old_id)
    if old_result is None:
        console.print(f"[supersede] Error: Entry {old_id} not found in BATON.md.", markup=False)
        return 1
    old_type, old_entry = old_result

    new_result = find_entry(data, with_id)
    if new_result is None:
        console.print(f"[supersede] Error: Entry {with_id} not found in BATON.md.", markup=False)
        return 1
    new_type, new_entry = new_result

    # Step 3: Same-type enforcement
    if old_type != new_type:
        console.print(
            f"[supersede] Error: Cross-type supersession not allowed.", markup=False
        )
        console.print(
            f"             {old_id} is in {old_type}, {with_id} is in {new_type}.", markup=False
        )
        console.print(
            "             Both entries must be in the same list (decisions, anti_decisions, or landmines).",
            markup=False,
        )
        return 1

    # Step 4: Already-superseded check
    # Allow idempotent re-link: if old_id is already claimed by the same with_id, fall through.
    if derive_status(data, old_id) == "superseded":
        _sb = superseded_by_map(data)
        if _sb.get(old_id) != with_id:
            head = resolve_head(data, old_id)
            console.print(f"[supersede] Error: {old_id} is already superseded.", markup=False)
            console.print(
                f"             Its chain head is {head}. Use {head} as the old_id, or link to a different new entry.",
                markup=False,
            )
            return 1

    # Step 5: Reason validation
    if not reason.strip():
        console.print(
            "[supersede] Error: --reason is required when linking a supersession.", markup=False
        )
        return 1

    existing_reason = str(new_entry.get("reason") or "").strip()
    if existing_reason and existing_reason != reason.strip():
        console.print(
            f"[supersede] Error: {with_id} already has reason: \"{existing_reason}\"",
            markup=False,
        )
        console.print(
            "[supersede]   Provide the same reason or leave --reason empty to reuse it.",
            markup=False,
        )
        return 1

    # Step 6: validate_link
    errors = validate_link(data, old_id, with_id)
    if errors:
        for e in errors:
            console.print(f"[supersede] Error: {e}", markup=False)
        return 1

    # Step 7: Write the link (append-only, new entry ONLY)
    try:
        supersedes_list = new_entry.get("supersedes")
        if supersedes_list is None:
            new_entry["supersedes"] = [old_id]
        else:
            if old_id not in list(supersedes_list):
                supersedes_list.append(old_id)

        new_entry["reason"] = reason.strip() or existing_reason

        doc.save()

        doc.upsert_markdown_region(
            SUPERSEDED_START, SUPERSEDED_END, render_superseded_appendix(data)
        )
    except OSError as exc:
        console.print(f"[supersede] Error: {exc}", markup=False)
        return 1

    # Step 8: Confirmation
    applied_reason = reason.strip() or existing_reason
    console.print(f"[supersede] Done: {old_id} -> {with_id}", markup=False)
    console.print(f"             \"{applied_reason}\" appended to BATON.md.", markup=False)
    return 0
