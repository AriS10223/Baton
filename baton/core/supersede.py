"""
supersede.py -- Pure derivation module for supersession chains.

No I/O, no git, no YAML.  Mirrors core/drift.py style.
Consumed by commands/supersede.py, commands/history.py,
commands/status.py, commands/end.py.
"""
from __future__ import annotations

import difflib

from .schema import SUPERSEDABLE_TYPES

# ── Appendix marker constants ─────────────────────────────────────────────────

SUPERSEDED_START = "<!-- BATON:SUPERSEDED:START - auto-generated, do not edit by hand -->"
SUPERSEDED_END   = "<!-- BATON:SUPERSEDED:END -->"


# ── Basic accessors ───────────────────────────────────────────────────────────


def entries_for(data: dict, type_key: str) -> list:
    """Return the entry list for *type_key* from *data*.

    Returns [] if the key is absent or the value is not a list.
    """
    val = data.get(type_key)
    return val if isinstance(val, list) else []


def find_entry(data: dict, entry_id: str) -> tuple[str, dict] | None:
    """Scan all supersedable lists; return (type_key, entry) for *entry_id*.

    Returns None if no match is found.
    """
    for type_key in SUPERSEDABLE_TYPES:
        for entry in entries_for(data, type_key):
            if isinstance(entry, dict) and entry.get("id") == entry_id:
                return (type_key, entry)
    return None


# ── Supersession maps ─────────────────────────────────────────────────────────


def superseded_by_map(data: dict) -> dict[str, str]:
    """Build a reverse-lookup: old_id -> new_id.

    Scans every supersedable entry for a ``supersedes`` list and maps each
    old_id to the id of the newer entry.  Lenient: skips entries missing
    ``id`` or with malformed ``supersedes`` values.  Never raises.
    """
    result: dict[str, str] = {}
    for type_key in SUPERSEDABLE_TYPES:
        for entry in entries_for(data, type_key):
            if not isinstance(entry, dict):
                continue
            new_id = entry.get("id")
            if not new_id:
                continue
            supersedes = entry.get("supersedes")
            if not isinstance(supersedes, list):
                continue
            for old_id in supersedes:
                if isinstance(old_id, str) and old_id:
                    result[old_id] = new_id
    return result


# ── Status / chain resolution ─────────────────────────────────────────────────


def derive_status(data: dict, entry_id: str) -> str:
    """Return "superseded" if any other entry claims *entry_id*, else "active"."""
    sb_map = superseded_by_map(data)
    return "superseded" if entry_id in sb_map else "active"


def resolve_head(data: dict, entry_id: str) -> str:
    """Walk forward from *entry_id* through the superseded_by_map.

    Returns the id at the end of the chain (the canonical current version).
    Cycle-guarded: if a visited id is encountered again, stop and return
    the current id rather than looping forever.
    """
    sb_map = superseded_by_map(data)
    visited: set[str] = {entry_id}
    current = entry_id
    while current in sb_map:
        nxt = sb_map[current]
        if nxt in visited:
            # Cycle detected -- return the last safe id
            break
        visited.add(nxt)
        current = nxt
    return current


def chain_backward(data: dict, entry_id: str) -> list[list[dict]]:
    """Return the predecessor tree as a list of branches, oldest-first per branch.

    Each inner list is one branch of ancestors converging on *entry_id*.
    The queried entry itself is NOT included (callers add it as HEAD).

    For a linear chain A <- B <- entry_id: returns [[A_entry, B_entry]].
    For fan-in (d004 and d005 both superseded by entry_id):
        returns [[d004_entry], [d005_entry]].

    Cycle-guarded via a ``visited`` set passed through the recursion.
    """
    return _chain_backward_inner(data, entry_id, visited=frozenset({entry_id}))


def _chain_backward_inner(
    data: dict,
    entry_id: str,
    visited: frozenset[str],
) -> list[list[dict]]:
    """Recursive helper for chain_backward.  Uses an immutable visited set."""
    # Find the entry for entry_id and read its own supersedes list --
    # those are the direct predecessors (things entry_id supersedes).
    entry_result = find_entry(data, entry_id)
    if entry_result is None:
        return []
    _, entry = entry_result
    supersedes_raw = entry.get("supersedes")
    if not isinstance(supersedes_raw, list):
        return []

    predecessors: list[str] = [
        old_id for old_id in supersedes_raw
        if isinstance(old_id, str) and old_id and old_id not in visited
    ]

    if not predecessors:
        return []

    branches: list[list[dict]] = []
    for pred_id in predecessors:
        pred_result = find_entry(data, pred_id)
        if pred_result is None:
            continue
        _, pred_entry = pred_result
        # Recurse into the predecessor's ancestors
        sub_branches = _chain_backward_inner(
            data, pred_id, visited=visited | {pred_id}
        )
        if sub_branches:
            # Append this predecessor to the end of each sub-branch
            for branch in sub_branches:
                branches.append(branch + [pred_entry])
        else:
            # pred_id is the oldest in its line
            branches.append([pred_entry])

    return branches


# ── Validation ────────────────────────────────────────────────────────────────


def validate_link(data: dict, old_id: str, new_id: str) -> list[str]:
    """Strict validation for linking old_id -> new_id.

    Returns a list of error strings.  Empty list means the link is valid.

    Checks (in order, all collected before returning):
    - old_id and new_id both exist in data
    - No cycle: walking forward from new_id must not reach old_id
    - Single-claim: old_id must not already appear in another entry's supersedes
      (unless that claimer is new_id itself -- idempotent re-link is allowed)

    Rule 4 (same-type enforcement) is the caller's responsibility.
    """
    errors: list[str] = []

    old_found = find_entry(data, old_id) is not None
    new_found = find_entry(data, new_id) is not None

    if not old_found:
        errors.append(f"Entry {old_id} not found")
    if not new_found:
        errors.append(f"Entry {new_id} not found")

    # Can only perform graph checks when both ids exist
    if old_found and new_found:
        # Cycle check: walk forward from new_id; if we reach old_id it's a cycle
        sb_map = superseded_by_map(data)
        visited: set[str] = {new_id}
        current = new_id
        while current in sb_map:
            nxt = sb_map[current]
            if nxt == old_id:
                errors.append(f"Cycle detected: {new_id} -> ... -> {old_id}")
                break
            if nxt in visited:
                break  # pre-existing cycle, not our problem
            visited.add(nxt)
            current = nxt

        # Single-claim check: old_id must not already be claimed by someone else
        claimer = sb_map.get(old_id)
        if claimer and claimer != new_id:
            errors.append(f"Already superseded by {claimer}")

    return errors


# ── Appendix rendering ────────────────────────────────────────────────────────


def render_superseded_appendix(data: dict) -> str:
    """Build the inner markdown for the Superseded appendix block.

    Collects one bullet per superseded entry across all three lists,
    sorted by the new entry's date field ascending (dated entries first,
    then landmines sorted by new_id alphabetically).

    Returns "" if no supersession links exist.
    """
    bullets: list[tuple] = []  # (sort_key, bullet_str)

    for type_key, type_meta in SUPERSEDABLE_TYPES.items():
        date_field = type_meta["date"]  # None for landmines
        for entry in entries_for(data, type_key):
            if not isinstance(entry, dict):
                continue
            new_id = entry.get("id", "")
            supersedes = entry.get("supersedes")
            if not isinstance(supersedes, list) or not supersedes:
                continue
            reason = entry.get("reason", "")
            date_val = entry.get(date_field, "") if date_field else None

            for old_id in supersedes:
                if not isinstance(old_id, str) or not old_id:
                    continue
                if date_val:
                    # Dated entry: sort by date ascending, then new_id
                    sort_key = (0, str(date_val), new_id)
                    bullet = f"- {old_id} -> {new_id} ({date_val}): \"{reason}\""
                else:
                    # Landmine (no date): sort after dated entries, then by new_id
                    sort_key = (1, "", new_id)
                    bullet = f"- {old_id} -> {new_id}: \"{reason}\""

                bullets.append((sort_key, bullet))

    if not bullets:
        return ""

    bullets.sort(key=lambda t: t[0])
    bullet_lines = "\n".join(b for _, b in bullets)

    return (
        "## Superseded\n"
        "\n"
        "_Entries replaced by newer decisions. Original text is preserved above._\n"
        "\n"
        f"{bullet_lines}"
    )


# ── Overlap detection ─────────────────────────────────────────────────────────


def detect_overlaps(
    data: dict,
    delta: dict,
    new_ids: set[str] | None = None,
) -> list[dict]:
    """Detect potential overlaps between newly-drafted delta entries and active existing entries.

    *delta* has the same shape as the merge delta: keys "decisions",
    "anti_decisions", "landmines" each mapping to lists of entries to be added.

    *new_ids*: ids just assigned during _merge_delta -- excluded from the
    existing-active pool to prevent self-matching.

    Returns a list of overlap dicts::

        {
            "draft":     <draft_entry>,
            "existing":  <existing_entry>,
            "type_key":  <type_key str>,
            "signal":    "evidence_match" | "text_similarity" | "location_match",
        }
    """
    _new_ids: set[str] = new_ids or set()
    overlaps: list[dict] = []

    for type_key, type_meta in SUPERSEDABLE_TYPES.items():
        draft_entries = delta.get(type_key)
        if not isinstance(draft_entries, list):
            continue

        # Collect active existing entries (exclude freshly-added ones)
        active_existing = [
            e for e in entries_for(data, type_key)
            if isinstance(e, dict)
            and e.get("id") not in _new_ids
            and derive_status(data, e.get("id", "")) == "active"
        ]

        text_field = type_meta["text"]  # schema-owned field name

        for draft in draft_entries:
            if not isinstance(draft, dict):
                continue

            for existing in active_existing:
                signal = _compare_entries(draft, existing, type_key, text_field)
                if signal:
                    overlaps.append({
                        "draft":    draft,
                        "existing": existing,
                        "type_key": type_key,
                        "signal":   signal,
                    })

    return overlaps


def _compare_entries(
    draft: dict,
    existing: dict,
    type_key: str,
    text_field: str,
) -> str | None:
    """Return the signal name if *draft* and *existing* overlap, else None."""
    if type_key == "decisions":
        # Structured match: same evidence.type AND evidence.value
        d_ev = draft.get("evidence")
        e_ev = existing.get("evidence")
        if (
            isinstance(d_ev, dict)
            and isinstance(e_ev, dict)
            and d_ev.get("type")
            and d_ev.get("type") == e_ev.get("type")
            and d_ev.get("value")
            and d_ev.get("value") == e_ev.get("value")
        ):
            return "evidence_match"
        # Fallback: text similarity on the primary text field
        if _text_similar(draft.get(text_field, ""), existing.get(text_field, "")):
            return "text_similarity"

    elif type_key == "anti_decisions":
        # Structured match: same pattern.value
        d_pat = draft.get("pattern")
        e_pat = existing.get("pattern")
        if (
            isinstance(d_pat, dict)
            and isinstance(e_pat, dict)
            and d_pat.get("value")
            and d_pat.get("value") == e_pat.get("value")
        ):
            return "evidence_match"
        # Fallback: text similarity
        if _text_similar(draft.get(text_field, ""), existing.get(text_field, "")):
            return "text_similarity"

    elif type_key == "landmines":
        # Location equality (string)
        d_loc = draft.get("location", "")
        e_loc = existing.get("location", "")
        if d_loc and d_loc == e_loc:
            # Optionally refine with marker if both have it
            d_mk = draft.get("marker")
            e_mk = existing.get("marker")
            if d_mk and e_mk and d_mk != e_mk:
                return None  # same location, different markers -- not a match
            return "location_match"

    return None


def _text_similar(a: str, b: str, threshold: float = 0.85) -> bool:
    """Return True if difflib SequenceMatcher ratio >= *threshold*."""
    if not a or not b:
        return False
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return ratio >= threshold
