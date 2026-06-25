"""
test_scope_match.py -- Tests for core/scope_match.py
"""
from __future__ import annotations

import pytest

from baton.core.scope_match import ScopeResult, apply_scope, build_scope


def _decision(eid: str, what: str, **kwargs) -> dict:
    return {"id": eid, "what": what, **kwargs}


def _anti(eid: str, rejected: str, **kwargs) -> dict:
    return {"id": eid, "rejected": rejected, **kwargs}


def _landmine(eid: str, actually: str, **kwargs) -> dict:
    return {"id": eid, "actually": actually, **kwargs}


def _question(eid: str, question: str, **kwargs) -> dict:
    return {"id": eid, "question": question, **kwargs}


def _data(**kwargs) -> dict:
    base: dict = {
        "decisions": [],
        "anti_decisions": [],
        "landmines": [],
        "open_questions": [],
    }
    base.update(kwargs)
    return base


# ── build_scope ───────────────────────────────────────────────────────────────

def test_tier1_keyword_hit() -> None:
    data = _data(decisions=[_decision("d001", "Use PostgreSQL for persistent storage")])
    result = build_scope("postgresql database choice", data)
    assert "d001" in result.entry_ids
    assert result.tier_counts["tier1"] >= 1


def test_tier1_no_match_returns_empty_non_global() -> None:
    data = _data(decisions=[_decision("d001", "Use Redis for caching")])
    result = build_scope("auth redirect bug", data)
    assert "d001" not in result.entry_ids


def test_tier2_path_hit() -> None:
    data = _data(decisions=[_decision("d002", "Auth middleware lives in src/auth/redirect.py")])
    result = build_scope("fix src/auth/redirect.py", data)
    assert "d002" in result.entry_ids


def test_global_always_included_no_keyword_match() -> None:
    data = _data(decisions=[_decision("d003", "Totally unrelated decision", **{"global": True})])
    result = build_scope("fix the login button", data)
    assert "d003" in result.entry_ids
    assert result.tier_counts["global"] >= 1


def test_global_not_double_counted() -> None:
    data = _data(decisions=[_decision("d004", "auth system", **{"global": True})])
    result = build_scope("auth redirect", data)
    # Should appear exactly once even though it matches both global and tier-1.
    assert result.entry_ids.count("d004") == 1


def test_under_threshold_true_when_less_than_3() -> None:
    data = _data(decisions=[_decision("d001", "auth system")])
    result = build_scope("auth", data)
    assert len(result.entry_ids) < 3
    assert result.under_threshold is True


def test_under_threshold_false_when_3_or_more() -> None:
    data = _data(
        decisions=[
            _decision("d001", "auth session token"),
            _decision("d002", "auth redirect url"),
            _decision("d003", "auth middleware"),
        ]
    )
    result = build_scope("auth", data)
    assert len(result.entry_ids) >= 3
    assert result.under_threshold is False


def test_unparseable_entry_skipped_no_crash() -> None:
    data = _data(decisions=["not a dict", None, _decision("d001", "auth system")])
    result = build_scope("auth", data)
    # d001 may or may not match but function must not raise.
    assert isinstance(result, ScopeResult)


def test_all_curated_sections_searched() -> None:
    data = _data(
        decisions=[_decision("d001", "auth token")],
        anti_decisions=[_anti("a001", "auth sessions rejected")],
        landmines=[_landmine("l001", "auth bypass actually intentional")],
        open_questions=[_question("q001", "auth scope question")],
    )
    result = build_scope("auth", data)
    assert "d001" in result.entry_ids
    assert "a001" in result.entry_ids
    assert "l001" in result.entry_ids
    assert "q001" in result.entry_ids


def test_keywords_returned_in_result() -> None:
    result = build_scope("auth redirect", _data())
    assert "auth" in result.keywords
    assert "redirect" in result.keywords


# ── apply_scope ───────────────────────────────────────────────────────────────

def test_apply_scope_keeps_snapshot_ids() -> None:
    data = _data(
        decisions=[_decision("d001", "keep"), _decision("d002", "drop")],
    )
    state = {"entry_ids": ["d001"]}
    out = apply_scope(data, state)
    ids = [e["id"] for e in out["decisions"]]
    assert "d001" in ids
    assert "d002" not in ids


def test_apply_scope_keeps_global_not_in_snapshot() -> None:
    data = _data(
        decisions=[
            _decision("d001", "keep", **{"global": True}),
            _decision("d002", "drop"),
        ],
    )
    state = {"entry_ids": []}
    out = apply_scope(data, state)
    ids = [e["id"] for e in out["decisions"]]
    assert "d001" in ids
    assert "d002" not in ids


def test_apply_scope_non_curated_unchanged() -> None:
    data = _data()
    data["sessions"] = [{"summary": "session one"}]
    state = {"entry_ids": []}
    out = apply_scope(data, state)
    assert out["sessions"] == [{"summary": "session one"}]


def test_apply_scope_empty_snapshot() -> None:
    data = _data(decisions=[_decision("d001", "auth")])
    out = apply_scope(data, {"entry_ids": []})
    assert out["decisions"] == []


def test_apply_scope_missing_section() -> None:
    data: dict = {}
    out = apply_scope(data, {"entry_ids": ["d001"]})
    # Should not raise; missing sections just absent.
    assert "decisions" not in out
