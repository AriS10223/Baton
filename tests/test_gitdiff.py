"""
test_gitdiff.py -- Tests for baton/core/gitdiff.py.

All tests use real filesystem + real git subprocess calls via tmp_path.
No mocking.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from baton.core.gitdiff import (
    MAX_DIFF_CHARS,
    _TRUNCATION_MARKER,
    count_changed_lines,
    get_diff,
    head_sha,
    resolve_base_ref,
)


# ── Git helper ────────────────────────────────────────────────────────────────

def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Create a minimal git repo in tmp_path."""
    git(["init"], tmp_path)
    git(["config", "user.email", "test@test.com"], tmp_path)
    git(["config", "user.name", "Test"], tmp_path)
    return tmp_path


def make_commit(repo: Path, filename: str, content: str, message: str = "commit") -> str:
    """Write a file, stage and commit it; return the resulting HEAD SHA."""
    (repo / filename).write_text(content, encoding="utf-8")
    git(["add", filename], repo)
    git(["commit", "-m", message], repo)
    return head_sha(repo)


# ── head_sha ──────────────────────────────────────────────────────────────────

def test_head_sha_returns_none_before_first_commit(repo: Path) -> None:
    assert head_sha(repo) is None


def test_head_sha_returns_sha_after_commit(repo: Path) -> None:
    make_commit(repo, "hello.txt", "hello\n")
    sha = head_sha(repo)
    assert sha is not None
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


# ── resolve_base_ref ──────────────────────────────────────────────────────────

def test_resolve_base_ref_prefers_since_flag() -> None:
    data = {"sessions": [{"date": "2026-01-01", "commit": "abc123def456"}]}
    result = resolve_base_ref(data, since="explicit-sha")
    assert result == "explicit-sha"


def test_resolve_base_ref_uses_last_session_commit() -> None:
    data = {
        "sessions": [
            {"date": "2026-01-01", "commit": "firstsha"},
            {"date": "2026-01-02", "commit": "lastsha1234567890"},
        ]
    }
    result = resolve_base_ref(data, since=None)
    assert result == "lastsha1234567890"


def test_resolve_base_ref_returns_none_when_no_sessions() -> None:
    result = resolve_base_ref({"sessions": []}, since=None)
    assert result is None


def test_resolve_base_ref_returns_none_when_sessions_key_missing() -> None:
    result = resolve_base_ref({}, since=None)
    assert result is None


def test_resolve_base_ref_returns_none_when_session_has_no_commit() -> None:
    data = {"sessions": [{"date": "2026-01-01"}]}  # no "commit" key
    result = resolve_base_ref(data, since=None)
    assert result is None


# ── get_diff ──────────────────────────────────────────────────────────────────

def test_get_diff_uncommitted_changes(repo: Path) -> None:
    # First commit establishes a tracked file.
    make_commit(repo, "app.py", "x = 1\n")
    # Now modify it without committing.
    (repo / "app.py").write_text("x = 1\ny = 2\n", encoding="utf-8")

    diff = get_diff(repo, None)
    assert diff  # non-empty
    assert "+y = 2" in diff


def test_get_diff_from_base_ref(repo: Path) -> None:
    sha_a = make_commit(repo, "app.py", "x = 1\n", "commit A")
    make_commit(repo, "app.py", "x = 1\ny = 2\n", "commit B")

    diff = get_diff(repo, sha_a)
    assert "+y = 2" in diff


def test_get_diff_truncation(repo: Path) -> None:
    # Commit a small initial version, then overwrite with a huge file.
    make_commit(repo, "bigfile.py", "# initial\n")
    huge_content = "x = 1\n" * 10_000  # ~60k chars of diff content
    (repo / "bigfile.py").write_text(huge_content, encoding="utf-8")
    # Keep it uncommitted so git diff HEAD catches it.

    diff = get_diff(repo, None)
    assert _TRUNCATION_MARKER in diff
    assert len(diff) <= MAX_DIFF_CHARS + len(_TRUNCATION_MARKER)


# ── count_changed_lines ───────────────────────────────────────────────────────

_SAMPLE_DIFF = """\
diff --git a/foo.py b/foo.py
index abc..def 100644
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 unchanged
-removed line
+added line
+another added
"""


def test_count_changed_lines_basic() -> None:
    # 1 removal + 2 additions = 3, ignoring the --- and +++ header lines
    assert count_changed_lines(_SAMPLE_DIFF) == 3


def test_count_changed_lines_ignores_headers() -> None:
    diff = "--- a/foo.py\n+++ b/foo.py\n+actual add\n"
    # Only the "+actual add" line counts; the --- and +++ are headers.
    assert count_changed_lines(diff) == 1


def test_count_changed_lines_empty_diff() -> None:
    assert count_changed_lines("") == 0


def test_count_changed_lines_only_context_lines() -> None:
    diff = " context line\n context line 2\n"
    assert count_changed_lines(diff) == 0
