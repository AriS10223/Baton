"""
test_resolve_since.py -- Tests for resolve_since() in baton/core/gitdiff.py.

All tests use real filesystem + real git subprocess calls via tmp_path.
No mocking.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from baton.core.gitdiff import GitError, head_sha, resolve_since


# ── Git helpers ───────────────────────────────────────────────────────────────

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
    """Create a minimal git repo with one commit."""
    git(["init"], tmp_path)
    git(["config", "user.email", "test@test.com"], tmp_path)
    git(["config", "user.name", "Test"], tmp_path)
    (tmp_path / "file.txt").write_text("initial\n", encoding="utf-8")
    git(["add", "file.txt"], tmp_path)
    git(["commit", "-m", "initial commit"], tmp_path)
    return tmp_path


def make_commit(repo: Path, filename: str, content: str, message: str = "commit") -> str:
    """Write a file, stage and commit it; return the resulting HEAD SHA."""
    (repo / filename).write_text(content, encoding="utf-8")
    git(["add", filename], repo)
    git(["commit", "-m", message], repo)
    return head_sha(repo)


# ── resolve_since tests ───────────────────────────────────────────────────────

def test_resolve_since_full_sha(repo: Path) -> None:
    """A full 40-char SHA resolves to itself."""
    sha = head_sha(repo)
    result = resolve_since(repo, sha)
    assert result == sha
    assert len(result) == 40


def test_resolve_since_short_sha(repo: Path) -> None:
    """A short SHA (7 chars) resolves to the full 40-char SHA."""
    sha = head_sha(repo)
    short = sha[:7]
    result = resolve_since(repo, short)
    assert result == sha


def test_resolve_since_branch_name(repo: Path) -> None:
    """A branch name (main/master) resolves to the HEAD SHA of that branch."""
    sha = head_sha(repo)
    # Determine the default branch name
    result_main = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    branch = result_main.stdout.strip()
    result = resolve_since(repo, branch)
    assert result == sha


def test_resolve_since_head_tilde_zero(repo: Path) -> None:
    """HEAD~0 resolves to the current HEAD SHA."""
    sha = head_sha(repo)
    result = resolve_since(repo, "HEAD~0")
    assert result == sha


def test_resolve_since_head_tilde_one(repo: Path) -> None:
    """HEAD~1 resolves to the parent commit SHA."""
    sha_first = head_sha(repo)
    make_commit(repo, "second.txt", "second\n", "second commit")
    result = resolve_since(repo, "HEAD~1")
    assert result == sha_first


def test_resolve_since_head_at_zero(repo: Path) -> None:
    """@{0} is reflog syntax for the current HEAD -- always resolves in a local repo."""
    sha = head_sha(repo)
    result = resolve_since(repo, "@{0}")
    assert result == sha


def test_resolve_since_reflog_at_n(repo: Path) -> None:
    """@{0} resolves via the literal path (step 1); verifying reflog date path works."""
    sha = head_sha(repo)
    # HEAD@{0} is a valid reflog ref and should resolve on step 1
    result = resolve_since(repo, "HEAD@{0}")
    assert result == sha


def test_resolve_since_unresolvable_raises_git_error(repo: Path) -> None:
    """An unresolvable value raises GitError naming both forms tried.

    Note: the bad value must not contain natural-language date words (like
    'yesterday', 'ago', 'week', etc.) or alphabetic sequences that git's
    date parser might interpret as relative dates. 'NOPE' and 'XXXFAKEXXX'
    are safe because they contain no parseable date tokens.
    """
    bad = "XXXFAKEXXX"
    with pytest.raises(GitError) as exc_info:
        resolve_since(repo, bad)
    msg = str(exc_info.value)
    assert bad in msg
    assert f"@{{{bad}}}" in msg


def test_resolve_since_error_message_mentions_original_and_date_form(repo: Path) -> None:
    """Error message clearly shows both forms that were attempted."""
    bad = "NOT-A-REF"
    with pytest.raises(GitError) as exc_info:
        resolve_since(repo, bad)
    msg = str(exc_info.value)
    # Original form
    assert bad in msg
    # Date-wrapped form
    assert f"@{{{bad}}}" in msg


def test_resolve_since_tag(repo: Path) -> None:
    """A git tag resolves to the tagged commit SHA."""
    sha = head_sha(repo)
    git(["tag", "v1.0.0"], repo)
    result = resolve_since(repo, "v1.0.0")
    assert result == sha


def test_resolve_since_returns_string(repo: Path) -> None:
    """Return type is always a plain str (no trailing newline)."""
    sha = head_sha(repo)
    result = resolve_since(repo, sha)
    assert isinstance(result, str)
    assert "\n" not in result
