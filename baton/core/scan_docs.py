"""
scan_docs.py -- Documentation scanner for ``baton init --scan``.

Reads structured documentation to produce draft decision entries:
  - README.md:  Extracts content from ## Architecture, ## Design, ## Decisions
                sections only (not the full README)
  - docs/adr/   ADR files: extracts "## Decision" section text
  - docs/decisions/  same ADR format
  - CLAUDE.md, AGENTS.md: full content scanned for DECISION: markers
                           using core/markers.parse_markers

Draft entries have:
    what:       extracted decision text (first sentence if long)
    why:        context text if found
    made:       today (ISO date)
    made_in:    ""
    source:     "scan:docs"
    confidence: "medium"   (ADRs with clear Decision section: "high")
    status:     "pending_review"

Public API:
    scan_docs(repo_root, today=None) -> list[dict]
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

from baton.core.markers import parse_markers
from baton.core.schema import PENDING_REVIEW

# README section headers that suggest decision/architecture content
_README_DECISION_HEADERS = re.compile(
    r"^#{1,3}\s+(?:Architecture|Design Decisions?|Decisions?|Technical Decisions?|"
    r"Tech Stack|ADR|Architecture Decisions?|Why .+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Any markdown heading
_ANY_HEADER = re.compile(r"^#{1,6}\s+", re.MULTILINE)

# ADR "## Decision" section
_ADR_DECISION_HEADER = re.compile(r"^#{1,3}\s+Decision\s*$", re.IGNORECASE | re.MULTILINE)
_ADR_STATUS_HEADER   = re.compile(r"^#{1,3}\s+Status\s*$", re.IGNORECASE | re.MULTILINE)
_ADR_CONTEXT_HEADER  = re.compile(r"^#{1,3}\s+Context\s*$", re.IGNORECASE | re.MULTILINE)


def scan_docs(repo_root: Path, today: str | None = None) -> list[dict]:
    """Scan documentation files for architectural decisions.

    Args:
        repo_root: Project root directory.
        today:     ISO date for the ``made`` field (default: today).

    Returns:
        List of decision draft dicts.
    """
    if today is None:
        today = datetime.date.today().isoformat()

    entries: list[dict] = []
    seen: set[str] = set()

    def _add(what: str, why: str, confidence: str) -> None:
        what = _first_sentence(what.strip())
        if not what or what in seen:
            return
        seen.add(what)
        entries.append({
            "what": what,
            "why": why.strip(),
            "made": today,
            "made_in": "",
            "source": "scan:docs",
            "confidence": confidence,
            "status": PENDING_REVIEW,
        })

    # 1. README.md — architecture/decision sections
    readme = repo_root / "README.md"
    if readme.exists():
        for what, why in _extract_readme_decisions(readme.read_text(encoding="utf-8", errors="replace")):
            _add(what, why, "medium")

    # 2. ADR folders
    for adr_dir in [repo_root / "docs" / "adr", repo_root / "docs" / "decisions"]:
        if adr_dir.is_dir():
            for adr_file in sorted(adr_dir.glob("*.md")):
                for what, why, confidence in _extract_adr(adr_file.read_text(encoding="utf-8", errors="replace")):
                    _add(what, why, confidence)

    # 3. CLAUDE.md / AGENTS.md — marker-based extraction
    for fname in ("CLAUDE.md", "AGENTS.md"):
        fpath = repo_root / fname
        if fpath.exists():
            text = fpath.read_text(encoding="utf-8", errors="replace")
            parsed = parse_markers(text.splitlines())
            for d in parsed.get("decisions", []):
                _add(d["what"], d.get("why", ""), "medium")

    return entries


def _extract_readme_decisions(text: str) -> list[tuple[str, str]]:
    """Extract (what, why) pairs from README decision/architecture sections."""
    results: list[tuple[str, str]] = []

    # Find all decision-related section positions
    matches = list(_README_DECISION_HEADERS.finditer(text))
    if not matches:
        return results

    for i, match in enumerate(matches):
        section_start = match.end()
        # Section ends at next any-level header or end of file
        next_headers = list(_ANY_HEADER.finditer(text, section_start))
        section_end = next_headers[0].start() if next_headers else len(text)
        section_text = text[section_start:section_end].strip()

        if not section_text:
            continue

        # Extract bullet points and numbered list items as decision candidates
        for line in section_text.splitlines():
            line = line.strip().lstrip("-*•123456789. ").strip()
            if len(line) > 15 and not line.startswith("#"):  # skip short/empty lines
                results.append((line, ""))

    return results


def _extract_adr(text: str) -> list[tuple[str, str, str]]:
    """Extract (what, why, confidence) from an ADR file."""
    results = []

    # Find "## Decision" section
    m_decision = _ADR_DECISION_HEADER.search(text)
    if not m_decision:
        return results

    # Find context for the "why"
    why = ""
    m_context = _ADR_CONTEXT_HEADER.search(text)
    if m_context:
        ctx_start = m_context.end()
        next_h = _ANY_HEADER.search(text, ctx_start)
        ctx_end = next_h.start() if next_h else len(text)
        why = text[ctx_start:ctx_end].strip()[:200]  # first 200 chars

    # Extract decision text
    decision_start = m_decision.end()
    next_h = _ANY_HEADER.search(text, decision_start)
    decision_end = next_h.start() if next_h else len(text)
    decision_text = text[decision_start:decision_end].strip()

    if not decision_text:
        return results

    # Check if ADR has a "## Status" section with "accepted" / "approved"
    confidence = "medium"
    m_status = _ADR_STATUS_HEADER.search(text)
    if m_status:
        status_start = m_status.end()
        next_h = _ANY_HEADER.search(text, status_start)
        status_end = next_h.start() if next_h else len(text)
        status_text = text[status_start:status_end].strip().lower()
        if any(word in status_text for word in ("accepted", "approved", "superseded")):
            confidence = "high"

    results.append((decision_text, why, confidence))
    return results


def _first_sentence(text: str) -> str:
    """Return the first sentence (up to 120 chars) of a text block."""
    # Take first non-empty line if it's short enough
    for line in text.splitlines():
        line = line.strip()
        if line and len(line) <= 200:
            # Truncate at first period/newline if long
            m = re.search(r"[.!?]\s", line)
            if m and m.start() < 120:
                return line[:m.start() + 1]
            return line[:120]
    return text[:120]
