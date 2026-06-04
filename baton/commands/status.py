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

import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..adapters.base import extract_managed_block
from ..adapters.registry import detect_enabled, get_adapters
from ..core.config import BatonConfig
from ..core.document import BatonDocument, BatonDocumentError

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

    console.print(table)
