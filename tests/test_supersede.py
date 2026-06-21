"""
tests/test_supersede.py — Phase A test file covering:
  - pure derivation  (core/supersede.py)
  - block helpers    (adapters/base.py generic functions)
  - document region  (core/document.py upsert_markdown_region)
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from baton.commands.supersede import run_supersede
from baton.core.supersede import (
    SUPERSEDED_START,
    SUPERSEDED_END,
    entries_for,
    find_entry,
    superseded_by_map,
    derive_status,
    resolve_head,
    chain_backward,
    validate_link,
    render_superseded_appendix,
    detect_overlaps,
)
from baton.adapters.base import (
    upsert_named_block,
    extract_named_block,
    upsert_managed_block,
    extract_managed_block,
    MARKER_START,
    MARKER_END,
)
from baton.core.document import BatonDocument

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_BATON = FIXTURES / "sample_baton.md"


# ── Shared helper ─────────────────────────────────────────────────────────────


def _make_data(decisions=None, anti_decisions=None, landmines=None):
    """Build a minimal data dict with the three supersedable lists."""
    return {
        "decisions": decisions or [],
        "anti_decisions": anti_decisions or [],
        "landmines": landmines or [],
    }


# ══════════════════════════════════════════════════════════════════════════════
# Section 1: entries_for
# ══════════════════════════════════════════════════════════════════════════════


def test_entries_for_returns_list():
    data = _make_data(decisions=[{"id": "d001", "what": "SQLite"}])
    result = entries_for(data, "decisions")
    assert result == [{"id": "d001", "what": "SQLite"}]


def test_entries_for_returns_empty_on_missing():
    data = {}
    result = entries_for(data, "decisions")
    assert result == []


def test_entries_for_returns_empty_on_wrong_type():
    data = {"decisions": "not-a-list"}
    result = entries_for(data, "decisions")
    assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# Section 2: find_entry
# ══════════════════════════════════════════════════════════════════════════════


def test_find_entry_finds_decision():
    entry = {"id": "d001", "what": "SQLite"}
    data = _make_data(decisions=[entry])
    result = find_entry(data, "d001")
    assert result is not None
    type_key, found = result
    assert type_key == "decisions"
    assert found["id"] == "d001"


def test_find_entry_finds_anti():
    entry = {"id": "a001", "rejected": "TypeScript"}
    data = _make_data(anti_decisions=[entry])
    result = find_entry(data, "a001")
    assert result is not None
    type_key, found = result
    assert type_key == "anti_decisions"
    assert found["id"] == "a001"


def test_find_entry_returns_none_on_missing():
    data = _make_data(decisions=[{"id": "d001", "what": "x"}])
    assert find_entry(data, "d999") is None


# ══════════════════════════════════════════════════════════════════════════════
# Section 3: superseded_by_map
# ══════════════════════════════════════════════════════════════════════════════


def test_superseded_by_map_empty():
    data = _make_data(
        decisions=[{"id": "d001", "what": "a"}, {"id": "d002", "what": "b"}]
    )
    assert superseded_by_map(data) == {}


def test_superseded_by_map_one_link():
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "old"},
            {"id": "d002", "what": "new", "supersedes": ["d001"]},
        ]
    )
    result = superseded_by_map(data)
    assert result == {"d001": "d002"}


def test_superseded_by_map_multiple_olds():
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "a"},
            {"id": "d002", "what": "b"},
            {"id": "d003", "what": "c", "supersedes": ["d001", "d002"]},
        ]
    )
    result = superseded_by_map(data)
    assert result == {"d001": "d003", "d002": "d003"}


def test_superseded_by_map_lenient_on_missing_id():
    # Entry has supersedes but no id — should be silently skipped
    data = _make_data(
        decisions=[
            {"what": "no-id-entry", "supersedes": ["d001"]},
            {"id": "d001", "what": "target"},
        ]
    )
    result = superseded_by_map(data)
    assert result == {}


# ══════════════════════════════════════════════════════════════════════════════
# Section 4: derive_status
# ══════════════════════════════════════════════════════════════════════════════


def test_derive_status_active():
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "a"},
            {"id": "d002", "what": "b"},
        ]
    )
    assert derive_status(data, "d001") == "active"


def test_derive_status_superseded():
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "old"},
            {"id": "d002", "what": "new", "supersedes": ["d001"]},
        ]
    )
    assert derive_status(data, "d001") == "superseded"


# ══════════════════════════════════════════════════════════════════════════════
# Section 5: resolve_head (including cycle guard)
# ══════════════════════════════════════════════════════════════════════════════


def test_resolve_head_no_chain():
    data = _make_data(decisions=[{"id": "d001", "what": "a"}])
    assert resolve_head(data, "d001") == "d001"


def test_resolve_head_linear_chain():
    # d001 -> d002 -> d003
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "a"},
            {"id": "d002", "what": "b", "supersedes": ["d001"]},
            {"id": "d003", "what": "c", "supersedes": ["d002"]},
        ]
    )
    assert resolve_head(data, "d001") == "d003"


def test_resolve_head_cycle_guard():
    # d001.supersedes = [d002], d002.supersedes = [d001] — mutual cycle
    # resolve_head should return without infinite looping
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "a", "supersedes": ["d002"]},
            {"id": "d002", "what": "b", "supersedes": ["d001"]},
        ]
    )
    # sb_map: {d002: d001, d001: d002}
    # Starting from d001: current=d001, nxt=d002, nxt=d001 (visited) -> break, return d002
    result = resolve_head(data, "d001")
    assert result in {"d001", "d002"}  # guard kicked in, no infinite loop


# ══════════════════════════════════════════════════════════════════════════════
# Section 6: chain_backward
# ══════════════════════════════════════════════════════════════════════════════


def test_chain_backward_no_predecessors():
    data = _make_data(decisions=[{"id": "d001", "what": "a"}])
    result = chain_backward(data, "d001")
    assert result == []


def test_chain_backward_linear():
    # d001 <- d002 <- d003 (d003 supersedes d002; d002 supersedes d001)
    d001 = {"id": "d001", "what": "a"}
    d002 = {"id": "d002", "what": "b", "supersedes": ["d001"]}
    d003 = {"id": "d003", "what": "c", "supersedes": ["d002"]}
    data = _make_data(decisions=[d001, d002, d003])

    # chain_backward(d003) should return [[d001_entry, d002_entry]]
    # (d003's predecessor is d002; d002's predecessor is d001; oldest first)
    result = chain_backward(data, "d003")
    assert len(result) == 1
    branch = result[0]
    assert len(branch) == 2
    assert branch[0]["id"] == "d001"
    assert branch[1]["id"] == "d002"


def test_chain_backward_fan_in():
    # d004 and d005 both superseded by d006 (d006.supersedes = [d004, d005])
    d004 = {"id": "d004", "what": "a"}
    d005 = {"id": "d005", "what": "b"}
    d006 = {"id": "d006", "what": "c", "supersedes": ["d004", "d005"]}
    data = _make_data(decisions=[d004, d005, d006])

    result = chain_backward(data, "d006")
    assert len(result) == 2

    branch_ids = {b[0]["id"] for b in result}
    assert branch_ids == {"d004", "d005"}


# ══════════════════════════════════════════════════════════════════════════════
# Section 7: validate_link
# ══════════════════════════════════════════════════════════════════════════════


def test_validate_link_valid():
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "old"},
            {"id": "d002", "what": "new"},
        ]
    )
    errors = validate_link(data, "d001", "d002")
    assert errors == []


def test_validate_link_old_not_found():
    data = _make_data(decisions=[{"id": "d002", "what": "new"}])
    errors = validate_link(data, "d999", "d002")
    assert any("d999" in e or "not found" in e.lower() for e in errors)


def test_validate_link_new_not_found():
    data = _make_data(decisions=[{"id": "d001", "what": "old"}])
    errors = validate_link(data, "d001", "d999")
    assert any("d999" in e or "not found" in e.lower() for e in errors)


def test_validate_link_cycle():
    # d001 supersedes d002, d002 supersedes d003.
    # sb_map = {d002: d001, d003: d002}
    # Try validate_link(old="d001", new="d003"):
    #   cycle-check walks from d003 -> d002 -> d001 (== old_id) => Cycle detected
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "a", "supersedes": ["d002"]},
            {"id": "d002", "what": "b", "supersedes": ["d003"]},
            {"id": "d003", "what": "c"},
        ]
    )
    errors = validate_link(data, "d001", "d003")
    assert any("Cycle" in e or "cycle" in e.lower() for e in errors)


def test_validate_link_already_claimed():
    # d001 already in d002.supersedes; try to link d001 -> d003
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "old"},
            {"id": "d002", "what": "claimer", "supersedes": ["d001"]},
            {"id": "d003", "what": "new"},
        ]
    )
    errors = validate_link(data, "d001", "d003")
    assert any("Already superseded" in e for e in errors)


def test_validate_link_idempotent_reclam():
    # d001 already in d002.supersedes; linking d001 -> d002 again is idempotent
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "old"},
            {"id": "d002", "what": "claimer", "supersedes": ["d001"]},
        ]
    )
    errors = validate_link(data, "d001", "d002")
    assert errors == []


# ══════════════════════════════════════════════════════════════════════════════
# Section 8: render_superseded_appendix
# ══════════════════════════════════════════════════════════════════════════════


def test_render_appendix_empty_on_no_supersessions():
    data = _make_data(
        decisions=[{"id": "d001", "what": "a"}, {"id": "d002", "what": "b"}]
    )
    assert render_superseded_appendix(data) == ""


def test_render_appendix_single_decision():
    # d002 supersedes [d001], reason="reason1", made="2026-06-15"
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "old"},
            {
                "id": "d002",
                "what": "new",
                "supersedes": ["d001"],
                "reason": "reason1",
                "made": "2026-06-15",
            },
        ]
    )
    output = render_superseded_appendix(data)
    assert 'd001 -> d002 (2026-06-15): "reason1"' in output


def test_render_appendix_landmine_no_date():
    # landmine l002 supersedes [l001], reason="r2" — no date field
    data = _make_data(
        landmines=[
            {"id": "l001", "location": "a.py", "looks_like": "x", "actually": "y"},
            {
                "id": "l002",
                "location": "b.py",
                "looks_like": "p",
                "actually": "q",
                "supersedes": ["l001"],
                "reason": "r2",
            },
        ]
    )
    output = render_superseded_appendix(data)
    # Landmine bullets have no date parenthetical
    assert 'l001 -> l002: "r2"' in output
    # Should not contain a parenthesized date
    assert "(20" not in output.split('l001 -> l002')[1].split("\n")[0]


def test_render_appendix_sort_order():
    # anti ruled_out "2026-06-05", decision made "2026-06-10", landmine (no date)
    # Expected order: anti first (2026-06-05), decision second (2026-06-10), landmine last
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "old"},
            {
                "id": "d002",
                "what": "new",
                "supersedes": ["d001"],
                "reason": "dec-reason",
                "made": "2026-06-10",
            },
        ],
        anti_decisions=[
            {"id": "a001", "rejected": "old-anti"},
            {
                "id": "a002",
                "rejected": "new-anti",
                "supersedes": ["a001"],
                "reason": "anti-reason",
                "ruled_out": "2026-06-05",
            },
        ],
        landmines=[
            {"id": "l001", "location": "a.py", "looks_like": "x", "actually": "y"},
            {
                "id": "l002",
                "location": "b.py",
                "looks_like": "p",
                "actually": "q",
                "supersedes": ["l001"],
                "reason": "lm-reason",
            },
        ],
    )
    output = render_superseded_appendix(data)
    pos_anti = output.index("a001 -> a002")
    pos_dec = output.index("d001 -> d002")
    pos_lm = output.index("l001 -> l002")
    assert pos_anti < pos_dec < pos_lm


def test_render_appendix_fan_in_two_bullets():
    # d003 supersedes [d001, d002], reason="r", made="2026-06-20"
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "old1"},
            {"id": "d002", "what": "old2"},
            {
                "id": "d003",
                "what": "unified",
                "supersedes": ["d001", "d002"],
                "reason": "r",
                "made": "2026-06-20",
            },
        ]
    )
    output = render_superseded_appendix(data)
    assert 'd001 -> d003 (2026-06-20): "r"' in output
    assert 'd002 -> d003 (2026-06-20): "r"' in output


# ══════════════════════════════════════════════════════════════════════════════
# Section 9: block helpers (generic + coexistence)
# ══════════════════════════════════════════════════════════════════════════════

_CUSTOM_START = "<!-- CUSTOM:START -->"
_CUSTOM_END = "<!-- CUSTOM:END -->"
_SUP_START = "<!-- SUPERSEDED:START -->"
_SUP_END = "<!-- SUPERSEDED:END -->"


def test_upsert_named_block_creates():
    text = ""
    result = upsert_named_block(text, "inner content", _CUSTOM_START, _CUSTOM_END)
    extracted = extract_named_block(result, _CUSTOM_START, _CUSTOM_END)
    assert extracted == "inner content"


def test_upsert_named_block_updates():
    # First create
    text = "Outer text above.\n"
    result = upsert_named_block(text, "original inner", _CUSTOM_START, _CUSTOM_END)
    # Then update
    result2 = upsert_named_block(result, "updated inner", _CUSTOM_START, _CUSTOM_END)
    assert "Outer text above." in result2
    extracted = extract_named_block(result2, _CUSTOM_START, _CUSTOM_END)
    assert extracted == "updated inner"
    # Old inner should not be present
    assert "original inner" not in result2


def test_extract_named_block_returns_none_absent():
    text = "some text without any markers"
    result = extract_named_block(text, _CUSTOM_START, _CUSTOM_END)
    assert result is None


def test_extract_named_block_returns_inner():
    inner = "the inner content\nline two"
    text = f"{_CUSTOM_START}\n{inner}\n{_CUSTOM_END}"
    result = extract_named_block(text, _CUSTOM_START, _CUSTOM_END)
    assert result == inner


def test_coexistence_two_blocks_in_one_file():
    # Start with some base content
    base = "# My File\n\nSome content here.\n"

    # Add the standard managed block (BATON:START/END)
    with_managed = upsert_managed_block(base, "managed block inner")

    # Add a second block with SUPERSEDED markers in the same text
    with_both = upsert_named_block(with_managed, "superseded inner", _SUP_START, _SUP_END)

    # Both blocks should be independently retrievable
    managed_inner = extract_managed_block(with_both)
    superseded_inner = extract_named_block(with_both, _SUP_START, _SUP_END)

    assert managed_inner == "managed block inner"
    assert superseded_inner == "superseded inner"

    # Updating one should not affect the other
    with_updated_managed = upsert_managed_block(with_both, "managed updated")
    assert extract_named_block(with_updated_managed, _SUP_START, _SUP_END) == "superseded inner"

    with_updated_superseded = upsert_named_block(with_both, "superseded updated", _SUP_START, _SUP_END)
    assert extract_managed_block(with_updated_superseded) == "managed block inner"


# ══════════════════════════════════════════════════════════════════════════════
# Section 10: document.upsert_markdown_region
# ══════════════════════════════════════════════════════════════════════════════


def test_upsert_markdown_region_creates_appendix(tmp_path):
    tmp_baton = tmp_path / "BATON.md"
    shutil.copy(SAMPLE_BATON, tmp_baton)

    doc = BatonDocument.load(tmp_baton)
    doc.upsert_markdown_region(SUPERSEDED_START, SUPERSEDED_END, "## Superseded\n\nhello")

    text = tmp_baton.read_text(encoding="utf-8")
    assert SUPERSEDED_START in text
    assert "hello" in text
    # The yaml fence should still be intact
    assert "```yaml" in text
    assert "```" in text


def test_upsert_markdown_region_no_op_on_empty_inner(tmp_path):
    tmp_baton = tmp_path / "BATON.md"
    shutil.copy(SAMPLE_BATON, tmp_baton)

    original_content = tmp_baton.read_text(encoding="utf-8")
    doc = BatonDocument.load(tmp_baton)
    doc.upsert_markdown_region(SUPERSEDED_START, SUPERSEDED_END, "")

    result = tmp_baton.read_text(encoding="utf-8")
    # File must be unchanged — SUPERSEDED_START not added
    assert SUPERSEDED_START not in result
    assert result == original_content


def test_upsert_markdown_region_updates_not_overwrites_yaml(tmp_path):
    tmp_baton = tmp_path / "BATON.md"
    shutil.copy(SAMPLE_BATON, tmp_baton)

    doc = BatonDocument.load(tmp_baton)
    doc.data["project"]["purpose"] = "Updated"
    doc.save()

    # Now add the superseded appendix
    doc.upsert_markdown_region(
        SUPERSEDED_START, SUPERSEDED_END, "## Superseded\n\nnew content"
    )

    text = tmp_baton.read_text(encoding="utf-8")
    # The updated purpose should appear in the yaml section
    assert "Updated" in text
    # The new appendix content should be present
    assert "new content" in text
    # The yaml fence should still be intact
    assert "```yaml" in text


# ══════════════════════════════════════════════════════════════════════════════
# Section 11: multi-old fan-in
# ══════════════════════════════════════════════════════════════════════════════


def test_fan_in_hand_edited_supersedes_list():
    # d003 has supersedes: [d001, d002] set directly in data dict
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "a"},
            {"id": "d002", "what": "b"},
            {"id": "d003", "what": "unified", "supersedes": ["d001", "d002"]},
        ]
    )
    sb_map = superseded_by_map(data)
    assert sb_map == {"d001": "d003", "d002": "d003"}

    assert derive_status(data, "d001") == "superseded"
    assert derive_status(data, "d002") == "superseded"
    assert derive_status(data, "d003") == "active"

    assert resolve_head(data, "d001") == "d003"
    assert resolve_head(data, "d002") == "d003"


def test_fan_in_appendix_two_bullets():
    # Same fan-in data with reason and made fields
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "a"},
            {"id": "d002", "what": "b"},
            {
                "id": "d003",
                "what": "unified",
                "supersedes": ["d001", "d002"],
                "reason": "shared reason",
                "made": "2026-06-20",
            },
        ]
    )
    output = render_superseded_appendix(data)
    assert 'd001 -> d003 (2026-06-20): "shared reason"' in output
    assert 'd002 -> d003 (2026-06-20): "shared reason"' in output


def test_fan_in_conflicting_second_reason_is_not_validated_here():
    # d001 already in d003.supersedes; validate_link for d002 -> d003 should return []
    # because d002 is not yet claimed by anyone
    data = _make_data(
        decisions=[
            {"id": "d001", "what": "a"},
            {"id": "d002", "what": "b"},
            {"id": "d003", "what": "unified", "supersedes": ["d001"]},
        ]
    )
    # d001 is already claimed by d003
    # d002 is NOT yet in anyone's supersedes -> linking d002 -> d003 is valid
    errors = validate_link(data, "d002", "d003")
    assert errors == []


# ══════════════════════════════════════════════════════════════════════════════
# Section 12: run_supersede command (Phase B end-to-end)
# ══════════════════════════════════════════════════════════════════════════════


def _write_baton_with_supersedable_entries(path):
    """Write a BATON.md to path with d001, d002, a001, l001 entries."""
    yaml_content = (
        'baton_version: "1.0"\n'
        'last_updated: "2026-06-20"\n'
        'last_session_tool: ""\n'
        '\n'
        'project:\n'
        '  name: "Test"\n'
        '  purpose: "Test project"\n'
        '  target_user: ""\n'
        '  stage: "prototype"\n'
        '\n'
        'architecture:\n'
        '  overview: ""\n'
        '  key_directories: []\n'
        '  entry_point: ""\n'
        '  data_flow: ""\n'
        '\n'
        'stack: []\n'
        'laws: []\n'
        '\n'
        'current_sprint:\n'
        '  goal: ""\n'
        '  done: []\n'
        '  in_progress: []\n'
        '  blocked: []\n'
        '  next: []\n'
        '\n'
        'decisions:\n'
        '  - id: "d001"\n'
        '    what: "Use SQLite"\n'
        '    why: "Simple"\n'
        '    made: "2026-06-01"\n'
        '    made_in: "test"\n'
        '  - id: "d002"\n'
        '    what: "Use Postgres"\n'
        '    why: "Scale"\n'
        '    made: "2026-06-10"\n'
        '    made_in: "test"\n'
        '\n'
        'anti_decisions:\n'
        '  - id: "a001"\n'
        '    rejected: "TypeScript"\n'
        '    why: "Python only"\n'
        '    ruled_out: "2026-06-01"\n'
        '\n'
        'landmines:\n'
        '  - id: "l001"\n'
        '    location: "auth/callback.py"\n'
        '    looks_like: "broken redirect"\n'
        '    actually: "intentional OAuth PKCE"\n'
        '\n'
        'open_questions: []\n'
        'sessions: []\n'
    )
    content = '# BATON.md\n\n```yaml\n' + yaml_content + '```\n'
    path.write_text(content, encoding='utf-8')


def test_run_supersede_success(tmp_path):
    baton = tmp_path / "BATON.md"
    _write_baton_with_supersedable_entries(baton)
    result = run_supersede(tmp_path, "d001", "d002", "Postgres scales better")
    assert result == 0
    text = baton.read_text(encoding="utf-8")
    assert "supersedes" in text
    assert "d001" in text
    assert "Postgres scales better" in text
    # Appendix section should appear in the file
    assert SUPERSEDED_START in text
    assert "d001 -> d002" in text


def test_run_supersede_old_id_not_found(tmp_path):
    baton = tmp_path / "BATON.md"
    _write_baton_with_supersedable_entries(baton)
    result = run_supersede(tmp_path, "d999", "d002", "some reason")
    assert result == 1
    # BATON.md must NOT be modified
    text = baton.read_text(encoding="utf-8")
    assert "supersedes" not in text


def test_run_supersede_new_id_not_found(tmp_path):
    baton = tmp_path / "BATON.md"
    _write_baton_with_supersedable_entries(baton)
    result = run_supersede(tmp_path, "d001", "d999", "some reason")
    assert result == 1


def test_run_supersede_cross_type_rejected(tmp_path):
    baton = tmp_path / "BATON.md"
    _write_baton_with_supersedable_entries(baton)
    # d001 is in decisions, a001 is in anti_decisions -- cross-type
    result = run_supersede(tmp_path, "d001", "a001", "some reason")
    assert result == 1
    text = baton.read_text(encoding="utf-8")
    assert "supersedes" not in text


def test_run_supersede_empty_reason_rejected(tmp_path):
    baton = tmp_path / "BATON.md"
    _write_baton_with_supersedable_entries(baton)
    result = run_supersede(tmp_path, "d001", "d002", "")
    assert result == 1
    text = baton.read_text(encoding="utf-8")
    assert "supersedes" not in text


def test_run_supersede_already_superseded_rejected(tmp_path):
    baton = tmp_path / "BATON.md"
    _write_baton_with_supersedable_entries(baton)
    # First supersede d001 -> d002
    result1 = run_supersede(tmp_path, "d001", "d002", "Postgres scales better")
    assert result1 == 0
    # Add a third decision d003, then try to supersede d001 -> d003 (different target)
    doc = BatonDocument.load(baton)
    doc.data["decisions"].append({"id": "d003", "what": "Use MySQL", "why": "legacy", "made": "2026-06-15", "made_in": "test"})
    doc.save()
    result2 = run_supersede(tmp_path, "d001", "d003", "different reason")
    assert result2 == 1  # d001 is already superseded by d002


def test_run_supersede_conflicting_reason_rejected(tmp_path):
    baton = tmp_path / "BATON.md"
    _write_baton_with_supersedable_entries(baton)
    # Add a third decision d003
    doc = BatonDocument.load(baton)
    doc.data["decisions"].append({"id": "d003", "what": "Use MySQL", "why": "legacy", "made": "2026-06-15", "made_in": "test"})
    doc.save()
    # Supersede d001 -> d003 with reason1
    result1 = run_supersede(tmp_path, "d001", "d003", "reason1")
    assert result1 == 0
    # Now try to supersede d002 -> d003 with a DIFFERENT reason -- should fail (conflicting reason)
    result2 = run_supersede(tmp_path, "d002", "d003", "totally different reason")
    assert result2 == 1


def test_run_supersede_same_reason_second_link_ok(tmp_path):
    baton = tmp_path / "BATON.md"
    _write_baton_with_supersedable_entries(baton)
    # Add a third decision d003
    doc = BatonDocument.load(baton)
    doc.data["decisions"].append({"id": "d003", "what": "Use MySQL", "why": "legacy", "made": "2026-06-15", "made_in": "test"})
    doc.save()
    # Supersede d001 -> d003 with shared reason
    result1 = run_supersede(tmp_path, "d001", "d003", "shared reason")
    assert result1 == 0
    # Supersede d002 -> d003 with the SAME reason -- should succeed (fan-in with shared reason)
    result2 = run_supersede(tmp_path, "d002", "d003", "shared reason")
    assert result2 == 0
    text = baton.read_text(encoding="utf-8")
    # Both d001 and d002 should appear in the appendix
    assert "d001 -> d003" in text
    assert "d002 -> d003" in text


def test_run_supersede_idempotent(tmp_path):
    baton = tmp_path / "BATON.md"
    _write_baton_with_supersedable_entries(baton)
    result1 = run_supersede(tmp_path, "d001", "d002", "Postgres scales better")
    result2 = run_supersede(tmp_path, "d001", "d002", "Postgres scales better")
    assert result1 == 0
    assert result2 == 0
    # d001 should appear exactly once in d002's supersedes list
    doc = BatonDocument.load(baton)
    d002 = next(e for e in doc.data["decisions"] if e["id"] == "d002")
    assert list(d002["supersedes"]).count("d001") == 1


def test_run_supersede_old_entry_untouched(tmp_path):
    """Append-only invariant: the old entry must not be modified."""
    baton = tmp_path / "BATON.md"
    _write_baton_with_supersedable_entries(baton)
    doc_before = BatonDocument.load(baton)
    d001_before = dict(doc_before.data["decisions"][0])  # snapshot

    run_supersede(tmp_path, "d001", "d002", "Postgres scales better")

    doc_after = BatonDocument.load(baton)
    d001_after = dict(doc_after.data["decisions"][0])
    assert d001_before == d001_after, "Old entry was modified -- append-only violated"
