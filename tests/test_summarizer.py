"""
test_summarizer.py -- Unit tests for baton/core/summarizer.py.

Covers build_prompt() exhaustively: output shape, section headers,
field fallbacks, empty/missing data, diff rendering, sprint item
rendering via feature_label, and the constant system prompt.

No LLM calls. No filesystem access.
"""
from __future__ import annotations

import pytest

from baton.core.summarizer import SYSTEM_INSTRUCTIONS, build_prompt


# ── Helpers ───────────────────────────────────────────────────────────────────

def _minimal_data(**overrides) -> dict:
    """Return a valid minimal data dict, optionally overriding keys."""
    base = {
        "project": {
            "name": "MyProject",
            "purpose": "Do the thing",
            "stage": "prototype",
        },
        "current_sprint": {
            "goal": "Ship it",
            "done": [],
            "in_progress": [],
            "next": [],
        },
    }
    base.update(overrides)
    return base


def _get_user(diff: str = "diff stuff", **overrides) -> str:
    _, user = build_prompt(diff, _minimal_data(**overrides))
    return user


# ── Return type ───────────────────────────────────────────────────────────────

def test_build_prompt_returns_two_strings() -> None:
    result = build_prompt("some diff", _minimal_data())
    assert isinstance(result, tuple)
    assert len(result) == 2
    system, user = result
    assert isinstance(system, str)
    assert isinstance(user, str)


# ── System prompt is the constant ─────────────────────────────────────────────

def test_build_prompt_system_equals_constant() -> None:
    system, _ = build_prompt("diff", _minimal_data())
    assert system is SYSTEM_INSTRUCTIONS


def test_build_prompt_system_is_same_across_calls() -> None:
    system_a, _ = build_prompt("diff 1", _minimal_data())
    system_b, _ = build_prompt("diff 2", _minimal_data(project={"name": "Other"}))
    assert system_a == system_b


# ── System prompt content ─────────────────────────────────────────────────────

def test_system_contains_json_key_session() -> None:
    assert '"session"' in SYSTEM_INSTRUCTIONS


def test_system_contains_json_key_sprint_done() -> None:
    assert '"sprint_done"' in SYSTEM_INSTRUCTIONS


def test_system_contains_json_key_sprint_next() -> None:
    assert '"sprint_next"' in SYSTEM_INSTRUCTIONS


def test_system_contains_json_key_highlights() -> None:
    assert '"highlights"' in SYSTEM_INSTRUCTIONS


def test_system_mentions_priority_values() -> None:
    assert "high" in SYSTEM_INSTRUCTIONS
    assert "medium" in SYSTEM_INSTRUCTIONS
    assert "low" in SYSTEM_INSTRUCTIONS


# ── User prompt section headers ───────────────────────────────────────────────

def test_user_contains_project_brief_header() -> None:
    assert "=== PROJECT BRIEF ===" in _get_user()


def test_user_contains_current_sprint_header() -> None:
    assert "=== CURRENT SPRINT ===" in _get_user()


def test_user_contains_git_diff_header() -> None:
    assert "=== GIT DIFF (this session) ===" in _get_user()


# ── Project fields ────────────────────────────────────────────────────────────

def test_user_contains_project_name() -> None:
    user = _get_user(project={"name": "AwesomeApp", "purpose": "Test", "stage": ""})
    assert "AwesomeApp" in user


def test_user_contains_project_purpose() -> None:
    user = _get_user(project={"name": "X", "purpose": "Unique purpose text", "stage": ""})
    assert "Unique purpose text" in user


def test_user_contains_stage_when_set() -> None:
    user = _get_user(project={"name": "X", "purpose": "Y", "stage": "mvp"})
    assert "mvp" in user


def test_user_omits_stage_when_empty() -> None:
    user = _get_user(project={"name": "X", "purpose": "Y", "stage": ""})
    assert "Stage:" not in user


def test_user_omits_stage_when_key_absent() -> None:
    user = _get_user(project={"name": "X", "purpose": "Y"})
    assert "Stage:" not in user


def test_user_fallback_project_name_when_missing() -> None:
    user = _get_user(project={"purpose": "Y", "stage": ""})
    assert "Unknown project" in user


def test_user_fallback_project_name_when_empty_string() -> None:
    user = _get_user(project={"name": "", "purpose": "Y", "stage": ""})
    assert "Unknown project" in user


def test_user_fallback_purpose_when_missing() -> None:
    user = _get_user(project={"name": "X", "stage": ""})
    assert "(no purpose set)" in user


def test_user_fallback_purpose_when_none() -> None:
    user = _get_user(project={"name": "X", "purpose": None, "stage": ""})
    assert "(no purpose set)" in user


def test_user_project_key_missing_entirely_does_not_raise() -> None:
    data = {"current_sprint": {"goal": "g", "done": [], "in_progress": [], "next": []}}
    _, user = build_prompt("d", data)
    assert "Unknown project" in user


# ── Sprint fields ──────────────────────────────────────────────────────────────

def test_user_contains_sprint_goal() -> None:
    user = _get_user(current_sprint={"goal": "Deploy to prod", "done": [], "in_progress": [], "next": []})
    assert "Deploy to prod" in user


def test_user_fallback_sprint_goal_when_missing() -> None:
    user = _get_user(current_sprint={"done": [], "in_progress": [], "next": []})
    assert "(no sprint goal set)" in user


def test_user_contains_done_item_name() -> None:
    sprint = {
        "goal": "g",
        "done": [{"feature": "Auth system", "confidence": "stable"}],
        "in_progress": [],
        "next": [],
    }
    user = _get_user(current_sprint=sprint)
    assert "Auth system" in user


def test_user_contains_in_progress_item_name() -> None:
    sprint = {
        "goal": "g",
        "done": [],
        "in_progress": [{"feature": "Dashboard"}],
        "next": [],
    }
    user = _get_user(current_sprint=sprint)
    assert "Dashboard" in user


def test_user_contains_next_item_name() -> None:
    sprint = {
        "goal": "g",
        "done": [],
        "in_progress": [],
        "next": [{"feature": "Billing page", "priority": "high"}],
    }
    user = _get_user(current_sprint=sprint)
    assert "Billing page" in user


def test_user_sprint_done_label_present_when_items_exist() -> None:
    sprint = {
        "goal": "g",
        "done": [{"feature": "X"}],
        "in_progress": [],
        "next": [],
    }
    user = _get_user(current_sprint=sprint)
    assert "Done:" in user


def test_user_sprint_done_label_absent_when_empty() -> None:
    sprint = {"goal": "g", "done": [], "in_progress": [], "next": []}
    user = _get_user(current_sprint=sprint)
    assert "Done:" not in user


def test_user_sprint_in_progress_label_absent_when_empty() -> None:
    sprint = {"goal": "g", "done": [], "in_progress": [], "next": []}
    user = _get_user(current_sprint=sprint)
    assert "In progress:" not in user


def test_user_sprint_next_label_absent_when_empty() -> None:
    sprint = {"goal": "g", "done": [], "in_progress": [], "next": []}
    user = _get_user(current_sprint=sprint)
    assert "Up next:" not in user


def test_user_sprint_item_as_plain_string() -> None:
    sprint = {"goal": "g", "done": ["Bare string task"], "in_progress": [], "next": []}
    user = _get_user(current_sprint=sprint)
    assert "Bare string task" in user


def test_user_sprint_multiple_done_items_comma_separated() -> None:
    sprint = {
        "goal": "g",
        "done": [{"feature": "Alpha"}, {"feature": "Beta"}],
        "in_progress": [],
        "next": [],
    }
    user = _get_user(current_sprint=sprint)
    assert "Alpha" in user
    assert "Beta" in user


def test_user_sprint_key_missing_entirely_does_not_raise() -> None:
    data = {"project": {"name": "X", "purpose": "Y", "stage": ""}}
    _, user = build_prompt("d", data)
    assert "(no sprint goal set)" in user


def test_user_empty_data_dict_does_not_raise() -> None:
    _, user = build_prompt("diff text", {})
    assert "Unknown project" in user
    assert "(no sprint goal set)" in user


# ── Diff rendering ────────────────────────────────────────────────────────────

def test_user_contains_diff_text() -> None:
    diff = "--- a/foo.py\n+++ b/foo.py\n+x = 1"
    _, user = build_prompt(diff, _minimal_data())
    assert "+x = 1" in user


def test_user_empty_diff_renders_placeholder() -> None:
    _, user = build_prompt("", _minimal_data())
    assert "(no diff -- working tree is clean)" in user


def test_user_whitespace_only_diff_renders_placeholder() -> None:
    _, user = build_prompt("   \n\t  ", _minimal_data())
    assert "(no diff -- working tree is clean)" in user


def test_user_diff_not_truncated_by_build_prompt() -> None:
    long_diff = "+" + "x" * 30_000
    _, user = build_prompt(long_diff, _minimal_data())
    assert long_diff.strip() in user


def test_user_diff_with_special_characters_not_escaped() -> None:
    diff = "--- a/test.py\n+++ b/test.py\n+val = 'it\\'s fine'"
    _, user = build_prompt(diff, _minimal_data())
    assert "val = 'it\\'s fine'" in user


# ── Section ordering in user prompt ──────────────────────────────────────────

def test_user_brief_appears_before_sprint() -> None:
    user = _get_user()
    assert user.index("PROJECT BRIEF") < user.index("CURRENT SPRINT")


def test_user_sprint_appears_before_diff() -> None:
    user = _get_user()
    assert user.index("CURRENT SPRINT") < user.index("GIT DIFF")


def test_user_project_name_appears_in_brief_section() -> None:
    data = _minimal_data(project={"name": "UniqueMarker", "purpose": "p", "stage": ""})
    _, user = build_prompt("d", data)
    brief_start = user.index("PROJECT BRIEF")
    sprint_start = user.index("CURRENT SPRINT")
    brief_section = user[brief_start:sprint_start]
    assert "UniqueMarker" in brief_section


def test_user_diff_appears_after_diff_header() -> None:
    diff = "UNIQUE_DIFF_CONTENT_7734"
    _, user = build_prompt(diff, _minimal_data())
    diff_header_pos = user.index("GIT DIFF")
    diff_content_pos = user.index(diff)
    assert diff_content_pos > diff_header_pos
