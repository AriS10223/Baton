"""
end.py -- ``baton end``: capture the current session into BATON.md.

Three-tier fallback chain (cheapest first, all converge on the same tail):

  heuristic  default   Zero-cost.  Derived from diff stats + commit subjects.
  apply      --apply   Read pre-drafted delta JSON from stdin; fall back to
                       the heuristic on empty / malformed input.
  api        --api     Call the configured LLM provider (requires API key).

Other flags:
  --diff-only  Print the git diff + JSON contract for a host agent; exit 0.
               No writes.  No threshold check.

Shared pipeline tail (heuristic / apply / api all run through this):
  1. Load BATON.md + config.
  2. Resolve git diff (commit-aware, from last session SHA).
  3. --diff-only: print context + spec and return True (no further processing).
  4. Skip if diff is below min_diff_lines and --force is not set.
  5. Produce delta (mode-specific, see above).
  6. Review proposed changes (per-section accept/reject in the terminal).
  7. Merge accepted changes into BATON.md (ruamel round-trip-safe appends).
  8. doc.save() then run_sync() if config.auto_sync is True.

ASCII-only output throughout (Law 6: CP1252-safe console on Windows).
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.rule import Rule

from ..core.config import BatonConfig
from ..core.document import BatonDocument, BatonDocumentError
from ..core.gitdiff import (
    GitError,
    count_changed_lines,
    get_commit_log,
    get_diff,
    head_sha,
    resolve_base_ref,
)
from ..core.heuristic import heuristic_delta
from ..core.schema import feature_label
from ..core.summarizer import JSON_SPEC, build_prompt, parse_delta
from ..core.summarizer import summarize as _default_summarizer

console = Console()

# Type alias for the injectable summarizer seam (DO NOT CHANGE -- test suite
# and the --api path depend on this signature).
SummarizerFn = Callable[[str, str, BatonConfig], str]


# ── Public entry point ────────────────────────────────────────────────────────


def run_end(
    repo_root: Path,
    *,
    force: bool = False,
    since: str | None = None,
    tool: str = "",
    auto_accept: bool = False,
    summarizer: SummarizerFn | None = None,
    mode: str = "heuristic",
    stdin_reader: Callable[[], str] | None = None,
) -> bool:
    """Run baton end.

    Args:
        repo_root:    Project root (where BATON.md lives).
        force:        Bypass the min_diff_lines threshold.
        since:        Override base ref (git SHA or branch) for the diff.
        tool:         AI tool name recorded in the session entry (e.g. 'claude-code').
        auto_accept:  Skip interactive prompts; accept all sections. For tests.
        summarizer:   Injectable LLM seam for the api path. Defaults to the
                      real provider call.  DO NOT REMOVE: tests and the --api
                      path depend on this kwarg.  Passing a non-None value
                      implies mode='api' (backward compatibility).
        mode:         Summary source: 'heuristic' (default, zero-cost),
                      'api' (LLM call, requires API key), 'apply' (read from
                      stdin), or 'diff-only' (print context + spec and exit).
        stdin_reader: Callable returning raw stdin text for '--apply' mode.
                      Defaults to sys.stdin.read().  Injectable for tests.

    Returns:
        True on success (or clean skip), False if an error occurred.
    """
    # -- Mode resolution ------------------------------------------------------
    # Backward compat: an explicit summarizer= injection implies api mode,
    # preserving existing test contracts without any test file changes.
    if summarizer is not None:
        effective_mode = "api"
    elif mode == "api":
        effective_mode = "api"
        summarizer = _default_summarizer
    else:
        effective_mode = mode

    _read_stdin: Callable[[], str] = (
        stdin_reader if stdin_reader is not None else lambda: sys.stdin.read()
    )

    # ── 1. Load BATON.md ──────────────────────────────────────────
    baton_path = repo_root / "BATON.md"
    try:
        doc = BatonDocument.load(baton_path)
    except BatonDocumentError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return False

    config = BatonConfig.load(repo_root)

    # ── 2. Resolve diff ───────────────────────────────────────────
    try:
        sha = head_sha(repo_root)
        base_ref = resolve_base_ref(doc.data, since)
        diff_text = get_diff(repo_root, base_ref)
    except GitError as exc:
        console.print(f"[red]Git error:[/red] {exc}")
        return False

    changed = count_changed_lines(diff_text)

    # ── 3. --diff-only: print context + spec and exit ─────────────
    # No threshold check; the host agent always needs the full context.
    if effective_mode == "diff-only":
        _, user = build_prompt(diff_text, doc.data)
        console.print(user)
        console.print()
        console.print(JSON_SPEC)
        return True

    # ── 4. Threshold check ────────────────────────────────────────
    if changed < config.min_diff_lines and not force:
        console.print(
            f"[yellow]Skipping:[/yellow] only {changed} changed line(s) "
            f"(threshold: {config.min_diff_lines}). "
            "Use [bold]--force[/bold] to override."
        )
        return True

    console.print()
    console.print(Rule("baton end"))
    if base_ref:
        console.print(f"  Diffing from: [dim]{base_ref}[/dim]")
    console.print(f"  Changed lines: [cyan]{changed}[/cyan]")
    console.print()

    # ── 5. Produce delta (mode-specific) ──────────────────────────
    if effective_mode == "api":
        # LLM path -- requires a provider API key.
        console.print("[dim]Calling LLM to summarise session...[/dim]")
        try:
            system, user = build_prompt(diff_text, doc.data)
            raw = summarizer(system, user, config)  # type: ignore[misc]
            delta = parse_delta(raw)
        except ValueError as exc:
            console.print(f"[red]Parse error:[/red] {exc}")
            return False
        except RuntimeError as exc:
            console.print(f"[red]LLM error:[/red] {exc}")
            return False

    elif effective_mode == "apply":
        # Read pre-drafted JSON from stdin; fall back to heuristic on failure.
        delta = _delta_from_stdin(_read_stdin, diff_text, base_ref, repo_root, doc.data)

    else:  # "heuristic" (default)
        # Zero-cost deterministic summary -- no model, no API key.
        console.print("[dim]Heuristic summarizer: no model or API key required.[/dim]")
        commit_log = get_commit_log(repo_root, base_ref)
        delta = heuristic_delta(diff_text, commit_log, doc.data)

    # ── 6. Review ─────────────────────────────────────────────────
    accepted = _review(delta, auto_accept)
    if accepted is None:
        console.print("[yellow]Cancelled. BATON.md unchanged.[/yellow]")
        return True

    # ── 7. Merge ──────────────────────────────────────────────────
    today = datetime.date.today().isoformat()
    _merge_delta(doc.data, accepted, sha, tool, today)

    doc.data["last_updated"] = today
    if tool:
        doc.data["last_session_tool"] = tool

    try:
        doc.save()
    except OSError as exc:
        console.print(f"[red]Error saving BATON.md:[/red] {exc}")
        return False
    console.print("[green]BATON.md updated.[/green]")

    # ── 8. Auto-sync ──────────────────────────────────────────────
    if config.auto_sync:
        from ..commands.sync import run_sync
        if not run_sync(repo_root):
            console.print("[yellow]Warning:[/yellow] auto-sync failed. Run 'baton sync' manually.")

    return True


# ── Apply-from-stdin helper ───────────────────────────────────────────────────


def _delta_from_stdin(
    stdin_reader: Callable[[], str],
    diff_text: str,
    base_ref: str | None,
    repo_root: Path,
    doc_data: dict,
) -> dict:
    """Read a delta JSON from stdin; fall back to the heuristic on any failure.

    Failure cases that trigger the fallback:
    - Empty stdin (no input piped)
    - Malformed or non-JSON content
    - Any I/O error reading stdin

    Prints a plain notice when the fallback fires so the user knows the summary
    was captured at reduced fidelity and can re-run for the full version.
    """
    _FALLBACK_NOTICE = (
        "[yellow]Notice:[/yellow] Captured a structural summary; the richer "
        "summary did not complete. Re-run [bold]baton end[/bold] (or invoke "
        "the skill) once your session resets for the full version."
    )
    try:
        raw = stdin_reader()
        delta = parse_delta(raw)
        console.print("[dim]Applied delta from stdin.[/dim]")
        return delta
    except (ValueError, OSError, EOFError) as exc:
        console.print(f"[yellow]stdin not usable:[/yellow] {exc}")
        console.print(_FALLBACK_NOTICE)
        commit_log = get_commit_log(repo_root, base_ref)
        return heuristic_delta(diff_text, commit_log, doc_data)


# ── Review UI ─────────────────────────────────────────────────────────────────


def _review(delta: dict, auto_accept: bool) -> dict | None:
    """Display the proposed delta and return the accepted subset.

    Returns None if the user cancels entirely.
    When auto_accept is True, skips prompts and accepts everything.

    ASCII-only output (Law 6).
    """
    console.print(Rule("Proposed session update"))

    # -- Session summary
    session = delta["session"]
    console.print(f"\n[bold]Session summary:[/bold]  {session['summary']}")
    if session["highlights"]:
        console.print("[bold]Highlights:[/bold]")
        for h in session["highlights"]:
            console.print(f"  * {h}")

    # -- Sprint done
    sprint_done = delta.get("sprint_done") or []
    console.print()
    if sprint_done:
        console.print("[bold]Sprint items proposed as DONE:[/bold]")
        for item in sprint_done:
            console.print(f"  [green]+[/green] {item}")
    else:
        console.print("[dim]No sprint items proposed as done.[/dim]")

    # -- Sprint next
    sprint_next = delta.get("sprint_next") or []
    if sprint_next:
        console.print()
        console.print("[bold]Sprint items proposed as NEXT:[/bold]")
        for item in sprint_next:
            pri = item.get("priority", "medium")
            console.print(f"  [cyan]+[/cyan] [{pri}] {item['feature']}")

    # -- Curated sections (shown only when present)
    decisions     = delta.get("decisions")     or []
    anti_decisions = delta.get("anti_decisions") or []
    landmines     = delta.get("landmines")     or []
    open_questions = delta.get("open_questions") or []

    if decisions:
        console.print()
        console.print("[bold]Decisions proposed:[/bold]")
        for d in decisions:
            console.print(f"  [yellow]+[/yellow] {d.get('what', '')}")

    if anti_decisions:
        console.print()
        console.print("[bold]Anti-decisions proposed:[/bold]")
        for a in anti_decisions:
            console.print(f"  [yellow]+[/yellow] REJECTED: {a.get('rejected', '')}")

    if landmines:
        console.print()
        console.print("[bold]Landmines proposed:[/bold]")
        for lm in landmines:
            loc = f" (in {lm['location']})" if lm.get("location") else ""
            console.print(f"  [yellow]+[/yellow]{loc} {lm.get('actually', '')}")

    if open_questions:
        console.print()
        console.print("[bold]Open questions proposed:[/bold]")
        for q in open_questions:
            console.print(f"  [yellow]+[/yellow] {q.get('question', '')}")

    console.print()

    if auto_accept:
        console.print("[dim]Auto-accepting all sections (--yes).[/dim]")
        return delta

    # Per-section accept/reject via typer prompts.
    import typer

    try:
        keep_session = typer.confirm("Accept session log entry?", default=True)
        keep_done = False
        if sprint_done:
            keep_done = typer.confirm("Accept sprint-done updates?", default=True)
        keep_next = False
        if sprint_next:
            keep_next = typer.confirm("Accept sprint-next additions?", default=True)
        keep_decisions = False
        if decisions:
            keep_decisions = typer.confirm("Accept proposed decisions?", default=True)
        keep_anti = False
        if anti_decisions:
            keep_anti = typer.confirm("Accept proposed anti-decisions?", default=True)
        keep_landmines = False
        if landmines:
            keep_landmines = typer.confirm("Accept proposed landmines?", default=True)
        keep_questions = False
        if open_questions:
            keep_questions = typer.confirm("Accept proposed open questions?", default=True)
        proceed = typer.confirm("Write to BATON.md?", default=True)
    except typer.Abort:
        return None

    if not proceed:
        return None

    return {
        "session":        delta["session"] if keep_session else None,
        "sprint_done":    sprint_done if keep_done else [],
        "sprint_next":    sprint_next if keep_next else [],
        "decisions":      decisions if keep_decisions else [],
        "anti_decisions": anti_decisions if keep_anti else [],
        "landmines":      landmines if keep_landmines else [],
        "open_questions": open_questions if keep_questions else [],
    }


# ── Merge ─────────────────────────────────────────────────────────────────────


def _append_sprint_items(seq, new_items: list, make_entry) -> None:
    """Append items from *new_items* into *seq*, skipping duplicates by feature label."""
    existing = {feature_label(i) for i in seq}
    for item in new_items:
        label = feature_label(item)
        if label not in existing:
            seq.append(make_entry(item))
            existing.add(label)


def _next_id(seq, prefix: str) -> str:
    """Compute the next zero-padded ID for *seq* entries with an ``id`` field.

    Scans existing entries for IDs matching ``<prefix><digits>`` (e.g. ``d001``),
    tolerates gaps and malformed values, and returns the next sequential ID.
    Always zero-padded to at least 3 digits.

    Examples:
        [] -> "d001"
        [{"id": "d001"}] -> "d002"
        [{"id": "d001"}, {"id": "d003"}] -> "d004"   (gap-tolerant)
    """
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


def _merge_delta(
    data: dict,
    accepted: dict,
    sha: str | None,
    tool: str,
    today: str,
) -> None:
    """Apply the accepted delta to the ruamel CommentedMap *data* in-place.

    Append-only: never modifies existing entries; only appends new ones.
    Plain Python dicts/lists are safe to append into CommentedSeq --
    ruamel serialises them correctly on the next save() call.

    Note: field names are hardcoded here (consistent with the pre-existing
    pattern for sessions/sprint).  Law 2 ("schema.py owns field names") is
    acknowledged; centralising all merge field names in schema.py is a
    worthwhile future refactor but is out of scope here.
    """
    sprint = data.get("current_sprint")

    # ── Sprint done ───────────────────────────────────────────────
    new_done = accepted.get("sprint_done") or []
    if new_done and sprint is not None:
        done_list = sprint.get("done")
        if done_list is not None:
            _append_sprint_items(
                done_list, new_done,
                lambda s: {"feature": s, "confidence": "stable"},
            )

    # ── Sprint next ───────────────────────────────────────────────
    new_next = accepted.get("sprint_next") or []
    if new_next and sprint is not None:
        next_list = sprint.get("next")
        if next_list is not None:
            _append_sprint_items(
                next_list, new_next,
                lambda item: {
                    "feature": feature_label(item),
                    "priority": item.get("priority", "medium") if isinstance(item, dict) else "medium",
                },
            )

    # ── Decisions ─────────────────────────────────────────────────
    new_decisions = accepted.get("decisions") or []
    if new_decisions:
        decisions_list = data.get("decisions")
        if decisions_list is not None:
            existing_whats = {
                str(e.get("what") or "") for e in decisions_list if isinstance(e, dict)
            }
            for d in new_decisions:
                what = str(d.get("what") or "")
                if what and what not in existing_whats:
                    new_id = _next_id(decisions_list, "d")
                    decisions_list.append({
                        "id":      new_id,
                        "what":    what,
                        "why":     str(d.get("why") or ""),
                        "made":    today,
                        "made_in": str(d.get("made_in") or tool or ""),
                    })
                    existing_whats.add(what)

    # ── Anti-decisions ────────────────────────────────────────────
    new_anti = accepted.get("anti_decisions") or []
    if new_anti:
        anti_list = data.get("anti_decisions")
        if anti_list is not None:
            existing_rejected = {
                str(e.get("rejected") or "") for e in anti_list if isinstance(e, dict)
            }
            for a in new_anti:
                rejected = str(a.get("rejected") or "")
                if rejected and rejected not in existing_rejected:
                    new_id = _next_id(anti_list, "a")
                    anti_list.append({
                        "id":         new_id,
                        "rejected":   rejected,
                        "why":        str(a.get("why") or ""),
                        "ruled_out":  today,
                    })
                    existing_rejected.add(rejected)

    # ── Landmines ─────────────────────────────────────────────────
    new_landmines = accepted.get("landmines") or []
    if new_landmines:
        landmines_list = data.get("landmines")
        if landmines_list is not None:
            existing_locations = {
                str(e.get("location") or "") for e in landmines_list if isinstance(e, dict)
            }
            existing_actuallys = {
                str(e.get("actually") or "") for e in landmines_list if isinstance(e, dict)
            }
            for lm in new_landmines:
                location = str(lm.get("location") or "")
                actually = str(lm.get("actually") or "")
                # Dedup by location (if non-empty) or by the actually text.
                dedup_key = location if location else actually
                if dedup_key and (
                    location not in existing_locations or not location
                ) and actually not in existing_actuallys:
                    landmines_list.append({
                        "location":   location,
                        "looks_like": str(lm.get("looks_like") or ""),
                        "actually":   actually,
                    })
                    if location:
                        existing_locations.add(location)
                    existing_actuallys.add(actually)

    # ── Open questions ────────────────────────────────────────────
    new_questions = accepted.get("open_questions") or []
    if new_questions:
        questions_list = data.get("open_questions")
        if questions_list is not None:
            existing_questions = {
                str(e.get("question") or "") for e in questions_list if isinstance(e, dict)
            }
            for q in new_questions:
                question = str(q.get("question") or "")
                if question and question not in existing_questions:
                    new_id = _next_id(questions_list, "q")
                    questions_list.append({
                        "id":       new_id,
                        "question": question,
                        "context":  str(q.get("context") or ""),
                        "status":   str(q.get("status") or "open"),
                    })
                    existing_questions.add(question)

    # ── Session log ───────────────────────────────────────────────
    session_payload = accepted.get("session")
    if session_payload:
        sessions_list = data.get("sessions")
        if sessions_list is not None:
            entry: dict = {
                "date":       today,
                "tool":       tool or "",
                "summary":    session_payload.get("summary") or "",
                "highlights": list(session_payload.get("highlights") or []),
                # commit SHA lets the next baton end diff from this point.
                "commit":     sha or "",
            }
            sessions_list.append(entry)
