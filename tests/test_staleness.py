"""
tests/test_staleness.py -- Tests for baton/core/staleness.py

Uses in-memory data dicts (no filesystem).  The ``today`` date is
pinned to a known value in each test so age-based checks are deterministic.
"""
from __future__ import annotations

import datetime

import pytest
from baton.core.staleness import (
    COMPRESSIBLE_CHAIN,
    DECISION_MISSING_EVIDENCE,
    ENTRY_COUNTS,
    IDLESS_LANDMINE,
    POSSIBLY_RESOLVED_LANDMINE,
    RESOLVED_LANDMINE,
    RESOLVED_QUESTION_PRESENT,
    STALE_DECISION,
    STALE_QUESTION,
    SUPERSEDED_PRESENT,
    PrunableEntry,
    chain_depth,
    chain_heads,
    collect_findings,
    collect_prunable,
    detect_compressible_chains,
    detect_idless_landmines,
    detect_missing_evidence,
    detect_resolved_landmines,
    detect_resolved_questions_present,
    detect_stale_decisions,
    detect_stale_questions,
    detect_superseded_present,
    entry_counts,
    is_stale_question,
    parse_date,
    question_age_days,
)

TODAY = datetime.date(2025, 6, 25)


# ── parse_date ────────────────────────────────────────────────────────────────

def test_parse_date_valid():
    d = parse_date("2024-01-15")
    assert d == datetime.date(2024, 1, 15)


def test_parse_date_invalid():
    assert parse_date("not-a-date") is None
    assert parse_date("") is None
    assert parse_date(None) is None
    assert parse_date(42) is None


def test_parse_date_strips_whitespace():
    d = parse_date("  2024-03-01  ")
    assert d == datetime.date(2024, 3, 1)


# ── question_age_days ─────────────────────────────────────────────────────────

def test_question_age_days_correct():
    entry = {"raised": "2025-05-26"}  # 30 days before TODAY
    age = question_age_days(entry, TODAY)
    assert age == 30


def test_question_age_days_missing_raised():
    assert question_age_days({}, TODAY) is None
    assert question_age_days({"raised": ""}, TODAY) is None


# ── is_stale_question ─────────────────────────────────────────────────────────

def test_is_stale_question_over_threshold():
    entry = {"raised": "2025-05-25", "status": "open"}  # 31 days
    assert is_stale_question(entry, TODAY, max_age_days=30) is True


def test_is_stale_question_under_threshold():
    entry = {"raised": "2025-06-10", "status": "open"}  # 15 days
    assert is_stale_question(entry, TODAY, max_age_days=30) is False


def test_is_stale_question_resolved_not_stale():
    # Resolved questions don't count as stale (only 'open' counts)
    entry = {"raised": "2024-01-01", "status": "resolved"}
    assert is_stale_question(entry, TODAY, max_age_days=30) is False


def test_is_stale_question_no_raised():
    entry = {"status": "open"}
    assert is_stale_question(entry, TODAY, max_age_days=30) is False


# ── chain_depth ───────────────────────────────────────────────────────────────

def _build_linear_chain():
    """d001 <- d002 <- d003 (head-inclusive depth = 3)"""
    return {
        "decisions": [
            {"id": "d001", "what": "old decision", "made": "2024-01-01"},
            {"id": "d002", "what": "better decision", "made": "2024-06-01",
             "supersedes": ["d001"]},
            {"id": "d003", "what": "latest decision", "made": "2025-01-01",
             "supersedes": ["d002"]},
        ]
    }


def test_chain_depth_linear():
    data = _build_linear_chain()
    assert chain_depth(data, "d003") == 3  # d003 + d002 + d001


def test_chain_depth_no_ancestors():
    data = {"decisions": [{"id": "d001", "what": "standalone"}]}
    assert chain_depth(data, "d001") == 1


def test_chain_depth_two():
    data = {
        "decisions": [
            {"id": "d001", "what": "old"},
            {"id": "d002", "what": "new", "supersedes": ["d001"]},
        ]
    }
    assert chain_depth(data, "d002") == 2


# ── chain_heads ───────────────────────────────────────────────────────────────

def test_chain_heads_finds_head():
    data = _build_linear_chain()
    heads = chain_heads(data)
    # d003 is active and has supersedes; d002 is superseded by d003
    assert "d003" in heads
    assert "d002" not in heads  # superseded, not a head
    assert "d001" not in heads  # superseded


def test_chain_heads_empty_data():
    assert chain_heads({}) == []


def test_chain_heads_no_chains():
    data = {"decisions": [{"id": "d001", "what": "standalone"}]}
    assert chain_heads(data) == []


# ── detect_superseded_present ─────────────────────────────────────────────────

def test_detect_superseded_present_found():
    data = _build_linear_chain()
    findings = detect_superseded_present(data)
    assert len(findings) == 1
    f = findings[0]
    assert f["type"] == SUPERSEDED_PRESENT
    assert f["severity"] == "warn"
    assert "d001" in f["entry_ids"]
    assert "d002" in f["entry_ids"]


def test_detect_superseded_present_none():
    data = {"decisions": [{"id": "d001", "what": "standalone"}]}
    assert detect_superseded_present(data) == []


def test_detect_superseded_present_empty():
    assert detect_superseded_present({}) == []


# ── detect_resolved_landmines ─────────────────────────────────────────────────

def test_detect_confirmed_resolved_landmine():
    data = {
        "landmines": [
            {"id": "l001", "location": "src/auth.py", "looks_like": "bug",
             "actually": "intentional", "status": "confirmed_resolved"},
        ]
    }
    findings = detect_resolved_landmines(data)
    assert len(findings) == 1
    assert findings[0]["type"] == RESOLVED_LANDMINE
    assert findings[0]["severity"] == "warn"
    assert "l001" in findings[0]["entry_ids"]


def test_detect_possibly_resolved_landmine():
    data = {
        "landmines": [
            {"id": "l002", "location": "src/db.py", "looks_like": "slow",
             "actually": "ok", "status": "possibly_resolved"},
        ]
    }
    findings = detect_resolved_landmines(data)
    assert len(findings) == 1
    assert findings[0]["type"] == POSSIBLY_RESOLVED_LANDMINE
    assert findings[0]["severity"] == "info"


def test_detect_open_landmine_not_flagged():
    data = {
        "landmines": [
            {"id": "l001", "location": "src/auth.py", "looks_like": "bug",
             "actually": "intentional", "status": "open"},
        ]
    }
    assert detect_resolved_landmines(data) == []


# ── detect_stale_decisions ────────────────────────────────────────────────────

def test_detect_stale_decisions_found():
    data = {
        "decisions": [
            {"id": "d001", "what": "Use PyYAML", "status": "stale"},
            {"id": "d002", "what": "Use ruamel", "status": "active"},
        ]
    }
    findings = detect_stale_decisions(data)
    assert len(findings) == 1
    assert findings[0]["type"] == STALE_DECISION
    assert "d001" in findings[0]["entry_ids"]


def test_detect_stale_decisions_contradicted():
    data = {
        "decisions": [
            {"id": "d001", "what": "Use PyYAML", "status": "contradicted"},
        ]
    }
    findings = detect_stale_decisions(data)
    assert len(findings) == 1
    assert "d001" in findings[0]["entry_ids"]


def test_detect_stale_decisions_no_status_not_flagged():
    data = {
        "decisions": [
            {"id": "d001", "what": "Use Python"},  # no status field
        ]
    }
    assert detect_stale_decisions(data) == []


# ── detect_stale_questions ────────────────────────────────────────────────────

def test_detect_stale_question_40_days():
    old_date = (TODAY - datetime.timedelta(days=40)).isoformat()
    data = {
        "open_questions": [
            {"id": "q001", "question": "Which ORM?", "raised": old_date, "status": "open"},
        ]
    }
    findings = detect_stale_questions(data, TODAY, max_age_days=30)
    assert len(findings) == 1
    assert "q001" in findings[0]["entry_ids"]


def test_detect_stale_question_20_days_not_flagged():
    recent_date = (TODAY - datetime.timedelta(days=20)).isoformat()
    data = {
        "open_questions": [
            {"id": "q001", "question": "Which ORM?", "raised": recent_date, "status": "open"},
        ]
    }
    assert detect_stale_questions(data, TODAY, max_age_days=30) == []


# ── detect_resolved_questions_present ────────────────────────────────────────

def test_detect_resolved_question_present():
    data = {
        "open_questions": [
            {"id": "q001", "question": "Which DB?", "status": "resolved",
             "resolved_date": "2025-01-01"},
        ]
    }
    findings = detect_resolved_questions_present(data)
    assert len(findings) == 1
    assert findings[0]["type"] == RESOLVED_QUESTION_PRESENT
    assert findings[0]["severity"] == "info"
    assert "q001" in findings[0]["entry_ids"]


def test_detect_open_question_not_flagged_as_resolved():
    data = {
        "open_questions": [
            {"id": "q001", "question": "Which DB?", "status": "open"},
        ]
    }
    assert detect_resolved_questions_present(data) == []


# ── detect_compressible_chains ────────────────────────────────────────────────

def test_detect_compressible_chain_depth_3():
    data = _build_linear_chain()
    findings = detect_compressible_chains(data, min_depth=3)
    assert len(findings) == 1
    f = findings[0]
    assert f["type"] == COMPRESSIBLE_CHAIN
    assert "d003" in f["entry_ids"]


def test_detect_compressible_chain_below_threshold():
    data = _build_linear_chain()
    # With min_depth=4, the depth-3 chain should not be flagged
    findings = detect_compressible_chains(data, min_depth=4)
    assert findings == []


def test_detect_compressible_chain_depth_2_not_flagged_at_3():
    data = {
        "decisions": [
            {"id": "d001", "what": "old"},
            {"id": "d002", "what": "new", "supersedes": ["d001"]},
        ]
    }
    findings = detect_compressible_chains(data, min_depth=3)
    assert findings == []


# ── detect_missing_evidence ───────────────────────────────────────────────────

def test_detect_missing_evidence():
    data = {
        "decisions": [
            {"id": "d001", "what": "Use ruamel.yaml"},  # no evidence
            {"id": "d002", "what": "Use typer",
             "evidence": {"type": "dependency", "value": "typer"}},
        ]
    }
    findings = detect_missing_evidence(data)
    assert len(findings) == 1
    assert findings[0]["type"] == DECISION_MISSING_EVIDENCE
    assert findings[0]["severity"] == "info"
    assert "d001" in findings[0]["entry_ids"]


def test_detect_no_missing_evidence():
    data = {
        "decisions": [
            {"id": "d001", "what": "Use typer",
             "evidence": {"type": "dependency", "value": "typer"}},
        ]
    }
    assert detect_missing_evidence(data) == []


# ── detect_idless_landmines ───────────────────────────────────────────────────

def test_detect_idless_landmine():
    data = {
        "landmines": [
            {"location": "src/hack.py", "looks_like": "bug", "actually": "intentional"},
        ]
    }
    findings = detect_idless_landmines(data)
    assert len(findings) == 1
    f = findings[0]
    assert f["type"] == IDLESS_LANDMINE
    assert f["severity"] == "info"
    assert f["entry_ids"] == []


def test_detect_idless_landmine_none_when_all_have_ids():
    data = {
        "landmines": [
            {"id": "l001", "location": "src/hack.py", "looks_like": "bug",
             "actually": "intentional"},
        ]
    }
    assert detect_idless_landmines(data) == []


# ── entry_counts ──────────────────────────────────────────────────────────────

def test_entry_counts():
    data = {
        "decisions":      [{"id": "d001", "what": "x"}] * 3,
        "anti_decisions": [{"id": "a001", "rejected": "y"}],
        "landmines":      [],
        "open_questions": [{"id": "q001", "question": "z"}] * 2,
    }
    f = entry_counts(data)
    assert f["type"] == ENTRY_COUNTS
    assert f["severity"] == "info"
    assert "decisions=3" in f["detail"]
    assert "total=6" in f["detail"]


# ── collect_findings integration ──────────────────────────────────────────────

class _MockConfig:
    staleness_question_days = 30
    compress_min_depth = 3


def test_collect_findings_empty_data():
    findings = collect_findings({}, _MockConfig(), TODAY)
    # Should always have entry_counts finding
    types = [f["type"] for f in findings]
    assert ENTRY_COUNTS in types


def test_collect_findings_detects_stale_decision():
    data = {
        "decisions": [
            {"id": "d001", "what": "Use PyYAML", "status": "stale"},
        ]
    }
    findings = collect_findings(data, _MockConfig(), TODAY)
    types = [f["type"] for f in findings]
    assert STALE_DECISION in types


def test_collect_findings_detects_superseded():
    data = _build_linear_chain()
    findings = collect_findings(data, _MockConfig(), TODAY)
    types = [f["type"] for f in findings]
    assert SUPERSEDED_PRESENT in types


# ── collect_prunable ──────────────────────────────────────────────────────────

def test_collect_prunable_priority_order():
    """Resolved questions (priority 1) must come before stale questions (priority 3)."""
    old_date = (TODAY - datetime.timedelta(days=40)).isoformat()
    data = {
        "open_questions": [
            {"id": "q001", "question": "Stale open Q", "raised": old_date, "status": "open"},
            {"id": "q002", "question": "Resolved Q", "status": "resolved", "resolved_date": "2025-01-01"},
        ]
    }
    prunable = collect_prunable(data, _MockConfig(), TODAY)
    # q002 (resolved, priority=1) must come first
    assert len(prunable) >= 2
    assert prunable[0].entry.get("id") == "q002"
    # q001 (stale open, priority=3) comes later
    ids = [p.entry.get("id") for p in prunable]
    assert ids.index("q002") < ids.index("q001")


def test_collect_prunable_excludes_superseded_ancestors():
    """Superseded ancestors must NOT appear in collect_prunable (only --compress)."""
    data = _build_linear_chain()
    prunable = collect_prunable(data, _MockConfig(), TODAY)
    ids = [p.entry.get("id") for p in prunable]
    assert "d001" not in ids
    assert "d002" not in ids


def test_collect_prunable_empty():
    data = {
        "decisions": [{"id": "d001", "what": "Good decision"}],
    }
    assert collect_prunable(data, _MockConfig(), TODAY) == []
