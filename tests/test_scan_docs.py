"""Tests for baton/core/scan_docs.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from baton.core.scan_docs import scan_docs
from baton.core.schema import PENDING_REVIEW


# ── Fixtures ──────────────────────────────────────────────────────────────────

TODAY = "2026-01-01"


def _make_readme(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "README.md"
    p.write_text(content, encoding="utf-8")
    return p


def _make_adr(tmp_path: Path, filename: str, content: str, folder: str = "adr") -> Path:
    adr_dir = tmp_path / "docs" / folder
    adr_dir.mkdir(parents=True, exist_ok=True)
    p = adr_dir / filename
    p.write_text(content, encoding="utf-8")
    return p


# ── README tests ──────────────────────────────────────────────────────────────

def test_readme_architecture_section_extracts_bullets(tmp_path):
    _make_readme(tmp_path, """\
# My Project

## Architecture

- Use FastAPI for the HTTP layer because it is async-native
- Store data in PostgreSQL with SQLAlchemy ORM

## Usage

Some usage text here.
""")
    entries = scan_docs(tmp_path, today=TODAY)
    whats = [e["what"] for e in entries]
    assert any("FastAPI" in w for w in whats), f"Expected FastAPI entry, got: {whats}"
    assert any("PostgreSQL" in w for w in whats), f"Expected PostgreSQL entry, got: {whats}"


def test_readme_decisions_section_extracts_bullets(tmp_path):
    _make_readme(tmp_path, """\
# My Project

## Decisions

- We chose React over Vue because the team knows it better
- Server-side rendering is disabled for now

## Getting Started

...
""")
    entries = scan_docs(tmp_path, today=TODAY)
    whats = [e["what"] for e in entries]
    assert any("React" in w for w in whats)
    assert any("rendering" in w.lower() for w in whats)


def test_readme_no_decision_sections_returns_empty(tmp_path):
    _make_readme(tmp_path, """\
# My Project

## Installation

Run pip install myproject.

## Usage

Import and use.
""")
    entries = scan_docs(tmp_path, today=TODAY)
    assert entries == []


def test_readme_missing_returns_empty(tmp_path):
    # No README.md at all
    entries = scan_docs(tmp_path, today=TODAY)
    assert entries == []


def test_readme_entries_have_correct_metadata(tmp_path):
    _make_readme(tmp_path, """\
## Architecture

- Use Docker for containerization to simplify deployment
""")
    entries = scan_docs(tmp_path, today=TODAY)
    assert len(entries) >= 1
    e = entries[0]
    assert e["source"] == "scan:docs"
    assert e["confidence"] == "medium"
    assert e["status"] == PENDING_REVIEW
    assert e["made"] == TODAY
    assert e["made_in"] == ""


def test_readme_why_field_is_empty_string(tmp_path):
    _make_readme(tmp_path, """\
## Architecture

- Use Redis for caching because reads are frequent
""")
    entries = scan_docs(tmp_path, today=TODAY)
    assert len(entries) >= 1
    # README-sourced entries have empty why (no structured context section)
    assert entries[0]["why"] == ""


def test_readme_design_decisions_header_variant(tmp_path):
    _make_readme(tmp_path, """\
## Design Decisions

- Avoid microservices until traffic justifies complexity
""")
    entries = scan_docs(tmp_path, today=TODAY)
    assert any("microservices" in e["what"].lower() for e in entries)


# ── ADR tests ─────────────────────────────────────────────────────────────────

_ADR_ACCEPTED = """\
# ADR 001: Use PostgreSQL

## Status

Accepted

## Context

We need a relational database for structured data with strong consistency.

## Decision

We will use PostgreSQL as the primary data store.

## Consequences

Schema migrations are required for every model change.
"""

_ADR_PROPOSED = """\
# ADR 002: Use Redis

## Status

Proposed

## Context

Cache layer needed.

## Decision

Use Redis for caching hot data.
"""

_ADR_NO_DECISION = """\
# ADR 003: Something

## Status

Proposed

## Context

Some background here.

## Consequences

Things happen.
"""


def test_adr_accepted_status_yields_high_confidence(tmp_path):
    _make_adr(tmp_path, "0001-postgres.md", _ADR_ACCEPTED)
    entries = scan_docs(tmp_path, today=TODAY)
    assert len(entries) == 1
    assert entries[0]["confidence"] == "high"
    assert "PostgreSQL" in entries[0]["what"]


def test_adr_proposed_status_yields_medium_confidence(tmp_path):
    _make_adr(tmp_path, "0002-redis.md", _ADR_PROPOSED)
    entries = scan_docs(tmp_path, today=TODAY)
    assert len(entries) == 1
    assert entries[0]["confidence"] == "medium"


def test_adr_no_decision_section_yields_empty(tmp_path):
    _make_adr(tmp_path, "0003-no-decision.md", _ADR_NO_DECISION)
    entries = scan_docs(tmp_path, today=TODAY)
    assert entries == []


def test_adr_context_section_populates_why(tmp_path):
    _make_adr(tmp_path, "0001-postgres.md", _ADR_ACCEPTED)
    entries = scan_docs(tmp_path, today=TODAY)
    assert len(entries) == 1
    assert "relational database" in entries[0]["why"]


def test_adr_folder_not_present_no_crash(tmp_path):
    # No docs/adr directory
    entries = scan_docs(tmp_path, today=TODAY)
    assert entries == []


def test_adr_decisions_folder_variant(tmp_path):
    _make_adr(tmp_path, "0001-use-fastapi.md", _ADR_ACCEPTED, folder="decisions")
    entries = scan_docs(tmp_path, today=TODAY)
    assert len(entries) == 1
    assert entries[0]["confidence"] == "high"


def test_adr_multiple_files_all_extracted(tmp_path):
    _make_adr(tmp_path, "0001-postgres.md", _ADR_ACCEPTED)
    _make_adr(tmp_path, "0002-redis.md", _ADR_PROPOSED)
    entries = scan_docs(tmp_path, today=TODAY)
    assert len(entries) == 2


def test_adr_entries_have_correct_source(tmp_path):
    _make_adr(tmp_path, "0001-postgres.md", _ADR_ACCEPTED)
    entries = scan_docs(tmp_path, today=TODAY)
    assert entries[0]["source"] == "scan:docs"
    assert entries[0]["status"] == PENDING_REVIEW


# ── CLAUDE.md / AGENTS.md marker tests ───────────────────────────────────────

def test_claude_md_decision_marker_extracted(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("DECISION: Use FastAPI for the REST API\n", encoding="utf-8")
    entries = scan_docs(tmp_path, today=TODAY)
    assert len(entries) == 1
    assert "FastAPI" in entries[0]["what"]


def test_agents_md_decision_marker_extracted(tmp_path):
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("DECISION: Never use global state in components\n", encoding="utf-8")
    entries = scan_docs(tmp_path, today=TODAY)
    assert len(entries) == 1
    assert "global state" in entries[0]["what"]


def test_claude_md_no_markers_returns_empty(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# Project instructions\n\nDo stuff.\n", encoding="utf-8")
    entries = scan_docs(tmp_path, today=TODAY)
    assert entries == []


def test_claude_md_marker_confidence_is_medium(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("DECISION: Keep all business logic in the service layer\n", encoding="utf-8")
    entries = scan_docs(tmp_path, today=TODAY)
    assert entries[0]["confidence"] == "medium"


# ── Deduplication tests ────────────────────────────────────────────────────────

def test_duplicate_decisions_deduplicated(tmp_path):
    # Same text from both CLAUDE.md and README.md -> only one entry
    _make_readme(tmp_path, """\
## Architecture

- Use PostgreSQL as the primary data store
""")
    claude_md = tmp_path / "CLAUDE.md"
    # The first sentence of the ADR and README bullet will be different enough
    # so let's use exact same text via CLAUDE.md marker
    claude_md.write_text("DECISION: Use PostgreSQL as the primary data store\n", encoding="utf-8")
    entries = scan_docs(tmp_path, today=TODAY)
    texts = [e["what"] for e in entries]
    # Dedup by exact `what` text — same text appears at most once
    assert len(texts) == len(set(texts))


# ── Default today ─────────────────────────────────────────────────────────────

def test_default_today_is_populated(tmp_path):
    import datetime
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("DECISION: Use type hints everywhere\n", encoding="utf-8")
    entries = scan_docs(tmp_path)  # no today= argument
    assert entries[0]["made"] == datetime.date.today().isoformat()
