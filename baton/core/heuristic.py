"""
heuristic.py -- Zero-cost, deterministic session delta for ``baton end``.

Derives a session summary entirely from git data (diff stats + commit subjects)
without making any model call.  Used as the default for bare ``baton end`` and
as the automatic fallback when ``--apply`` receives empty or malformed JSON.

High-fidelity sections (decisions, anti-decisions, landmines, open-questions)
MUST NEVER be inferred from ordinary diff content -- curation is a human/agent
concern.  They are populated ONLY from explicit inline markers:

  In commit-message subjects or added diff lines (+), case-insensitive:

    DECISION:  <text>   ->  decisions  (what field)
    ANTI:      <text>   ->  anti_decisions  (rejected field)
    REJECTED:  <text>   ->  anti_decisions  (rejected field)
    LANDMINE:  <text>   ->  landmines  (actually field; location/looks_like blank)
    QUESTION:  <text>   ->  open_questions  (question field, status: open)
    OPENQ:     <text>   ->  open_questions  (question field, status: open)

If NO markers are found the curated sections are absent from the returned dict.
This preserves the invariant: no curated memory from inference alone.
"""
from __future__ import annotations

import re

# ── Marker regexes (case-insensitive; match at the start of meaningful text) ──
# These extract curated-memory entries from commit subjects or added diff lines.

_MARKER_DECISION  = re.compile(r"(?i)DECISION\s*:\s*(.+)")
_MARKER_ANTI      = re.compile(r"(?i)(?:ANTI|REJECTED)\s*:\s*(.+)")
_MARKER_LANDMINE  = re.compile(r"(?i)LANDMINE\s*:\s*(.+)")
_MARKER_QUESTION  = re.compile(r"(?i)(?:QUESTION|OPENQ)\s*:\s*(.+)")

# ── Commit-subject keywords that suggest "work was completed" ─────────────────

_DONE_KEYWORDS = re.compile(
    r"\b(?:add(?:ed)?|implement(?:ed)?|fix(?:ed)?|complete(?:d)?|"
    r"finish(?:ed)?|close(?:d)?|build|built|ship(?:ped)?|deploy(?:ed)?)\b",
    re.IGNORECASE,
)

# ── Public API ────────────────────────────────────────────────────────────────


def heuristic_delta(
    diff_text: str,
    commit_log: list[str],
    doc_data: dict,
) -> dict:
    """Derive a session delta from git data, no model required.

    Returns a dict shaped identically to ``parse_delta()`` output so it flows
    into the existing ``_review -> _merge_delta -> save`` tail unchanged.

    Args:
        diff_text:   Raw git diff string (may be empty).
        commit_log:  List of commit-message subjects since the last session.
        doc_data:    The loaded BATON.md data dict (for future context use).

    Curated sections (decisions / anti_decisions / landmines / open_questions)
    are included ONLY when explicit markers are found in commit subjects or
    added diff lines.  They are NEVER inferred from ordinary diff content.
    """
    insertions, deletions, files_changed = _parse_diff_stats(diff_text)
    summary    = _build_summary(commit_log, insertions, deletions, files_changed)
    highlights = _build_highlights(commit_log, insertions, deletions)
    sprint_done = _infer_sprint_done(commit_log)
    sprint_next = _infer_sprint_next(diff_text)

    delta: dict = {
        "session": {
            "summary":    summary,
            "highlights": highlights,
        },
        "sprint_done": sprint_done,
        "sprint_next": sprint_next,
    }

    # ── Curated sections from explicit markers only ───────────────────────────
    curated = _extract_markers(commit_log, diff_text)
    delta.update(curated)  # keys absent when no markers found -- intentional

    return delta


# ── Internal helpers ──────────────────────────────────────────────────────────


def _parse_diff_stats(diff_text: str) -> tuple[int, int, int]:
    """Return (insertions, deletions, files_changed) from a unified diff."""
    insertions = 0
    deletions = 0
    files: set[str] = set()

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            # "diff --git a/foo.py b/foo.py" -- extract the b/ filename.
            parts = line.split(" b/", 1)
            if len(parts) == 2:
                files.add(parts[1].strip())
        elif line.startswith("+++") or line.startswith("---"):
            continue  # file-header lines, not body changes
        elif line.startswith("+"):
            insertions += 1
        elif line.startswith("-"):
            deletions += 1

    return insertions, deletions, len(files)


def _build_summary(
    commit_log: list[str],
    insertions: int,
    deletions: int,
    files_changed: int,
) -> str:
    """Build a one-sentence session summary from git stats."""
    if not commit_log and insertions == 0 and deletions == 0:
        return "No changes detected in this session."

    parts: list[str] = []

    if commit_log:
        n = len(commit_log)
        parts.append(f"{n} commit{'s' if n != 1 else ''}")

    if insertions or deletions:
        stat = f"+{insertions}/-{deletions} lines"
        if files_changed:
            stat += f" across {files_changed} file{'s' if files_changed != 1 else ''}"
        parts.append(stat)

    if commit_log:
        # Lead with the most recent commit subject.
        parts.insert(0, commit_log[0])

    return ". ".join(p.rstrip(".") for p in parts) + "."


def _build_highlights(
    commit_log: list[str],
    insertions: int,
    deletions: int,
) -> list[str]:
    """Return 1-3 highlight strings from commit subjects (or stats fallback)."""
    highlights = list(commit_log[:3])  # up to 3 commit subjects

    # If there are no commits but there are changes, surface the stat line.
    if not highlights and (insertions or deletions):
        highlights.append(f"Uncommitted changes: +{insertions}/-{deletions} lines.")

    return highlights


def _infer_sprint_done(commit_log: list[str]) -> list[str]:
    """Return commit subjects that contain a 'work completed' keyword."""
    return [s for s in commit_log if _DONE_KEYWORDS.search(s)]


def _infer_sprint_next(diff_text: str) -> list[dict]:
    """Scan added lines for TODO comments; return as sprint-next dicts.

    Only examines added lines (``+`` prefix) -- removing a TODO is not a task.
    Deduplicates by exact text.
    """
    items: list[dict] = []
    seen: set[str] = set()

    for line in diff_text.splitlines():
        if not line.startswith("+"):
            continue
        # Match:  # TODO: ...   or   // TODO: ...   (common comment styles)
        m = re.search(r"(?:#|//)\s*TODO[:\s]+(.+?)(?:\*/)?$", line, re.IGNORECASE)
        if m:
            text = m.group(1).strip().rstrip("*/").strip()
            if text and text not in seen:
                items.append({"feature": text, "priority": "medium"})
                seen.add(text)

    return items


def _extract_markers(commit_log: list[str], diff_text: str) -> dict:
    """Scan commit subjects and added diff lines for curated-memory markers.

    Returns a dict containing only the sections that had at least one match.
    Absent keys mean "no markers found" -- callers must not infer curated
    memory from their absence.

    Deduplicates by the primary text field (what / rejected / actually / question).
    """
    decisions:     list[dict] = []
    anti_decisions: list[dict] = []
    landmines:     list[dict] = []
    open_questions: list[dict] = []

    seen_decisions:  set[str] = set()
    seen_anti:       set[str] = set()
    seen_landmines:  set[str] = set()
    seen_questions:  set[str] = set()

    # Sources: commit subjects + added (+) lines from the diff.
    sources: list[str] = list(commit_log)
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            sources.append(line[1:])  # strip leading +

    for text in sources:
        text = text.strip()
        if not text:
            continue

        m = _MARKER_DECISION.search(text)
        if m:
            val = m.group(1).strip()
            if val and val not in seen_decisions:
                decisions.append({"what": val, "why": "", "made_in": ""})
                seen_decisions.add(val)
            continue

        m = _MARKER_ANTI.search(text)
        if m:
            val = m.group(1).strip()
            if val and val not in seen_anti:
                anti_decisions.append({"rejected": val, "why": ""})
                seen_anti.add(val)
            continue

        m = _MARKER_LANDMINE.search(text)
        if m:
            val = m.group(1).strip()
            if val and val not in seen_landmines:
                landmines.append({"location": "", "looks_like": "", "actually": val})
                seen_landmines.add(val)
            continue

        m = _MARKER_QUESTION.search(text)
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
    return result
