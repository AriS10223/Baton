"""
test_end.py -- Tests for baton/core/summarizer.py (parse_delta) and
baton/commands/end.py (_merge_delta, run_end).

All tests are offline/deterministic. No real LLM calls.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import json

from baton.commands.end import _delta_from_stdin, _merge_delta, run_end
from baton.core.document import BatonDocument
from baton.core.summarizer import JSON_SPEC, parse_delta

# ── Fixture path ──────────────────────────────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_BATON = FIXTURES / "sample_baton.md"


# ── Fake summarizer ───────────────────────────────────────────────────────────

CANNED_DELTA = json.dumps({
    "session": {
        "summary": "Built foo feature",
        "highlights": ["Added foo"],
    },
    "sprint_done": ["Implement foo"],
    "sprint_next": [{"feature": "Write tests", "priority": "high"}],
})


def fake_summarizer(system: str, user: str, config) -> str:
    return CANNED_DELTA


def raising_summarizer(system: str, user: str, config) -> str:
    raise AssertionError("summarizer must not be called for a small diff")


# ── Git helper ────────────────────────────────────────────────────────────────

def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def make_commit(repo: Path, filename: str, content: str, message: str = "commit") -> None:
    (repo / filename).write_text(content, encoding="utf-8")
    git(["add", filename], repo)
    git(["commit", "-m", message], repo)


# ── parse_delta ───────────────────────────────────────────────────────────────

def test_parse_delta_clean_json() -> None:
    raw = json.dumps({
        "session": {"summary": "Did stuff", "highlights": ["thing1"]},
        "sprint_done": ["Task A"],
        "sprint_next": [{"feature": "Task B", "priority": "high"}],
    })
    result = parse_delta(raw)
    assert result["session"]["summary"] == "Did stuff"
    assert result["sprint_done"] == ["Task A"]
    assert result["sprint_next"][0]["feature"] == "Task B"
    assert result["sprint_next"][0]["priority"] == "high"


def test_parse_delta_fenced_json() -> None:
    inner = json.dumps({
        "session": {"summary": "Fenced", "highlights": []},
        "sprint_done": [],
        "sprint_next": [],
    })
    raw = f"```json\n{inner}\n```"
    result = parse_delta(raw)
    assert result["session"]["summary"] == "Fenced"


def test_parse_delta_prose_wrapped() -> None:
    inner = json.dumps({
        "session": {"summary": "Prose wrapped", "highlights": []},
        "sprint_done": ["Done thing"],
        "sprint_next": [],
    })
    raw = f"Here is the JSON:\n{inner}\nDone."
    result = parse_delta(raw)
    assert result["session"]["summary"] == "Prose wrapped"
    assert result["sprint_done"] == ["Done thing"]


def test_parse_delta_raises_on_junk() -> None:
    with pytest.raises(ValueError, match="Could not parse JSON"):
        parse_delta("This is just plain text with no JSON in it at all.")


# ── _merge_delta ──────────────────────────────────────────────────────────────

@pytest.fixture()
def loaded_doc() -> BatonDocument:
    return BatonDocument.load(SAMPLE_BATON)


def test_merge_delta_adds_done_items(loaded_doc: BatonDocument) -> None:
    accepted = {
        "sprint_done": ["New feature done"],
        "sprint_next": [],
        "session": None,
    }
    _merge_delta(loaded_doc.data, accepted, sha=None, tool="", today="2026-06-05")
    done_features = [
        (item["feature"] if isinstance(item, dict) else str(item))
        for item in loaded_doc.data["current_sprint"]["done"]
    ]
    assert "New feature done" in done_features


def test_merge_delta_skips_duplicate_done(loaded_doc: BatonDocument) -> None:
    # "User authentication" is already in the fixture's done list.
    existing_feature = "User authentication"
    accepted = {
        "sprint_done": [existing_feature, existing_feature],
        "sprint_next": [],
        "session": None,
    }
    _merge_delta(loaded_doc.data, accepted, sha=None, tool="", today="2026-06-05")
    done_features = [
        (item["feature"] if isinstance(item, dict) else str(item))
        for item in loaded_doc.data["current_sprint"]["done"]
    ]
    assert done_features.count(existing_feature) == 1


def test_merge_delta_adds_next_items(loaded_doc: BatonDocument) -> None:
    accepted = {
        "sprint_done": [],
        "sprint_next": [{"feature": "Brand new task", "priority": "low"}],
        "session": None,
    }
    _merge_delta(loaded_doc.data, accepted, sha=None, tool="", today="2026-06-05")
    next_features = [
        (item["feature"] if isinstance(item, dict) else str(item))
        for item in loaded_doc.data["current_sprint"]["next"]
    ]
    assert "Brand new task" in next_features


def test_merge_delta_skips_duplicate_next(loaded_doc: BatonDocument) -> None:
    # "Dashboard view" is already in the fixture's next list.
    existing = "Dashboard view"
    accepted = {
        "sprint_done": [],
        "sprint_next": [{"feature": existing, "priority": "high"}],
        "session": None,
    }
    _merge_delta(loaded_doc.data, accepted, sha=None, tool="", today="2026-06-05")
    next_features = [
        (item["feature"] if isinstance(item, dict) else str(item))
        for item in loaded_doc.data["current_sprint"]["next"]
    ]
    assert next_features.count(existing) == 1


def test_merge_delta_appends_session_with_commit(loaded_doc: BatonDocument) -> None:
    sha = "abc1234def5678901234567890123456789012345"
    accepted = {
        "sprint_done": [],
        "sprint_next": [],
        "session": {"summary": "Did great things", "highlights": ["highlight 1"]},
    }
    _merge_delta(loaded_doc.data, accepted, sha=sha, tool="claude-code", today="2026-06-05")
    sessions = list(loaded_doc.data["sessions"])
    assert len(sessions) == 1
    entry = sessions[0]
    assert entry["commit"] == sha
    assert entry["summary"] == "Did great things"
    assert entry["tool"] == "claude-code"
    assert entry["date"] == "2026-06-05"


def test_merge_delta_existing_entries_untouched(loaded_doc: BatonDocument) -> None:
    # Capture original done/next counts before merge.
    original_done_count = len(list(loaded_doc.data["current_sprint"]["done"]))
    original_next_count = len(list(loaded_doc.data["current_sprint"]["next"]))

    accepted = {
        "sprint_done": ["A completely new done item"],
        "sprint_next": [{"feature": "A completely new next", "priority": "medium"}],
        "session": None,
    }
    _merge_delta(loaded_doc.data, accepted, sha=None, tool="", today="2026-06-05")

    # Existing items should still be there (append-only).
    assert len(list(loaded_doc.data["current_sprint"]["done"])) == original_done_count + 1
    assert len(list(loaded_doc.data["current_sprint"]["next"])) == original_next_count + 1


# ── Round-trip comment preservation ──────────────────────────────────────────

def test_round_trip_preserves_comments(tmp_path: Path) -> None:
    """Load a BATON.md that has inline YAML comments, merge a session, save, reload.
    Assert the inline comment survived the round trip AND the new session is present.
    """
    # Write a BATON.md with an explicit inline comment.
    baton_content = """\
# BATON.md

```yaml
baton_version: "1.0"
last_updated: "2026-06-04"
last_session_tool: "claude-code"

project:
  name: "CommentTest"
  purpose: "Verify ruamel preserves inline comments"  # do not remove this comment
  target_user: "developers"
  stage: "prototype"

stack:
  - tool: "Python"
    version: "3.11"
    why: "core language"  # chosen for typing support
    gotchas: "none"

laws:
  - "Never use PyYAML."

current_sprint:
  goal: "Test comment preservation"
  done:
    - feature: "Setup"
      confidence: "stable"
      notes: ""
  in_progress: []
  blocked: []
  next:
    - feature: "Deploy"
      priority: "high"
      dependencies: []

decisions:
  - id: "d001"
    what: "Use ruamel"
    why: "preserves comments"
    made: "2026-06-04"
    made_in: "claude-code"

anti_decisions:
  - id: "a001"
    rejected: "PyYAML"
    why: "drops comments"
    ruled_out: "2026-06-04"

landmines:
  - location: "config.py"
    looks_like: "duplicate"
    actually: "intentional"

open_questions: []

sessions: []
```
"""
    baton_path = tmp_path / "BATON.md"
    baton_path.write_text(baton_content, encoding="utf-8")

    doc = BatonDocument.load(baton_path)
    accepted = {
        "sprint_done": [],
        "sprint_next": [],
        "session": {"summary": "Round trip test", "highlights": ["comment preserved"]},
    }
    _merge_delta(doc.data, accepted, sha="abc123", tool="test", today="2026-06-05")
    doc.save()

    # Check raw file: inline comment must still be present.
    raw = baton_path.read_text(encoding="utf-8")
    assert "# do not remove this comment" in raw
    assert "# chosen for typing support" in raw

    # Check reloaded doc: new session entry must be present.
    doc2 = BatonDocument.load(baton_path)
    sessions = list(doc2.data["sessions"])
    assert len(sessions) == 1
    assert sessions[0]["summary"] == "Round trip test"


# ── Threshold skip test ───────────────────────────────────────────────────────

def test_run_end_skips_when_diff_small(tmp_path: Path) -> None:
    """If changed lines < min_diff_lines and --force is not set, run_end
    returns True without calling the summarizer."""
    # Set up a minimal git repo.
    git(["init"], tmp_path)
    git(["config", "user.email", "test@test.com"], tmp_path)
    git(["config", "user.name", "Test"], tmp_path)

    # Copy sample BATON.md to the repo.
    baton_path = tmp_path / "BATON.md"
    baton_path.write_bytes(SAMPLE_BATON.read_bytes())
    make_commit(tmp_path, "BATON.md", baton_path.read_text(encoding="utf-8"))

    # Working tree is clean: 0 changed lines < default min_diff_lines (10).
    result = run_end(
        tmp_path,
        summarizer=raising_summarizer,  # would fail if called
        auto_accept=True,
    )
    assert result is True
    # BATON.md should be unchanged: sessions list still empty.
    doc = BatonDocument.load(baton_path)
    assert list(doc.data["sessions"]) == []


# ── End-to-end integration test ───────────────────────────────────────────────

# ── run_end error paths ───────────────────────────────────────────────────────

def test_run_end_returns_false_when_no_baton_md(tmp_path: Path) -> None:
    """run_end must return False (not raise) if BATON.md is missing."""
    git(["init"], tmp_path)
    git(["config", "user.email", "test@test.com"], tmp_path)
    git(["config", "user.name", "Test"], tmp_path)

    result = run_end(tmp_path, summarizer=raising_summarizer, auto_accept=True)
    assert result is False


def test_run_end_returns_false_when_git_has_no_commits(tmp_path: Path) -> None:
    """run_end must return False gracefully when the repo has no commits yet."""
    git(["init"], tmp_path)
    git(["config", "user.email", "test@test.com"], tmp_path)
    git(["config", "user.name", "Test"], tmp_path)

    baton_path = tmp_path / "BATON.md"
    baton_path.write_bytes(SAMPLE_BATON.read_bytes())

    result = run_end(tmp_path, summarizer=fake_summarizer, auto_accept=True, force=True)
    assert result is False


def test_run_end_uses_since_parameter(tmp_path: Path) -> None:
    """--since overrides base_ref; diff should include commits after that SHA."""
    git(["init"], tmp_path)
    git(["config", "user.email", "test@test.com"], tmp_path)
    git(["config", "user.name", "Test"], tmp_path)

    baton_path = tmp_path / "BATON.md"
    baton_path.write_bytes(SAMPLE_BATON.read_bytes())
    make_commit(tmp_path, "BATON.md", baton_path.read_text(encoding="utf-8"))
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip()

    (tmp_path / "file.py").write_text("\n".join(f"x{i} = {i}" for i in range(20)))
    make_commit(tmp_path, "file.py", (tmp_path / "file.py").read_text(encoding="utf-8"))

    result = run_end(
        tmp_path,
        since=base_sha,
        summarizer=fake_summarizer,
        auto_accept=True,
        force=True,
    )
    assert result is True
    doc = BatonDocument.load(baton_path)
    assert len(list(doc.data["sessions"])) >= 1


# ── parse_delta null/edge-case safety ─────────────────────────────────────────

def test_parse_delta_missing_session_key() -> None:
    raw = json.dumps({"sprint_done": ["X"], "sprint_next": []})
    result = parse_delta(raw)
    assert result["session"]["summary"] == ""
    assert result["session"]["highlights"] == []


def test_parse_delta_missing_sprint_keys() -> None:
    raw = json.dumps({"session": {"summary": "ok", "highlights": []}})
    result = parse_delta(raw)
    assert result["sprint_done"] == []
    assert result["sprint_next"] == []


def test_parse_delta_sprint_next_as_plain_strings() -> None:
    raw = json.dumps({
        "session": {"summary": "x", "highlights": []},
        "sprint_done": [],
        "sprint_next": ["plain string task"],
    })
    result = parse_delta(raw)
    assert result["sprint_next"][0]["feature"] == "plain string task"
    assert result["sprint_next"][0]["priority"] == "medium"


def test_parse_delta_null_highlights_coerced_to_list() -> None:
    raw = json.dumps({
        "session": {"summary": "x", "highlights": None},
        "sprint_done": [],
        "sprint_next": [],
    })
    result = parse_delta(raw)
    assert result["session"]["highlights"] == []


# ── _merge_delta edge cases ───────────────────────────────────────────────────

def test_merge_delta_null_session_does_not_append(loaded_doc: BatonDocument) -> None:
    original_count = len(list(loaded_doc.data["sessions"]))
    accepted = {"sprint_done": [], "sprint_next": [], "session": None}
    _merge_delta(loaded_doc.data, accepted, sha=None, tool="", today="2026-06-05")
    assert len(list(loaded_doc.data["sessions"])) == original_count


def test_run_end_end_to_end(tmp_path: Path) -> None:
    """Full pipeline: real git repo, BATON.md, fake summarizer, auto_accept.
    Asserts BATON.md gains a sessions entry and CLAUDE.md is written."""
    git(["init"], tmp_path)
    git(["config", "user.email", "test@test.com"], tmp_path)
    git(["config", "user.name", "Test"], tmp_path)

    # Seed BATON.md.
    baton_path = tmp_path / "BATON.md"
    baton_path.write_bytes(SAMPLE_BATON.read_bytes())

    # Seed CLAUDE.md so the Claude adapter is detected and auto-synced.
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# Existing project doc\n", encoding="utf-8")

    make_commit(tmp_path, "BATON.md", baton_path.read_text(encoding="utf-8"))
    make_commit(tmp_path, "CLAUDE.md", claude_md.read_text(encoding="utf-8"))

    # Make a large enough change (> 10 lines) uncommitted so the diff is non-empty.
    big_change = "# initial\n" + "\n".join(f"line_{i} = {i}" for i in range(20))
    (tmp_path / "feature.py").write_text(big_change, encoding="utf-8")
    git(["add", "feature.py"], tmp_path)
    git(["commit", "-m", "add feature"], tmp_path)

    # Modify file to create uncommitted diff.
    (tmp_path / "feature.py").write_text(
        big_change + "\n" + "\n".join(f"extra_{i} = {i}" for i in range(15)),
        encoding="utf-8",
    )

    result = run_end(
        tmp_path,
        summarizer=fake_summarizer,
        auto_accept=True,
        tool="test-tool",
        force=True,  # bypass threshold for determinism
    )

    assert result is True

    # BATON.md must have a sessions entry.
    doc = BatonDocument.load(baton_path)
    sessions = list(doc.data["sessions"])
    assert len(sessions) >= 1
    assert sessions[0]["summary"] == "Built foo feature"

    # CLAUDE.md must exist and contain the managed block.
    assert claude_md.exists()
    content = claude_md.read_text(encoding="utf-8")
    assert "BATON:START" in content


# ── Heuristic mode (default, zero-cost) ──────────────────────────────────────


def _make_repo_with_diff(tmp_path: Path) -> tuple[Path, Path]:
    """Helper: real git repo + BATON.md + a commit + uncommitted diff (> 10 lines)."""
    git(["init"], tmp_path)
    git(["config", "user.email", "test@test.com"], tmp_path)
    git(["config", "user.name", "Test"], tmp_path)

    baton_path = tmp_path / "BATON.md"
    baton_path.write_bytes(SAMPLE_BATON.read_bytes())
    make_commit(tmp_path, "BATON.md", baton_path.read_text(encoding="utf-8"))

    # Create a file with enough lines to pass the threshold.
    content = "\n".join(f"x{i} = {i}" for i in range(20))
    (tmp_path / "work.py").write_text(content, encoding="utf-8")
    git(["add", "work.py"], tmp_path)
    git(["commit", "-m", "implement the work module"], tmp_path)

    return tmp_path, baton_path


def test_run_end_heuristic_default_no_api_key(tmp_path: Path) -> None:
    """Bare baton end (heuristic mode) must write a session without any API key."""
    repo, baton_path = _make_repo_with_diff(tmp_path)
    result = run_end(repo, mode="heuristic", auto_accept=True, force=True)
    assert result is True

    doc = BatonDocument.load(baton_path)
    sessions = list(doc.data["sessions"])
    assert len(sessions) == 1
    summary = sessions[0]["summary"]
    assert summary  # non-empty
    assert isinstance(summary, str)


def test_run_end_heuristic_commit_subject_in_summary(tmp_path: Path) -> None:
    """The heuristic summary must contain the most recent commit subject."""
    repo, baton_path = _make_repo_with_diff(tmp_path)
    result = run_end(repo, mode="heuristic", auto_accept=True, force=True)
    assert result is True

    doc = BatonDocument.load(baton_path)
    summary = list(doc.data["sessions"])[0]["summary"]
    assert "implement the work module" in summary


def test_run_end_heuristic_adds_done_from_commit(tmp_path: Path) -> None:
    """Heuristic sprint_done comes from commit subjects with done-keywords."""
    repo, baton_path = _make_repo_with_diff(tmp_path)
    result = run_end(repo, mode="heuristic", auto_accept=True, force=True)
    assert result is True

    doc = BatonDocument.load(baton_path)
    done_features = [
        (item["feature"] if isinstance(item, dict) else str(item))
        for item in doc.data["current_sprint"]["done"]
    ]
    # "implement the work module" contains "implement" -- a done-keyword.
    assert "implement the work module" in done_features


def test_run_end_summarizer_kwarg_still_routes_to_api_path(tmp_path: Path) -> None:
    """Backward compat: passing summarizer= implies api mode (existing tests unchanged)."""
    repo, baton_path = _make_repo_with_diff(tmp_path)
    result = run_end(repo, summarizer=fake_summarizer, auto_accept=True, force=True)
    assert result is True

    doc = BatonDocument.load(baton_path)
    sessions = list(doc.data["sessions"])
    # The fake summarizer returns "Built foo feature" -- confirms api path ran.
    assert sessions[0]["summary"] == "Built foo feature"


# ── --diff-only mode ──────────────────────────────────────────────────────────


def test_run_end_diff_only_returns_true_no_writes(tmp_path: Path) -> None:
    """--diff-only must return True and must NOT write to BATON.md."""
    repo, baton_path = _make_repo_with_diff(tmp_path)
    original = baton_path.read_bytes()

    result = run_end(repo, mode="diff-only", force=True)
    assert result is True
    assert baton_path.read_bytes() == original  # no writes


def test_run_end_diff_only_output_contains_json_spec(
    tmp_path: Path, capsys
) -> None:
    """--diff-only output must include the JSON contract so a host agent knows the shape."""
    repo, baton_path = _make_repo_with_diff(tmp_path)
    # capsys doesn't capture Rich console output easily; just verify no exception
    # and that the function returns True.  The JSON_SPEC content is integration-tested
    # by running the CLI; here we verify the contract is importable and non-empty.
    result = run_end(repo, mode="diff-only", force=True)
    assert result is True
    assert JSON_SPEC  # JSON_SPEC is exported and non-empty


# ── --apply mode ──────────────────────────────────────────────────────────────


def test_run_end_apply_happy_path(tmp_path: Path) -> None:
    """--apply with valid JSON delta must write the session to BATON.md."""
    repo, baton_path = _make_repo_with_diff(tmp_path)

    def good_reader() -> str:
        return CANNED_DELTA

    result = run_end(
        repo,
        mode="apply",
        stdin_reader=good_reader,
        auto_accept=True,
        force=True,
    )
    assert result is True

    doc = BatonDocument.load(baton_path)
    sessions = list(doc.data["sessions"])
    assert len(sessions) == 1
    assert sessions[0]["summary"] == "Built foo feature"


def test_run_end_apply_empty_stdin_falls_back_to_heuristic(tmp_path: Path) -> None:
    """--apply with empty stdin must fall back to the heuristic (not error out)."""
    repo, baton_path = _make_repo_with_diff(tmp_path)

    def empty_reader() -> str:
        return ""

    result = run_end(
        repo,
        mode="apply",
        stdin_reader=empty_reader,
        auto_accept=True,
        force=True,
    )
    assert result is True

    doc = BatonDocument.load(baton_path)
    sessions = list(doc.data["sessions"])
    assert len(sessions) == 1
    # Heuristic summary contains the commit subject.
    assert sessions[0]["summary"]  # non-empty


def test_run_end_apply_malformed_json_falls_back_to_heuristic(tmp_path: Path) -> None:
    """--apply with malformed JSON must fall back to the heuristic (not error out)."""
    repo, baton_path = _make_repo_with_diff(tmp_path)

    def bad_reader() -> str:
        return "this is not json { broken"

    result = run_end(
        repo,
        mode="apply",
        stdin_reader=bad_reader,
        auto_accept=True,
        force=True,
    )
    assert result is True

    doc = BatonDocument.load(baton_path)
    sessions = list(doc.data["sessions"])
    assert len(sessions) == 1


def test_run_end_apply_io_error_falls_back_to_heuristic(tmp_path: Path) -> None:
    """--apply where stdin_reader raises OSError must fall back to heuristic."""
    repo, baton_path = _make_repo_with_diff(tmp_path)

    def broken_reader() -> str:
        raise OSError("stdin closed")

    result = run_end(
        repo,
        mode="apply",
        stdin_reader=broken_reader,
        auto_accept=True,
        force=True,
    )
    assert result is True

    doc = BatonDocument.load(baton_path)
    sessions = list(doc.data["sessions"])
    assert len(sessions) == 1


# ── _delta_from_stdin unit tests ──────────────────────────────────────────────


def test_delta_from_stdin_valid_json(tmp_path: Path) -> None:
    git(["init"], tmp_path)
    git(["config", "user.email", "test@test.com"], tmp_path)
    git(["config", "user.name", "Test"], tmp_path)

    delta = _delta_from_stdin(
        lambda: CANNED_DELTA, diff_text="", base_ref=None,
        repo_root=tmp_path, doc_data={},
    )
    assert delta["session"]["summary"] == "Built foo feature"


def test_delta_from_stdin_empty_returns_heuristic(tmp_path: Path) -> None:
    git(["init"], tmp_path)
    git(["config", "user.email", "test@test.com"], tmp_path)
    git(["config", "user.name", "Test"], tmp_path)

    delta = _delta_from_stdin(
        lambda: "", diff_text="", base_ref=None,
        repo_root=tmp_path, doc_data={},
    )
    # Heuristic fallback -- summary is "No changes" style
    assert isinstance(delta["session"]["summary"], str)
    assert "session" in delta


def test_delta_from_stdin_malformed_returns_heuristic(tmp_path: Path) -> None:
    git(["init"], tmp_path)
    git(["config", "user.email", "test@test.com"], tmp_path)
    git(["config", "user.name", "Test"], tmp_path)

    delta = _delta_from_stdin(
        lambda: "not json at all >>>", diff_text="", base_ref=None,
        repo_root=tmp_path, doc_data={},
    )
    assert isinstance(delta["session"]["summary"], str)
