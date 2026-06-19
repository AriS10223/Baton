"""
heuristic.py -- Zero-cost, deterministic session delta for ``baton end``.

Derives a session summary entirely from git data (diff stats + commit subjects)
without making any model call.  Used as the default for bare ``baton end`` and
as the automatic fallback when ``--apply`` receives empty or malformed JSON.

High-fidelity sections (decisions, anti-decisions, landmines, open-questions)
MUST NEVER be inferred from diff content -- curation is a human/agent concern.
They will be populated via explicit inline markers in a future commit.
For now they are intentionally absent from the returned delta dict.

Marker convention (reserved for future use, case-insensitive):
  DECISION:         ...  ->  decisions
  ANTI: / REJECTED: ...  ->  anti_decisions
  LANDMINE:         ...  ->  landmines
  QUESTION: / OPENQ: ... ->  open_questions
"""
from __future__ import annotations

import re

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

    Note: decisions / anti_decisions / landmines / open_questions are
    intentionally absent.  They must never be inferred from diff content.
    """
    insertions, deletions, files_changed = _parse_diff_stats(diff_text)
    summary   = _build_summary(commit_log, insertions, deletions, files_changed)
    highlights = _build_highlights(commit_log, insertions, deletions)
    sprint_done = _infer_sprint_done(commit_log)
    sprint_next = _infer_sprint_next(diff_text)

    return {
        "session": {
            "summary":    summary,
            "highlights": highlights,
        },
        "sprint_done": sprint_done,
        "sprint_next": sprint_next,
        # decisions / anti_decisions / landmines / open_questions come in Commit B
        # via explicit inline markers.  Never add them here via inference.
    }


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
