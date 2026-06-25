"""
scope_render.py -- Render the committable .baton/scope.md artifact.

Output is ASCII-only (Windows CP1252 safe).  The header carries a per-run
timestamp; the body is id-sorted and idempotent across runs with identical data.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .scope_match import ScopeResult, _CURATED_KEYS

# Section display labels (ASCII-only).
_SECTION_LABELS: dict[str, str] = {
    "decisions": "Decisions",
    "anti_decisions": "Anti-decisions",
    "landmines": "Landmines",
    "open_questions": "Open questions",
}

# Primary text field for each curated section (used in body rendering).
_PRIMARY_FIELD: dict[str, str] = {
    "decisions": "what",
    "anti_decisions": "rejected",
    "landmines": "actually",
    "open_questions": "question",
}


def _estimate_tokens(text: str) -> int | None:
    """Deferred seam: returns None until a token counter is wired in."""
    return None


def _render_entry(entry: dict, section: str) -> str:
    """Render a single entry as a compact bullet line."""
    eid = entry.get("id", "?")
    primary_key = _PRIMARY_FIELD.get(section, "what")
    text = entry.get(primary_key, "")
    if not text:
        # fallback: first non-empty text field
        for f in ("what", "rejected", "actually", "question", "note"):
            text = entry.get(f, "")
            if text:
                break
    return f"- [{eid}] {text}"


def render_scope_md(result: ScopeResult, data: dict) -> str:
    """Render .baton/scope.md content.

    Header: task + ISO timestamp + regenerate hint (changes every run).
    Body:   id-sorted per-section bullets (idempotent given same data).
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: list[str] = [
        "# Baton Scope",
        f"Task: {result.task}",
        f"Generated: {now_iso}",
        "Regenerate: baton scope \"<task>\"",
        "",
    ]

    snapshot_ids: set[str] = set(result.entry_ids)
    any_section = False

    for key in _CURATED_KEYS:
        entries = data.get(key) or []
        # Keep only in-scope entries, sorted by id for idempotent output.
        in_scope = sorted(
            [e for e in entries if isinstance(e, dict) and e.get("id") in snapshot_ids],
            key=lambda e: e.get("id", ""),
        )
        if not in_scope:
            continue
        any_section = True
        label = _SECTION_LABELS.get(key, key)
        lines.append(f"## {label}")
        for entry in in_scope:
            lines.append(_render_entry(entry, key))
        lines.append("")

    if not any_section:
        lines.append("(No entries matched this scope.)")
        lines.append("")

    token_count = _estimate_tokens("\n".join(lines))
    if token_count is not None:
        lines.append(f"Estimated tokens: {token_count}")
        lines.append("")

    return "\n".join(lines)
