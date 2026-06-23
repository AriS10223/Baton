"""
markers.py -- Shared curated-memory marker parser.

Provides the six marker regexes and ``parse_markers()`` used by both
``baton end`` (commit subjects / added diff lines) and
``baton init --scan`` (PR descriptions).

Markers extracted (all case-insensitive):
    DECISION:  <text>   ->  decisions  (what field)
    ANTI:      <text>   ->  anti_decisions  (rejected field)
    REJECTED:  <text>   ->  anti_decisions  (rejected field)
    LANDMINE:  <text>   ->  landmines  (actually field)
    QUESTION:  <text>   ->  open_questions  (question field, status: open)
    OPENQ:     <text>   ->  open_questions  (question field, status: open)
    WHY:       <text>   ->  why context (str, enriches linked entry)
    BATON:     <ids>    ->  baton_ids (list[str], links to existing BATON.md entries)

The BATON: marker captures entry IDs (e.g. "d001, l003") so PR descriptions
can be linked to existing BATON.md entries.  It deliberately does NOT match
the HTML managed-block markers BATON:START / BATON:END / BATON:SUPERSEDED
which are structurally different.
"""
from __future__ import annotations

import re

# ── Marker regexes ────────────────────────────────────────────────────────────
# All case-insensitive.  Capture group 1 is the payload text.

MARKER_DECISION = re.compile(r"(?i)DECISION\s*:\s*(.+)")
MARKER_ANTI     = re.compile(r"(?i)(?:ANTI|REJECTED)\s*:\s*(.+)")
MARKER_LANDMINE = re.compile(r"(?i)LANDMINE\s*:\s*(.+)")
MARKER_QUESTION = re.compile(r"(?i)(?:QUESTION|OPENQ)\s*:\s*(.+)")
MARKER_WHY      = re.compile(r"(?i)WHY\s*:\s*(.+)")
# BATON: must NOT match BATON:START / BATON:END / BATON:SUPERSEDED (managed-block markers).
# Require the value to start with a word character (an id like "d001") or whitespace+id.
MARKER_BATON    = re.compile(r"(?i)BATON\s*:\s*(?!START\b)(?!END\b)(?!SUPERSEDED\b)(\S.+)")


def parse_markers(lines: list[str]) -> dict:
    """Scan a list of text lines for curated-memory markers.

    Accepts either commit-message subjects (as ``baton end`` uses) or
    PR-body lines (as ``baton init --scan`` PR scanner uses).

    Returns a dict with these optional keys (only present when at least one
    match found):
        decisions       list[dict]  {what, why, made_in}
        anti_decisions  list[dict]  {rejected, why}
        landmines       list[dict]  {location, looks_like, actually}
        open_questions  list[dict]  {question, context, status}
        why             str         last WHY: value found (used to enrich entries)
        baton_ids       list[str]   ids from BATON: markers

    Deduplicates by primary text field.
    Each line yields at most one curated-section match (first match wins);
    WHY: and BATON: markers are collected independently (non-exclusive).
    """
    decisions:      list[dict] = []
    anti_decisions: list[dict] = []
    landmines:      list[dict] = []
    open_questions: list[dict] = []

    seen_decisions:  set[str] = set()
    seen_anti:       set[str] = set()
    seen_landmines:  set[str] = set()
    seen_questions:  set[str] = set()

    why_value: str = ""
    baton_ids: list[str] = []

    for raw in lines:
        text = raw.strip()
        if not text:
            continue

        # WHY: and BATON: are collected on every line (not exclusive with curated types)
        m = MARKER_WHY.search(text)
        if m:
            why_value = m.group(1).strip()

        m = MARKER_BATON.search(text)
        if m:
            # Parse comma/space separated ids, e.g. "d001, l003  q002"
            raw_ids = re.split(r"[,\s]+", m.group(1).strip())
            baton_ids.extend(i.strip() for i in raw_ids if i.strip())

        # Curated section markers: first match wins per line
        m = MARKER_DECISION.search(text)
        if m:
            val = m.group(1).strip()
            if val and val not in seen_decisions:
                decisions.append({"what": val, "why": "", "made_in": ""})
                seen_decisions.add(val)
            continue

        m = MARKER_ANTI.search(text)
        if m:
            val = m.group(1).strip()
            if val and val not in seen_anti:
                anti_decisions.append({"rejected": val, "why": ""})
                seen_anti.add(val)
            continue

        m = MARKER_LANDMINE.search(text)
        if m:
            val = m.group(1).strip()
            if val and val not in seen_landmines:
                landmines.append({"location": "", "looks_like": "", "actually": val})
                seen_landmines.add(val)
            continue

        m = MARKER_QUESTION.search(text)
        if m:
            val = m.group(1).strip()
            if val and val not in seen_questions:
                open_questions.append({"question": val, "context": "", "status": "open"})
                seen_questions.add(val)
            continue

    result: dict = {}
    if decisions:
        result["decisions"] = decisions
    if anti_decisions:
        result["anti_decisions"] = anti_decisions
    if landmines:
        result["landmines"] = landmines
    if open_questions:
        result["open_questions"] = open_questions
    if why_value:
        result["why"] = why_value
    if baton_ids:
        result["baton_ids"] = baton_ids
    return result
