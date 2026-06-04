"""
registry.py — Detect which adapters are enabled for a project.

Detection heuristic: scan the repo root for existing agent files / directories.
If any are found, enable only those adapters (the user is already using those
tools).  If nothing is detected (brand-new project), enable all five.

The ``enabled_adapters`` list in ``.baton.toml`` overrides auto-detection.
"""
from __future__ import annotations

from pathlib import Path

from .base import BaseAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .copilot import CopilotAdapter
from .cursor import CursorAdapter
from .gemini import GeminiAdapter

# Map of adapter name → class.  Community adapters register here.
ADAPTER_MAP: dict[str, type[BaseAdapter]] = {
    "claude":  ClaudeAdapter,
    "codex":   CodexAdapter,
    "cursor":  CursorAdapter,
    "gemini":  GeminiAdapter,
    "copilot": CopilotAdapter,
}

# (adapter_name, path_relative_to_repo_root_that_triggers_detection)
_DETECTION_RULES: list[tuple[str, str]] = [
    ("claude",  "CLAUDE.md"),
    ("codex",   "AGENTS.md"),
    ("cursor",  ".cursor"),
    ("gemini",  "GEMINI.md"),
    ("copilot", ".github/copilot-instructions.md"),
]


def detect_enabled(repo_root: Path) -> list[str]:
    """Return adapter names whose indicator path exists under *repo_root*.

    Falls back to all five adapters when nothing is detected (new project).
    """
    found = [name for name, path in _DETECTION_RULES if (repo_root / path).exists()]
    return found if found else list(ADAPTER_MAP.keys())


def get_adapters(enabled: list[str]) -> list[BaseAdapter]:
    """Instantiate ``BaseAdapter`` instances for the given *enabled* names.

    Unknown names are silently skipped so a typo in ``.baton.toml`` doesn't
    crash the CLI.
    """
    adapters: list[BaseAdapter] = []
    for name in enabled:
        cls = ADAPTER_MAP.get(name)
        if cls is not None:
            adapters.append(cls())
    return adapters
