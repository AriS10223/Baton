"""
test_hooks.py -- Tests for baton/commands/hooks.py.

Uses real temporary directories (tmp_path).  No mocking of filesystem calls.
"""
from __future__ import annotations

import stat
from pathlib import Path

import pytest

from baton.adapters.base import extract_managed_block
from baton.commands.hooks import (
    _POST_COMMIT_INNER,
    _PRE_COMMIT_REMINDER_INNER,
    _PRE_COMMIT_STRICT_INNER,
    _write_hook,
    install_post_commit_hook,
    install_pre_commit_reminder,
    install_pre_commit_strict,
    run_hooks_install,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def hooks_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".git" / "hooks"
    d.mkdir(parents=True)
    return d


@pytest.fixture()
def repo_with_git(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    return tmp_path


# ── _write_hook ───────────────────────────────────────────────────────────────


def test_write_hook_creates_new_file(hooks_dir: Path) -> None:
    import sys

    result = _write_hook(hooks_dir, "post-commit", _POST_COMMIT_INNER)
    assert result == "created"
    hook_path = hooks_dir / "post-commit"
    assert hook_path.exists()
    content = hook_path.read_text(encoding="utf-8")
    assert content.startswith("#!/bin/sh\n")
    assert extract_managed_block(content) is not None
    # Check executable bit on the owner (not meaningful on Windows)
    if sys.platform != "win32":
        mode = hook_path.stat().st_mode
        assert mode & stat.S_IEXEC


def test_write_hook_is_idempotent(hooks_dir: Path) -> None:
    _write_hook(hooks_dir, "post-commit", _POST_COMMIT_INNER)
    result = _write_hook(hooks_dir, "post-commit", _POST_COMMIT_INNER)
    assert result == "unchanged"


def test_write_hook_updates_existing_block(hooks_dir: Path) -> None:
    _write_hook(hooks_dir, "post-commit", _POST_COMMIT_INNER)
    result = _write_hook(hooks_dir, "post-commit", _PRE_COMMIT_REMINDER_INNER)
    assert result == "updated"
    content = (hooks_dir / "post-commit").read_text(encoding="utf-8")
    # Shebang must still be at top
    assert content.startswith("#!/bin/sh\n")
    # New inner content must be present
    inner = extract_managed_block(content)
    assert inner is not None
    assert "baton end" in inner


def test_write_hook_preserves_user_content(hooks_dir: Path) -> None:
    from baton.adapters.base import upsert_managed_block

    user_content = "#!/bin/sh\n# my own stuff\necho hello\n"
    existing = user_content + upsert_managed_block("", _POST_COMMIT_INNER)
    hook_path = hooks_dir / "pre-commit"
    hook_path.write_text(existing, encoding="utf-8")

    result = _write_hook(hooks_dir, "pre-commit", _PRE_COMMIT_REMINDER_INNER)
    assert result == "updated"

    updated = hook_path.read_text(encoding="utf-8")
    assert "my own stuff" in updated
    assert "echo hello" in updated
    inner = extract_managed_block(updated)
    assert inner is not None
    assert "baton end" in inner


def test_write_hook_appends_to_hook_without_block(hooks_dir: Path) -> None:
    hook_path = hooks_dir / "pre-commit"
    user_content = "#!/bin/sh\n# existing hook without baton\necho done\n"
    hook_path.write_text(user_content, encoding="utf-8")

    result = _write_hook(hooks_dir, "pre-commit", _POST_COMMIT_INNER)
    assert result == "updated"

    content = hook_path.read_text(encoding="utf-8")
    assert "existing hook without baton" in content
    assert "echo done" in content
    assert extract_managed_block(content) is not None


# ── install_* helpers ─────────────────────────────────────────────────────────


def test_install_post_commit_hook_creates_file(hooks_dir: Path) -> None:
    install_post_commit_hook(hooks_dir)
    assert (hooks_dir / "post-commit").exists()


def test_install_pre_commit_reminder_creates_file(hooks_dir: Path) -> None:
    install_pre_commit_reminder(hooks_dir)
    assert (hooks_dir / "pre-commit").exists()


def test_install_pre_commit_strict_creates_file(hooks_dir: Path) -> None:
    install_pre_commit_strict(hooks_dir)
    hook_path = hooks_dir / "pre-commit"
    assert hook_path.exists()
    content = hook_path.read_text(encoding="utf-8")
    inner = extract_managed_block(content)
    assert inner is not None
    assert "fail-on block" in inner


def test_install_pre_commit_strict_replaces_reminder(hooks_dir: Path) -> None:
    install_pre_commit_reminder(hooks_dir)
    result = install_pre_commit_strict(hooks_dir)
    assert result == "updated"
    content = (hooks_dir / "pre-commit").read_text(encoding="utf-8")
    inner = extract_managed_block(content)
    assert inner is not None
    assert "fail-on block" in inner
    # Reminder-only content should be gone from the managed block
    assert "baton end" not in inner


# ── run_hooks_install ─────────────────────────────────────────────────────────


def test_run_hooks_install_creates_post_commit(repo_with_git: Path) -> None:
    run_hooks_install(repo_with_git)
    assert (repo_with_git / ".git" / "hooks" / "post-commit").exists()


def test_run_hooks_install_strict_creates_pre_commit(repo_with_git: Path) -> None:
    run_hooks_install(repo_with_git, strict=True)
    assert (repo_with_git / ".git" / "hooks" / "post-commit").exists()
    assert (repo_with_git / ".git" / "hooks" / "pre-commit").exists()


def test_run_hooks_install_no_git_dir_does_not_raise(tmp_path: Path) -> None:
    # No .git directory present -- should not raise, just print a message.
    run_hooks_install(tmp_path)
