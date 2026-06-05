"""
test_sync.py — Tests for the baton sync command.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from baton.adapters.base import MARKER_END, MARKER_START, extract_managed_block
from baton.commands.sync import run_sync

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A temp dir with a valid BATON.md."""
    shutil.copy(FIXTURES / "sample_baton.md", tmp_path / "BATON.md")
    return tmp_path


# ── Basic sync ────────────────────────────────────────────────────────────────

def test_sync_creates_claude_md(repo: Path) -> None:
    run_sync(repo, quiet=True)
    assert (repo / "CLAUDE.md").exists()


def test_sync_creates_agents_md(repo: Path) -> None:
    run_sync(repo, quiet=True)
    assert (repo / "AGENTS.md").exists()


def test_sync_creates_gemini_md(repo: Path) -> None:
    run_sync(repo, quiet=True)
    assert (repo / "GEMINI.md").exists()


def test_sync_creates_cursor_mdc(repo: Path) -> None:
    run_sync(repo, quiet=True)
    mdc = repo / ".cursor" / "rules" / "baton.mdc"
    assert mdc.exists()


def test_sync_creates_copilot_instructions(repo: Path) -> None:
    run_sync(repo, quiet=True)
    assert (repo / ".github" / "copilot-instructions.md").exists()


def test_sync_injects_baton_block(repo: Path) -> None:
    run_sync(repo, quiet=True)
    content = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert MARKER_START in content
    assert MARKER_END in content


def test_sync_includes_project_name(repo: Path) -> None:
    run_sync(repo, quiet=True)
    content = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert "TestProject" in content


# ── Managed-block safety ──────────────────────────────────────────────────────

def test_sync_preserves_existing_hand_written_content(repo: Path) -> None:
    """Sync must not erase hand-written prose already in CLAUDE.md."""
    hand_written = "# My Notes\n\nThis is hand-written — never delete.\n"
    (repo / "CLAUDE.md").write_text(hand_written, encoding="utf-8")

    run_sync(repo, quiet=True)

    content = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert "This is hand-written — never delete." in content
    assert MARKER_START in content


def test_sync_replaces_existing_baton_block(repo: Path) -> None:
    """A second sync must update the block, not append a second one."""
    run_sync(repo, quiet=True)
    run_sync(repo, quiet=True)

    content = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert content.count(MARKER_START) == 1


def test_sync_returns_true_on_success(repo: Path) -> None:
    assert run_sync(repo, quiet=True) is True


def test_sync_returns_false_when_no_baton_md(tmp_path: Path) -> None:
    # No BATON.md in the directory.
    result = run_sync(tmp_path, quiet=True)
    assert result is False


# ── Cursor MDC front-matter ───────────────────────────────────────────────────

def test_sync_cursor_has_frontmatter(repo: Path) -> None:
    run_sync(repo, quiet=True)
    content = (repo / ".cursor" / "rules" / "baton.mdc").read_text(encoding="utf-8")
    assert content.startswith("---")
    assert "alwaysApply" in content


def test_sync_cursor_only_one_baton_block_after_two_syncs(repo: Path) -> None:
    run_sync(repo, quiet=True)
    run_sync(repo, quiet=True)
    content = (repo / ".cursor" / "rules" / "baton.mdc").read_text(encoding="utf-8")
    assert content.count(MARKER_START) == 1


# ── .baton.toml adapter overrides ────────────────────────────────────────────

def test_sync_respects_enabled_adapters_in_toml(repo: Path) -> None:
    """When .baton.toml limits adapters to ['claude'], only CLAUDE.md is written."""
    (repo / ".baton.toml").write_text(
        '[adapters]\nenabled = ["claude"]\n', encoding="utf-8"
    )
    run_sync(repo, quiet=True)
    assert (repo / "CLAUDE.md").exists()
    assert not (repo / "AGENTS.md").exists()
    assert not (repo / "GEMINI.md").exists()


def test_sync_with_multiple_explicit_adapters(repo: Path) -> None:
    (repo / ".baton.toml").write_text(
        '[adapters]\nenabled = ["claude", "codex"]\n', encoding="utf-8"
    )
    run_sync(repo, quiet=True)
    assert (repo / "CLAUDE.md").exists()
    assert (repo / "AGENTS.md").exists()
    assert not (repo / "GEMINI.md").exists()
