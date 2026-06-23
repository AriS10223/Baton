"""
test_pending_review.py -- Tests for pending_review exclusion across all blast-radius sites.

Verifies that entries with ``status: pending_review`` are excluded from:
- Drift detection (baton check --drift)
- Sync rendering (baton sync)
- Score counts (baton score)
- Supersession detect_overlaps
- _merge_delta dedup (baton end)

And that active_entries() helper works correctly.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from baton.core.schema import PENDING_REVIEW, active_entries


# ── Fixtures ──────────────────────────────────────────────────────────────────

ACTIVE_DECISION = {
    "id": "d001",
    "what": "Use FastAPI",
    "why": "native async",
    "made": "2026-01-01",
    "made_in": "claude-code",
}

PENDING_DECISION = {
    "id": "d002",
    "what": "Uses react",
    "why": "",
    "made": "2026-06-01",
    "made_in": "",
    "source": "scan:manifest",
    "confidence": "high",
    "status": PENDING_REVIEW,
    "evidence": {"type": "dependency", "value": "react"},
}

ACTIVE_ANTI = {
    "id": "a001",
    "rejected": "moment.js",
    "why": "bundle size",
    "ruled_out": "2026-01-01",
    "pattern": {"type": "dependency", "value": "moment"},
    "severity": "block",
}

PENDING_ANTI = {
    "id": "a002",
    "rejected": "lodash",
    "why": "",
    "ruled_out": "2026-06-01",
    "source": "scan:pr_history",
    "confidence": "medium",
    "status": PENDING_REVIEW,
}

ACTIVE_LANDMINE = {
    "id": "l001",
    "location": "auth/callback.py:42",
    "looks_like": "dead code",
    "actually": "OAuth state machine",
    "marker": "l001",
}

PENDING_LANDMINE = {
    "id": "l002",
    "location": "app.py:10",
    "looks_like": "wrong",
    "actually": "HACK: intentional workaround",
    "source": "scan:comment",
    "confidence": "high",
    "status": PENDING_REVIEW,
}


# ── active_entries() ──────────────────────────────────────────────────────────

def test_active_entries_keeps_entries_without_status():
    entries = [{"id": "d001", "what": "foo"}]
    assert active_entries(entries) == entries


def test_active_entries_keeps_active_status():
    entries = [{"id": "d001", "what": "foo", "status": "active"}]
    assert active_entries(entries) == entries


def test_active_entries_drops_pending_review():
    entries = [
        {"id": "d001", "what": "foo"},
        {"id": "d002", "what": "bar", "status": PENDING_REVIEW},
    ]
    result = active_entries(entries)
    assert len(result) == 1
    assert result[0]["id"] == "d001"


def test_active_entries_empty_list():
    assert active_entries([]) == []


def test_active_entries_none_input():
    assert active_entries(None) == []  # type: ignore


def test_active_entries_all_pending():
    entries = [
        {"id": "d001", "status": PENDING_REVIEW},
        {"id": "d002", "status": PENDING_REVIEW},
    ]
    assert active_entries(entries) == []


# ── Drift detection exclusion ─────────────────────────────────────────────────

def _make_baton_yaml(decisions=None, anti_decisions=None, landmines=None):
    """Build a minimal BATON.md YAML string with the given entry lists."""
    import yaml  # ruamel or stdlib; we just need to produce valid YAML for the test
    from ruamel.yaml import YAML
    import io
    yml = YAML()
    data = {
        "baton_version": "1.0",
        "last_updated": "2026-01-01",
        "last_session_tool": "",
        "project": {"name": "test", "purpose": "testing", "target_user": "devs", "stage": "prototype"},
        "architecture": {"overview": "", "key_directories": [], "entry_point": "", "data_flow": ""},
        "stack": [],
        "laws": [],
        "current_sprint": {"goal": "test", "done": [], "in_progress": [], "blocked": [], "next": []},
        "decisions": decisions or [],
        "anti_decisions": anti_decisions or [],
        "landmines": landmines or [],
        "open_questions": [],
        "sessions": [],
    }
    buf = io.StringIO()
    yml.dump(data, buf)
    return buf.getvalue()


def _write_baton(repo_root, yaml_data):
    baton_path = repo_root / "BATON.md"
    baton_path.write_text(f"# BATON.md\n\n```yaml\n{yaml_data}\n```\n", encoding="utf-8")
    return baton_path


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    _git(["init"], tmp_path)
    _git(["config", "user.email", "test@test.com"], tmp_path)
    _git(["config", "user.name", "Test"], tmp_path)
    return tmp_path


def test_drift_excludes_pending_anti_decision(repo):
    """A pending_review anti_decision with a block pattern must NOT trigger a drift alert."""
    from baton.commands.check import run_check

    pending_anti = dict(PENDING_ANTI)
    pending_anti["pattern"] = {"type": "dependency", "value": "lodash"}
    pending_anti["severity"] = "block"

    yaml = _make_baton_yaml(anti_decisions=[pending_anti])
    _write_baton(repo, yaml)
    _git(["add", "."], repo)
    _git(["commit", "-m", "init"], repo)

    # Diff that adds lodash -- should NOT alert because entry is pending_review
    diff_text = "+  \"lodash\": \"^4.0.0\""
    # We can't easily inject a diff here without a second commit, so use staged
    (repo / "package.json").write_text('{"dependencies": {"lodash": "^4.0.0"}}')
    _git(["add", "package.json"], repo)

    code = run_check(repo, staged=True, fmt="json")
    # Should exit 0 (no alerts) because pending_review entry is excluded
    assert code == 0


def test_drift_excludes_pending_decision(repo):
    """A pending_review decision with evidence must NOT trigger a drift alert."""
    from baton.commands.check import run_check

    pending = dict(PENDING_DECISION)
    pending["evidence"] = {"type": "dependency", "value": "fastapi"}

    yaml = _make_baton_yaml(decisions=[pending])
    _write_baton(repo, yaml)
    _git(["add", "."], repo)
    _git(["commit", "-m", "init"], repo)

    code = run_check(repo, staged=True, fmt="json")
    assert code == 0


def test_drift_still_catches_active_entry(repo):
    """Active entries still trigger drift alerts (regression guard)."""
    from baton.commands.check import run_check

    active_anti = dict(ACTIVE_ANTI)

    yaml = _make_baton_yaml(anti_decisions=[active_anti])
    _write_baton(repo, yaml)
    _git(["add", "."], repo)
    _git(["commit", "-m", "init"], repo)

    # Stage a change that adds moment.js (one dep per line so diff parser matches)
    (repo / "package.json").write_text(
        '{\n  "dependencies": {\n    "moment": "^2.0.0"\n  }\n}'
    )
    _git(["add", "package.json"], repo)

    code = run_check(repo, staged=True, fmt="json")
    assert code != 0  # should alert on block-severity anti_decision violation


# ── Sync exclusion ────────────────────────────────────────────────────────────

def test_sync_does_not_render_pending_decisions(tmp_path):
    """pending_review decisions must not appear in synced agent files."""
    from baton.commands.sync import _render_data

    data = {
        "decisions": [ACTIVE_DECISION, PENDING_DECISION],
        "anti_decisions": [ACTIVE_ANTI, PENDING_ANTI],
        "landmines": [ACTIVE_LANDMINE, PENDING_LANDMINE],
        "open_questions": [],
    }
    filtered = _render_data(data)

    # Verify filtered lists contain only active entries
    assert len(filtered["decisions"]) == 1
    assert filtered["decisions"][0]["id"] == "d001"
    assert len(filtered["anti_decisions"]) == 1
    assert filtered["anti_decisions"][0]["id"] == "a001"
    assert len(filtered["landmines"]) == 1
    assert filtered["landmines"][0]["id"] == "l001"


# ── Score exclusion ───────────────────────────────────────────────────────────

def test_score_excludes_pending_decisions():
    """Score checks must not count pending_review decisions as real entries."""
    from baton.core.schema import _check_decisions, _check_anti_decisions, _check_landmines

    data_pending_only = {
        "decisions": [PENDING_DECISION],
        "anti_decisions": [PENDING_ANTI],
        "landmines": [PENDING_LANDMINE],
    }
    # With only pending entries, scores should be "fail" (no active entries)
    status_d, _, _ = _check_decisions(data_pending_only)
    assert status_d == "fail"

    status_a, _, _ = _check_anti_decisions(data_pending_only)
    assert status_a == "fail"

    status_l, _, _ = _check_landmines(data_pending_only)
    assert status_l == "fail"


def test_score_counts_active_decisions():
    """Score checks must count active decisions correctly."""
    from baton.core.schema import _check_decisions

    data = {"decisions": [ACTIVE_DECISION, PENDING_DECISION]}
    status, detail, _ = _check_decisions(data)
    assert status == "pass"
    assert "1 entry" in detail  # only 1 active entry counted


# ── Supersession exclusion ────────────────────────────────────────────────────

def test_detect_overlaps_excludes_pending_existing():
    """detect_overlaps must not report a match against a pending_review existing entry."""
    from baton.core.supersede import detect_overlaps

    data = {
        "decisions": [PENDING_DECISION],  # pending_review, should be ignored
        "anti_decisions": [],
        "landmines": [],
    }
    # Draft has the same dep evidence as the pending entry
    delta = {
        "decisions": [{
            "what": "Uses react for UI",
            "why": "for performance",
            "evidence": {"type": "dependency", "value": "react"},
        }]
    }
    overlaps = detect_overlaps(data, delta)
    assert overlaps == []  # pending_review entry must be excluded from comparison pool


def test_detect_overlaps_still_catches_active_match():
    """detect_overlaps must still report matches against active entries."""
    from baton.core.supersede import detect_overlaps

    data = {
        "decisions": [ACTIVE_DECISION],  # active, should be matched
        "anti_decisions": [],
        "landmines": [],
    }
    delta = {
        "decisions": [{
            "what": "Use FastAPI",  # same text as ACTIVE_DECISION
            "why": "for performance",
        }]
    }
    overlaps = detect_overlaps(data, delta)
    assert len(overlaps) == 1
    assert overlaps[0]["signal"] == "text_similarity"


# ── _merge_delta dedup exclusion ──────────────────────────────────────────────

def test_merge_delta_does_not_dedup_against_pending_review(tmp_path):
    """A real baton-end decision must not be silently dropped against a pending draft."""
    from ruamel.yaml import YAML
    import io

    from baton.commands.end import _merge_delta

    yml = YAML()
    data = {
        "decisions": [dict(PENDING_DECISION)],  # "Uses react" is pending
        "anti_decisions": [],
        "landmines": [],
        "open_questions": [],
        "current_sprint": {"done": [], "next": []},
        "sessions": [],
    }
    # CommentedMap needed for ruamel; load via YAML
    buf = io.StringIO()
    yml.dump(data, buf)
    ruamel_data = yml.load(buf.getvalue())

    accepted = {
        "decisions": [{"what": "Uses react", "why": "for SSR", "made_in": "claude-code"}],
        "session": {"summary": "test", "highlights": []},
    }
    _merge_delta(ruamel_data, accepted, sha=None, tool="claude-code", today="2026-06-23")

    # The new active decision should have been appended despite the pending draft with same text
    decisions = ruamel_data.get("decisions", [])
    # d002 = pending draft, d003 = newly merged active entry
    assert len(decisions) == 2
    new_entry = next((d for d in decisions if d.get("id") not in ("d002",) and d.get("what") == "Uses react"), None)
    assert new_entry is not None, "Active entry was not merged because it deduped against pending draft"
    assert new_entry.get("status") != PENDING_REVIEW
