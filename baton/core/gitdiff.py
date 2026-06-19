"""
gitdiff.py -- git helpers for ``baton end``.

Commit-aware diffing strategy:
- ``resolve_base_ref`` returns the HEAD SHA stored in the last session entry,
  so ``get_diff`` captures all commits made *since* that point plus any
  uncommitted changes still in the working tree.
- Falls back to ``git diff HEAD`` (uncommitted changes only) on the first
  run or when no prior session SHA exists.
- Diffs are capped at MAX_DIFF_CHARS (~24k) to avoid blowing the token budget.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

MAX_DIFF_CHARS = 24_000
_TRUNCATION_MARKER = (
    "\n... [diff truncated -- too large to include in full] ...\n"
)


class GitError(Exception):
    """Raised when git is unavailable or the repo has no git history."""


def _run(args: list[str], cwd: Path) -> str:
    """Run a git command; return stdout. Raise GitError on failure."""
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise GitError(
            "git not found. Install git and try again."
        )
    if result.returncode != 0:
        msg = result.stderr.strip() or f"git exited with code {result.returncode}"
        raise GitError(msg)
    return result.stdout


def head_sha(repo_root: Path) -> str | None:
    """Return the current HEAD SHA, or None if the repo has no commits."""
    try:
        return _run(["git", "rev-parse", "HEAD"], repo_root).strip()
    except GitError:
        return None


def resolve_base_ref(doc_data: dict, since: str | None) -> str | None:
    """Return the git ref to diff from, in priority order:

    1. ``--since`` flag (explicit user override)
    2. ``commit`` field of the last session entry in BATON.md
    3. None -- caller falls back to ``git diff HEAD``
    """
    if since:
        return since
    sessions = doc_data.get("sessions")
    if sessions and isinstance(sessions, list) and sessions:
        last = sessions[-1]
        if isinstance(last, dict):
            return last.get("commit") or None
    return None


def get_diff(repo_root: Path, base_ref: str | None) -> str:
    """Return the git diff as a string, capped at MAX_DIFF_CHARS.

    When *base_ref* is given: ``git diff <base_ref>`` -- includes all commits
    since that SHA plus any uncommitted working-tree changes.
    When *base_ref* is None: ``git diff HEAD`` -- uncommitted changes only.
    """
    if base_ref:
        args = ["git", "diff", base_ref]
    else:
        args = ["git", "diff", "HEAD"]

    diff = _run(args, repo_root)

    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + _TRUNCATION_MARKER

    return diff


def count_changed_lines(diff: str) -> int:
    """Count added/removed body lines in a unified diff.

    Ignores ``+++``/``---`` file-header lines; only body ``+``/``-`` lines
    count toward the min_diff_lines threshold.
    """
    count = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            count += 1
    return count


def get_commit_log(
    repo_root: Path,
    base_ref: str | None,
    max_entries: int = 20,
) -> list[str]:
    """Return commit-message subjects since *base_ref* (or the last *max_entries*).

    Returns an empty list (never raises) if git is unavailable, the repo has
    no commits, or *base_ref* is unknown -- the heuristic summarizer degrades
    gracefully when the log is empty.
    """
    if base_ref:
        args = [
            "git", "log",
            f"{base_ref}..HEAD",
            "--format=%s",
            f"--max-count={max_entries}",
        ]
    else:
        args = ["git", "log", "-n", str(max_entries), "--format=%s"]

    try:
        out = _run(args, repo_root)
        return [line.strip() for line in out.splitlines() if line.strip()]
    except GitError:
        return []
