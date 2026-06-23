"""
tests/test_scan_pr.py -- Tests for the PR history scanner (baton/core/scan_pr.py).

Uses injectable runner to avoid requiring a real GitHub remote or gh CLI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from baton.core.scan_pr import scan_prs, _why_confidence
from baton.core.schema import PENDING_REVIEW


# ── Runner factory ────────────────────────────────────────────────────────────

def _make_runner(prs: list[dict], has_gh: bool = True, has_remote: bool = True):
    """Injectable runner that fakes gh and git output."""
    def runner(args):
        if args[0] == "gh" and args[1] == "--version":
            if not has_gh:
                return -1, "", "gh: command not found"
            return 0, "gh version 2.0.0", ""
        if args[0] == "git" and "remote" in args:
            if not has_remote:
                return 0, "", ""  # no github.com in output
            return 0, "origin  https://github.com/user/repo.git (fetch)", ""
        if args[0] == "gh" and "pr" in args:
            return 0, json.dumps(prs), ""
        return 0, "", ""
    return runner


# ── Graceful-degradation tests ────────────────────────────────────────────────

def test_gh_not_installed(tmp_path):
    entries, note = scan_prs(tmp_path, runner=_make_runner([], has_gh=False))
    assert entries == []
    assert note == "skipped: gh not found"


def test_no_github_remote(tmp_path):
    entries, note = scan_prs(tmp_path, runner=_make_runner([], has_remote=False))
    assert entries == []
    assert note == "skipped: no GitHub remote"


def test_empty_pr_list(tmp_path):
    entries, note = scan_prs(tmp_path, runner=_make_runner([]))
    assert entries == []
    assert note == "0 PRs scanned"


def test_one_pr_scanned_summary(tmp_path):
    prs = [{"number": 1, "title": "Add Vite", "body": "DECISION: Use Vite", "mergedAt": "2024-01-01"}]
    entries, note = scan_prs(tmp_path, runner=_make_runner(prs))
    assert note == "1 PR scanned"


def test_multiple_prs_summary(tmp_path):
    prs = [
        {"number": i, "title": f"PR {i}", "body": "", "mergedAt": "2024-01-01"}
        for i in range(5)
    ]
    _, note = scan_prs(tmp_path, runner=_make_runner(prs))
    assert note == "5 PRs scanned"


# ── Decision extraction tests ─────────────────────────────────────────────────

def test_decision_extracted(tmp_path):
    prs = [{"number": 1, "title": "", "body": "DECISION: Use Vite", "mergedAt": "2024-01-01"}]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    assert len(entries) == 1
    e = entries[0]
    assert e["what"] == "Use Vite"
    assert e["source"] == "scan:pr_history"
    assert e["status"] == PENDING_REVIEW


def test_decision_in_title(tmp_path):
    prs = [{"number": 1, "title": "DECISION: Use Vite", "body": "", "mergedAt": "2024-01-01"}]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    assert len(entries) == 1
    assert entries[0]["what"] == "Use Vite"


def test_decision_with_why(tmp_path):
    prs = [{
        "number": 1,
        "title": "",
        "body": "DECISION: Use Vite\nWHY: Chosen for native async support and HMR speed",
        "mergedAt": "2024-01-01",
    }]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    assert len(entries) == 1
    e = entries[0]
    assert e["why"] == "Chosen for native async support and HMR speed"
    assert e["confidence"] == "medium"


# ── Anti-decision extraction tests ───────────────────────────────────────────

def test_anti_decision_extracted(tmp_path):
    prs = [{"number": 1, "title": "", "body": "ANTI: moment.js", "mergedAt": "2024-01-01"}]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    assert len(entries) == 1
    e = entries[0]
    assert e["rejected"] == "moment.js"
    assert e["source"] == "scan:pr_history"
    assert e["status"] == PENDING_REVIEW


def test_rejected_marker(tmp_path):
    prs = [{"number": 1, "title": "", "body": "REJECTED: Redux", "mergedAt": "2024-01-01"}]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    assert len(entries) == 1
    assert entries[0]["rejected"] == "Redux"


# ── Landmine extraction tests ─────────────────────────────────────────────────

def test_landmine_extracted(tmp_path):
    prs = [{"number": 1, "title": "", "body": "LANDMINE: The async loop must not be awaited", "mergedAt": "2024-01-01"}]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    assert len(entries) == 1
    e = entries[0]
    assert e["actually"] == "The async loop must not be awaited"
    assert e["source"] == "scan:pr_history"
    assert e["status"] == PENDING_REVIEW


# ── Open question extraction tests ────────────────────────────────────────────

def test_open_question_extracted(tmp_path):
    prs = [{"number": 1, "title": "", "body": "QUESTION: Should we use GraphQL?", "mergedAt": "2024-01-01"}]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    assert len(entries) == 1
    e = entries[0]
    assert e["question"] == "Should we use GraphQL?"
    assert e["status"] == "open"
    assert e["source"] == "scan:pr_history"
    # open_questions do NOT have PENDING_REVIEW status
    assert e["status"] != PENDING_REVIEW


def test_openq_marker(tmp_path):
    prs = [{"number": 1, "title": "", "body": "OPENQ: Should we migrate to Bun?", "mergedAt": "2024-01-01"}]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    assert len(entries) == 1
    assert entries[0]["question"] == "Should we migrate to Bun?"


# ── Status invariants ─────────────────────────────────────────────────────────

def test_decisions_have_pending_review_status(tmp_path):
    prs = [{"number": 1, "title": "", "body": "DECISION: Use PostgreSQL", "mergedAt": "2024-01-01"}]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    for e in entries:
        if "what" in e:
            assert e["status"] == PENDING_REVIEW


def test_anti_decisions_have_pending_review_status(tmp_path):
    prs = [{"number": 1, "title": "", "body": "ANTI: Firebase", "mergedAt": "2024-01-01"}]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    for e in entries:
        if "rejected" in e:
            assert e["status"] == PENDING_REVIEW


def test_landmines_have_pending_review_status(tmp_path):
    prs = [{"number": 1, "title": "", "body": "LANDMINE: Weird recursion here", "mergedAt": "2024-01-01"}]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    for e in entries:
        if "actually" in e:
            assert e["status"] == PENDING_REVIEW


def test_open_questions_have_open_status_not_pending_review(tmp_path):
    prs = [{"number": 1, "title": "", "body": "QUESTION: Do we need caching?", "mergedAt": "2024-01-01"}]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    for e in entries:
        if "question" in e:
            assert e["status"] == "open"
            assert e["status"] != PENDING_REVIEW


# ── Source field ──────────────────────────────────────────────────────────────

def test_all_entries_have_correct_source(tmp_path):
    prs = [{
        "number": 1,
        "title": "",
        "body": (
            "DECISION: Use Vite\n"
            "ANTI: Webpack\n"
            "LANDMINE: The loop delay is intentional\n"
            "QUESTION: Should we add SSR?\n"
        ),
        "mergedAt": "2024-01-01",
    }]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    assert len(entries) == 4
    for e in entries:
        assert e["source"] == "scan:pr_history"


# ── Confidence tests ──────────────────────────────────────────────────────────

def test_why_external_ref_see_slack(tmp_path):
    prs = [{
        "number": 1,
        "title": "",
        "body": "DECISION: Use Vite\nWHY: see Slack",
        "mergedAt": "2024-01-01",
    }]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    assert entries[0]["confidence"] == "low"


def test_why_bare_url(tmp_path):
    prs = [{
        "number": 1,
        "title": "",
        "body": "DECISION: Use Vite\nWHY: https://example.com/blog",
        "mergedAt": "2024-01-01",
    }]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    assert entries[0]["confidence"] == "low"


def test_why_too_short(tmp_path):
    prs = [{
        "number": 1,
        "title": "",
        "body": "DECISION: Use Vite\nWHY: ok",
        "mergedAt": "2024-01-01",
    }]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    assert entries[0]["confidence"] == "low"


def test_why_good_reason(tmp_path):
    prs = [{
        "number": 1,
        "title": "",
        "body": "DECISION: Use Vite\nWHY: Faster HMR than Webpack with better ESM support",
        "mergedAt": "2024-01-01",
    }]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    assert entries[0]["confidence"] == "medium"


def test_no_why_defaults_to_medium(tmp_path):
    prs = [{"number": 1, "title": "", "body": "DECISION: Use Vite", "mergedAt": "2024-01-01"}]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    assert entries[0]["confidence"] == "medium"


# ── Deduplication tests ───────────────────────────────────────────────────────

def test_same_decision_across_prs_deduplicated(tmp_path):
    prs = [
        {"number": 1, "title": "", "body": "DECISION: Use Vite", "mergedAt": "2024-01-01"},
        {"number": 2, "title": "", "body": "DECISION: Use Vite", "mergedAt": "2024-01-02"},
    ]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    decisions = [e for e in entries if "what" in e]
    assert len(decisions) == 1


def test_same_anti_across_prs_deduplicated(tmp_path):
    prs = [
        {"number": 1, "title": "", "body": "ANTI: moment.js", "mergedAt": "2024-01-01"},
        {"number": 2, "title": "", "body": "ANTI: moment.js", "mergedAt": "2024-01-02"},
    ]
    entries, _ = scan_prs(tmp_path, runner=_make_runner(prs))
    antis = [e for e in entries if "rejected" in e]
    assert len(antis) == 1


# ── _why_confidence unit tests ────────────────────────────────────────────────

def test_why_confidence_empty_is_medium():
    assert _why_confidence("") == "medium"


def test_why_confidence_single_char_is_low():
    assert _why_confidence("x") == "low"


def test_why_confidence_14_chars_is_low():
    # 14 chars < 15 threshold
    assert _why_confidence("a" * 14) == "low"


def test_why_confidence_15_chars_is_medium():
    # 15 chars = threshold, no longer low due to length
    assert _why_confidence("a" * 15) == "medium"


def test_why_confidence_per_meeting():
    assert _why_confidence("per meeting with the team") == "low"


def test_why_confidence_as_discussed():
    assert _why_confidence("as discussed in the standup today") == "low"


def test_why_confidence_per_call():
    assert _why_confidence("per call with stakeholders") == "low"


def test_why_confidence_in_thread():
    assert _why_confidence("in thread on GitHub Issues") == "low"


def test_why_confidence_bare_https_url():
    assert _why_confidence("https://example.com/blog/post") == "low"


def test_why_confidence_bare_http_url():
    assert _why_confidence("http://internal.wiki/page") == "low"


def test_why_confidence_good_long_reason():
    reason = "Provides native ESM support and significantly faster HMR than Webpack"
    assert _why_confidence(reason) == "medium"


# ── PR with no body/title skipped ────────────────────────────────────────────

def test_pr_with_no_body_and_no_title_skipped(tmp_path):
    prs = [
        {"number": 1, "title": "", "body": "", "mergedAt": "2024-01-01"},
        {"number": 2, "title": "DECISION: Use Vite", "body": "", "mergedAt": "2024-01-02"},
    ]
    entries, note = scan_prs(tmp_path, runner=_make_runner(prs))
    assert len(entries) == 1
    assert note == "2 PRs scanned"  # count includes the skipped PR


# ── today parameter ───────────────────────────────────────────────────────────

def test_today_parameter_used_for_made_field(tmp_path):
    prs = [{"number": 1, "title": "", "body": "DECISION: Use Vite", "mergedAt": "2024-01-01"}]
    entries, _ = scan_prs(tmp_path, today="2025-06-15", runner=_make_runner(prs))
    assert entries[0]["made"] == "2025-06-15"


def test_today_parameter_used_for_ruled_out_field(tmp_path):
    prs = [{"number": 1, "title": "", "body": "ANTI: Redux", "mergedAt": "2024-01-01"}]
    entries, _ = scan_prs(tmp_path, today="2025-06-15", runner=_make_runner(prs))
    assert entries[0]["ruled_out"] == "2025-06-15"


# ── gh error handling ─────────────────────────────────────────────────────────

def test_gh_pr_list_error(tmp_path):
    """Runner returns non-zero from gh pr list."""
    def runner(args):
        if args[0] == "gh" and args[1] == "--version":
            return 0, "gh version 2.0.0", ""
        if args[0] == "git":
            return 0, "origin  https://github.com/user/repo.git (fetch)", ""
        if args[0] == "gh" and "pr" in args:
            return 1, "", "API error: unauthorized"
        return 0, "", ""

    entries, note = scan_prs(tmp_path, runner=runner)
    assert entries == []
    assert note.startswith("skipped: gh error:")


def test_gh_returns_invalid_json(tmp_path):
    def runner(args):
        if args[0] == "gh" and args[1] == "--version":
            return 0, "gh version 2.0.0", ""
        if args[0] == "git":
            return 0, "origin  https://github.com/user/repo.git (fetch)", ""
        if args[0] == "gh" and "pr" in args:
            return 0, "not valid json{{", ""
        return 0, "", ""

    entries, note = scan_prs(tmp_path, runner=runner)
    assert entries == []
    assert note == "skipped: gh returned invalid JSON"


def test_gh_returns_empty_stdout(tmp_path):
    def runner(args):
        if args[0] == "gh" and args[1] == "--version":
            return 0, "gh version 2.0.0", ""
        if args[0] == "git":
            return 0, "origin  https://github.com/user/repo.git (fetch)", ""
        if args[0] == "gh" and "pr" in args:
            return 0, "", ""
        return 0, "", ""

    entries, note = scan_prs(tmp_path, runner=runner)
    assert entries == []
    assert note == "0 PRs scanned"
