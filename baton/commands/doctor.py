"""
doctor.py -- ``baton doctor``: diagnose your Baton setup.

Runs five check groups in order and prints a PASS / WARN / FAIL line for
each item, with an inline fix hint on failures.  Always exits 0 -- this
command is informational only and never blocks a workflow.
"""
from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console
from rich.rule import Rule

from ..adapters.base import extract_managed_block
from ..adapters.registry import ADAPTER_MAP, _DETECTION_RULES, detect_enabled, get_adapters
from ..core.config import BatonConfig
from ..core.document import BatonDocument, BatonDocumentError

console = Console()

_PASS = "[bold green]PASS[/bold green]"
_WARN = "[bold yellow]WARN[/bold yellow]"
_FAIL = "[bold red]FAIL[/bold red]"


def _row(status: str, label: str, hint: str = "") -> None:
    line = f"  {status}  {label}"
    console.print(line)
    if hint:
        console.print(f"        [dim]{hint}[/dim]")


# ── Check groups ──────────────────────────────────────────────────────────────

def _check_baton_md(repo_root: Path) -> BatonDocument | None:
    console.print(Rule("[bold]BATON.md[/bold]", style="blue"))
    baton_path = repo_root / "BATON.md"

    if not baton_path.exists():
        _row(_FAIL, "BATON.md not found",
             "Fix: baton init")
        return None

    _row(_PASS, "BATON.md found")

    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        _row(_FAIL, f"BATON.md could not be parsed: {exc}",
             "Fix: ensure the file contains a ```yaml ... ``` block")
        return None

    _row(_PASS, "Valid YAML block parsed")
    return doc


def _check_config(repo_root: Path) -> BatonConfig:
    console.print(Rule("[bold]Config (.baton.toml)[/bold]", style="blue"))
    toml_path = repo_root / ".baton.toml"

    if not toml_path.exists():
        _row(_WARN, ".baton.toml not found -- using defaults",
             "Fix: baton init  (or create .baton.toml manually)")
        config = BatonConfig.load(repo_root)
    else:
        config = BatonConfig.load(repo_root)
        _row(_PASS, ".baton.toml found")

    console.print(f"  [dim]llm_provider = {config.llm_provider}[/dim]")
    console.print(f"  [dim]model        = {config.model or '(provider default)'}[/dim]")
    console.print(f"  [dim]min_diff_lines = {config.min_diff_lines}[/dim]")
    console.print(f"  [dim]auto_sync    = {config.auto_sync}[/dim]")
    return config


def _check_adapters(repo_root: Path, config: BatonConfig) -> list[str]:
    console.print(Rule("[bold]Adapters[/bold]", style="blue"))

    if config.enabled_adapters:
        source = "from .baton.toml [adapters] section"
        enabled = config.enabled_adapters
    else:
        source = "auto-detected from repo root"
        enabled = detect_enabled(repo_root)

    if not enabled:
        _row(_WARN, f"No adapters enabled ({source})",
             "Fix: run baton init or add [adapters] enabled = [...] to .baton.toml")
        return []

    _row(_PASS, f"{len(enabled)} adapter(s) enabled ({source})")

    for name in enabled:
        cls = ADAPTER_MAP.get(name)
        if cls is None:
            _row(_WARN, f"  {name}: unknown adapter name -- will be skipped",
                 "Fix: check spelling in .baton.toml [adapters] enabled list")
        else:
            target = cls().file_path()
            _row(_PASS, f"  {name:<10} -> {target}")

    # Show which tools are NOT detected (informational)
    all_names = list(ADAPTER_MAP.keys())
    not_enabled = [n for n in all_names if n not in enabled]
    if not_enabled:
        console.print(f"  [dim]Not enabled: {', '.join(not_enabled)}[/dim]")

    return enabled


def _check_agent_files(repo_root: Path, doc: BatonDocument | None, enabled: list[str]) -> None:
    console.print(Rule("[bold]Agent files (dry-run sync)[/bold]", style="blue"))

    if doc is None:
        _row(_WARN, "Skipped -- BATON.md could not be loaded",
             "Fix the BATON.md issues above first")
        return

    if not enabled:
        _row(_WARN, "Skipped -- no adapters enabled")
        return

    adapters = get_adapters(enabled)
    for adapter in adapters:
        target = repo_root / adapter.file_path()
        name = type(adapter).__name__.replace("Adapter", "").lower()

        if not target.exists():
            _row(_WARN, f"{name:<10} {adapter.file_path()}  [yellow]missing[/yellow]",
                 "Fix: baton sync")
            continue

        existing = target.read_text(encoding="utf-8")
        block = extract_managed_block(existing)

        if block is None:
            _row(_WARN, f"{name:<10} {adapter.file_path()}  [yellow]unmanaged[/yellow]",
                 "Fix: baton sync  (will insert Baton block without overwriting your content)")
            continue

        expected = adapter.render(doc.data)
        if block.strip() == expected.strip():
            _row(_PASS, f"{name:<10} {adapter.file_path()}  in-sync")
        else:
            _row(_WARN, f"{name:<10} {adapter.file_path()}  [yellow]drifted[/yellow]",
                 "Fix: baton sync")


def _check_api_keys(config: BatonConfig) -> None:
    console.print(Rule("[bold]API keys[/bold]", style="blue"))

    active = config.llm_provider

    checks = [
        (
            "anthropic",
            "ANTHROPIC_API_KEY",
            os.environ.get("ANTHROPIC_API_KEY", ""),
            "Optional -- baton end already works for free via markers\n"
            "        (DECISION:/ANTI:/LANDMINE:/QUESTION: in commits) and the\n"
            "        Claude Code skill (`baton install-skill`).\n"
            "        Add a key only if you want baton end --api directly, without\n"
            "        writing markers or running inside an agent session.\n"
            "        Fix: export ANTHROPIC_API_KEY=sk-ant-...",
        ),
        (
            "openai",
            "OPENAI_API_KEY",
            os.environ.get("OPENAI_API_KEY", ""),
            "Fix: export OPENAI_API_KEY=sk-...  and pip install \"baton-pass[openai]\"",
        ),
        (
            "vertex",
            "GOOGLE_APPLICATION_CREDENTIALS",
            os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
            "Fix: export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json  "
            "and export BATON_VERTEX_PROJECT=my-project  "
            "and pip install \"baton-pass[vertex]\"",
        ),
    ]

    for provider, env_var, value, hint in checks:
        tag = "  [dim](active provider)[/dim]" if provider == active else ""
        if value:
            masked = value[:8] + "..." if len(value) > 8 else "***"
            _row(_PASS, f"{env_var:<38} set ({masked}){tag}")
        else:
            if provider == "anthropic":
                status = _WARN
                show_hint = True
            elif provider == active:
                status = _FAIL
                show_hint = True
            else:
                status = _WARN
                show_hint = False
            _row(status, f"{env_var:<38} not set{tag}", hint if show_hint else "")

    # Vertex needs a second env var
    vertex_project = os.environ.get("BATON_VERTEX_PROJECT", "")
    if active == "vertex" and not vertex_project:
        _row(_FAIL, "BATON_VERTEX_PROJECT                   not set",
             "Fix: export BATON_VERTEX_PROJECT=my-gcp-project")
    elif vertex_project:
        _row(_PASS, f"BATON_VERTEX_PROJECT                   set ({vertex_project})")


def _check_optional_deps() -> None:
    """Check optional dependencies used by baton health / baton trim."""
    console.print(Rule("[bold]Optional dependencies[/bold]", style="blue"))

    from ..core.tokens import tiktoken_available
    if tiktoken_available():
        _row(_PASS, "tiktoken installed (accurate token counts for baton health)")
    else:
        _row(
            _WARN,
            "tiktoken not installed -- token counts will use word-count heuristic",
            'Fix: pip install "baton-pass[tokens]"',
        )


# ── Public entry point ────────────────────────────────────────────────────────

def run_doctor(repo_root: Path) -> None:
    """Run all diagnostic checks and print a human-readable report."""
    console.print()
    console.print("[bold]baton doctor[/bold] -- diagnosing your setup\n")

    doc = _check_baton_md(repo_root)
    console.print()

    config = _check_config(repo_root)
    console.print()

    enabled = _check_adapters(repo_root, config)
    console.print()

    _check_agent_files(repo_root, doc, enabled)
    console.print()

    _check_api_keys(config)
    console.print()

    _check_optional_deps()
    console.print()
