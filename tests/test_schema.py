"""
test_schema.py — Tests for schema.py (SCORE_CHECKS integrity and check functions).
"""
from __future__ import annotations

import pytest

from baton.core.schema import (
    SCORE_CHECKS,
    VALID_QUESTION_STATUSES,
    _check_anti_decisions,
    _check_decisions,
    _check_inprogress_owners,
    _check_landmines,
    _check_laws,
    _check_open_question_statuses,
    _check_project_purpose,
    _check_sprint_goal,
    _check_stack_entries,
    _check_stack_gotchas,
    _check_stack_why_version,
)


# ── Invariants ────────────────────────────────────────────────────────────────

def test_score_checks_total_100() -> None:
    assert sum(c.points for c in SCORE_CHECKS) == 100


def test_score_checks_all_have_unique_ids() -> None:
    ids = [c.id for c in SCORE_CHECKS]
    assert len(ids) == len(set(ids))


def test_score_checks_warn_points_lte_full_points() -> None:
    for c in SCORE_CHECKS:
        assert c.warn_points <= c.points, f"{c.id}: warn_points > points"


# ── project_purpose ───────────────────────────────────────────────────────────

def test_purpose_pass() -> None:
    status, _, _ = _check_project_purpose({"project": {"purpose": "Solve X for Y"}})
    assert status == "pass"


def test_purpose_fail_empty_string() -> None:
    status, _, tip = _check_project_purpose({"project": {"purpose": ""}})
    assert status == "fail"
    assert tip


def test_purpose_fail_missing_key() -> None:
    status, _, _ = _check_project_purpose({})
    assert status == "fail"


# ── stack_entries ─────────────────────────────────────────────────────────────

def test_stack_entries_pass() -> None:
    status, detail, _ = _check_stack_entries({"stack": [{"tool": "Flask"}]})
    assert status == "pass"
    assert "1" in detail


def test_stack_entries_fail_empty_list() -> None:
    status, _, _ = _check_stack_entries({"stack": []})
    assert status == "fail"


def test_stack_entries_fail_no_key() -> None:
    status, _, _ = _check_stack_entries({})
    assert status == "fail"


# ── stack_why_version ─────────────────────────────────────────────────────────

def test_stack_why_version_pass() -> None:
    data = {"stack": [{"tool": "Flask", "why": "Simple", "version": "3.0"}]}
    status, _, _ = _check_stack_why_version(data)
    assert status == "pass"


def test_stack_why_version_warn_partial() -> None:
    data = {"stack": [
        {"tool": "Flask", "why": "Simple", "version": "3.0"},
        {"tool": "SQLite", "why": "", "version": ""},
    ]}
    status, detail, tip = _check_stack_why_version(data)
    assert status == "warn"
    assert "missing" in detail
    assert "SQLite" in tip  # missing tool name is in the tip, not the detail


def test_stack_why_version_fail_all_missing() -> None:
    data = {"stack": [{"tool": "Flask", "why": "", "version": ""}]}
    status, _, _ = _check_stack_why_version(data)
    assert status == "fail"


# ── stack_gotchas ─────────────────────────────────────────────────────────────

def test_stack_gotchas_pass_all_present() -> None:
    data = {"stack": [{"tool": "Flask", "gotchas": "Don't upgrade"}]}
    status, _, _ = _check_stack_gotchas(data)
    assert status == "pass"


def test_stack_gotchas_warn_some_missing() -> None:
    data = {"stack": [
        {"tool": "Flask", "gotchas": "Don't upgrade"},
        {"tool": "SQLite", "gotchas": ""},
    ]}
    status, _, _ = _check_stack_gotchas(data)
    assert status == "warn"


def test_stack_gotchas_pass_no_stack() -> None:
    status, _, _ = _check_stack_gotchas({})
    assert status == "pass"


# ── laws ──────────────────────────────────────────────────────────────────────

def test_laws_pass() -> None:
    status, _, _ = _check_laws({"laws": ["Never use TypeScript."]})
    assert status == "pass"


def test_laws_fail_empty() -> None:
    status, _, tip = _check_laws({"laws": []})
    assert status == "fail"
    assert tip


# ── decisions ─────────────────────────────────────────────────────────────────

def test_decisions_pass() -> None:
    status, detail, _ = _check_decisions({"decisions": [{"id": "d001"}]})
    assert status == "pass"
    assert "1" in detail


def test_decisions_fail_empty() -> None:
    status, _, _ = _check_decisions({"decisions": []})
    assert status == "fail"


# ── anti_decisions ────────────────────────────────────────────────────────────

def test_anti_decisions_pass() -> None:
    status, _, _ = _check_anti_decisions({"anti_decisions": [{"id": "a001"}]})
    assert status == "pass"


def test_anti_decisions_fail_empty() -> None:
    status, detail, tip = _check_anti_decisions({"anti_decisions": []})
    assert status == "fail"
    assert tip  # some actionable suggestion is returned
    assert "decided" in tip.lower() or "anti" in tip.lower()


# ── sprint_goal ───────────────────────────────────────────────────────────────

def test_sprint_goal_pass() -> None:
    status, _, _ = _check_sprint_goal({"current_sprint": {"goal": "Build feature X"}})
    assert status == "pass"


def test_sprint_goal_fail_empty() -> None:
    status, _, _ = _check_sprint_goal({"current_sprint": {"goal": ""}})
    assert status == "fail"


# ── in_progress_owners ────────────────────────────────────────────────────────

def test_inprogress_owners_pass_all_have_owner() -> None:
    data = {"current_sprint": {"in_progress": [
        {"feature": "F1", "owner": "Aryan"},
    ]}}
    status, _, _ = _check_inprogress_owners(data)
    assert status == "pass"


def test_inprogress_owners_warn_some_missing() -> None:
    data = {"current_sprint": {"in_progress": [
        {"feature": "F1", "owner": "Aryan"},
        {"feature": "F2", "owner": ""},
    ]}}
    status, detail, tip = _check_inprogress_owners(data)
    assert status == "warn"
    assert "missing" in detail
    assert "F2" in tip  # missing feature name is in the tip, not the detail


def test_inprogress_owners_pass_no_items() -> None:
    data = {"current_sprint": {"in_progress": []}}
    status, _, _ = _check_inprogress_owners(data)
    assert status == "pass"


# ── open_question_statuses ────────────────────────────────────────────────────

def test_open_q_statuses_pass_valid() -> None:
    for s in VALID_QUESTION_STATUSES:
        data = {"open_questions": [{"id": "q001", "status": s}]}
        status, _, _ = _check_open_question_statuses(data)
        assert status == "pass", f"Expected pass for status={s}"


def test_open_q_statuses_warn_invalid() -> None:
    data = {"open_questions": [{"id": "q001", "status": "maybe"}]}
    status, _, _ = _check_open_question_statuses(data)
    assert status == "warn"


def test_open_q_statuses_pass_empty() -> None:
    status, _, _ = _check_open_question_statuses({"open_questions": []})
    assert status == "pass"


# ── landmines ─────────────────────────────────────────────────────────────────

def test_landmines_pass() -> None:
    data = {"landmines": [{"location": "auth/callback.py", "looks_like": "bug", "actually": "intentional"}]}
    status, _, _ = _check_landmines(data)
    assert status == "pass"


def test_landmines_fail_empty() -> None:
    status, detail, tip = _check_landmines({"landmines": []})
    assert status == "fail"
    assert "intentional" in tip.lower()
