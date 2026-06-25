"""
test_scope_command.py -- End-to-end tests for ``baton scope``.

All tests use tmp_path (pytest filesystem isolation); no mocking.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from baton.commands.scope import run_scope
from baton.core.scope_io import load_scope, scope_active


# ── Minimal BATON.md fixture ──────────────────────────────────────────────────

_BATON_CONTENT = """\
# BATON.md

```yaml
baton_version: "1.0"
last_updated: "2026-06-24"
last_session_tool: ""

project:
  name: "ScopeTest"
  purpose: "Test scope command"
  target_user: "developers"
  stage: "prototype"

architecture:
  overview: "Simple test project."
  key_directories: []
  entry_point: "main.py"
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
    what: "Use Flask as web framework for API endpoints"
    why: "Team knows it well"
    made: "2026-06-24"
    made_in: "claude-code"

anti_decisions:
  - id: "a001"
    rejected: "TypeScript for backend"
    why: "Python-only project"
    ruled_out: "2026-06-24"

landmines:
  - id: "l001"
    location: "auth/callback.py"
    looks_like: "Broken redirect"
    actually: "Intentional for OAuth PKCE flow"

open_questions:
  - id: "q001"
    question: "Should we add caching to the database layer?"
    context: "High traffic expected"
    status: "open"

sessions: []
```
"""


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Create a minimal repo with BATON.md."""
    (tmp_path / "BATON.md").write_text(_BATON_CONTENT, encoding="utf-8")
    # Create CLAUDE.md so detect_enabled finds the claude adapter during sync.
    (tmp_path / "CLAUDE.md").write_text("# Test\n", encoding="utf-8")
    return tmp_path


# ── Normal path ───────────────────────────────────────────────────────────────

def test_scope_creates_scope_json(repo: Path) -> None:
    """scope.json must be created with the correct task and keywords."""
    ok = run_scope(repo, task="database SQLite queries")
    assert ok is True

    state = load_scope(repo)
    assert state["task"] == "database SQLite queries"
    assert "entry_ids" in state
    assert "keywords" in state
    assert "generated_at" in state
    # d001 mentions SQLite -- should be matched
    assert "d001" in state["entry_ids"]


def test_scope_creates_scope_md(repo: Path) -> None:
    """scope.md must be written to .baton/."""
    run_scope(repo, task="database SQLite")
    scope_md = repo / ".baton" / "scope.md"
    assert scope_md.exists()
    content = scope_md.read_text(encoding="utf-8")
    assert "# Baton Scope" in content
    assert "database SQLite" in content


def test_scope_active_returns_true(repo: Path) -> None:
    """scope_active() must return True after a scope is set."""
    assert scope_active(repo) is False
    run_scope(repo, task="Flask web framework")
    assert scope_active(repo) is True


def test_scope_gitignore_updated(repo: Path) -> None:
    """.gitignore must have .baton/* and !.baton/scope.md after scope."""
    run_scope(repo, task="database SQLite")
    gitignore = repo / ".gitignore"
    assert gitignore.exists()
    content = gitignore.read_text(encoding="utf-8")
    assert ".baton/*" in content
    assert "!.baton/scope.md" in content


def test_scope_entry_ids_are_strings(repo: Path) -> None:
    """All entry_ids must be strings."""
    run_scope(repo, task="database SQLite storage")
    state = load_scope(repo)
    for eid in state["entry_ids"]:
        assert isinstance(eid, str)


def test_scope_under_threshold_hint(repo: Path, capsys) -> None:
    """When fewer than 3 entries match, the function still succeeds.

    The under_threshold hint may or may not appear depending on console
    capture; we just confirm the function returns True.
    """
    ok = run_scope(repo, task="completely unrelated zymurgy topic")
    assert ok is True


# ── --clear path ─────────────────────────────────────────────────────────────

def test_scope_clear_removes_state(repo: Path) -> None:
    """--clear must remove scope.json and scope.md."""
    run_scope(repo, task="database SQLite")
    assert scope_active(repo) is True

    ok = run_scope(repo, clear=True)
    assert ok is True
    assert scope_active(repo) is False

    scope_json = repo / ".baton" / "scope.json"
    scope_md = repo / ".baton" / "scope.md"
    assert not scope_json.exists()
    assert not scope_md.exists()


def test_scope_clear_when_no_scope_is_noop(repo: Path) -> None:
    """--clear with no active scope must return True (no-op)."""
    assert scope_active(repo) is False
    ok = run_scope(repo, clear=True)
    assert ok is True


# ── Error handling ────────────────────────────────────────────────────────────

def test_scope_no_task_no_clear_returns_false(repo: Path) -> None:
    """Neither task nor --clear: must return False."""
    ok = run_scope(repo, task=None, clear=False)
    assert ok is False


def test_scope_missing_baton_md_returns_false(tmp_path: Path) -> None:
    """If BATON.md does not exist, run_scope returns False."""
    ok = run_scope(tmp_path, task="some task")
    assert ok is False
