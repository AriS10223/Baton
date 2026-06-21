"""run_history() -- display the full supersession timeline for a BATON.md entry."""
from __future__ import annotations

from pathlib import Path

from rich.console import Console

from ..core.document import BatonDocument, BatonDocumentError
from ..core.schema import SUPERSEDABLE_TYPES
from ..core.supersede import (
    chain_backward,
    derive_status,
    find_entry,
    resolve_head,
    superseded_by_map,
)

console = Console()


def _format_entry_line(e: dict, type_key: str, marker: str) -> str:
    """Return a single display line for an entry.

    Format:  {marker} {id}  {text_value}  {date_field: date_value}
    Marker is one of: '*' (queried entry), ' ' (predecessor/successor),
    '^' (chain head when not the queried entry).
    """
    type_meta = SUPERSEDABLE_TYPES[type_key]
    text_field = type_meta["text"]
    date_field = type_meta["date"]

    entry_id = e.get("id", "?")
    text_val = e.get(text_field, "")
    date_part = ""
    if date_field:
        date_val = e.get(date_field, "")
        if date_val:
            date_part = f"  {date_field}: {date_val}"

    return f"  {marker} {entry_id}  {text_val}{date_part}"


def run_history(repo_root: Path, entry_id: str) -> int:
    """Display the full supersession timeline for a BATON.md entry.

    Returns 0 on success, 1 on error.
    """
    # Step 1: Load BATON.md
    baton_path = repo_root / "BATON.md"
    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        console.print(f"[history] Error: {exc}", markup=False)
        return 1
    data = doc.data

    # Step 2: Find the entry
    result = find_entry(data, entry_id)
    if result is None:
        console.print(
            f"[history] Error: Entry {entry_id} not found in BATON.md.", markup=False
        )
        return 1
    type_key, entry = result

    # Step 3: Get chain_backward result (predecessors of queried entry)
    branches = chain_backward(data, entry_id)

    # Step 4: Determine if this entry is the chain head
    status = derive_status(data, entry_id)
    head_id = resolve_head(data, entry_id)
    is_head = (head_id == entry_id)

    # Step 5: Display header
    console.print(f"[history] {entry_id} ({type_key})", markup=False)
    console.print("", markup=False)

    # Step 6: Display the chain

    if not branches:
        # No predecessors -- single entry or just show queried entry
        head_suffix = "   [HEAD]" if is_head else ""
        console.print(
            _format_entry_line(entry, type_key, "*") + head_suffix, markup=False
        )
    elif len(branches) == 1:
        # Linear chain: print oldest-first, then the queried entry
        for pred_entry in branches[0]:
            console.print(_format_entry_line(pred_entry, type_key, " "), markup=False)
        head_suffix = "   [HEAD]" if is_head else ""
        console.print(
            _format_entry_line(entry, type_key, "*") + head_suffix, markup=False
        )
    else:
        # Fan-in: multiple branches converge on the queried entry
        for branch_num, branch in enumerate(branches, start=1):
            for pred_entry in branch:
                console.print(
                    f"  [branch {branch_num}]" + _format_entry_line(pred_entry, type_key, " ").lstrip(),
                    markup=False,
                )
        console.print("  => merged at:", markup=False)
        head_suffix = "   [HEAD]" if is_head else ""
        console.print(
            _format_entry_line(entry, type_key, "*") + head_suffix, markup=False
        )

    # Step 7: If the queried entry is superseded, show forward chain to head
    if not is_head:
        sb_map = superseded_by_map(data)
        immediate_superseder = sb_map.get(entry_id, "")
        console.print(
            f"  (superseded -> head: {head_id})", markup=False
        )

    return 0
