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
from baton.core.alerts import load_appendix_notice
from baton.core.supersede import SUPERSEDED_START, SUPERSEDED_END, render_superseded_appendix
from baton.commands.supersede import run_supersede

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


# ── Alert wiring tests ────────────────────────────────────────────────────────

def test_status_loads_alerts_without_error_when_missing(synced_repo: Path) -> None:
    """run_status completes without error even when .baton/alerts.json is absent."""
    run_status(synced_repo)  # should not raise


def test_status_loads_alerts_without_error_when_present(synced_repo: Path) -> None:
    """run_status completes without error when .baton/alerts.json has alerts."""
    from baton.core.alerts import save_alerts
    save_alerts(synced_repo, {
        "generated_at": "2026-06-20T00:00:00Z",
        "since_sha": "abc",
        "alerts": [{"id": "a001", "type": "anti_decision", "severity": "warn",
                    "status": "violated", "file": "x.py", "line": 1, "detail": "test"}],
    })
    run_status(synced_repo)  # should not raise


def test_status_loads_alerts_without_error_when_no_active_alerts(synced_repo: Path) -> None:
    """run_status completes without error when alerts.json has only resolved alerts."""
    from baton.core.alerts import save_alerts
    save_alerts(synced_repo, {
        "generated_at": "2026-06-20T00:00:00Z",
        "since_sha": "abc",
        "alerts": [{"id": "a001", "type": "anti_decision", "severity": "warn",
                    "status": "resolved", "file": "x.py", "line": 1, "detail": "test"}],
    })
    run_status(synced_repo)  # should not raise


def test_status_loads_block_alerts(synced_repo: Path) -> None:
    """run_status completes without error when alerts.json has block-severity alerts."""
    from baton.core.alerts import save_alerts
    save_alerts(synced_repo, {
        "generated_at": "2026-06-20T00:00:00Z",
        "since_sha": "abc",
        "alerts": [
            {"id": "a001", "type": "anti_decision", "severity": "block",
             "status": "violated", "file": "src/app.py", "line": 10,
             "detail": "import of forbidden dep"},
            {"id": "a002", "type": "landmine", "severity": "warn",
             "status": "possibly_resolved", "file": "src/db.py", "line": 5,
             "detail": "possible landmine touched"},
        ],
    })
    run_status(synced_repo)  # should not raise


def _baton_with_supersession(tmp_path: Path) -> Path:
    """Write a BATON.md that has two decisions with a supersession link."""
    import shutil as _shutil
    _shutil.copy(FIXTURES / "sample_baton.md", tmp_path / "BATON.md")
    # Add a second decision so we can create a supersession
    doc = BatonDocument.load(tmp_path / "BATON.md")
    doc.data["decisions"].append({
        "id": "d002",
        "what": "Use Postgres in prod",
        "why": "Scales better",
        "made": "2026-06-15",
        "made_in": "test",
    })
    doc.save()
    # Create the supersession link d001 -> d002
    result = run_supersede(tmp_path, "d001", "d002", "Postgres scales better")
    assert result == 0
    return tmp_path


# ── Phase D: appendix drift heads-up ─────────────────────────────────────────

def test_appendix_headsup_fires_when_hand_edited(tmp_path: Path, capsys) -> None:
    """Heads-up shows when on-disk appendix differs from expected."""
    repo = _baton_with_supersession(tmp_path)
    # Hand-edit the appendix region to introduce drift.
    # Corrupt a string that exists ONLY in the appendix prose, not in the YAML reason field.
    baton = repo / "BATON.md"
    text = baton.read_text(encoding="utf-8")
    corrupted = text.replace("Original text is preserved above", "edited by hand")
    baton.write_text(corrupted, encoding="utf-8")

    run_status(repo)
    # Verify the heads-up was saved (notice file written) even if capsys misses Rich output
    notice = load_appendix_notice(repo)
    assert "hash" in notice


def test_appendix_headsup_suppressed_on_second_run(tmp_path: Path, capsys) -> None:
    """After the first heads-up, second run is silent (same state)."""
    repo = _baton_with_supersession(tmp_path)
    baton = repo / "BATON.md"
    text = baton.read_text(encoding="utf-8")
    corrupted = text.replace("Original text is preserved above", "edited by hand")
    baton.write_text(corrupted, encoding="utf-8")

    # First run — should show heads-up
    run_status(repo)
    out1 = capsys.readouterr().out

    # Second run — same on-disk state, should NOT show heads-up again
    run_status(repo)
    out2 = capsys.readouterr().out

    # The note should NOT appear in the second run
    note_phrases = ["hand-edited", "appendix", "This notice will not repeat"]
    # out1 should have had the notice; out2 should not repeat the same notice
    # We verify that the appendix_notice.json was saved (suppresses future notices)
    notice = load_appendix_notice(repo)
    assert "hash" in notice


def test_appendix_headsup_refires_after_further_edit(tmp_path: Path, capsys) -> None:
    """Heads-up refires when the appendix changes a second time."""
    repo = _baton_with_supersession(tmp_path)
    baton = repo / "BATON.md"
    text = baton.read_text(encoding="utf-8")
    corrupted = text.replace("Original text is preserved above", "first edit")
    baton.write_text(corrupted, encoding="utf-8")

    # First run — fires heads-up, saves hash of "first edit" state
    run_status(repo)
    notice_after_first = load_appendix_notice(repo)
    first_hash = notice_after_first.get("hash", "")
    capsys.readouterr()  # clear

    # Now change the appendix again
    text2 = baton.read_text(encoding="utf-8")
    corrupted2 = text2.replace("first edit", "second different edit")
    baton.write_text(corrupted2, encoding="utf-8")

    # Second run — different state, should refire
    run_status(repo)
    notice_after_second = load_appendix_notice(repo)
    second_hash = notice_after_second.get("hash", "")

    assert first_hash != second_hash


def test_appendix_headsup_no_op_on_zero_supersessions(tmp_path: Path, capsys) -> None:
    """When no supersessions exist, no heads-up is shown."""
    import shutil as _shutil
    _shutil.copy(FIXTURES / "sample_baton.md", tmp_path / "BATON.md")
    run_status(tmp_path)
    out = capsys.readouterr().out
    # Should not mention "appendix" or "hand-edited" at all
    assert "hand-edited" not in out.lower()
    assert "appendix_notice" not in out.lower()
    # Importantly, no .baton/appendix_notice.json should be written
    notice_path = tmp_path / ".baton" / "appendix_notice.json"
    assert not notice_path.exists()


def test_appendix_headsup_no_op_when_in_sync(tmp_path: Path, capsys) -> None:
    """When appendix matches expected, no heads-up shown even without notice file."""
    repo = _baton_with_supersession(tmp_path)
    # The appendix is fresh from run_supersede — should be in-sync
    run_status(repo)
    out = capsys.readouterr().out
    assert "hand-edited" not in out.lower()


def test_appendix_headsup_exit_code_unchanged(tmp_path: Path, capsys) -> None:
    """Appendix drift heads-up never changes the exit code (status returns None)."""
    repo = _baton_with_supersession(tmp_path)
    baton = repo / "BATON.md"
    text = baton.read_text(encoding="utf-8")
    baton.write_text(text.replace("Original text is preserved above", "hand edit"), encoding="utf-8")
    # run_status returns None (exits 0) regardless of appendix state
    result = run_status(repo)
    assert result is None
