"""Tests for baton/core/pr_template.py."""
from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from baton.core.pr_template import write_pr_template, _TEMPLATE_CONTENT, _TARGET


# ── Helper ────────────────────────────────────────────────────────────────────

def _silent_console() -> Console:
    """Return a Rich console that writes to a StringIO buffer."""
    return Console(file=StringIO(), highlight=False)


def _capturing_console() -> tuple[Console, StringIO]:
    buf = StringIO()
    return Console(file=buf, highlight=False, markup=True), buf


# ── Creation tests ────────────────────────────────────────────────────────────

def test_creates_file_when_absent(tmp_path):
    result = write_pr_template(tmp_path, console=_silent_console())
    target = tmp_path / _TARGET
    assert target.exists()
    assert result is True


def test_returns_true_on_creation(tmp_path):
    result = write_pr_template(tmp_path, console=_silent_console())
    assert result is True


def test_file_contains_why_marker(tmp_path):
    write_pr_template(tmp_path, console=_silent_console())
    content = (tmp_path / _TARGET).read_text(encoding="utf-8")
    assert "WHY:" in content


def test_file_contains_baton_marker(tmp_path):
    write_pr_template(tmp_path, console=_silent_console())
    content = (tmp_path / _TARGET).read_text(encoding="utf-8")
    assert "BATON:" in content


def test_file_content_matches_template(tmp_path):
    write_pr_template(tmp_path, console=_silent_console())
    content = (tmp_path / _TARGET).read_text(encoding="utf-8")
    assert content == _TEMPLATE_CONTENT


def test_creates_github_directory_if_missing(tmp_path):
    github_dir = tmp_path / ".github"
    assert not github_dir.exists()
    write_pr_template(tmp_path, console=_silent_console())
    assert github_dir.is_dir()


def test_file_is_utf8(tmp_path):
    write_pr_template(tmp_path, console=_silent_console())
    # Should be readable as UTF-8 without error
    content = (tmp_path / _TARGET).read_bytes().decode("utf-8")
    assert "WHY:" in content


# ── Idempotency / existing-file tests ────────────────────────────────────────

def test_returns_false_when_file_exists(tmp_path):
    write_pr_template(tmp_path, console=_silent_console())
    result = write_pr_template(tmp_path, console=_silent_console())
    assert result is False


def test_does_not_overwrite_existing_file(tmp_path):
    target = tmp_path / _TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    original = "# Custom PR template\n\nDo not overwrite me.\n"
    target.write_text(original, encoding="utf-8")

    write_pr_template(tmp_path, console=_silent_console())

    assert target.read_text(encoding="utf-8") == original


def test_existing_file_content_is_preserved(tmp_path):
    target = tmp_path / _TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    custom_content = "## My Custom Template\n\nI have my own format.\n"
    target.write_text(custom_content, encoding="utf-8")

    write_pr_template(tmp_path, console=_silent_console())

    assert target.read_text(encoding="utf-8") == custom_content


def test_warn_printed_when_file_exists(tmp_path):
    write_pr_template(tmp_path, console=_silent_console())
    console, buf = _capturing_console()
    write_pr_template(tmp_path, console=console)
    output = buf.getvalue()
    assert "already exists" in output or "WARN" in output


def test_warn_mentions_why_marker(tmp_path):
    write_pr_template(tmp_path, console=_silent_console())
    console, buf = _capturing_console()
    write_pr_template(tmp_path, console=console)
    output = buf.getvalue()
    assert "WHY:" in output


def test_warn_mentions_baton_marker(tmp_path):
    write_pr_template(tmp_path, console=_silent_console())
    console, buf = _capturing_console()
    write_pr_template(tmp_path, console=console)
    output = buf.getvalue()
    assert "BATON:" in output


# ── Default console ───────────────────────────────────────────────────────────

def test_default_console_does_not_crash(tmp_path):
    # Should not raise even with no console arg
    result = write_pr_template(tmp_path)
    assert result is True


# ── Target path ───────────────────────────────────────────────────────────────

def test_target_path_is_github_pr_template(tmp_path):
    write_pr_template(tmp_path, console=_silent_console())
    expected = tmp_path / ".github" / "pull_request_template.md"
    assert expected.exists()
