"""
test_review.py -- Tests for ``baton review`` (pending entry walkthrough).

Covers:
- Empty queue: clear message, exit 0
- Accept: status flipped to "active" in BATON.md
- Delete: entry removed from BATON.md
- Skip: entry stays as pending_review
- High-confidence entries sorted before low-confidence
- CLI wiring (CliRunner)
"""
from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from baton.cli import app
from baton.commands.review import (
    _accept_entry,
    _collect_pending,
    _delete_entry,
)
from baton.core.document import BatonDocument
from baton.core.schema import PENDING_REVIEW

runner = CliRunner()

# ── Fixtures ──────────────────────────────────────────────────────────────────

_SAMPLE_YAML = """\
baton_version: "1.0"
last_updated: "2026-06-23"
last_session_tool: ""
project:
  name: TestProject
  purpose: testing
  target_user: devs
  stage: prototype
architecture:
  overview: ""
  key_directories: []
  entry_point: ""
  data_flow: ""
stack: []
laws: []
current_sprint:
  goal: test
  done: []
  in_progress: []
  blocked: []
  next: []
decisions:
  - id: d001
    what: Active decision
    why: because
    made: "2026-01-01"
    made_in: claude-code
  - id: d002
    what: Draft manifest entry
    why: ""
    made: "2026-06-23"
    made_in: ""
    source: scan:manifest
    confidence: high
    status: pending_review
    evidence:
      type: dependency
      value: fastapi
  - id: d003
    what: Draft docs entry
    why: ""
    made: "2026-06-23"
    made_in: ""
    source: scan:docs
    confidence: medium
    status: pending_review
anti_decisions: []
landmines:
  - id: l001
    location: app.py:10
    looks_like: wrong
    actually: HACK workaround
    source: scan:comment
    confidence: high
    status: pending_review
open_questions: []
sessions: []
"""


def _write_baton(tmp_path: Path, yaml_content: str = _SAMPLE_YAML) -> Path:
    baton = tmp_path / "BATON.md"
    baton.write_text(f"# BATON.md\n\n```yaml\n{yaml_content}\n```\n", encoding="utf-8")
    return baton


# ── _collect_pending ──────────────────────────────────────────────────────────

def test_collect_pending_returns_only_pending(tmp_path):
    baton = _write_baton(tmp_path)
    doc = BatonDocument.load(baton)
    pending = _collect_pending(doc.data)
    ids = [e.get("id") for _, e in pending]
    assert "d002" in ids
    assert "d003" in ids
    assert "l001" in ids
    assert "d001" not in ids  # active entry excluded


def test_collect_pending_sorts_high_confidence_first(tmp_path):
    baton = _write_baton(tmp_path)
    doc = BatonDocument.load(baton)
    pending = _collect_pending(doc.data)
    confidences = [e.get("confidence") for _, e in pending]
    # high entries should all precede medium entries
    high_indices = [i for i, c in enumerate(confidences) if c == "high"]
    medium_indices = [i for i, c in enumerate(confidences) if c == "medium"]
    if high_indices and medium_indices:
        assert max(high_indices) < min(medium_indices)


def test_collect_pending_empty_when_no_pending(tmp_path):
    yaml = _SAMPLE_YAML.replace("status: pending_review", "status: active")
    baton = _write_baton(tmp_path, yaml)
    doc = BatonDocument.load(baton)
    assert _collect_pending(doc.data) == []


# ── _accept_entry ─────────────────────────────────────────────────────────────

def test_accept_entry_flips_status_to_active(tmp_path):
    baton = _write_baton(tmp_path)
    doc = BatonDocument.load(baton)
    pending = _collect_pending(doc.data)

    # Accept the first pending entry
    type_key, entry = pending[0]
    _accept_entry(doc, type_key, entry)

    # Verify the status changed in the data
    entries = doc.data.get(type_key, [])
    accepted = next((e for e in entries if e.get("id") == entry.get("id")), None)
    assert accepted is not None
    assert accepted.get("status") == "active"


def test_accept_entry_does_not_affect_other_entries(tmp_path):
    baton = _write_baton(tmp_path)
    doc = BatonDocument.load(baton)

    # Accept d002
    entry = next(e for e in doc.data.get("decisions", []) if e.get("id") == "d002")
    _accept_entry(doc, "decisions", entry)

    # d003 still pending
    d003 = next(e for e in doc.data.get("decisions", []) if e.get("id") == "d003")
    assert d003.get("status") == PENDING_REVIEW


# ── _delete_entry ─────────────────────────────────────────────────────────────

def test_delete_entry_removes_from_list(tmp_path):
    baton = _write_baton(tmp_path)
    doc = BatonDocument.load(baton)

    # Delete d002
    decisions = doc.data.get("decisions", [])
    initial_count = len(decisions)
    entry = next(e for e in decisions if e.get("id") == "d002")
    _delete_entry(doc, "decisions", entry)

    assert len(doc.data.get("decisions", [])) == initial_count - 1
    ids = [e.get("id") for e in doc.data.get("decisions", [])]
    assert "d002" not in ids
    assert "d001" in ids  # active entry unaffected


def test_delete_entry_noop_when_not_found(tmp_path):
    baton = _write_baton(tmp_path)
    doc = BatonDocument.load(baton)
    initial_count = len(doc.data.get("decisions", []))
    _delete_entry(doc, "decisions", {"id": "d999", "what": "nonexistent"})
    assert len(doc.data.get("decisions", [])) == initial_count


# ── baton review CLI ──────────────────────────────────────────────────────────

def test_review_empty_queue_prints_message(tmp_path, monkeypatch):
    """With no pending entries, review prints a clear message and exits 0."""
    monkeypatch.chdir(tmp_path)
    yaml = _SAMPLE_YAML.replace("status: pending_review", "status: active")
    _write_baton(tmp_path, yaml)

    result = runner.invoke(app, ["review"])
    assert result.exit_code == 0
    assert "Nothing to review" in result.output


def test_review_exits_1_on_missing_baton_md(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # No BATON.md in tmp_path
    result = runner.invoke(app, ["review"])
    assert result.exit_code == 1


def test_review_with_pending_entries_prompts_user(tmp_path, monkeypatch):
    """With pending entries, review should prompt for at least one action."""
    monkeypatch.chdir(tmp_path)
    _write_baton(tmp_path)

    # Skip all entries (input 's' for each prompt)
    result = runner.invoke(app, ["review"], input="s\ns\ns\n")
    assert result.exit_code == 0
    # Should show the entry count and prompt
    assert "pending" in result.output.lower()


def test_review_accept_writes_active_status(tmp_path, monkeypatch):
    """Accepting an entry should flip its status to 'active' and save to disk."""
    monkeypatch.chdir(tmp_path)
    _write_baton(tmp_path)

    # Accept first entry, skip the rest
    result = runner.invoke(app, ["review"], input="a\ns\ns\n")
    assert result.exit_code == 0

    # Reload and verify one entry was accepted
    doc = BatonDocument.load(tmp_path / "BATON.md")
    all_entries = [
        e for section_key in ("decisions", "anti_decisions", "landmines", "open_questions")
        for e in (doc.data.get(section_key) or [])
        if isinstance(e, dict)
    ]
    # d001 has no status field (implicitly active); accepted draft should have status="active"
    explicitly_accepted = [e for e in all_entries if e.get("status") == "active"]
    assert len(explicitly_accepted) >= 1, "No pending entry was flipped to active"


def test_review_delete_removes_entry(tmp_path, monkeypatch):
    """Deleting the first pending entry should remove it from BATON.md."""
    monkeypatch.chdir(tmp_path)
    _write_baton(tmp_path)

    doc_before = BatonDocument.load(tmp_path / "BATON.md")
    pending_before = _collect_pending(doc_before.data)
    first_type, first_entry = pending_before[0]
    first_id = first_entry.get("id")

    # Delete first, skip rest
    result = runner.invoke(app, ["review"], input="d\ns\ns\n")
    assert result.exit_code == 0

    doc_after = BatonDocument.load(tmp_path / "BATON.md")
    all_ids = [
        e.get("id")
        for section_key in ("decisions", "anti_decisions", "landmines", "open_questions")
        for e in (doc_after.data.get(section_key) or [])
        if isinstance(e, dict)
    ]
    assert first_id not in all_ids


# ── CLI registration ──────────────────────────────────────────────────────────

def test_review_command_registered():
    """baton review should be a registered CLI command."""
    result = runner.invoke(app, ["--help"])
    assert "review" in result.output
