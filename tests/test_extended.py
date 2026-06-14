"""
test_extended.py -- Edge-case and gap-filling tests for modules already
covered by test_end.py, test_gitdiff.py, and test_llm.py.

Focuses on:
  - parse_delta: null fields, unknown keys, fence variants, empty object
  - _merge_delta: missing BATON.md keys, multi-session accumulation, priority
  - run_end: force flag, bad/raising summarizer, threshold behaviour
  - gitdiff: invalid base ref, non-git dir, count_changed_lines edge cases
  - BatonConfig: malformed TOML, partial sections, explicit adapter list

All tests are offline.  Git tests use real subprocess via tmp_path.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from baton.commands.end import _merge_delta, run_end
from baton.core.config import BatonConfig
from baton.core.document import BatonDocument
from baton.core.gitdiff import GitError, count_changed_lines, get_diff, head_sha, resolve_base_ref
from baton.core.summarizer import parse_delta

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_BATON = FIXTURES / "sample_baton.md"


# ── Git helpers ───────────────────────────────────────────────────────────────

def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, check=True)


def _make_repo(tmp_path: Path) -> Path:
    _git(["init"], tmp_path)
    _git(["config", "user.email", "t@t.com"], tmp_path)
    _git(["config", "user.name", "T"], tmp_path)
    return tmp_path


def _commit(repo: Path, filename: str, content: str, msg: str = "c") -> str:
    (repo / filename).write_text(content, encoding="utf-8")
    _git(["add", filename], repo)
    _git(["commit", "-m", msg], repo)
    return head_sha(repo)


# ─────────────────────────────────────────────────────────────────────────────
# parse_delta — extra edge cases
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_delta_extra_unknown_keys_are_ignored() -> None:
    raw = json.dumps({
        "session": {"summary": "ok", "highlights": []},
        "sprint_done": [],
        "sprint_next": [],
        "extra_unknown_key": "should be ignored",
        "another_key": 42,
    })
    result = parse_delta(raw)
    assert "extra_unknown_key" not in result
    assert result["session"]["summary"] == "ok"


def test_parse_delta_null_sprint_done_coerced_to_list() -> None:
    raw = json.dumps({
        "session": {"summary": "x", "highlights": []},
        "sprint_done": None,
        "sprint_next": [],
    })
    result = parse_delta(raw)
    assert result["sprint_done"] == []


def test_parse_delta_null_sprint_next_coerced_to_list() -> None:
    raw = json.dumps({
        "session": {"summary": "x", "highlights": []},
        "sprint_done": [],
        "sprint_next": None,
    })
    result = parse_delta(raw)
    assert result["sprint_next"] == []


def test_parse_delta_sprint_next_dict_missing_priority_defaults_to_medium() -> None:
    raw = json.dumps({
        "session": {"summary": "x", "highlights": []},
        "sprint_done": [],
        "sprint_next": [{"feature": "No priority here"}],
    })
    result = parse_delta(raw)
    assert result["sprint_next"][0]["priority"] == "medium"


def test_parse_delta_sprint_next_dict_missing_feature_uses_empty_or_repr() -> None:
    raw = json.dumps({
        "session": {"summary": "x", "highlights": []},
        "sprint_done": [],
        "sprint_next": [{"priority": "high"}],
    })
    result = parse_delta(raw)
    # feature key must exist (may be empty string or fallback repr)
    assert "feature" in result["sprint_next"][0]


def test_parse_delta_empty_json_object_returns_safe_defaults() -> None:
    result = parse_delta("{}")
    assert result["session"]["summary"] == ""
    assert result["session"]["highlights"] == []
    assert result["sprint_done"] == []
    assert result["sprint_next"] == []


def test_parse_delta_generic_fence_without_json_keyword() -> None:
    inner = json.dumps({
        "session": {"summary": "fenced", "highlights": []},
        "sprint_done": [],
        "sprint_next": [],
    })
    raw = f"```\n{inner}\n```"
    result = parse_delta(raw)
    assert result["session"]["summary"] == "fenced"


def test_parse_delta_json_after_prose_paragraph() -> None:
    inner = json.dumps({
        "session": {"summary": "after prose", "highlights": ["h1"]},
        "sprint_done": ["done thing"],
        "sprint_next": [],
    })
    raw = (
        "Sure! Here is my analysis of the diff.\n\n"
        "The session was productive.\n\n"
        + inner
        + "\n\nLet me know if you have questions."
    )
    result = parse_delta(raw)
    assert result["session"]["summary"] == "after prose"
    assert result["sprint_done"] == ["done thing"]


def test_parse_delta_sprint_done_with_integer_coerced_to_string() -> None:
    raw = json.dumps({
        "session": {"summary": "x", "highlights": []},
        "sprint_done": [42],
        "sprint_next": [],
    })
    result = parse_delta(raw)
    assert result["sprint_done"] == ["42"]


def test_parse_delta_highlights_with_non_string_items_coerced() -> None:
    raw = json.dumps({
        "session": {"summary": "x", "highlights": [1, True, "real string"]},
        "sprint_done": [],
        "sprint_next": [],
    })
    result = parse_delta(raw)
    assert all(isinstance(h, str) for h in result["session"]["highlights"])


def test_parse_delta_raises_on_empty_string() -> None:
    with pytest.raises(ValueError, match="Could not parse JSON"):
        parse_delta("")


def test_parse_delta_raises_on_truncated_json() -> None:
    with pytest.raises(ValueError, match="Could not parse JSON"):
        parse_delta('{"session": {"summary": "incomplete"')


# ─────────────────────────────────────────────────────────────────────────────
# _merge_delta — missing keys in data
# ─────────────────────────────────────────────────────────────────────────────

def test_merge_delta_no_current_sprint_key_does_not_raise() -> None:
    data: dict = {"sessions": []}
    accepted = {
        "sprint_done": ["done thing"],
        "sprint_next": [{"feature": "next thing", "priority": "high"}],
        "session": None,
    }
    _merge_delta(data, accepted, sha=None, tool="", today="2026-06-13")
    # Should be a no-op for sprint changes; no raise.
    assert "current_sprint" not in data


def test_merge_delta_no_done_list_does_not_raise() -> None:
    data: dict = {
        "current_sprint": {"goal": "g", "next": [], "in_progress": []},
        "sessions": [],
    }
    accepted = {"sprint_done": ["x"], "sprint_next": [], "session": None}
    _merge_delta(data, accepted, sha=None, tool="", today="2026-06-13")
    # 'done' key was absent; should not be created silently
    assert "done" not in data["current_sprint"]


def test_merge_delta_no_next_list_does_not_raise() -> None:
    data: dict = {
        "current_sprint": {"goal": "g", "done": [], "in_progress": []},
        "sessions": [],
    }
    accepted = {"sprint_done": [], "sprint_next": [{"feature": "y", "priority": "low"}], "session": None}
    _merge_delta(data, accepted, sha=None, tool="", today="2026-06-13")
    assert "next" not in data["current_sprint"]


def test_merge_delta_no_sessions_list_does_not_raise() -> None:
    data: dict = {
        "current_sprint": {"goal": "g", "done": [], "next": []},
    }
    accepted = {
        "sprint_done": [],
        "sprint_next": [],
        "session": {"summary": "s", "highlights": []},
    }
    _merge_delta(data, accepted, sha=None, tool="", today="2026-06-13")
    assert "sessions" not in data


def test_merge_delta_multiple_sessions_accumulate() -> None:
    doc = BatonDocument.load(SAMPLE_BATON)
    for i in range(3):
        accepted = {
            "sprint_done": [],
            "sprint_next": [],
            "session": {"summary": f"Session {i}", "highlights": []},
        }
        _merge_delta(doc.data, accepted, sha=f"sha{i}", tool="tool", today=f"2026-06-{13+i:02d}")
    sessions = list(doc.data["sessions"])
    assert len(sessions) == 3
    assert sessions[0]["summary"] == "Session 0"
    assert sessions[2]["summary"] == "Session 2"


def test_merge_delta_next_item_priority_stored() -> None:
    doc = BatonDocument.load(SAMPLE_BATON)
    accepted = {
        "sprint_done": [],
        "sprint_next": [{"feature": "New feature", "priority": "low"}],
        "session": None,
    }
    _merge_delta(doc.data, accepted, sha=None, tool="", today="2026-06-13")
    next_items = list(doc.data["current_sprint"]["next"])
    added = next(i for i in next_items if (i.get("feature") if isinstance(i, dict) else i) == "New feature")
    assert added["priority"] == "low"


def test_merge_delta_tool_stored_in_session() -> None:
    doc = BatonDocument.load(SAMPLE_BATON)
    accepted = {
        "sprint_done": [],
        "sprint_next": [],
        "session": {"summary": "Test session", "highlights": []},
    }
    _merge_delta(doc.data, accepted, sha="abc", tool="cursor", today="2026-06-13")
    sessions = list(doc.data["sessions"])
    assert sessions[0]["tool"] == "cursor"


def test_merge_delta_session_sha_is_none_stored_as_empty_string() -> None:
    doc = BatonDocument.load(SAMPLE_BATON)
    accepted = {
        "sprint_done": [],
        "sprint_next": [],
        "session": {"summary": "No sha", "highlights": []},
    }
    _merge_delta(doc.data, accepted, sha=None, tool="", today="2026-06-13")
    sessions = list(doc.data["sessions"])
    assert sessions[0]["commit"] == ""


def test_merge_delta_done_item_as_string_not_dict() -> None:
    doc = BatonDocument.load(SAMPLE_BATON)
    original_count = len(list(doc.data["current_sprint"]["done"]))
    accepted = {
        "sprint_done": ["String-style done item"],
        "sprint_next": [],
        "session": None,
    }
    _merge_delta(doc.data, accepted, sha=None, tool="", today="2026-06-13")
    done = list(doc.data["current_sprint"]["done"])
    assert len(done) == original_count + 1


def test_merge_delta_empty_accepted_is_no_op() -> None:
    doc = BatonDocument.load(SAMPLE_BATON)
    original_done = len(list(doc.data["current_sprint"]["done"]))
    original_next = len(list(doc.data["current_sprint"]["next"]))
    original_sessions = len(list(doc.data["sessions"]))
    accepted = {"sprint_done": [], "sprint_next": [], "session": None}
    _merge_delta(doc.data, accepted, sha=None, tool="", today="2026-06-13")
    assert len(list(doc.data["current_sprint"]["done"])) == original_done
    assert len(list(doc.data["current_sprint"]["next"])) == original_next
    assert len(list(doc.data["sessions"])) == original_sessions


# ─────────────────────────────────────────────────────────────────────────────
# run_end — additional paths
# ─────────────────────────────────────────────────────────────────────────────

def test_run_end_force_flag_calls_summarizer_even_with_small_diff(tmp_path: Path) -> None:
    """--force bypasses the min_diff_lines threshold and calls the summarizer."""
    repo = _make_repo(tmp_path)
    baton_path = repo / "BATON.md"
    baton_path.write_bytes(SAMPLE_BATON.read_bytes())
    _commit(repo, "BATON.md", baton_path.read_text(encoding="utf-8"))

    calls: list[str] = []

    def counting_summarizer(system, user, config):
        calls.append("called")
        return json.dumps({
            "session": {"summary": "Force test", "highlights": []},
            "sprint_done": [],
            "sprint_next": [],
        })

    # Working tree is clean (0 changed lines < threshold 10) but force=True.
    result = run_end(repo, force=True, summarizer=counting_summarizer, auto_accept=True)
    assert result is True
    assert calls == ["called"]


def test_run_end_bad_json_from_summarizer_returns_false(tmp_path: Path) -> None:
    """Summarizer returning invalid JSON causes run_end to return False."""
    repo = _make_repo(tmp_path)
    baton_path = repo / "BATON.md"
    baton_path.write_bytes(SAMPLE_BATON.read_bytes())
    _commit(repo, "BATON.md", baton_path.read_text(encoding="utf-8"))
    # Create enough diff to pass threshold.
    big = "\n".join(f"x{i} = {i}" for i in range(20))
    _commit(repo, "big.py", big)

    result = run_end(
        repo,
        force=True,
        summarizer=lambda s, u, c: "this is not json at all",
        auto_accept=True,
    )
    assert result is False


def test_run_end_runtime_error_from_summarizer_returns_false(tmp_path: Path) -> None:
    """RuntimeError from the LLM provider is caught and returns False."""
    repo = _make_repo(tmp_path)
    baton_path = repo / "BATON.md"
    baton_path.write_bytes(SAMPLE_BATON.read_bytes())
    _commit(repo, "BATON.md", baton_path.read_text(encoding="utf-8"))

    def raising(s, u, c):
        raise RuntimeError("API rate limit exceeded")

    result = run_end(repo, force=True, summarizer=raising, auto_accept=True)
    assert result is False


def test_run_end_threshold_not_bypassed_without_force(tmp_path: Path) -> None:
    """Without --force and with a small diff, the summarizer is never called."""
    repo = _make_repo(tmp_path)
    baton_path = repo / "BATON.md"
    baton_path.write_bytes(SAMPLE_BATON.read_bytes())
    _commit(repo, "BATON.md", baton_path.read_text(encoding="utf-8"))
    # Working tree is clean → 0 lines changed.

    calls: list[str] = []

    def would_fail(s, u, c):
        calls.append("called")
        raise AssertionError("Should not be called below threshold")

    result = run_end(repo, force=False, summarizer=would_fail, auto_accept=True)
    assert result is True  # skipped, not an error
    assert calls == []


def test_run_end_baton_md_saved_after_merge(tmp_path: Path) -> None:
    """After a successful run, BATON.md on disk has the new session entry."""
    repo = _make_repo(tmp_path)
    baton_path = repo / "BATON.md"
    baton_path.write_bytes(SAMPLE_BATON.read_bytes())
    _commit(repo, "BATON.md", baton_path.read_text(encoding="utf-8"))
    big = "\n".join(f"line{i} = {i}" for i in range(20))
    _commit(repo, "data.py", big)

    canned = json.dumps({
        "session": {"summary": "Disk save test", "highlights": ["saved"]},
        "sprint_done": [],
        "sprint_next": [],
    })
    run_end(repo, force=True, summarizer=lambda s, u, c: canned, auto_accept=True)

    reloaded = BatonDocument.load(baton_path)
    sessions = list(reloaded.data["sessions"])
    assert any(s["summary"] == "Disk save test" for s in sessions)


# ─────────────────────────────────────────────────────────────────────────────
# gitdiff — additional edge cases
# ─────────────────────────────────────────────────────────────────────────────

def test_head_sha_on_non_git_directory_returns_none(tmp_path: Path) -> None:
    """head_sha must return None (not raise) for a plain directory."""
    result = head_sha(tmp_path)
    assert result is None


def test_get_diff_with_invalid_base_ref_raises_git_error(tmp_path: Path) -> None:
    """Passing a non-existent SHA as base_ref raises GitError."""
    repo = _make_repo(tmp_path)
    _commit(repo, "f.py", "x = 1")
    with pytest.raises(GitError):
        get_diff(repo, "0000000000000000000000000000000000000000")


def test_count_changed_lines_only_plus_plus_plus_header_not_counted() -> None:
    diff = "+++ b/new_file.py\n"
    assert count_changed_lines(diff) == 0


def test_count_changed_lines_only_minus_minus_minus_header_not_counted() -> None:
    diff = "--- a/old_file.py\n"
    assert count_changed_lines(diff) == 0


def test_count_changed_lines_mixed_header_and_body() -> None:
    diff = (
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "-removed line\n"
        "+added line\n"
        " context\n"
    )
    assert count_changed_lines(diff) == 2


def test_count_changed_lines_no_plus_no_minus_returns_zero() -> None:
    diff = "diff --git a/foo b/foo\nindex abc..def 100644\n@@ -1,1 +1,1 @@\n context\n"
    assert count_changed_lines(diff) == 0


def test_resolve_base_ref_sessions_is_not_a_list_returns_none() -> None:
    data = {"sessions": "not a list"}
    result = resolve_base_ref(data, since=None)
    assert result is None


def test_resolve_base_ref_last_session_is_not_dict_returns_none() -> None:
    data = {"sessions": ["just a string session"]}
    result = resolve_base_ref(data, since=None)
    assert result is None


def test_resolve_base_ref_since_empty_string_treated_as_falsy() -> None:
    data = {"sessions": [{"commit": "stored-sha"}]}
    # Empty string is falsy → should fall through to session-based ref.
    result = resolve_base_ref(data, since="")
    assert result == "stored-sha"


def test_get_diff_returns_string_for_clean_repo(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _commit(repo, "r.txt", "hi\n")
    diff = get_diff(repo, None)
    assert isinstance(diff, str)


# ─────────────────────────────────────────────────────────────────────────────
# BatonConfig — loading edge cases
# ─────────────────────────────────────────────────────────────────────────────

def test_config_defaults_when_no_toml(tmp_path: Path) -> None:
    config = BatonConfig.load(tmp_path)
    assert config.llm_provider == "anthropic"
    assert config.model == ""
    assert config.min_diff_lines == 10
    assert config.auto_sync is True
    assert config.enabled_adapters == []


def test_config_malformed_toml_returns_defaults(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text("not valid [toml content}\n", encoding="utf-8")
    config = BatonConfig.load(tmp_path)
    assert config.llm_provider == "anthropic"
    assert config.min_diff_lines == 10


def test_config_partial_baton_section_uses_defaults_for_missing(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text(
        "[baton]\nllm_provider = \"openai\"\n", encoding="utf-8"
    )
    config = BatonConfig.load(tmp_path)
    assert config.llm_provider == "openai"
    assert config.model == ""  # default
    assert config.min_diff_lines == 10  # default


def test_config_adapter_list_loaded_from_toml(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text(
        "[adapters]\nenabled = [\"claude\", \"cursor\"]\n", encoding="utf-8"
    )
    config = BatonConfig.load(tmp_path)
    assert config.enabled_adapters == ["claude", "cursor"]


def test_config_min_diff_lines_read_from_toml(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text(
        "[baton]\nmin_diff_lines = 25\n", encoding="utf-8"
    )
    config = BatonConfig.load(tmp_path)
    assert config.min_diff_lines == 25


def test_config_auto_sync_false_read_from_toml(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text(
        "[baton]\nauto_sync = false\n", encoding="utf-8"
    )
    config = BatonConfig.load(tmp_path)
    assert config.auto_sync is False


def test_config_model_read_from_toml(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text(
        "[baton]\nmodel = \"claude-opus-4-8\"\n", encoding="utf-8"
    )
    config = BatonConfig.load(tmp_path)
    assert config.model == "claude-opus-4-8"


def test_config_empty_toml_file_returns_defaults(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text("", encoding="utf-8")
    config = BatonConfig.load(tmp_path)
    assert config.llm_provider == "anthropic"
