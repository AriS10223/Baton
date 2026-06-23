"""
test_alerts.py -- Tests for baton/core/alerts.py.

All tests use real filesystem via tmp_path.  No mocking, no external deps.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from baton.core.alerts import (
    load_acks,
    load_alerts,
    load_last_check_sha,
    save_acks,
    save_alerts,
    save_last_check_sha,
)


# ── load_alerts ───────────────────────────────────────────────────────────────

def test_load_alerts_missing_file_returns_empty(tmp_path: Path) -> None:
    result = load_alerts(tmp_path)
    assert result == {"alerts": [], "since_sha": "", "generated_at": ""}


def test_save_load_alerts_roundtrip(tmp_path: Path) -> None:
    data = {
        "generated_at": "2026-06-20T00:00:00Z",
        "since_sha": "abc123",
        "alerts": [
            {
                "id": "a002",
                "type": "anti_decision",
                "severity": "block",
                "status": "violated",
                "file": "src/utils/date.ts",
                "line": 14,
                "detail": "Uses moment.js which was ruled out",
            }
        ],
    }
    save_alerts(tmp_path, data)
    loaded = load_alerts(tmp_path)
    assert loaded == data


def test_save_alerts_creates_baton_dir(tmp_path: Path) -> None:
    baton_dir = tmp_path / ".baton"
    assert not baton_dir.exists()
    save_alerts(tmp_path, {"alerts": [], "since_sha": "", "generated_at": ""})
    assert baton_dir.is_dir()
    assert (baton_dir / "alerts.json").is_file()


def test_load_alerts_corrupt_json_returns_empty(tmp_path: Path) -> None:
    baton_dir = tmp_path / ".baton"
    baton_dir.mkdir()
    (baton_dir / "alerts.json").write_text("{not valid json", encoding="utf-8")
    result = load_alerts(tmp_path)
    assert result == {"alerts": [], "since_sha": "", "generated_at": ""}


# ── load_acks / save_acks ─────────────────────────────────────────────────────

def test_load_acks_missing_file_returns_empty_list(tmp_path: Path) -> None:
    result = load_acks(tmp_path)
    assert result == []


def test_save_load_acks_roundtrip(tmp_path: Path) -> None:
    acks = [
        {
            "id": "a002",
            "reason": "intentional, migrating",
            "sha": "abc123",
            "date": "2026-06-20",
        }
    ]
    save_acks(tmp_path, acks)
    loaded = load_acks(tmp_path)
    assert loaded == acks


def test_load_acks_corrupt_json_returns_empty(tmp_path: Path) -> None:
    baton_dir = tmp_path / ".baton"
    baton_dir.mkdir()
    (baton_dir / "ack.json").write_text("[broken", encoding="utf-8")
    result = load_acks(tmp_path)
    assert result == []


# ── load_last_check_sha / save_last_check_sha ─────────────────────────────────

def test_load_last_check_sha_missing_returns_none(tmp_path: Path) -> None:
    result = load_last_check_sha(tmp_path)
    assert result is None


def test_save_load_last_check_sha_roundtrip(tmp_path: Path) -> None:
    sha = "deadbeef1234567890abcdef"
    save_last_check_sha(tmp_path, sha)
    loaded = load_last_check_sha(tmp_path)
    assert loaded == sha


def test_save_last_check_sha_creates_baton_dir(tmp_path: Path) -> None:
    baton_dir = tmp_path / ".baton"
    assert not baton_dir.exists()
    save_last_check_sha(tmp_path, "somesha")
    assert baton_dir.is_dir()
    assert (baton_dir / "last_check_sha").is_file()
