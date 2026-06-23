"""
scan.py -- ``baton init --scan``: zero-token codebase scanning.

Orchestrates four Tier-1 source scanners in order:
    scan:manifest   package manifests (prod deps -> decisions)
    scan:comment    HACK/FIXME/TODO/WARNING in source files (-> landmines)
    scan:docs       README/ADR/CLAUDE.md (-> decisions)
    scan:pr_history gh pr list (-> any entry type, graceful if gh absent)

Multi-source dedup:
    - Manifest entries are canonical when a dep appears in both manifest and PR.
    - PR ``WHY:`` text enriches the matching manifest entry's ``why`` field.
    - All other types: dedup by primary text field across sources.

IDs are assigned here (not in scanners) so they are unique across all sources.
Draft entries are appended to the existing BATON.md (append-only on existing
entries, no ``--force`` needed).

By default only high-confidence entries are appended.  ``--exhaustive`` adds
medium and low confidence.

Public API:
    run_scan(repo_root, exhaustive, skip_pr_history, skip_docs) -> bool
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..core.document import BatonDocument, BatonDocumentError
from ..core.schema import PENDING_REVIEW

console = Console(highlight=False)


def run_scan(
    repo_root: Path,
    *,
    exhaustive: bool = False,
    skip_pr_history: bool = False,
    skip_docs: bool = False,
) -> bool:
    """Run the codebase scanner and append draft entries to BATON.md.

    Args:
        repo_root:        Project root (where BATON.md lives).
        exhaustive:       Include medium/low-confidence entries (default: high only).
        skip_pr_history:  Skip the gh PR history scan.
        skip_docs:        Skip README/ADR scanning.

    Returns:
        True on success, False if BATON.md could not be loaded/saved.
    """
    baton_path = repo_root / "BATON.md"
    today = datetime.date.today().isoformat()

    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        console.print(f"[red]Error loading BATON.md:[/red] {exc}", markup=True)
        return False

    # ── Phase 1: run all Tier-1 scanners ─────────────────────────────────────

    scan_results: dict[str, tuple[list[dict], str]] = {}

    # Manifest scanner
    console.print("Scanning manifests...", end="  ")
    try:
        from ..core.scan_manifest import scan_manifests
        manifest_entries = scan_manifests(repo_root, today=today)
        scan_results["scan:manifest"] = (manifest_entries, "decisions")
        console.print(f"[dim]{len(manifest_entries)} entries[/dim]", markup=True)
    except ImportError:
        manifest_entries = []
        console.print("[dim]skipped (module not available)[/dim]", markup=True)

    # Comment scanner
    console.print("Scanning comments...", end="  ")
    try:
        from ..core.scan_comments import scan_comments
        comment_entries = scan_comments(repo_root, today=today)
        scan_results["scan:comment"] = (comment_entries, "landmines")
        console.print(f"[dim]{len(comment_entries)} entries[/dim]", markup=True)
    except ImportError:
        comment_entries = []
        console.print("[dim]skipped (module not available)[/dim]", markup=True)

    # Docs scanner
    if not skip_docs:
        console.print("Scanning docs...", end="  ")
        try:
            from ..core.scan_docs import scan_docs
            docs_entries = scan_docs(repo_root, today=today)
            scan_results["scan:docs"] = (docs_entries, "decisions")
            console.print(f"[dim]{len(docs_entries)} entries[/dim]", markup=True)
        except ImportError:
            docs_entries = []
            console.print("[dim]skipped (module not available)[/dim]", markup=True)
    else:
        docs_entries = []

    # PR history scanner
    pr_note = "skipped (--skip-pr-history)"
    pr_entries: list[dict] = []
    if not skip_pr_history:
        console.print("Scanning PR history (gh)...", end="  ")
        try:
            from ..core.scan_pr import scan_prs
            pr_entries, pr_note = scan_prs(repo_root, today=today)
            console.print(f"[dim]{pr_note}[/dim]", markup=True)
        except ImportError:
            pr_note = "skipped (module not available)"
            console.print(f"[dim]{pr_note}[/dim]", markup=True)

    # ── Phase 2: multi-source merge ───────────────────────────────────────────

    all_decisions: list[dict] = []
    all_anti_decisions: list[dict] = []
    all_landmines: list[dict] = []
    all_questions: list[dict] = []

    # Manifest entries are canonical for decisions (keyed by evidence.value)
    manifest_by_dep: dict[str, dict] = {}
    for entry in manifest_entries:
        dep = entry.get("evidence", {}).get("value", "")
        if dep:
            manifest_by_dep[dep] = entry
        all_decisions.append(entry)

    # Enrich manifest entries with WHY: from PR descriptions
    for entry in pr_entries:
        if "what" in entry and entry.get("source") == "scan:pr_history":
            why = entry.get("why", "")
            # Check if this corresponds to a manifest dep entry
            dep_name = _extract_dep_from_what(entry.get("what", ""))
            if dep_name and dep_name in manifest_by_dep and why:
                if not manifest_by_dep[dep_name].get("why"):
                    manifest_by_dep[dep_name]["why"] = why
                continue  # absorbed into manifest entry, don't duplicate
            # Novel decision from PR (not in manifest)
            all_decisions.append(entry)
        elif "rejected" in entry:
            all_anti_decisions.append(entry)
        elif "actually" in entry:
            all_landmines.append(entry)
        elif "question" in entry:
            all_questions.append(entry)

    # Add docs decisions (dedup against manifest)
    manifest_whats = {e.get("what", "").lower() for e in all_decisions}
    for entry in docs_entries:
        if entry.get("what", "").lower() not in manifest_whats:
            all_decisions.append(entry)
            manifest_whats.add(entry.get("what", "").lower())

    # Add comment landmines
    all_landmines.extend(comment_entries)

    # ── Phase 3: confidence filter ────────────────────────────────────────────

    if not exhaustive:
        all_decisions    = [e for e in all_decisions    if e.get("confidence") == "high"]
        all_anti_decisions = [e for e in all_anti_decisions if e.get("confidence") == "high"]
        all_landmines    = [e for e in all_landmines    if e.get("confidence") == "high"]
        all_questions    = [e for e in all_questions    if e.get("confidence") == "high"]

    # ── Phase 4: dedup against existing entries in BATON.md ──────────────────

    existing_whats = {
        str(e.get("what") or "").lower()
        for e in (doc.data.get("decisions") or [])
        if isinstance(e, dict)
    }
    existing_rejected = {
        str(e.get("rejected") or "").lower()
        for e in (doc.data.get("anti_decisions") or [])
        if isinstance(e, dict)
    }
    existing_locations = {
        str(e.get("location") or "")
        for e in (doc.data.get("landmines") or [])
        if isinstance(e, dict)
    }
    existing_actuallys = {
        str(e.get("actually") or "").lower()
        for e in (doc.data.get("landmines") or [])
        if isinstance(e, dict)
    }
    existing_questions = {
        str(e.get("question") or "").lower()
        for e in (doc.data.get("open_questions") or [])
        if isinstance(e, dict)
    }

    new_decisions    = _dedup_decisions(all_decisions, existing_whats)
    new_anti         = _dedup_anti(all_anti_decisions, existing_rejected)
    new_landmines    = _dedup_landmines(all_landmines, existing_locations, existing_actuallys)
    new_questions    = _dedup_questions(all_questions, existing_questions)

    # ── Phase 5: assign IDs and append ───────────────────────────────────────
    # Use `is not None` (not `or []`) to avoid disconnecting a live ruamel
    # CommentedSeq: an empty CommentedSeq is falsy, so `or []` would bind a
    # disconnected plain list and doc.save() would silently write an empty section.

    decisions_list = doc.data.get("decisions")
    if decisions_list is None:
        doc.data["decisions"] = decisions_list = []

    anti_list = doc.data.get("anti_decisions")
    if anti_list is None:
        doc.data["anti_decisions"] = anti_list = []

    landmines_list = doc.data.get("landmines")
    if landmines_list is None:
        doc.data["landmines"] = landmines_list = []

    questions_list = doc.data.get("open_questions")
    if questions_list is None:
        doc.data["open_questions"] = questions_list = []

    for entry in new_decisions:
        new_id = _next_id(decisions_list, "d")
        entry["id"] = new_id
        decisions_list.append(entry)

    for entry in new_anti:
        new_id = _next_id(anti_list, "a")
        entry["id"] = new_id
        anti_list.append(entry)

    for entry in new_landmines:
        new_id = _next_id(landmines_list, "l")
        entry["id"] = new_id
        landmines_list.append(entry)

    for entry in new_questions:
        new_id = _next_id(questions_list, "q")
        entry["id"] = new_id
        questions_list.append(entry)

    # ── Phase 6: save ────────────────────────────────────────────────────────

    total_new = len(new_decisions) + len(new_anti) + len(new_landmines) + len(new_questions)

    if total_new == 0:
        console.print("\n[dim]No new entries found (all already in BATON.md).[/dim]", markup=True)
        return True

    try:
        doc.save()
    except Exception as exc:
        console.print(f"[red]Error saving BATON.md:[/red] {exc}", markup=True)
        return False

    # ── Summary table ─────────────────────────────────────────────────────────

    needs_review = sum(
        1 for lst in (new_decisions, new_anti, new_landmines, new_questions)
        for e in lst
        if e.get("confidence") != "high" or e.get("source") != "scan:manifest"
    )

    console.print()
    _print_summary(
        decisions=len(new_decisions),
        anti_decisions=len(new_anti),
        landmines=len(new_landmines),
        questions=len(new_questions),
        pr_note=pr_note,
        needs_review=needs_review,
    )
    return True


# ── Internal helpers ──────────────────────────────────────────────────────────


def _next_id(seq, prefix: str) -> str:
    """Compute the next zero-padded id for *seq* entries with an ``id`` field."""
    import re as _re
    pattern = _re.compile(r"^" + _re.escape(prefix) + r"(\d+)$", _re.IGNORECASE)
    max_n = 0
    for entry in seq:
        if isinstance(entry, dict):
            raw = str(entry.get("id") or "")
            m = pattern.match(raw)
            if m:
                max_n = max(max_n, int(m.group(1)))
    return f"{prefix}{max_n + 1:03d}"


def _extract_dep_from_what(what: str) -> str:
    """Extract dep name from 'Uses <dep>' text (normalised lowercase)."""
    m = re.match(r"(?i)uses?\s+(.+)", what.strip())
    if m:
        return m.group(1).strip().lower().replace("_", "-")
    return ""


def _dedup_decisions(entries: list[dict], existing_whats: set[str]) -> list[dict]:
    """Return entries not already in existing_whats; dedup within new entries too."""
    seen: set[str] = set(existing_whats)
    result: list[dict] = []
    for e in entries:
        key = str(e.get("what") or "").lower()
        if key and key not in seen:
            result.append(e)
            seen.add(key)
    return result


def _dedup_anti(entries: list[dict], existing_rejected: set[str]) -> list[dict]:
    seen: set[str] = set(existing_rejected)
    result: list[dict] = []
    for e in entries:
        key = str(e.get("rejected") or "").lower()
        if key and key not in seen:
            result.append(e)
            seen.add(key)
    return result


def _dedup_landmines(
    entries: list[dict],
    existing_locations: set[str],
    existing_actuallys: set[str],
) -> list[dict]:
    seen_locs: set[str] = set(existing_locations)
    seen_acts: set[str] = set(existing_actuallys)
    result: list[dict] = []
    for e in entries:
        loc = str(e.get("location") or "")
        act = str(e.get("actually") or "").lower()
        if loc and loc in seen_locs:
            continue
        if act and act in seen_acts:
            continue
        result.append(e)
        if loc:
            seen_locs.add(loc)
        if act:
            seen_acts.add(act)
    return result


def _dedup_questions(entries: list[dict], existing_questions: set[str]) -> list[dict]:
    seen: set[str] = set(existing_questions)
    result: list[dict] = []
    for e in entries:
        key = str(e.get("question") or "").lower()
        if key and key not in seen:
            result.append(e)
            seen.add(key)
    return result


def _print_summary(
    decisions: int,
    anti_decisions: int,
    landmines: int,
    questions: int,
    pr_note: str,
    needs_review: int,
) -> None:
    """Print the scan summary table."""
    total = decisions + anti_decisions + landmines + questions

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("label", style="dim", width=36)
    table.add_column("count", justify="right", width=6)
    table.add_column("note", style="dim")

    if decisions:
        table.add_row("decisions drafted", str(decisions), "[high confidence]")
    if anti_decisions:
        table.add_row("anti-decisions drafted", str(anti_decisions), "[mixed]")
    if landmines:
        table.add_row("landmines drafted", str(landmines), "[high confidence]")
    if questions:
        table.add_row("open questions drafted", str(questions), "[mixed]")

    table.add_row("", "", "")
    table.add_row("Total drafted", str(total), "")
    if needs_review:
        table.add_row("Needs your input", str(needs_review), "")

    console.print(table)
    console.print()
    console.print(
        "Run [bold cyan]baton review[/bold cyan] to walk through pending entries, "
        "or open BATON.md directly.",
        markup=True,
    )
    if pr_note.startswith("skipped"):
        console.print(f"[dim]PR history: {pr_note}[/dim]", markup=True)
    console.print()
