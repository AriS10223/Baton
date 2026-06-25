"""
scope_io.py -- State I/O for the active scope stored in .baton/.

Two files are managed here:
  .baton/scope.json   -- active scope state (task, keywords, entry_ids, generated_at)
  .baton/scope.md     -- committable rendered artifact (written by commands/scope.py)

All loaders return safe defaults when files are absent or corrupt -- never raise.
Write functions create .baton/ if it does not yet exist.
"""
from __future__ import annotations

import json
from pathlib import Path


# ── Internal helpers ──────────────────────────────────────────────────────────

def _baton_dir(repo_root: Path) -> Path:
    return repo_root / ".baton"


def _ensure_baton_dir(repo_root: Path) -> Path:
    d = _baton_dir(repo_root)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Scope state I/O ───────────────────────────────────────────────────────────

def load_scope(repo_root: Path) -> dict:
    """Load .baton/scope.json.

    Returns {} if the file is absent or contains invalid JSON.
    Schema: {task, keywords, entry_ids, generated_at}
    """
    path = _baton_dir(repo_root) / "scope.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def save_scope(repo_root: Path, state: dict) -> None:
    """Write .baton/scope.json.  Creates .baton/ dir if needed."""
    d = _ensure_baton_dir(repo_root)
    (d / "scope.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def scope_active(repo_root: Path) -> bool:
    """Return True if a scope is currently active (scope.json exists and is non-empty)."""
    state = load_scope(repo_root)
    return bool(state.get("task"))


def clear_scope(repo_root: Path) -> None:
    """Delete .baton/scope.json and .baton/scope.md if they exist.

    Safe to call when no scope is active -- never raises.
    """
    baton_dir = _baton_dir(repo_root)
    for name in ("scope.json", "scope.md"):
        p = baton_dir / name
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
