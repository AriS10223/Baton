"""
scope_match.py -- Entry matching logic for ``baton scope``.

Two-tier matching:
  Tier-1  keyword overlap  (zero token cost, main signal)
  Tier-2  file-path token  (entries whose text references a path token in the task)

Always-include: entries with ``global: true`` survive regardless of keyword match.

``apply_scope`` is called by sync/status AFTER active_entries() filtering to
produce the scoped dataset that gets written into managed blocks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .scope_keywords import extract_keywords
from .schema import is_global

# Entry types that hold curated, filterable entries.
_CURATED_KEYS = ("decisions", "anti_decisions", "landmines", "open_questions")

# Per-entry text fields searched for keyword overlap.
_TEXT_FIELDS = ("what", "rejected", "note", "question", "actually", "why")

# Threshold below which we emit a skill-escalation hint.
_UNDER_THRESHOLD = 3

# Regex that matches a path separator so we can extract path tokens.
_PATH_TOKEN_RE = re.compile(r"[/\\]")


@dataclass
class ScopeResult:
    task: str
    keywords: list[str]
    entry_ids: list[str]
    tier_counts: dict = field(default_factory=dict)
    under_threshold: bool = False


def _entry_text(entry: dict) -> str:
    """Concatenate all searchable text fields of an entry into one string."""
    parts = []
    for f in _TEXT_FIELDS:
        v = entry.get(f)
        if v:
            parts.append(str(v).lower())
    # also include tags if present
    tags = entry.get("tags")
    if isinstance(tags, list):
        parts.extend(str(t).lower() for t in tags)
    elif tags:
        parts.append(str(tags).lower())
    return " ".join(parts)


def _path_tokens(text: str) -> set[str]:
    """Extract path-like segments from text (e.g. 'auth' from 'src/auth/redirect.py')."""
    tokens: set[str] = set()
    for segment in _PATH_TOKEN_RE.split(text):
        segment = segment.strip().lower()
        if len(segment) >= 3:
            # also split on dot for file extensions
            base = segment.split(".")[0]
            if len(base) >= 3:
                tokens.add(base)
            tokens.add(segment)
    return tokens


def build_scope(task: str, data: dict) -> ScopeResult:
    """Match BATON.md entries against *task* using two-tier keyword matching.

    Caller is responsible for passing data that has already been filtered by
    active_entries() -- this function never calls active_entries() itself.

    Returns a ScopeResult with matched entry ids and tier breakdown counts.
    """
    keywords = extract_keywords(task)
    task_path_tokens = _path_tokens(task)

    matched_ids: list[str] = []
    tier1_count = 0
    tier2_count = 0
    global_count = 0

    kw_set = set(keywords)

    for key in _CURATED_KEYS:
        entries = data.get(key) or []
        for entry in entries:
            try:
                eid = entry.get("id", "")
                if not eid or eid in matched_ids:
                    continue

                # Always-include: global entries
                if is_global(entry):
                    matched_ids.append(eid)
                    global_count += 1
                    continue

                text = _entry_text(entry)

                # Tier-1: keyword overlap
                entry_words = set(text.split())
                if kw_set & entry_words:
                    matched_ids.append(eid)
                    tier1_count += 1
                    continue

                # Tier-2: file-path token overlap
                entry_path_tokens = _path_tokens(text)
                if task_path_tokens & entry_path_tokens:
                    matched_ids.append(eid)
                    tier2_count += 1

            except Exception:
                # Skip unparseable entries; never crash.
                continue

    return ScopeResult(
        task=task,
        keywords=keywords,
        entry_ids=matched_ids,
        tier_counts={"tier1": tier1_count, "tier2": tier2_count, "global": global_count},
        under_threshold=len(matched_ids) < _UNDER_THRESHOLD,
    )


def apply_scope(rendered_data: dict, scope_state: dict) -> dict:
    """Return a copy of *rendered_data* filtered to the active scope.

    Keeps an entry iff its id is in scope_state['entry_ids'] OR it is marked
    global: true.  All non-curated sections pass through unchanged.

    Called by sync/status AFTER _render_data() (which already ran active_entries()).
    """
    snapshot_ids: set[str] = set(scope_state.get("entry_ids") or [])
    filtered = dict(rendered_data)
    for key in _CURATED_KEYS:
        raw = rendered_data.get(key)
        if not isinstance(raw, list):
            continue
        filtered[key] = [
            e for e in raw
            if (isinstance(e, dict) and e.get("id") in snapshot_ids)
            or is_global(e)
        ]
    return filtered
