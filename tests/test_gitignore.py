"""
test_gitignore.py -- Tests for core/gitignore.py
"""
from __future__ import annotations

import pytest

from baton.core.gitignore import ensure_scope_committable


def _write_gitignore(tmp_path, content: str) -> None:
    (tmp_path / ".gitignore").write_text(content, encoding="utf-8")


def _read_gitignore(tmp_path) -> str:
    return (tmp_path / ".gitignore").read_text(encoding="utf-8")


def _lines(tmp_path) -> list[str]:
    return _read_gitignore(tmp_path).splitlines()


# ── Core mechanic ─────────────────────────────────────────────────────────────

def test_bare_baton_dir_transformed_to_glob(tmp_path) -> None:
    _write_gitignore(tmp_path, ".baton/\n")
    ensure_scope_committable(tmp_path)
    lines = _lines(tmp_path)
    assert ".baton/*" in lines
    assert ".baton/" not in lines


def test_negation_added_after_transform(tmp_path) -> None:
    _write_gitignore(tmp_path, ".baton/\n")
    ensure_scope_committable(tmp_path)
    lines = _lines(tmp_path)
    assert "!.baton/scope.md" in lines


def test_negation_immediately_after_glob_line(tmp_path) -> None:
    _write_gitignore(tmp_path, ".baton/\n")
    ensure_scope_committable(tmp_path)
    lines = _lines(tmp_path)
    glob_idx = lines.index(".baton/*")
    neg_idx = lines.index("!.baton/scope.md")
    assert neg_idx == glob_idx + 1


def test_scope_md_not_ignored_alerts_json_still_ignored(tmp_path) -> None:
    """Verify the resulting .gitignore text has the correct structure.

    We can't call `git check-ignore` without a real git repo, so we assert on
    the gitignore content which is what the real git engine reads.
    """
    _write_gitignore(tmp_path, ".baton/\n")
    ensure_scope_committable(tmp_path)
    lines = _lines(tmp_path)
    # .baton/* ignores contents (alerts.json, etc.)
    assert ".baton/*" in lines
    # Negation un-ignores scope.md specifically.
    assert "!.baton/scope.md" in lines
    # The bare directory form is gone (it would block negation from working).
    assert ".baton/" not in lines


# ── Idempotency ───────────────────────────────────────────────────────────────

def test_idempotent_double_run(tmp_path) -> None:
    _write_gitignore(tmp_path, ".baton/\n")
    ensure_scope_committable(tmp_path)
    content_after_first = _read_gitignore(tmp_path)
    ensure_scope_committable(tmp_path)
    content_after_second = _read_gitignore(tmp_path)
    assert content_after_first == content_after_second


def test_idempotent_triple_run_line_count(tmp_path) -> None:
    _write_gitignore(tmp_path, ".baton/\n")
    ensure_scope_committable(tmp_path)
    first_lines = _lines(tmp_path)
    ensure_scope_committable(tmp_path)
    ensure_scope_committable(tmp_path)
    assert _lines(tmp_path) == first_lines


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_no_baton_line_appends_both(tmp_path) -> None:
    _write_gitignore(tmp_path, "*.pyc\n__pycache__/\n")
    ensure_scope_committable(tmp_path)
    lines = _lines(tmp_path)
    assert ".baton/*" in lines
    assert "!.baton/scope.md" in lines


def test_no_gitignore_creates_one(tmp_path) -> None:
    assert not (tmp_path / ".gitignore").exists()
    ensure_scope_committable(tmp_path)
    assert (tmp_path / ".gitignore").exists()
    lines = _lines(tmp_path)
    assert ".baton/*" in lines
    assert "!.baton/scope.md" in lines


def test_surrounding_lines_preserved(tmp_path) -> None:
    _write_gitignore(tmp_path, "*.pyc\n.baton/\ndist/\n")
    ensure_scope_committable(tmp_path)
    lines = _lines(tmp_path)
    assert "*.pyc" in lines
    assert "dist/" in lines


def test_other_baton_rules_preserved(tmp_path) -> None:
    content = "*.pyc\n.baton/\n# Baton adapter outputs\nCLAUDE.md\n"
    _write_gitignore(tmp_path, content)
    ensure_scope_committable(tmp_path)
    lines = _lines(tmp_path)
    assert "CLAUDE.md" in lines
    assert "# Baton adapter outputs" in lines
