"""
test_sync_scope.py -- Test that run_sync writes SCOPED blocks when scope is active.

Uses tmp_path; no mocking. Verifies that when a scope is active, the managed
block in CLAUDE.md contains only in-scope entries.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from baton.commands.sync import run_sync
from baton.core.scope_io import save_scope, clear_scope, scope_active
from baton.adapters.base import extract_managed_block


# ── BATON.md with two distinct decisions ─────────────────────────────────────

_BATON_TWO_DECISIONS = """\
# BATON.md

```yaml
baton_version: "1.0"
last_updated: "2026-06-24"
last_session_tool: ""

project:
  name: "SyncScopeTest"
  purpose: "Test scope filtering in sync"
  target_user: "developers"
  stage: "prototype"

architecture:
  overview: ""
  key_directories: []
  entry_point: ""
  data_flow: ""

stack: []
laws: []

current_sprint:
  goal: ""
  done: []
  in_progress: []
  blocked: []
  next: []

decisions:
  - id: "d001"
    what: "Use SQLite for local database storage"
    why: "Zero config needed"
    made: "2026-06-24"
    made_in: "claude-code"
  - id: "d002"
    what: "Use Flask as web framework for HTTP endpoints"
    why: "Team knows it well"
    made: "2026-06-24"
    made_in: "claude-code"

anti_decisions: []
landmines: []
open_questions: []
sessions: []
```
"""


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Create a minimal repo with two decisions."""
    (tmp_path / "BATON.md").write_text(_BATON_TWO_DECISIONS, encoding="utf-8")
    # CLAUDE.md must exist so detect_enabled finds the claude adapter.
    (tmp_path / "CLAUDE.md").write_text("# Test\n", encoding="utf-8")
    return tmp_path


def _read_managed_block(repo: Path) -> str:
    content = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    block = extract_managed_block(content)
    assert block is not None, "No managed block found in CLAUDE.md"
    return block


# ── Full sync (no scope) ──────────────────────────────────────────────────────

def test_full_sync_includes_both_decisions(repo: Path) -> None:
    """Without a scope, sync includes all decisions."""
    ok = run_sync(repo, quiet=True)
    assert ok is True
    block = _read_managed_block(repo)
    assert "SQLite" in block
    assert "Flask" in block


# ── Scoped sync ───────────────────────────────────────────────────────────────

def test_scoped_sync_includes_only_matched_decision(repo: Path) -> None:
    """With scope set to only d001, d002 must NOT appear in the managed block."""
    # Activate a scope that includes only d001.
    scope_state = {
        "task": "database SQLite queries",
        "keywords": ["database", "sqlite", "queries"],
        "entry_ids": ["d001"],
        "generated_at": "2026-06-24T00:00:00Z",
    }
    save_scope(repo, scope_state)
    assert scope_active(repo) is True

    ok = run_sync(repo, quiet=True)
    assert ok is True
    block = _read_managed_block(repo)
    # d001 (SQLite) should be present
    assert "SQLite" in block
    # d002 (Flask) must NOT be present
    assert "Flask" not in block


def test_scoped_sync_excludes_all_when_empty_ids(repo: Path) -> None:
    """With empty entry_ids, no curated entries appear in the block."""
    scope_state = {
        "task": "some unrelated task",
        "keywords": [],
        "entry_ids": [],
        "generated_at": "2026-06-24T00:00:00Z",
    }
    save_scope(repo, scope_state)
    ok = run_sync(repo, quiet=True)
    assert ok is True
    block = _read_managed_block(repo)
    # Neither decision should appear
    assert "SQLite" not in block
    assert "Flask" not in block


def test_clear_scope_restores_full_sync(repo: Path) -> None:
    """After clearing scope, sync restores both decisions."""
    # Set a narrow scope first.
    scope_state = {
        "task": "database",
        "keywords": ["database"],
        "entry_ids": ["d001"],
        "generated_at": "2026-06-24T00:00:00Z",
    }
    save_scope(repo, scope_state)
    run_sync(repo, quiet=True)

    # Verify scoped state.
    block_scoped = _read_managed_block(repo)
    assert "Flask" not in block_scoped

    # Clear and re-sync.
    clear_scope(repo)
    assert scope_active(repo) is False
    run_sync(repo, quiet=True)

    block_full = _read_managed_block(repo)
    assert "SQLite" in block_full
    assert "Flask" in block_full
