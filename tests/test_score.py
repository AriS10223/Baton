"""
test_score.py — Tests for the baton score command.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from baton.commands.score import run_score
from baton.core.schema import SCORE_CHECKS

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    shutil.copy(FIXTURES / "sample_baton.md", tmp_path / "BATON.md")
    return tmp_path


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    """Repo with a mostly-empty BATON.md."""
    empty_baton = tmp_path / "BATON.md"
    empty_baton.write_text(
        "# BATON.md\n```yaml\nproject:\n  purpose: \"\"\nstack: []\nlaws: []\n"
        "decisions: []\nanti_decisions: []\ncurrent_sprint:\n  goal: \"\"\n"
        "landmines: []\nopen_questions: []\n```\n",
        encoding="utf-8",
    )
    return tmp_path


# ── Basic smoke tests ─────────────────────────────────────────────────────────

def test_score_runs_without_error_on_sample(sample_repo: Path) -> None:
    run_score(sample_repo)


def test_score_runs_without_error_on_empty(empty_repo: Path) -> None:
    run_score(empty_repo)


def test_score_raises_sysexit_when_no_baton_md(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        run_score(tmp_path)


# ── Score calculation ─────────────────────────────────────────────────────────

def _compute_score(data: dict) -> int:
    """Run all checks against *data* and return the total score."""
    total = 0
    for check in SCORE_CHECKS:
        status, _, _ = check.fn(data)
        if status == "pass":
            total += check.points
        elif status == "warn":
            total += check.warn_points
    return total


def test_fully_filled_data_scores_high() -> None:
    """The sample fixture should score significantly above 50."""
    from baton.core.document import BatonDocument
    doc = BatonDocument.load(FIXTURES / "sample_baton.md")
    score = _compute_score(doc.data)
    # sample_baton.md: purpose ✅, stack ✅, why+version (one missing gotcha → warn),
    # laws ✅, decisions ✅, anti_decisions ✅, sprint_goal ✅,
    # inprogress_owners ✅, open_q_statuses ✅, landmines ✅
    # Expect at least 80/100.
    assert score >= 80, f"Expected ≥80, got {score}"


def test_empty_data_scores_zero_or_low() -> None:
    score = _compute_score({})
    # Nothing filled in → most checks fail.
    # stack_gotchas passes (no stack = n/a) and open_q passes (no questions = ok).
    # Everything else fails.  Should be ≤ 15.
    assert score <= 15, f"Expected ≤15, got {score}"


def test_purpose_adds_correct_points() -> None:
    from baton.core.schema import _check_project_purpose, SCORE_CHECKS
    check = next(c for c in SCORE_CHECKS if c.id == "project_purpose")
    status, _, _ = _check_project_purpose({"project": {"purpose": "Solving X"}})
    assert status == "pass"
    assert check.points == 10


def test_decisions_fail_contributes_zero() -> None:
    from baton.core.schema import _check_decisions, SCORE_CHECKS
    check = next(c for c in SCORE_CHECKS if c.id == "decisions")
    status, _, _ = _check_decisions({"decisions": []})
    assert status == "fail"
    assert check.points == 15   # would add 15 if passing
    # Score contribution is 0.
    score = _compute_score({"decisions": []})
    # decisions fail → 0 from that check.
    from baton.core.schema import _check_decisions
    # Just verify the check really contributes 0.
    contrib = 0 if status == "fail" else check.points
    assert contrib == 0
