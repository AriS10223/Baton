"""
scan_manifest.py -- Manifest scanner for ``baton init --scan``.

Reads package manifests via ``core/manifest.read_manifest_deps()`` and
produces draft ``decisions`` entries for production dependencies.

Only production dependencies become entries.  Dev/test/lint/build deps
are skipped because they are not architectural decisions.

Each entry has:
    what:       "Uses <name>" (capitalised)
    why:        ""  (human fills this in via baton review)
    made:       today (ISO date)
    made_in:    ""
    evidence:   {type: "dependency", value: <name>}
    source:     "scan:manifest"
    confidence: "high"
    status:     "pending_review"

Public API:
    scan_manifests(repo_root, today=None) -> list[dict]
"""
from __future__ import annotations

import datetime
from pathlib import Path

from baton.core.manifest import read_manifest_deps
from baton.core.schema import PENDING_REVIEW


def scan_manifests(repo_root: Path, today: str | None = None) -> list[dict]:
    """Return draft decision entries for each production dependency found.

    Args:
        repo_root: Project root (where manifests live alongside BATON.md).
        today:     ISO date string for the ``made`` field (default: today).

    Returns:
        List of decision draft dicts.  Empty when no manifests found.
        Deduplicates by normalised dependency name -- if the same dep appears
        in multiple manifests (e.g. pyproject.toml and requirements.txt),
        only one entry is produced.
    """
    if today is None:
        today = datetime.date.today().isoformat()

    deps = read_manifest_deps(repo_root)
    seen: set[str] = set()
    entries: list[dict] = []

    for dep in deps:
        name = dep["name"]
        section = dep.get("section", "unknown")

        # Only prod dependencies become decision entries.
        # dev / optional / unknown are skipped.
        if section not in ("prod",):
            continue

        if name in seen:
            continue
        seen.add(name)

        # Capitalise the display name: "fastapi" -> "FastAPI" would be nice
        # but we can't always guess capitalisation from the normalised name.
        # Use the original casing from the manifest entry's name field.
        display = name

        entries.append({
            "what": f"Uses {display}",
            "why": "",
            "made": today,
            "made_in": "",
            "evidence": {"type": "dependency", "value": name},
            "source": "scan:manifest",
            "confidence": "high",
            "status": PENDING_REVIEW,
        })

    return entries
