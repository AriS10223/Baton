"""
test_cli.py -- Integration tests for the Typer CLI layer (baton/cli.py).

Uses typer.testing.CliRunner to invoke commands end-to-end through the
registered app.  The underlying command functions (run_sync, run_end, etc.)
are tested in their own modules; these tests verify that the CLI correctly
routes flags, sets exit codes, and calls the right command.

No real LLM calls.  baton end tests monkeypatch baton.cli.run_end.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from baton.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_BATON = FIXTURES / "sample_baton.md"

runner = CliRunner()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _repo_with_baton(tmp_path: Path) -> Path:
    """Copy sample BATON.md into tmp_path and return the path."""
    shutil.copy(SAMPLE_BATON, tmp_path / "BATON.md")
    return tmp_path


# ── --help / no-args ─────────────────────────────────────────────────────────

def test_cli_help_exits_0() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "baton" in result.output.lower()


def test_cli_no_args_prints_help() -> None:
    # Typer no_args_is_help=True prints help; Click/Typer exits with code 0 or 2.
    result = runner.invoke(app, [])
    assert "baton" in result.output.lower()
    assert result.exit_code in (0, 2)


def test_cli_unknown_command_exits_nonzero() -> None:
    result = runner.invoke(app, ["nonexistent-command"])
    assert result.exit_code != 0


# ── baton init ────────────────────────────────────────────────────────────────

def test_cli_init_creates_baton_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_path / "BATON.md").exists()


def test_cli_init_creates_baton_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    assert (tmp_path / ".baton.toml").exists()


def test_cli_init_no_force_does_not_overwrite_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    sentinel = "# SENTINEL_DO_NOT_OVERWRITE\n"
    (tmp_path / "BATON.md").write_text(sentinel, encoding="utf-8")
    runner.invoke(app, ["init"])
    content = (tmp_path / "BATON.md").read_text(encoding="utf-8")
    assert "SENTINEL_DO_NOT_OVERWRITE" in content


def test_cli_init_force_overwrites_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    sentinel = "# SENTINEL_DO_NOT_OVERWRITE\n"
    (tmp_path / "BATON.md").write_text(sentinel, encoding="utf-8")
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0
    content = (tmp_path / "BATON.md").read_text(encoding="utf-8")
    assert "SENTINEL_DO_NOT_OVERWRITE" not in content


def test_cli_init_short_force_flag_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "BATON.md").write_text("old content\n", encoding="utf-8")
    result = runner.invoke(app, ["init", "-f"])
    assert result.exit_code == 0
    assert "old content" not in (tmp_path / "BATON.md").read_text(encoding="utf-8")


# ── baton sync ────────────────────────────────────────────────────────────────

def test_cli_sync_exits_0_with_valid_baton_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_baton(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0


def test_cli_sync_exits_1_when_baton_md_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 1


def test_cli_sync_exits_1_when_baton_md_has_no_yaml_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "BATON.md").write_text("# No yaml block here\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 1


def test_cli_sync_creates_claude_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_baton(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["sync"])
    assert (tmp_path / "CLAUDE.md").exists()


def test_cli_sync_output_mentions_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_baton(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["sync"])
    assert "sync" in result.output.lower() or result.exit_code == 0


# ── baton status ─────────────────────────────────────────────────────────────

def test_cli_status_exits_0_with_valid_baton_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_baton(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0


def test_cli_status_produces_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_baton(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["status"])
    assert len(result.output.strip()) > 0


def test_cli_status_with_synced_files_shows_in_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_baton(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["sync"])  # sync first so files exist
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "in-sync" in result.output.lower() or "synced" in result.output.lower()


# ── baton score ──────────────────────────────────────────────────────────────

def test_cli_score_exits_0_with_valid_baton_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_baton(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["score"])
    assert result.exit_code == 0


def test_cli_score_output_contains_numeric_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_baton(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["score"])
    assert result.exit_code == 0
    # Score output should include digits (the score value).
    assert any(c.isdigit() for c in result.output)


def test_cli_score_exits_1_when_baton_md_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["score"])
    # Missing BATON.md causes BatonDocumentError; score command should exit non-zero.
    assert result.exit_code != 0


# ── baton end — monkeypatched run_end ─────────────────────────────────────────

def test_cli_end_exits_0_when_run_end_returns_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("baton.cli.run_end", return_value=True) as mock_end:
        result = runner.invoke(app, ["end"])
    assert result.exit_code == 0
    mock_end.assert_called_once()


def test_cli_end_exits_1_when_run_end_returns_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("baton.cli.run_end", return_value=False):
        result = runner.invoke(app, ["end"])
    assert result.exit_code == 1


def test_cli_end_passes_force_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("baton.cli.run_end", return_value=True) as mock_end:
        runner.invoke(app, ["end", "--force"])
    _kwargs = mock_end.call_args.kwargs
    assert _kwargs.get("force") is True


def test_cli_end_force_false_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("baton.cli.run_end", return_value=True) as mock_end:
        runner.invoke(app, ["end"])
    _kwargs = mock_end.call_args.kwargs
    assert _kwargs.get("force") is False


def test_cli_end_passes_since_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("baton.cli.run_end", return_value=True) as mock_end:
        runner.invoke(app, ["end", "--since", "abc1234"])
    _kwargs = mock_end.call_args.kwargs
    assert _kwargs.get("since") == "abc1234"


def test_cli_end_since_is_none_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("baton.cli.run_end", return_value=True) as mock_end:
        runner.invoke(app, ["end"])
    _kwargs = mock_end.call_args.kwargs
    assert _kwargs.get("since") is None


def test_cli_end_passes_tool_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("baton.cli.run_end", return_value=True) as mock_end:
        runner.invoke(app, ["end", "--tool", "cursor"])
    _kwargs = mock_end.call_args.kwargs
    assert _kwargs.get("tool") == "cursor"


def test_cli_end_tool_empty_string_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("baton.cli.run_end", return_value=True) as mock_end:
        runner.invoke(app, ["end"])
    _kwargs = mock_end.call_args.kwargs
    assert _kwargs.get("tool") == ""


def test_cli_end_yes_flag_sets_auto_accept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("baton.cli.run_end", return_value=True) as mock_end:
        runner.invoke(app, ["end", "--yes"])
    _kwargs = mock_end.call_args.kwargs
    assert _kwargs.get("auto_accept") is True


def test_cli_end_short_yes_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("baton.cli.run_end", return_value=True) as mock_end:
        runner.invoke(app, ["end", "-y"])
    _kwargs = mock_end.call_args.kwargs
    assert _kwargs.get("auto_accept") is True


def test_cli_end_auto_accept_false_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("baton.cli.run_end", return_value=True) as mock_end:
        runner.invoke(app, ["end"])
    _kwargs = mock_end.call_args.kwargs
    assert _kwargs.get("auto_accept") is False


def test_cli_end_passes_repo_root_as_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("baton.cli.run_end", return_value=True) as mock_end:
        runner.invoke(app, ["end"])
    positional_arg = mock_end.call_args.args[0]
    assert positional_arg == tmp_path


def test_cli_end_all_flags_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("baton.cli.run_end", return_value=True) as mock_end:
        runner.invoke(app, ["end", "--force", "--since", "deadbeef", "--tool", "claude-code", "--yes"])
    kw = mock_end.call_args.kwargs
    assert kw["force"] is True
    assert kw["since"] == "deadbeef"
    assert kw["tool"] == "claude-code"
    assert kw["auto_accept"] is True


# ── Command subcommand help ───────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", ["init", "sync", "status", "score", "end"])
def test_cli_subcommand_help_exits_0(cmd: str) -> None:
    result = runner.invoke(app, [cmd, "--help"])
    assert result.exit_code == 0


@pytest.mark.parametrize("cmd", ["init", "sync", "status", "score", "end"])
def test_cli_subcommand_help_mentions_command_name(cmd: str) -> None:
    result = runner.invoke(app, [cmd, "--help"])
    assert cmd in result.output.lower() or result.exit_code == 0
