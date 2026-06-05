"""
test_config.py -- Tests for baton/core/config.py (BatonConfig).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from baton.core.config import BatonConfig


# ── Defaults (no .baton.toml) ─────────────────────────────────────────────────

def test_defaults_when_no_toml(tmp_path: Path) -> None:
    config = BatonConfig.load(tmp_path)
    assert config.llm_provider == "anthropic"
    assert config.model == ""
    assert config.min_diff_lines == 10
    assert config.auto_sync is True
    assert config.enabled_adapters == []


def test_load_returns_batonconfig_instance(tmp_path: Path) -> None:
    config = BatonConfig.load(tmp_path)
    assert isinstance(config, BatonConfig)


# ── Reading values from .baton.toml ──────────────────────────────────────────

def test_reads_llm_provider(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text(
        '[baton]\nllm_provider = "openai"\n', encoding="utf-8"
    )
    config = BatonConfig.load(tmp_path)
    assert config.llm_provider == "openai"


def test_reads_model(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text(
        '[baton]\nmodel = "gpt-4o"\n', encoding="utf-8"
    )
    config = BatonConfig.load(tmp_path)
    assert config.model == "gpt-4o"


def test_reads_min_diff_lines(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text(
        '[baton]\nmin_diff_lines = 25\n', encoding="utf-8"
    )
    config = BatonConfig.load(tmp_path)
    assert config.min_diff_lines == 25


def test_reads_auto_sync_false(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text(
        '[baton]\nauto_sync = false\n', encoding="utf-8"
    )
    config = BatonConfig.load(tmp_path)
    assert config.auto_sync is False


def test_reads_enabled_adapters(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text(
        '[adapters]\nenabled = ["claude", "cursor"]\n', encoding="utf-8"
    )
    config = BatonConfig.load(tmp_path)
    assert config.enabled_adapters == ["claude", "cursor"]


def test_reads_full_config(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text(
        '[baton]\nllm_provider = "vertex"\nmodel = "gemini-1.5-pro"\n'
        'min_diff_lines = 5\nauto_sync = false\n\n'
        '[adapters]\nenabled = ["claude", "codex", "gemini"]\n',
        encoding="utf-8",
    )
    config = BatonConfig.load(tmp_path)
    assert config.llm_provider == "vertex"
    assert config.model == "gemini-1.5-pro"
    assert config.min_diff_lines == 5
    assert config.auto_sync is False
    assert config.enabled_adapters == ["claude", "codex", "gemini"]


# ── Partial configs use defaults for missing keys ─────────────────────────────

def test_partial_config_uses_defaults_for_missing_keys(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text(
        '[baton]\nllm_provider = "openai"\n', encoding="utf-8"
    )
    config = BatonConfig.load(tmp_path)
    assert config.model == ""
    assert config.min_diff_lines == 10
    assert config.auto_sync is True
    assert config.enabled_adapters == []


def test_empty_toml_uses_all_defaults(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text("", encoding="utf-8")
    config = BatonConfig.load(tmp_path)
    assert config.llm_provider == "anthropic"
    assert config.min_diff_lines == 10


# ── Malformed TOML falls back to defaults ─────────────────────────────────────

def test_malformed_toml_falls_back_to_defaults(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text(
        "this is not valid toml !!!\n[[[broken", encoding="utf-8"
    )
    config = BatonConfig.load(tmp_path)
    assert config.llm_provider == "anthropic"
    assert config.min_diff_lines == 10


def test_malformed_toml_does_not_raise(tmp_path: Path) -> None:
    (tmp_path / ".baton.toml").write_text("= bad = bad =", encoding="utf-8")
    config = BatonConfig.load(tmp_path)
    assert isinstance(config, BatonConfig)


# ── Dataclass field defaults ──────────────────────────────────────────────────

def test_enabled_adapters_default_is_empty_list() -> None:
    config = BatonConfig()
    assert config.enabled_adapters == []


def test_two_instances_do_not_share_enabled_adapters_list() -> None:
    a = BatonConfig()
    b = BatonConfig()
    a.enabled_adapters.append("claude")
    assert b.enabled_adapters == [], "mutable default must not be shared between instances"
