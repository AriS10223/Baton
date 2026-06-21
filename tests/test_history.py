"""
tests/test_history.py -- Phase C test file for `baton history`.

Covers run_history() in baton/commands/history.py across the following
scenarios:
  1. Single entry, no chain -- HEAD label
  2. Unknown id -- returns 1
  3. Linear chain queried at head -- shows all ids + HEAD
  4. Linear chain queried at non-head -- shows superseded indicator
  5. Fan-in queried at head -- shows both predecessors + HEAD
  6. Fan-in queried at predecessor -- shows superseded indicator
  7. Landmine with no date field -- no crash
  8. Anti-decision single entry -- returns 0
"""
from __future__ import annotations

from pathlib import Path

import pytest

from baton.commands.history import run_history
from baton.core.document import BatonDocument

FIXTURES = Path(__file__).parent / "fixtures"


# ── YAML rendering helpers ─────────────────────────────────────────────────────


def _decision_yaml(d: dict) -> str:
    """Render a decision dict as YAML lines (2-space indent for list item)."""
    lines = [f'  - id: "{d["id"]}"']
    lines.append(f'    what: "{d.get("what", "")}"')
    lines.append(f'    why: "{d.get("why", "")}"')
    lines.append(f'    made: "{d.get("made", "2026-06-01")}"')
    lines.append(f'    made_in: "{d.get("made_in", "test")}"')
    if d.get("supersedes"):
        ids_str = ", ".join(f'"{x}"' for x in d["supersedes"])
        lines.append(f"    supersedes: [{ids_str}]")
    if d.get("reason"):
        lines.append(f'    reason: "{d["reason"]}"')
    return "\n".join(lines)


def _anti_yaml(a: dict) -> str:
    """Render an anti_decision dict as YAML lines."""
    lines = [f'  - id: "{a["id"]}"']
    lines.append(f'    rejected: "{a.get("rejected", "")}"')
    lines.append(f'    why: "{a.get("why", "")}"')
    lines.append(f'    ruled_out: "{a.get("ruled_out", "2026-06-01")}"')
    if a.get("supersedes"):
        ids_str = ", ".join(f'"{x}"' for x in a["supersedes"])
        lines.append(f"    supersedes: [{ids_str}]")
    if a.get("reason"):
        lines.append(f'    reason: "{a["reason"]}"')
    return "\n".join(lines)


def _landmine_yaml(lm: dict) -> str:
    """Render a landmine dict as YAML lines."""
    lines = [f'  - id: "{lm["id"]}"']
    lines.append(f'    location: "{lm.get("location", "")}"')
    lines.append(f'    looks_like: "{lm.get("looks_like", "")}"')
    lines.append(f'    actually: "{lm.get("actually", "")}"')
    if lm.get("supersedes"):
        ids_str = ", ".join(f'"{x}"' for x in lm["supersedes"])
        lines.append(f"    supersedes: [{ids_str}]")
    if lm.get("reason"):
        lines.append(f'    reason: "{lm["reason"]}"')
    return "\n".join(lines)


def _render_list(key: str, items: list, renderer) -> str:
    if not items:
        return f"{key}: []\n"
    lines = [f"{key}:"]
    for item in items:
        lines.append(renderer(item))
    return "\n".join(lines) + "\n"


def _write_baton(
    path: Path,
    decisions: list | None = None,
    anti_decisions: list | None = None,
    landmines: list | None = None,
) -> None:
    """Write a valid minimal BATON.md to *path* with the given lists."""
    dec_block = _render_list("decisions", decisions or [], _decision_yaml)
    anti_block = _render_list("anti_decisions", anti_decisions or [], _anti_yaml)
    lm_block = _render_list("landmines", landmines or [], _landmine_yaml)

    content = (
        "# BATON.md\n\n"
        "```yaml\n"
        'baton_version: "1.0"\n'
        'last_updated: "2026-06-20"\n'
        'last_session_tool: ""\n'
        "project:\n"
        '  name: "Test"\n'
        '  purpose: "Testing"\n'
        '  target_user: ""\n'
        '  stage: "prototype"\n'
        "architecture:\n"
        '  overview: ""\n'
        "  key_directories: []\n"
        '  entry_point: ""\n'
        '  data_flow: ""\n'
        "stack: []\n"
        "laws: []\n"
        "current_sprint:\n"
        '  goal: ""\n'
        "  done: []\n"
        "  in_progress: []\n"
        "  blocked: []\n"
        "  next: []\n"
        + dec_block
        + "\n"
        + anti_block
        + "\n"
        + lm_block
        + "\n"
        "open_questions: []\n"
        "sessions: []\n"
        "```\n"
    )
    path.write_text(content, encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# Test 1: Single entry, no predecessors -- returns 0, HEAD label printed
# ══════════════════════════════════════════════════════════════════════════════


def test_history_single_entry_no_chain(tmp_path, capsys):
    """Single decision with no predecessors -- shows as HEAD, returns 0."""
    baton = tmp_path / "BATON.md"
    _write_baton(
        baton,
        decisions=[
            {"id": "d001", "what": "Use SQLite", "why": "Simple", "made": "2026-06-01", "made_in": "test"}
        ],
    )
    rc = run_history(tmp_path, "d001")
    assert rc == 0

    out = capsys.readouterr().out
    assert "d001" in out
    assert "HEAD" in out


# ══════════════════════════════════════════════════════════════════════════════
# Test 2: Unknown entry_id -- returns 1
# ══════════════════════════════════════════════════════════════════════════════


def test_history_unknown_id_returns_1(tmp_path):
    """Entry id not present in BATON.md -- run_history returns 1."""
    baton = tmp_path / "BATON.md"
    _write_baton(
        baton,
        decisions=[
            {"id": "d001", "what": "Use SQLite", "why": "Simple", "made": "2026-06-01", "made_in": "test"}
        ],
    )
    rc = run_history(tmp_path, "d999")
    assert rc == 1


# ══════════════════════════════════════════════════════════════════════════════
# Test 3: Linear chain d001 -> d002 -> d003, queried at HEAD (d003)
# ══════════════════════════════════════════════════════════════════════════════


def test_history_linear_chain_head(tmp_path, capsys):
    """d001 -> d002 -> d003 chain; querying d003 returns 0 and shows full chain + HEAD."""
    baton = tmp_path / "BATON.md"
    _write_baton(
        baton,
        decisions=[
            {"id": "d001", "what": "SQLite", "why": "simple", "made": "2026-06-01", "made_in": "test"},
            {"id": "d002", "what": "Postgres", "why": "scale", "made": "2026-06-05", "made_in": "test",
             "supersedes": ["d001"], "reason": "needed scale"},
            {"id": "d003", "what": "CockroachDB", "why": "distributed", "made": "2026-06-10", "made_in": "test",
             "supersedes": ["d002"], "reason": "needed distributed"},
        ],
    )
    rc = run_history(tmp_path, "d003")
    assert rc == 0

    out = capsys.readouterr().out
    assert "d001" in out
    assert "d002" in out
    assert "d003" in out
    assert "HEAD" in out


# ══════════════════════════════════════════════════════════════════════════════
# Test 4: Linear chain queried at non-head (d001 is superseded)
# ══════════════════════════════════════════════════════════════════════════════


def test_history_linear_chain_non_head(tmp_path, capsys):
    """d001 -> d002 -> d003 chain; querying d001 returns 0 and shows superseded info."""
    baton = tmp_path / "BATON.md"
    _write_baton(
        baton,
        decisions=[
            {"id": "d001", "what": "SQLite", "why": "simple", "made": "2026-06-01", "made_in": "test"},
            {"id": "d002", "what": "Postgres", "why": "scale", "made": "2026-06-05", "made_in": "test",
             "supersedes": ["d001"], "reason": "needed scale"},
            {"id": "d003", "what": "CockroachDB", "why": "distributed", "made": "2026-06-10", "made_in": "test",
             "supersedes": ["d002"], "reason": "needed distributed"},
        ],
    )
    rc = run_history(tmp_path, "d001")
    assert rc == 0

    out = capsys.readouterr().out
    assert "d001" in out
    assert "superseded" in out


# ══════════════════════════════════════════════════════════════════════════════
# Test 5: Fan-in (d003.supersedes=[d001, d002]) queried at HEAD (d003)
# ══════════════════════════════════════════════════════════════════════════════


def test_history_fan_in_head(tmp_path, capsys):
    """d003 supersedes [d001, d002]; querying d003 returns 0 and shows both predecessors + HEAD."""
    baton = tmp_path / "BATON.md"
    _write_baton(
        baton,
        decisions=[
            {"id": "d001", "what": "Option A", "why": "fast", "made": "2026-06-01", "made_in": "test"},
            {"id": "d002", "what": "Option B", "why": "cheap", "made": "2026-06-02", "made_in": "test"},
            {"id": "d003", "what": "Unified", "why": "best of both", "made": "2026-06-10", "made_in": "test",
             "supersedes": ["d001", "d002"], "reason": "merged"},
        ],
    )
    rc = run_history(tmp_path, "d003")
    assert rc == 0

    out = capsys.readouterr().out
    assert "d001" in out
    assert "d002" in out
    assert "d003" in out
    assert "HEAD" in out


# ══════════════════════════════════════════════════════════════════════════════
# Test 6: Fan-in queried at predecessor (d001 is superseded by d003)
# ══════════════════════════════════════════════════════════════════════════════


def test_history_fan_in_predecessor(tmp_path, capsys):
    """d003 supersedes [d001, d002]; querying d001 returns 0 and shows it is superseded."""
    baton = tmp_path / "BATON.md"
    _write_baton(
        baton,
        decisions=[
            {"id": "d001", "what": "Option A", "why": "fast", "made": "2026-06-01", "made_in": "test"},
            {"id": "d002", "what": "Option B", "why": "cheap", "made": "2026-06-02", "made_in": "test"},
            {"id": "d003", "what": "Unified", "why": "best of both", "made": "2026-06-10", "made_in": "test",
             "supersedes": ["d001", "d002"], "reason": "merged"},
        ],
    )
    rc = run_history(tmp_path, "d001")
    assert rc == 0

    out = capsys.readouterr().out
    assert "d001" in out
    assert "superseded" in out


# ══════════════════════════════════════════════════════════════════════════════
# Test 7: Landmine with supersedes but no date field -- no crash
# ══════════════════════════════════════════════════════════════════════════════


def test_history_landmine_no_date(tmp_path):
    """l002.supersedes=[l001]; landmines have no date field -- must not crash, returns 0."""
    baton = tmp_path / "BATON.md"
    _write_baton(
        baton,
        landmines=[
            {"id": "l001", "location": "auth.py", "looks_like": "broken", "actually": "intentional"},
            {"id": "l002", "location": "auth.py", "looks_like": "new broken", "actually": "also intentional",
             "supersedes": ["l001"], "reason": "updated landmine"},
        ],
    )
    rc = run_history(tmp_path, "l002")
    assert rc == 0


# ══════════════════════════════════════════════════════════════════════════════
# Test 8: Anti-decision single entry -- returns 0
# ══════════════════════════════════════════════════════════════════════════════


def test_history_anti_decision(tmp_path):
    """a001 anti-decision with no chain; returns 0."""
    baton = tmp_path / "BATON.md"
    _write_baton(
        baton,
        anti_decisions=[
            {"id": "a001", "rejected": "TypeScript", "why": "Python only", "ruled_out": "2026-06-01"},
        ],
    )
    rc = run_history(tmp_path, "a001")
    assert rc == 0
