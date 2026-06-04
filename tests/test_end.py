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

from baton.commands.end import _merge_delta, run_end
from baton.core.document import BatonDocument
from baton.core.summarizer import parse_delta

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
