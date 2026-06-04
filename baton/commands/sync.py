"""
sync.py — ``baton sync``: push BATON.md to all enabled agent config files.

This is the core operation of Baton.  For each enabled adapter it:
1. Calls ``adapter.render(data)`` to generate the inner block content.
2. Calls ``adapter.prepare_file(existing, inner)`` to upsert the managed block.
3. Writes the result, creating parent directories if needed.

Returns True if all adapters succeeded.
"""
from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..adapters.registry import detect_enabled, get_adapters
from ..core.config import BatonConfig
from ..core.document import BatonDocument, BatonDocumentError

console = Console()


def run_sync(repo_root: Path, quiet: bool = False) -> bool:
    """Sync BATON.md to all enabled agent files.

    Args:
        repo_root: Root of the project (where BATON.md lives).
        quiet:     Suppress Rich table output (used internally by ``init``).

    Returns:
        True if every adapter succeeded; False if any failed.
    """
    baton_path = repo_root / "BATON.md"

    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return False

    config = BatonConfig.load(repo_root)
    enabled_names = config.enabled_adapters or detect_enabled(repo_root)
    adapters = get_adapters(enabled_names)

    if not adapters:
        console.print("[yellow]No adapters enabled. Check .baton.toml or add agent files to the repo.[/yellow]")
        return True

    table = Table(title="baton sync", show_header=True, header_style="bold blue")
    table.add_column("Adapter", style="cyan", width=12)
    table.add_column("File", style="dim", no_wrap=True)
    table.add_column("Status")

    all_ok = True
    for adapter in adapters:
        target = repo_root / adapter.file_path()
        adapter_name = type(adapter).__name__.replace("Adapter", "").lower()

        try:
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            rendered = adapter.render(doc.data)
            new_content = adapter.prepare_file(existing, rendered)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new_content, encoding="utf-8")
            status = "[green]synced[/green]"
        except Exception as exc:
            status = f"[red]ERROR: {exc}[/red]"
            all_ok = False

        table.add_row(adapter_name, adapter.file_path(), status)

    if not quiet:
        console.print(table)

    return all_ok
