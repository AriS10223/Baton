"""
test_scope_render.py -- Tests for core/scope_render.py
"""
from __future__ import annotations

from baton.core.scope_match import ScopeResult
from baton.core.scope_render import render_scope_md


def _result(entry_ids=None, task="fix auth redirect") -> ScopeResult:
    return ScopeResult(
        task=task,
        keywords=["auth", "redirect"],
        entry_ids=entry_ids or [],
        tier_counts={"tier1": 1, "tier2": 0, "global": 0},
        under_threshold=False,
    )


def _data_with_decision(eid: str, what: str) -> dict:
    return {
        "decisions": [{"id": eid, "what": what}],
        "anti_decisions": [],
        "landmines": [],
        "open_questions": [],
    }


# ── ASCII-only output ─────────────────────────────────────────────────────────

def test_output_is_ascii() -> None:
    result = _result(["d001"])
    data = _data_with_decision("d001", "Use PostgreSQL")
    output = render_scope_md(result, data)
    output.encode("ascii")  # raises UnicodeEncodeError if non-ASCII present


def test_header_contains_task() -> None:
    result = _result(task="fix auth redirect")
    output = render_scope_md(result, {})
    assert "fix auth redirect" in output


def test_header_contains_timestamp() -> None:
    import re
    result = _result()
    output = render_scope_md(result, {})
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", output)


def test_body_contains_no_timestamp() -> None:
    import re
    result = _result(["d001"])
    data = _data_with_decision("d001", "Use PostgreSQL")
    output = render_scope_md(result, data)
    lines = output.splitlines()
    # timestamp only in first 4 header lines
    body_lines = lines[4:]
    timestamp_pattern = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
    for line in body_lines:
        assert not timestamp_pattern.search(line), f"Timestamp found in body: {line!r}"


# ── Idempotent body ───────────────────────────────────────────────────────────

def test_body_is_idempotent_across_two_renders() -> None:
    result = _result(["d001", "d002"])
    data = {
        "decisions": [
            {"id": "d001", "what": "Use PostgreSQL"},
            {"id": "d002", "what": "Use ruamel for YAML"},
        ],
        "anti_decisions": [],
        "landmines": [],
        "open_questions": [],
    }
    out1 = render_scope_md(result, data)
    out2 = render_scope_md(result, data)

    def _body(text: str) -> list[str]:
        # Strip the first 4 header lines (task, generated, regenerate, blank).
        lines = text.splitlines()
        return lines[4:]

    assert _body(out1) == _body(out2)


def test_two_renders_differ_only_in_header() -> None:
    result = _result(["d001"])
    data = _data_with_decision("d001", "Use PostgreSQL")
    out1 = render_scope_md(result, data)
    out2 = render_scope_md(result, data)
    # Bodies identical; headers may differ by timestamp.
    body1 = "\n".join(out1.splitlines()[4:])
    body2 = "\n".join(out2.splitlines()[4:])
    assert body1 == body2


# ── Content ───────────────────────────────────────────────────────────────────

def test_entry_appears_in_output() -> None:
    result = _result(["d001"])
    data = _data_with_decision("d001", "Use PostgreSQL")
    output = render_scope_md(result, data)
    assert "d001" in output
    assert "Use PostgreSQL" in output


def test_no_match_produces_empty_message() -> None:
    result = _result([])
    output = render_scope_md(result, {})
    assert "No entries matched" in output


def test_entries_are_id_sorted() -> None:
    result = _result(["d002", "d001"])
    data = {
        "decisions": [
            {"id": "d002", "what": "Second decision"},
            {"id": "d001", "what": "First decision"},
        ],
        "anti_decisions": [],
        "landmines": [],
        "open_questions": [],
    }
    output = render_scope_md(result, data)
    pos_d001 = output.index("d001")
    pos_d002 = output.index("d002")
    assert pos_d001 < pos_d002


def test_multiple_sections_rendered() -> None:
    result = _result(["d001", "l001"])
    data = {
        "decisions": [{"id": "d001", "what": "auth decision"}],
        "anti_decisions": [],
        "landmines": [{"id": "l001", "actually": "auth bypass intentional"}],
        "open_questions": [],
    }
    output = render_scope_md(result, data)
    assert "## Decisions" in output
    assert "## Landmines" in output
