"""
test_heuristic.py -- Tests for baton/core/heuristic.py.

All tests are deterministic: no git calls, no LLM, no filesystem.
"""
from __future__ import annotations

import pytest

from baton.core.heuristic import (
    _build_highlights,
    _build_summary,
    _extract_markers,
    _infer_sprint_done,
    _infer_sprint_next,
    _parse_diff_stats,
    heuristic_delta,
)

# ── Sample diff fixture ───────────────────────────────────────────────────────

SAMPLE_DIFF = """\
diff --git a/foo.py b/foo.py
index abc..def 100644
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 unchanged
-removed line
+added line
+# TODO: write tests for this function
diff --git a/bar.py b/bar.py
index 111..222 100644
--- a/bar.py
+++ b/bar.py
@@ -1,1 +1,2 @@
 bar = 1
+bar = 2
"""


# ── _parse_diff_stats ─────────────────────────────────────────────────────────


def test_parse_diff_stats_counts_insertions_deletions() -> None:
    ins, dels, files = _parse_diff_stats(SAMPLE_DIFF)
    # Added: "added line", "# TODO: write tests for this function", "bar = 2" = 3
    # Removed: "removed line" = 1
    assert ins == 3
    assert dels == 1
    assert files == 2


def test_parse_diff_stats_empty_diff() -> None:
    ins, dels, files = _parse_diff_stats("")
    assert ins == 0
    assert dels == 0
    assert files == 0


def test_parse_diff_stats_ignores_header_lines() -> None:
    diff = "--- a/foo.py\n+++ b/foo.py\n+real add\n-real remove\n"
    ins, dels, files = _parse_diff_stats(diff)
    assert ins == 1
    assert dels == 1


def test_parse_diff_stats_single_file() -> None:
    diff = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n+new line\n"
    _, _, files = _parse_diff_stats(diff)
    assert files == 1


# ── _build_summary ────────────────────────────────────────────────────────────


def test_build_summary_no_changes() -> None:
    summary = _build_summary([], 0, 0, 0)
    assert "No changes" in summary


def test_build_summary_with_commits_and_stats() -> None:
    summary = _build_summary(["implement the login flow"], 10, 2, 3)
    assert "implement the login flow" in summary
    assert "1 commit" in summary
    assert "+10/-2" in summary
    assert "3 files" in summary


def test_build_summary_multiple_commits_leads_with_latest() -> None:
    commits = ["latest commit", "earlier commit"]
    summary = _build_summary(commits, 5, 1, 1)
    assert summary.startswith("latest commit")
    assert "2 commits" in summary


def test_build_summary_uncommitted_only() -> None:
    summary = _build_summary([], 4, 2, 1)
    assert "+4/-2" in summary
    assert "1 file" in summary


def test_build_summary_ends_with_period() -> None:
    summary = _build_summary(["add feature"], 1, 0, 1)
    assert summary.endswith(".")


# ── _build_highlights ─────────────────────────────────────────────────────────


def test_build_highlights_uses_commit_subjects() -> None:
    commits = ["fix: auth bug", "add search", "update docs", "extra commit"]
    highlights = _build_highlights(commits, 0, 0)
    # At most 3 from commit log
    assert "fix: auth bug" in highlights
    assert "add search" in highlights
    assert "update docs" in highlights
    assert "extra commit" not in highlights
    assert len(highlights) == 3


def test_build_highlights_fallback_on_no_commits() -> None:
    highlights = _build_highlights([], 5, 2)
    assert len(highlights) == 1
    assert "+5/-2" in highlights[0]


def test_build_highlights_empty_when_no_data() -> None:
    highlights = _build_highlights([], 0, 0)
    assert highlights == []


# ── _infer_sprint_done ────────────────────────────────────────────────────────


def test_infer_sprint_done_finds_done_commits() -> None:
    commits = [
        "fix: add user auth",
        "implement search endpoint",
        "refactor database layer",   # no done keyword
        "build the filter sidebar",
        "ship the v1 release",
    ]
    done = _infer_sprint_done(commits)
    assert "fix: add user auth" in done
    assert "implement search endpoint" in done
    assert "build the filter sidebar" in done
    assert "ship the v1 release" in done
    assert "refactor database layer" not in done


def test_infer_sprint_done_empty_log() -> None:
    assert _infer_sprint_done([]) == []


def test_infer_sprint_done_no_done_keywords() -> None:
    commits = ["refactor: cleanup code", "docs: update README", "chore: bump version"]
    assert _infer_sprint_done(commits) == []


def test_infer_sprint_done_case_insensitive() -> None:
    commits = ["FIXED the bug", "Implemented feature X"]
    done = _infer_sprint_done(commits)
    assert len(done) == 2


# ── _infer_sprint_next ────────────────────────────────────────────────────────


def test_infer_sprint_next_from_python_todo() -> None:
    diff = "+# TODO: write integration tests\n"
    items = _infer_sprint_next(diff)
    assert len(items) == 1
    assert items[0]["feature"] == "write integration tests"
    assert items[0]["priority"] == "medium"


def test_infer_sprint_next_from_js_todo() -> None:
    diff = "+// TODO: add error handling\n"
    items = _infer_sprint_next(diff)
    assert len(items) == 1
    assert "add error handling" in items[0]["feature"]


def test_infer_sprint_next_deduplicates() -> None:
    diff = "+# TODO: write tests\n+# TODO: write tests\n"
    items = _infer_sprint_next(diff)
    assert len(items) == 1


def test_infer_sprint_next_ignores_removed_lines() -> None:
    diff = "-# TODO: old todo removed\n"
    assert _infer_sprint_next(diff) == []


def test_infer_sprint_next_ignores_context_lines() -> None:
    diff = " # TODO: context line (unchanged)\n"
    assert _infer_sprint_next(diff) == []


def test_infer_sprint_next_empty_diff() -> None:
    assert _infer_sprint_next("") == []


def test_infer_sprint_next_multiple_todos() -> None:
    diff = "+# TODO: task one\n+# TODO: task two\n"
    items = _infer_sprint_next(diff)
    features = [i["feature"] for i in items]
    assert "task one" in features
    assert "task two" in features


# ── heuristic_delta ───────────────────────────────────────────────────────────


def test_heuristic_delta_shape() -> None:
    """Return value has the same top-level keys as parse_delta()."""
    delta = heuristic_delta("", [], {})
    assert "session" in delta
    assert "summary" in delta["session"]
    assert "highlights" in delta["session"]
    assert "sprint_done" in delta
    assert "sprint_next" in delta


def test_heuristic_delta_types() -> None:
    delta = heuristic_delta("", [], {})
    assert isinstance(delta["session"]["summary"], str)
    assert isinstance(delta["session"]["highlights"], list)
    assert isinstance(delta["sprint_done"], list)
    assert isinstance(delta["sprint_next"], list)


def test_heuristic_delta_uses_commits_as_highlights() -> None:
    commits = ["fix: auth bug", "add search feature", "update docs"]
    delta = heuristic_delta("", commits, {})
    highlights = delta["session"]["highlights"]
    assert "fix: auth bug" in highlights
    assert "add search feature" in highlights


def test_heuristic_delta_sprint_next_items_are_dicts() -> None:
    diff = "+# TODO: implement caching\n"
    delta = heuristic_delta(diff, [], {})
    for item in delta["sprint_next"]:
        assert "feature" in item
        assert "priority" in item


def test_heuristic_delta_sprint_done_from_commit_keywords() -> None:
    commits = ["implement login flow", "refactor config"]
    delta = heuristic_delta("", commits, {})
    assert "implement login flow" in delta["sprint_done"]
    assert "refactor config" not in delta["sprint_done"]


def test_heuristic_delta_no_markers_means_curated_sections_absent() -> None:
    """Commit A invariant: decisions/anti/landmines/questions are NOT in the delta.

    Curated memory must never be inferred from diff content.
    These sections are populated only from explicit inline markers (Commit B).
    """
    diff = "+x = 1  # this looks like a decision\n"
    commits = ["add important architectural change"]
    delta = heuristic_delta(diff, commits, {})
    assert "decisions" not in delta
    assert "anti_decisions" not in delta
    assert "landmines" not in delta
    assert "open_questions" not in delta


def test_heuristic_delta_summary_contains_commit_info() -> None:
    commits = ["implement the login flow"]
    delta = heuristic_delta(SAMPLE_DIFF, commits, {})
    summary = delta["session"]["summary"]
    assert "implement the login flow" in summary
    assert summary  # non-empty


def test_heuristic_delta_empty_everything_returns_safe_string() -> None:
    delta = heuristic_delta("", [], {})
    assert delta["session"]["summary"] != ""
    assert "No changes" in delta["session"]["summary"]


# ── _extract_markers ──────────────────────────────────────────────────────────


def test_extract_markers_decision_from_commit() -> None:
    result = _extract_markers(["DECISION: use ruamel not PyYAML"], "")
    assert "decisions" in result
    assert result["decisions"][0]["what"] == "use ruamel not PyYAML"


def test_extract_markers_decision_from_diff_added_line() -> None:
    diff = "+# DECISION: inline comments must be preserved\n"
    result = _extract_markers([], diff)
    assert "decisions" in result
    assert result["decisions"][0]["what"] == "inline comments must be preserved"


def test_extract_markers_anti_from_commit() -> None:
    result = _extract_markers(["ANTI: PyYAML for YAML parsing"], "")
    assert "anti_decisions" in result
    assert result["anti_decisions"][0]["rejected"] == "PyYAML for YAML parsing"


def test_extract_markers_rejected_alias() -> None:
    result = _extract_markers(["REJECTED: full-file sync"], "")
    assert "anti_decisions" in result
    assert result["anti_decisions"][0]["rejected"] == "full-file sync"


def test_extract_markers_landmine_from_commit() -> None:
    result = _extract_markers(["LANDMINE: the re.sub in upsert_managed_block must use a lambda"], "")
    assert "landmines" in result
    lm = result["landmines"][0]
    assert "upsert_managed_block" in lm["actually"]
    assert lm["location"] == ""   # left blank for human review
    assert lm["looks_like"] == ""


def test_extract_markers_question_from_commit() -> None:
    result = _extract_markers(["QUESTION: should baton init auto-sync?"], "")
    assert "open_questions" in result
    assert result["open_questions"][0]["question"] == "should baton init auto-sync?"
    assert result["open_questions"][0]["status"] == "open"


def test_extract_markers_openq_alias() -> None:
    result = _extract_markers(["OPENQ: what token limit triggers baton end?"], "")
    assert "open_questions" in result


def test_extract_markers_case_insensitive() -> None:
    result = _extract_markers(["decision: lower case works"], "")
    assert "decisions" in result


def test_extract_markers_deduplicates() -> None:
    commits = ["DECISION: use ruamel", "DECISION: use ruamel"]
    result = _extract_markers(commits, "")
    assert len(result["decisions"]) == 1


def test_extract_markers_diff_ignored_lines() -> None:
    """Only added (+) lines in the diff are scanned, not removed or context lines."""
    diff = "-DECISION: old removed decision\n DECISION: context line\n"
    result = _extract_markers([], diff)
    assert "decisions" not in result


def test_extract_markers_empty_input_returns_empty_dict() -> None:
    result = _extract_markers([], "")
    assert result == {}


def test_extract_markers_multiple_types_in_one_call() -> None:
    commits = [
        "DECISION: use managed blocks",
        "ANTI: full file overwrite",
        "LANDMINE: the lambda in re.sub is intentional",
        "QUESTION: should we auto-sync after end?",
    ]
    result = _extract_markers(commits, "")
    assert "decisions" in result
    assert "anti_decisions" in result
    assert "landmines" in result
    assert "open_questions" in result


# ── heuristic_delta with markers ─────────────────────────────────────────────


def test_heuristic_delta_with_decision_marker_includes_decisions() -> None:
    commits = ["DECISION: adopt managed-block pattern for all adapters"]
    delta = heuristic_delta("", commits, {})
    assert "decisions" in delta
    assert delta["decisions"][0]["what"] == "adopt managed-block pattern for all adapters"


def test_heuristic_delta_with_landmine_marker() -> None:
    diff = "+# LANDMINE: this empty return is intentional -- see OAuth callback docs\n"
    delta = heuristic_delta(diff, [], {})
    assert "landmines" in delta
    assert "intentional" in delta["landmines"][0]["actually"]


def test_heuristic_delta_no_markers_still_absent() -> None:
    """Invariant unchanged: ordinary diff lines never produce curated sections."""
    diff = "+x = 1  # this looks like a decision\n"
    commits = ["add important architectural change"]
    delta = heuristic_delta(diff, commits, {})
    assert "decisions" not in delta
    assert "anti_decisions" not in delta
    assert "landmines" not in delta
    assert "open_questions" not in delta
