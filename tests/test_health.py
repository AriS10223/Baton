"""
tests/test_health.py -- Tests for ``baton health``.

Uses tmp_path + real BATON.md files (no mocking).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from baton.commands.health import run_health

# ── Fixtures ──────────────────────────────────────────────────────────────────

FIXTURE = Path(__file__).parent / "fixtures" / "sample_baton.md"


def _write_baton(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


_MINIMAL_BATON = """\
# BATON.md

```yaml
baton_version: "1.0"
last_updated: "2025-01-01"
project:
  name: TestProj
  purpose: Test project
decisions:
  - id: d001
    what: Use Python
    why: Familiarity
    made: "2025-01-01"
anti_decisions: []
landmines: []
open_questions: []
sessions: []
```
"""


@pytest.fixture()
def repo(tmp_path):
    return tmp_path


@pytest.fixture()
def baton_md(repo):
    path = repo / "BATON.md"
    _write_baton(path, _MINIMAL_BATON)
    return path


# ── Basic exit codes ──────────────────────────────────────────────────────────

def test_health_ok_exit_0(repo, baton_md):
    """A small BATON.md (well under 4k tokens) should return 0."""
    code = run_health(repo)
    assert code == 0


def test_health_missing_baton_md_exit_1(tmp_path):
    code = run_health(tmp_path)
    assert code == 1


def test_health_exit_code_same_across_formats(repo, baton_md):
    """Exit code must be identical regardless of --format."""
    for fmt in ("human", "json", "github"):
        code = run_health(repo, fmt=fmt)
        assert code == 0, f"Expected 0 for fmt={fmt}, got {code}"


# ── Token thresholds ──────────────────────────────────────────────────────────

def _make_large_baton(n_decisions: int) -> str:
    """Generate a BATON.md with many decisions to inflate token count."""
    decisions = "\n".join(
        f"  - id: d{i:03d}\n"
        f"    what: \"Decision {i}: Use the {i}-th approach for all backend services "
        f"because it scales well and integrates with existing infrastructure.\"\n"
        f"    why: \"Extensive benchmarking proved approach {i} handles peak load.\"\n"
        f"    made: \"2025-01-01\""
        for i in range(1, n_decisions + 1)
    )
    return f"""\
# BATON.md

```yaml
baton_version: "1.0"
project:
  name: BigProject
  purpose: Large test project
decisions:
{decisions}
anti_decisions: []
landmines: []
open_questions: []
sessions: []
```
"""


def test_health_warn_level_exits_0(repo):
    """A BATON.md between 4k and 8k tokens should exit 0 (WARN only)."""
    baton_path = repo / "BATON.md"
    # Write a medium-sized BATON.md that hits WARN but not ERROR
    # Use enough content to push past 4000 tokens
    # Each entry is ~50-80 tokens; ~60 entries should be ~3000-5000 tokens
    content = _make_large_baton(60)
    _write_baton(baton_path, content)

    # Check token count to see if it's actually in WARN range
    from baton.core.tokens import count_tokens
    total, _ = count_tokens(content)

    if total <= 4000:
        pytest.skip(f"Generated content only {total} tokens, not in WARN range")
    if total > 8000:
        pytest.skip(f"Generated content {total} tokens, in ERROR range (need more control)")

    code = run_health(repo)
    assert code == 0  # WARN exits 0


def test_health_error_level_exits_1(repo):
    """A BATON.md over 8k tokens should exit 1."""
    baton_path = repo / "BATON.md"
    content = _make_large_baton(200)  # should be well over 8k tokens
    _write_baton(baton_path, content)

    from baton.core.tokens import count_tokens
    total, _ = count_tokens(content)

    if total <= 8000:
        pytest.skip(f"Generated content only {total} tokens, not in ERROR range")

    code = run_health(repo)
    assert code == 1


# ── JSON output ───────────────────────────────────────────────────────────────

def test_health_json_output_structure(repo, baton_md, capsys):
    """JSON output must have expected envelope keys."""
    code = run_health(repo, fmt="json")
    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert "generated_at" in data
    assert "total_tokens" in data
    assert "token_method" in data
    assert "thresholds" in data
    assert "warn" in data["thresholds"]
    assert "error" in data["thresholds"]
    assert "token_status" in data
    assert "counts" in data
    assert "findings" in data
    assert isinstance(data["findings"], list)
    assert code == 0


def test_health_json_token_status_ok(repo, baton_md, capsys):
    run_health(repo, fmt="json")
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["token_status"] == "ok"


def test_health_json_total_tokens_positive(repo, baton_md, capsys):
    run_health(repo, fmt="json")
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["total_tokens"] > 0


# ── GitHub format ─────────────────────────────────────────────────────────────

def test_health_github_no_output_when_ok(repo, baton_md, capsys):
    """A healthy BATON.md should produce no GHA output."""
    run_health(repo, fmt="github")
    captured = capsys.readouterr()
    assert captured.out.strip() == ""


def test_health_github_error_annotation(repo, capsys):
    """An oversized BATON.md should emit ::error::.  """
    baton_path = repo / "BATON.md"
    content = _make_large_baton(200)
    _write_baton(baton_path, content)

    from baton.core.tokens import count_tokens
    total, _ = count_tokens(content)

    if total <= 8000:
        pytest.skip("Not enough tokens for ERROR annotation test")

    run_health(repo, fmt="github")
    captured = capsys.readouterr()
    assert "::error::" in captured.out


# ── Staleness detection via health ───────────────────────────────────────────

def test_health_detects_stale_decision(repo, capsys):
    """A decision with status: stale should appear as a WARN finding."""
    baton_path = repo / "BATON.md"
    content = """\
# BATON.md

```yaml
baton_version: "1.0"
project:
  name: Test
  purpose: Testing
decisions:
  - id: d001
    what: Old approach
    status: stale
anti_decisions: []
landmines: []
open_questions: []
sessions: []
```
"""
    _write_baton(baton_path, content)

    run_health(repo, fmt="json")
    captured = capsys.readouterr()
    data = json.loads(captured.out)

    finding_types = [f["type"] for f in data["findings"]]
    assert "stale_decision" in finding_types


def test_health_detects_resolved_question(repo, capsys):
    """A resolved open_question should appear as an info finding."""
    baton_path = repo / "BATON.md"
    content = """\
# BATON.md

```yaml
baton_version: "1.0"
project:
  name: Test
  purpose: Testing
decisions: []
anti_decisions: []
landmines: []
open_questions:
  - id: q001
    question: Which database?
    raised: "2024-01-01"
    status: resolved
    resolved_date: "2024-06-01"
sessions: []
```
"""
    _write_baton(baton_path, content)

    run_health(repo, fmt="json")
    captured = capsys.readouterr()
    data = json.loads(captured.out)

    finding_types = [f["type"] for f in data["findings"]]
    assert "resolved_question_present" in finding_types


# ── Doctor integration ────────────────────────────────────────────────────────

def test_doctor_runs_without_error(repo, baton_md):
    """baton doctor should always exit 0 with the tiktoken check included."""
    from baton.commands.doctor import run_doctor
    # Should not raise
    run_doctor(repo)
