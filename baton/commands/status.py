"""
status.py — ``baton status``: show drift between BATON.md and agent files.

Algorithm (no LLM, no git):
1. Load BATON.md.
2. For each enabled adapter, re-render from current data.
3. Read the on-disk agent file and extract the managed block.
4. Compare rendered inner content vs. on-disk block.
   - ``in-sync``   → they match
   - ``drifted``   → block exists but content differs (run `baton sync`)
   - ``unmanaged`` → file exists but has no BATON:START/END markers
   - ``missing``   → file does not exist yet
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..adapters.base import extract_managed_block, extract_named_block
from ..adapters.registry import detect_enabled, get_adapters
from ..core.alerts import load_alerts, load_appendix_notice, save_appendix_notice
from ..core.config import BatonConfig
from ..core.document import BatonDocument, BatonDocumentError
from ..core.supersede import render_superseded_appendix, SUPERSEDED_START, SUPERSEDED_END

console = Console()


def run_status(repo_root: Path) -> None:
    """Print a drift-status table for all enabled adapters."""
    baton_path = repo_root / "BATON.md"

    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    config = BatonConfig.load(repo_root)
    enabled_names = config.enabled_adapters or detect_enabled(repo_root)
    adapters = get_adapters(enabled_names)

    table = Table(title="baton status", show_header=True, header_style="bold blue")
    table.add_column("Adapter", style="cyan", width=12)
    table.add_column("File", style="dim", no_wrap=True)
    table.add_column("Status", width=14)
    table.add_column("Detail", style="dim")

    for adapter in adapters:
        target = repo_root / adapter.file_path()
        adapter_name = type(adapter).__name__.replace("Adapter", "").lower()

        if not target.exists():
            table.add_row(
                adapter_name, adapter.file_path(),
                "[yellow]missing[/yellow]",
                "Run `baton sync` to create",
            )
            continue

        existing = target.read_text(encoding="utf-8")
        existing_block = extract_managed_block(existing)

        if existing_block is None:
            table.add_row(
                adapter_name, adapter.file_path(),
                "[yellow]unmanaged[/yellow]",
                "No Baton block found — run `baton sync`",
            )
            continue

        expected_inner = adapter.render(doc.data)
        if existing_block.strip() == expected_inner.strip():
            table.add_row(
                adapter_name, adapter.file_path(),
                "[green]in-sync[/green]",
                "",
            )
        else:
            table.add_row(
                adapter_name, adapter.file_path(),
                "[red]drifted[/red]",
                "Run `baton sync` to update",
            )

    # ── Reality drift alerts (from baton check --drift) ──────────────────────
    alerts_data = load_alerts(repo_root)
    drift_alerts = alerts_data.get("alerts") or []
    active_alerts = [
        a for a in drift_alerts
        if a.get("status") in ("violated", "possibly_resolved", "touched")
    ]
    if active_alerts:
        warn_count = sum(1 for a in active_alerts if a.get("severity") == "warn")
        block_count = sum(1 for a in active_alerts if a.get("severity") == "block")
        console.print()
        console.print("[bold]Reality drift alerts:[/bold]")
        for alert in active_alerts:
            sev = alert.get("severity", "warn")
            aid = alert.get("id", "?")
            atype = alert.get("type", "?")
            status = alert.get("status", "?")
            afile = alert.get("file", "")
            aline = alert.get("line", 0)
            detail = alert.get("detail", "")
            loc = f" {afile}:{aline}" if afile else ""
            console.print(
                f"  [{sev}] {aid} ({atype}) {status}{loc} -- {detail}",
                markup=False,
            )
        counts = []
        if block_count:
            counts.append(f"{block_count} block")
        if warn_count:
            counts.append(f"{warn_count} warn")
        count_str = ", ".join(counts)
        console.print(
            f"  Run: baton check --drift --acknowledge <id> --reason \"...\" to suppress  ({count_str})",
            markup=False,
        )
        console.print()

    console.print(table)

    # ── Appendix drift heads-up (one-time, non-disruptive) ───────────────────
    # Read the raw BATON.md text to extract the on-disk appendix region.
    # We compare what's on disk vs what render_superseded_appendix would generate.
    # If they differ, show a one-time heads-up (gated by seen-hash).
    try:
        raw_text = baton_path.read_text(encoding="utf-8")
        expected_appendix = render_superseded_appendix(doc.data)
        on_disk_appendix = extract_named_block(raw_text, SUPERSEDED_START, SUPERSEDED_END) or ""

        # Zero-supersession no-op: if expected is empty and no region exists, in-sync.
        if expected_appendix == "" and on_disk_appendix == "":
            pass  # nothing to check
        elif expected_appendix.strip() != on_disk_appendix.strip():
            # Appendix is out of sync. Check if we've already shown this state.
            current_hash = hashlib.sha256(on_disk_appendix.encode("utf-8")).hexdigest()
            notice = load_appendix_notice(repo_root)
            last_hash = notice.get("hash", "")
            if current_hash != last_hash:
                console.print()
                console.print(
                    "Note: The Superseded appendix in BATON.md appears to have been hand-edited.",
                    markup=False,
                )
                console.print(
                    "  Run `baton supersede` to regenerate it, or edit BATON.md manually.",
                    markup=False,
                )
                console.print(
                    "  (This notice will not repeat unless the appendix changes again.)",
                    markup=False,
                )
                save_appendix_notice(repo_root, {"hash": current_hash})
    except Exception:
        pass  # Never let appendix check disrupt the main status output
