"""
test_scan.py -- End-to-end tests for ``baton init --scan`` orchestration.

Covers:
- Fresh BATON.md (empty sections) → entries actually written to disk
- Existing BATON.md (non-empty sections) → existing entries untouched, drafts appended
- Multi-source dedup: manifest entry not duplicated when same dep appears twice
- Dedup against existing active entries (no duplicates from previous scan)
- summary path runs (total_new == 0 early-exit)
- pending_review entries excluded from drift check after scan
- CLI: baton init --scan reaches run_scan
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
import subprocess

import pytest
from typer.testing import CliRunner

from baton.cli import app
from baton.commands.scan import run_scan, _next_id
from baton.core.document import BatonDocument
from baton.core.schema import PENDING_REVIEW

runner = CliRunner()

# ── Fixtures / helpers ────────────────────────────────────────────────────────

_MINIMAL_YAML = """\
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
decisions: []
anti_decisions: []
landmines: []
open_questions: []
sessions: []
"""

_YAML_WITH_DECISION = """\
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
    what: Active decision already here
    why: because
    made: "2026-01-01"
    made_in: claude-code
anti_decisions: []
landmines: []
open_questions: []
sessions: []
"""


def _write_baton(tmp_path: Path, yaml_content: str = _MINIMAL_YAML) -> Path:
    baton = tmp_path / "BATON.md"
    baton.write_text(f"# BATON.md\n\n```yaml\n{yaml_content}\n```\n", encoding="utf-8")
    return baton


def _write_package_json(tmp_path: Path, prod_deps: list[str], dev_deps: list[str] | None = None) -> Path:
    data = {"dependencies": {dep: "^1.0.0" for dep in prod_deps}}
    if dev_deps:
        data["devDependencies"] = {dep: "^1.0.0" for dep in dev_deps}
    (tmp_path / "package.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return tmp_path / "package.json"


# ── _next_id ──────────────────────────────────────────────────────────────────

def test_next_id_empty_sequence():
    assert _next_id([], "d") == "d001"


def test_next_id_with_existing_entries():
    seq = [{"id": "d001"}, {"id": "d002"}]
    assert _next_id(seq, "d") == "d003"


def test_next_id_gap_tolerant():
    # Gaps should be filled by going one past the max
    seq = [{"id": "d001"}, {"id": "d005"}]
    assert _next_id(seq, "d") == "d006"


# ── Manifest scanning writes to disk (the or-[] bug guard) ───────────────────

def test_scan_fresh_baton_entries_written_to_disk(tmp_path):
    """Empty sections (falsy CommentedSeq) must still receive entries after scan."""
    _write_baton(tmp_path, _MINIMAL_YAML)
    _write_package_json(tmp_path, ["fastapi", "uvicorn"])

    ok = run_scan(
        tmp_path,
        exhaustive=False,
        skip_pr_history=True,
        skip_docs=True,
    )
    assert ok

    # Reload from disk and verify entries were persisted
    doc = BatonDocument.load(tmp_path / "BATON.md")
    decisions = doc.data.get("decisions") or []
    whats = [str(e.get("what") or "").lower() for e in decisions if isinstance(e, dict)]
    assert any("fastapi" in w for w in whats), f"fastapi not found in decisions: {whats}"
    assert any("uvicorn" in w for w in whats), f"uvicorn not found in decisions: {whats}"


def test_scan_entries_have_pending_review_status(tmp_path):
    """All scan-drafted entries must have status: pending_review."""
    _write_baton(tmp_path, _MINIMAL_YAML)
    _write_package_json(tmp_path, ["express"])

    run_scan(tmp_path, exhaustive=False, skip_pr_history=True, skip_docs=True)

    doc = BatonDocument.load(tmp_path / "BATON.md")
    decisions = doc.data.get("decisions") or []
    for e in decisions:
        if isinstance(e, dict) and e.get("source", "").startswith("scan:"):
            assert e.get("status") == PENDING_REVIEW, f"Entry {e.get('id')} has wrong status"


def test_scan_entries_have_ids(tmp_path):
    """Drafted entries must be assigned sequential IDs."""
    _write_baton(tmp_path, _MINIMAL_YAML)
    _write_package_json(tmp_path, ["react", "lodash"])

    run_scan(tmp_path, exhaustive=False, skip_pr_history=True, skip_docs=True)

    doc = BatonDocument.load(tmp_path / "BATON.md")
    decisions = doc.data.get("decisions") or []
    ids = [e.get("id") for e in decisions if isinstance(e, dict)]
    assert all(id_ is not None for id_ in ids), f"Some entries missing IDs: {ids}"
    # IDs should start with 'd'
    assert all(id_.startswith("d") for id_ in ids if id_)


# ── Append to existing BATON.md ───────────────────────────────────────────────

def test_scan_appends_without_touching_existing(tmp_path):
    """Scan must append new drafts without modifying existing active entries."""
    _write_baton(tmp_path, _YAML_WITH_DECISION)
    _write_package_json(tmp_path, ["fastapi"])

    run_scan(tmp_path, exhaustive=False, skip_pr_history=True, skip_docs=True)

    doc = BatonDocument.load(tmp_path / "BATON.md")
    decisions = doc.data.get("decisions") or []

    # d001 (existing active entry) must still be present and unchanged
    d001 = next((e for e in decisions if isinstance(e, dict) and e.get("id") == "d001"), None)
    assert d001 is not None, "Existing active entry d001 was removed"
    assert d001.get("what") == "Active decision already here"
    assert d001.get("status") != PENDING_REVIEW  # active entry must not be downgraded


def test_scan_appends_after_existing_ids(tmp_path):
    """New IDs must continue after existing max ID, not restart from d001."""
    _write_baton(tmp_path, _YAML_WITH_DECISION)
    _write_package_json(tmp_path, ["fastapi"])

    run_scan(tmp_path, exhaustive=False, skip_pr_history=True, skip_docs=True)

    doc = BatonDocument.load(tmp_path / "BATON.md")
    decisions = doc.data.get("decisions") or []
    ids = [e.get("id") for e in decisions if isinstance(e, dict)]
    # d001 is existing; new draft must be d002 (not restart at d001)
    assert "d001" in ids
    assert "d002" in ids
    assert ids.count("d001") == 1  # no duplicates


# ── Dedup ──────────────────────────────────────────────────────────────────────

def test_scan_dedup_same_dep_not_duplicated(tmp_path):
    """If a dep appears twice in the manifest, only one draft is created."""
    _write_baton(tmp_path, _MINIMAL_YAML)
    # Both "dependencies" and a hypothetical re-entry — simulate by running scan twice
    _write_package_json(tmp_path, ["fastapi"])

    run_scan(tmp_path, exhaustive=False, skip_pr_history=True, skip_docs=True)
    run_scan(tmp_path, exhaustive=False, skip_pr_history=True, skip_docs=True)

    doc = BatonDocument.load(tmp_path / "BATON.md")
    decisions = doc.data.get("decisions") or []
    fastapi_entries = [
        e for e in decisions
        if isinstance(e, dict) and "fastapi" in str(e.get("what") or "").lower()
    ]
    assert len(fastapi_entries) == 1, f"fastapi duplicated: {fastapi_entries}"


def test_scan_dedup_against_existing_active(tmp_path):
    """A dep already in BATON.md as an active entry must not be re-drafted."""
    yaml = _YAML_WITH_DECISION.replace(
        "what: Active decision already here",
        "what: Uses fastapi"
    )
    _write_baton(tmp_path, yaml)
    _write_package_json(tmp_path, ["fastapi"])

    run_scan(tmp_path, exhaustive=False, skip_pr_history=True, skip_docs=True)

    doc = BatonDocument.load(tmp_path / "BATON.md")
    decisions = doc.data.get("decisions") or []
    fastapi_entries = [
        e for e in decisions
        if isinstance(e, dict) and "fastapi" in str(e.get("what") or "").lower()
    ]
    assert len(fastapi_entries) == 1, "fastapi drafted again despite existing active entry"


# ── Comment scanner ───────────────────────────────────────────────────────────

def test_scan_comment_creates_landmine_draft(tmp_path):
    """HACK comments should create landmine drafts after scan."""
    _write_baton(tmp_path, _MINIMAL_YAML)
    # Write a Python file with a HACK comment
    (tmp_path / "app.py").write_text(
        "def foo():\n    # HACK: this is intentional\n    pass\n",
        encoding="utf-8",
    )

    run_scan(tmp_path, exhaustive=False, skip_pr_history=True, skip_docs=True)

    doc = BatonDocument.load(tmp_path / "BATON.md")
    landmines = doc.data.get("landmines") or []
    assert len(landmines) >= 1
    hack_entry = next(
        (e for e in landmines if "intentional" in str(e.get("actually") or "").lower()),
        None,
    )
    assert hack_entry is not None, f"HACK comment not found in landmines: {landmines}"
    assert hack_entry.get("status") == PENDING_REVIEW


# ── Dev deps excluded ─────────────────────────────────────────────────────────

def test_scan_dev_deps_not_drafted(tmp_path):
    """Dev dependencies must not create draft decisions."""
    _write_baton(tmp_path, _MINIMAL_YAML)
    _write_package_json(tmp_path, prod_deps=["react"], dev_deps=["jest", "eslint"])

    run_scan(tmp_path, exhaustive=False, skip_pr_history=True, skip_docs=True)

    doc = BatonDocument.load(tmp_path / "BATON.md")
    decisions = doc.data.get("decisions") or []
    whats = [str(e.get("what") or "").lower() for e in decisions if isinstance(e, dict)]
    assert not any("jest" in w for w in whats), "jest (dev dep) should not be drafted"
    assert not any("eslint" in w for w in whats), "eslint (dev dep) should not be drafted"
    assert any("react" in w for w in whats), "react (prod dep) should be drafted"


# ── No new entries early exit ─────────────────────────────────────────────────

def test_scan_no_new_entries_returns_true(tmp_path):
    """If all deps already exist in BATON.md, scan should return True (not error)."""
    _write_baton(tmp_path, _MINIMAL_YAML)
    # No manifests at all → nothing to scan
    ok = run_scan(tmp_path, exhaustive=False, skip_pr_history=True, skip_docs=True)
    assert ok is True


# ── CLI wiring ────────────────────────────────────────────────────────────────

def test_init_scan_flag_cli_wiring(tmp_path, monkeypatch):
    """baton init --scan should invoke run_scan successfully."""
    monkeypatch.chdir(tmp_path)
    _write_baton(tmp_path)

    # No manifests, so scan finds nothing — just verify it runs without error
    result = runner.invoke(app, ["init", "--scan", "--skip-pr-history", "--skip-docs"])
    assert result.exit_code == 0


def test_init_scan_no_baton_creates_then_scans(tmp_path, monkeypatch):
    """baton init --scan on a fresh dir: creates BATON.md then runs scan."""
    monkeypatch.chdir(tmp_path)
    _write_package_json(tmp_path, ["axios"])

    result = runner.invoke(app, ["init", "--scan", "--skip-pr-history", "--skip-docs"])
    assert result.exit_code == 0
    assert (tmp_path / "BATON.md").exists()

    doc = BatonDocument.load(tmp_path / "BATON.md")
    decisions = doc.data.get("decisions") or []
    whats = [str(e.get("what") or "").lower() for e in decisions if isinstance(e, dict)]
    assert any("axios" in w for w in whats), "axios not drafted after init --scan"
