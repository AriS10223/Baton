"""
test_scope_io.py -- Tests for core/scope_io.py
"""
from __future__ import annotations

import json

import pytest

from baton.core.scope_io import clear_scope, load_scope, save_scope, scope_active


def test_load_scope_absent_returns_empty(tmp_path) -> None:
    assert load_scope(tmp_path) == {}


def test_load_scope_corrupt_returns_empty(tmp_path) -> None:
    baton_dir = tmp_path / ".baton"
    baton_dir.mkdir()
    (baton_dir / "scope.json").write_text("NOT JSON", encoding="utf-8")
    assert load_scope(tmp_path) == {}


def test_load_scope_non_dict_returns_empty(tmp_path) -> None:
    baton_dir = tmp_path / ".baton"
    baton_dir.mkdir()
    (baton_dir / "scope.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert load_scope(tmp_path) == {}


def test_save_load_roundtrip(tmp_path) -> None:
    state = {"task": "fix auth", "keywords": ["auth"], "entry_ids": ["d001"], "generated_at": "2026-01-01T00:00:00Z"}
    save_scope(tmp_path, state)
    loaded = load_scope(tmp_path)
    assert loaded == state


def test_save_creates_baton_dir(tmp_path) -> None:
    assert not (tmp_path / ".baton").exists()
    save_scope(tmp_path, {"task": "test"})
    assert (tmp_path / ".baton" / "scope.json").exists()


def test_scope_active_true_when_task_present(tmp_path) -> None:
    save_scope(tmp_path, {"task": "fix auth"})
    assert scope_active(tmp_path) is True


def test_scope_active_false_when_absent(tmp_path) -> None:
    assert scope_active(tmp_path) is False


def test_scope_active_false_when_empty_task(tmp_path) -> None:
    save_scope(tmp_path, {"task": ""})
    assert scope_active(tmp_path) is False


def test_clear_scope_removes_json_and_md(tmp_path) -> None:
    save_scope(tmp_path, {"task": "fix auth"})
    baton_dir = tmp_path / ".baton"
    (baton_dir / "scope.md").write_text("# Baton Scope\n", encoding="utf-8")
    clear_scope(tmp_path)
    assert not (baton_dir / "scope.json").exists()
    assert not (baton_dir / "scope.md").exists()


def test_clear_scope_safe_when_already_absent(tmp_path) -> None:
    clear_scope(tmp_path)  # must not raise


def test_load_scope_never_raises(tmp_path) -> None:
    (tmp_path / ".baton").mkdir()
    (tmp_path / ".baton" / "scope.json").write_bytes(b"\xff\xfe invalid")
    result = load_scope(tmp_path)
    assert isinstance(result, dict)
