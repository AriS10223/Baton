"""
test_check.py -- Integration tests for baton check --drift (run_check).

Uses real git repos via tmp_path + subprocess; no mocking.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from baton.commands.check import run_check
from baton.core.alerts import load_alerts


# ── Git helpers ───────────────────────────────────────────────────────────────


def git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    git(["init"], tmp_path)
    git(["config", "user.email", "test@test.com"], tmp_path)
    git(["config", "user.name", "Test"], tmp_path)
    return tmp_path


# ── BATON.md helpers ─────────────────────────────────────────────────────────


def write_baton(repo: Path, yaml_data: str) -> None:
    """Write a minimal BATON.md with yaml_data as the fenced block."""
    content = f"# BATON.md\n\n```yaml\n{yaml_data}\n```\n"
    (repo / "BATON.md").write_text(content, encoding="utf-8")


_MINIMAL_YAML = """\
baton_version: "1.0"
"""

_ANTI_YAML = """\
baton_version: "1.0"
anti_decisions:
  - id: "a001"
    rejected: "moment library"
    why: "Use date-fns instead"
    severity: "warn"
    pattern:
      type: "regex"
      value: "moment"
"""


def _initial_commit(repo: Path, yaml: str = _MINIMAL_YAML) -> str:
    """Write BATON.md, commit it, and return the HEAD sha (base for subsequent diffs)."""
    write_baton(repo, yaml)
    git(["add", "BATON.md"], repo)
    git(["commit", "-m", "init"], repo)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_run_check_no_baton_md_returns_1(repo):
    """run_check returns 1 when BATON.md is absent."""
    code = run_check(repo, quiet=True)
    assert code == 1


def test_run_check_no_alerts_returns_0(repo):
    """run_check returns 0 when BATON.md has no drift entries."""
    base_sha = _initial_commit(repo)
    # Add a harmless file and commit
    (repo / "hello.py").write_text("print('hello')\n", encoding="utf-8")
    git(["add", "hello.py"], repo)
    git(["commit", "-m", "add hello"], repo)
    code = run_check(repo, since=base_sha, quiet=True)
    assert code == 0
    alerts_data = load_alerts(repo)
    assert alerts_data["alerts"] == []


def test_run_check_anti_decision_violation(repo):
    """run_check detects an anti_decision violation and returns non-zero."""
    base_sha = _initial_commit(repo, _ANTI_YAML)
    # Add a file that violates the anti-decision
    (repo / "utils.py").write_text("import moment\n", encoding="utf-8")
    git(["add", "utils.py"], repo)
    git(["commit", "-m", "add utils"], repo)
    code = run_check(repo, since=base_sha, quiet=True)
    assert code != 0
    alerts_data = load_alerts(repo)
    assert len(alerts_data["alerts"]) >= 1
    assert alerts_data["alerts"][0]["id"] == "a001"


def test_run_check_fail_on_block_ignores_warnings(repo):
    """run_check with fail_on=block returns 0 for warn-severity alerts."""
    base_sha = _initial_commit(repo, _ANTI_YAML)
    # Add a violation (severity=warn from _ANTI_YAML)
    (repo / "utils.py").write_text("import moment\n", encoding="utf-8")
    git(["add", "utils.py"], repo)
    git(["commit", "-m", "add utils"], repo)
    # With fail_on=warn, we get non-zero (violation present)
    code_warn = run_check(repo, since=base_sha, fail_on="warn", quiet=True)
    assert code_warn != 0
    # With fail_on=block, warn alerts don't trigger non-zero
    code_block = run_check(repo, since=base_sha, fail_on="block", quiet=True)
    assert code_block == 0


def test_run_check_writes_alerts_json(repo):
    """run_check creates .baton/alerts.json after running."""
    _initial_commit(repo)
    run_check(repo, since="HEAD", quiet=True)
    alerts_path = repo / ".baton" / "alerts.json"
    assert alerts_path.exists()
    data = json.loads(alerts_path.read_text(encoding="utf-8"))
    assert "alerts" in data
    assert "generated_at" in data


def test_run_check_acknowledge_clears_alert(repo):
    """Acknowledging an alert removes it from alerts.json and returns 0."""
    base_sha = _initial_commit(repo, _ANTI_YAML)
    # Create a violation and commit it
    (repo / "utils.py").write_text("import moment\n", encoding="utf-8")
    git(["add", "utils.py"], repo)
    git(["commit", "-m", "add utils"], repo)
    # First run: get the alert
    code = run_check(repo, since=base_sha, quiet=True)
    assert code != 0
    alerts_before = load_alerts(repo)
    assert len(alerts_before["alerts"]) >= 1
    # Acknowledge the alert
    code_ack = run_check(
        repo,
        acknowledge="a001",
        reason="acceptable for this project",
        quiet=True,
    )
    assert code_ack == 0
    # After acknowledging, run again -- alert should be filtered out
    code_after = run_check(repo, since=base_sha, quiet=True)
    assert code_after == 0
    alerts_after = load_alerts(repo)
    assert all(a["id"] != "a001" for a in alerts_after["alerts"])


def test_run_check_staged_diff(repo):
    """run_check --staged detects violations in staged (not yet committed) changes."""
    # Commit BATON.md first so it's at the base
    _initial_commit(repo, _ANTI_YAML)
    # Stage a violation WITHOUT committing
    (repo / "utils.py").write_text("import moment\n", encoding="utf-8")
    git(["add", "utils.py"], repo)
    # Do NOT commit -- staged=True should see the cached diff
    code = run_check(repo, staged=True, quiet=True)
    assert code != 0
    # last_check_sha must NOT be written when --staged
    sha_path = repo / ".baton" / "last_check_sha"
    assert not sha_path.exists()


def test_run_check_updates_last_check_sha(repo):
    """run_check writes HEAD sha to .baton/last_check_sha after a non-staged run."""
    _initial_commit(repo)
    (repo / "hello.py").write_text("x = 1\n", encoding="utf-8")
    git(["add", "hello.py"], repo)
    git(["commit", "-m", "add hello"], repo)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    run_check(repo, since="HEAD~1", quiet=True)
    sha_path = repo / ".baton" / "last_check_sha"
    assert sha_path.exists()
    assert sha_path.read_text(encoding="utf-8").strip() == head


# ── --format tests ────────────────────────────────────────────────────────────


def test_format_json_stdout_is_valid_json(repo, capsys):
    """--format json prints valid JSON envelope to stdout."""
    base_sha = _initial_commit(repo)
    (repo / "ok.py").write_text("x = 1\n", encoding="utf-8")
    git(["add", "ok.py"], repo)
    git(["commit", "-m", "add ok"], repo)
    run_check(repo, since=base_sha, fmt="json")
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "generated_at" in data
    assert "alerts" in data
    assert isinstance(data["alerts"], list)


def test_format_json_alerts_have_enriched_fields(repo, capsys):
    """--format json: alerts include reason/suggestion/fix_command."""
    base_sha = _initial_commit(repo, _ANTI_YAML)
    (repo / "utils.py").write_text("import moment\n", encoding="utf-8")
    git(["add", "utils.py"], repo)
    git(["commit", "-m", "add utils"], repo)
    run_check(repo, since=base_sha, fmt="json")
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data["alerts"]) >= 1
    alert = data["alerts"][0]
    assert "reason" in alert
    assert "suggestion" in alert
    assert "fix_command" in alert


def test_format_github_clean_no_output(repo, capsys):
    """--format github: zero alerts produces no stdout."""
    base_sha = _initial_commit(repo)
    (repo / "ok.py").write_text("x = 1\n", encoding="utf-8")
    git(["add", "ok.py"], repo)
    git(["commit", "-m", "add ok"], repo)
    run_check(repo, since=base_sha, fmt="github")
    captured = capsys.readouterr()
    assert captured.out == ""


def test_format_github_alert_produces_workflow_command(repo, capsys):
    """--format github: an alert produces a ::warning or ::error line."""
    base_sha = _initial_commit(repo, _ANTI_YAML)
    (repo / "utils.py").write_text("import moment\n", encoding="utf-8")
    git(["add", "utils.py"], repo)
    git(["commit", "-m", "add utils"], repo)
    run_check(repo, since=base_sha, fmt="github")
    captured = capsys.readouterr()
    assert "::" in captured.out
    assert "warning" in captured.out or "error" in captured.out


def test_format_human_default_no_crash(repo):
    """Default --format human (Rich output) does not crash."""
    base_sha = _initial_commit(repo)
    (repo / "ok.py").write_text("x = 1\n", encoding="utf-8")
    git(["add", "ok.py"], repo)
    git(["commit", "-m", "add ok"], repo)
    code = run_check(repo, since=base_sha, fmt="human")
    assert code == 0


def test_quiet_deprecated_alias_for_format_json(repo, capsys):
    """--quiet emits JSON on stdout and a deprecation note to stderr."""
    base_sha = _initial_commit(repo)
    (repo / "ok.py").write_text("x = 1\n", encoding="utf-8")
    git(["add", "ok.py"], repo)
    git(["commit", "-m", "add ok"], repo)
    run_check(repo, since=base_sha, quiet=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "alerts" in data
    assert "--quiet is deprecated" in captured.err
    assert "--format json" in captured.err


def test_quiet_and_format_json_no_deprecation(repo, capsys):
    """Passing both --quiet and --format json does not print deprecation."""
    base_sha = _initial_commit(repo)
    (repo / "ok.py").write_text("x = 1\n", encoding="utf-8")
    git(["add", "ok.py"], repo)
    git(["commit", "-m", "add ok"], repo)
    run_check(repo, since=base_sha, quiet=True, fmt="json")
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert "alerts" in data


def test_format_github_exit_code_preserved(repo, capsys):
    """--format github still returns non-zero when warn alerts present."""
    base_sha = _initial_commit(repo, _ANTI_YAML)
    (repo / "utils.py").write_text("import moment\n", encoding="utf-8")
    git(["add", "utils.py"], repo)
    git(["commit", "-m", "add utils"], repo)
    code = run_check(repo, since=base_sha, fmt="github", fail_on="warn")
    assert code != 0


def test_format_json_exit_code_preserved(repo, capsys):
    """--format json still returns non-zero when warn alerts present."""
    base_sha = _initial_commit(repo, _ANTI_YAML)
    (repo / "utils.py").write_text("import moment\n", encoding="utf-8")
    git(["add", "utils.py"], repo)
    git(["commit", "-m", "add utils"], repo)
    code = run_check(repo, since=base_sha, fmt="json", fail_on="warn")
    assert code != 0


def test_since_head_resolves_without_error(repo, capsys):
    """run_check with --since HEAD resolves successfully (resolve_since integration)."""
    _initial_commit(repo)
    (repo / "ok.py").write_text("x = 1\n", encoding="utf-8")
    git(["add", "ok.py"], repo)
    git(["commit", "-m", "add ok"], repo)
    code = run_check(repo, since="HEAD", fmt="json")
    assert code == 0
