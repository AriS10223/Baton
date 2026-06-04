"""
test_status.py — Tests for the baton status command.

We test the underlying logic rather than Rich console output.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from baton.adapters.base import MARKER_END, MARKER_START, upsert_managed_block
from baton.adapters.claude import ClaudeAdapter
from baton.adapters.registry import detect_enabled
from baton.commands.sync import run_sync
from baton.commands.status import run_status
from baton.core.document import BatonDocument

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def synced_repo(tmp_path: Path) -> Path:
    """A repo that has been synced once — all agent files are in-sync."""
    shutil.copy(FIXTURES / "sample_baton.md", tmp_path / "BATON.md")
    run_sync(tmp_path, quiet=True)
    return tmp_path


# ── Status detection helpers (test the logic, not the Rich table) ─────────────

def _block_matches(repo: Path, file_rel: str) -> bool:
    """Return True if the adapter file's managed block matches a fresh render."""
    from baton.adapters.base import extract_managed_block

    baton_path = repo / "BATON.md"
    doc = BatonDocument.load(baton_path)
    adapter = ClaudeAdapter()

    target = repo / file_rel
    if not target.exists():
        return False
    existing = target.read_text(encoding="utf-8")
    block = extract_managed_block(existing)
    if block is None:
        return False
    expected = adapter.render(doc.data)
    return block.strip() == expected.strip()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_status_runs_without_error_after_sync(synced_repo: Path, capsys) -> None:
    """run_status should not raise for a healthy synced repo."""
    run_status(synced_repo)


def test_claude_md_in_sync_after_sync(synced_repo: Path) -> None:
    assert _block_matches(synced_repo, "CLAUDE.md") is True


def test_claude_md_drifted_after_manual_edit(synced_repo: Path) -> None:
    claude_path = synced_repo / "CLAUDE.md"
    original = claude_path.read_text(encoding="utf-8")
    # Manually corrupt the managed block content.
    drifted = original.replace("TestProject", "ManuallyEditedProject")
    claude_path.write_text(drifted, encoding="utf-8")
    assert _block_matches(synced_repo, "CLAUDE.md") is False


def test_claude_md_unmanaged_when_no_baton_block(synced_repo: Path) -> None:
    from baton.adapters.base import extract_managed_block

    claude_path = synced_repo / "CLAUDE.md"
    # Remove the managed block markers.
    content = claude_path.read_text(encoding="utf-8")
    content = content.replace(MARKER_START, "").replace(MARKER_END, "")
    claude_path.write_text(content, encoding="utf-8")
    assert extract_managed_block(content) is None


def test_sync_brings_drifted_file_back_in_sync(synced_repo: Path) -> None:
    claude_path = synced_repo / "CLAUDE.md"
    content = claude_path.read_text(encoding="utf-8")
    # Introduce drift.
    content = content.replace("TestProject", "DriftedProject")
    claude_path.write_text(content, encoding="utf-8")
    assert _block_matches(synced_repo, "CLAUDE.md") is False

    # Re-sync should fix it.
    run_sync(synced_repo, quiet=True)
    assert _block_matches(synced_repo, "CLAUDE.md") is True


def test_no_baton_md_raises_sysexit(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        run_status(tmp_path)
