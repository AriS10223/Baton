"""
staleness.py -- Shared staleness detection for ``baton health`` and ``baton trim``.

Pure module: no I/O, no git, no YAML writes.  Imports schema + supersede.

Public API:
    Finding         -- dict shape: {type, severity, detail, entry_ids, token_cost}
    PrunableEntry   -- dataclass: {type_key, entry, reason, priority, token_cost}

Predicates:
    parse_date(s)                -> date | None
    question_age_days(entry, today) -> int | None
    is_stale_question(entry, today, max_age_days) -> bool
    chain_depth(data, head_id)   -> int  (head-inclusive)
    chain_heads(data)            -> list[str]

Detectors (each -> list[Finding]):
    detect_superseded_present(data, *, model=None) -> list[Finding]
    detect_resolved_landmines(data, *, model=None) -> list[Finding]
    detect_stale_decisions(data, *, model=None)    -> list[Finding]
    detect_stale_questions(data, today, max_age, *, model=None) -> list[Finding]
    detect_resolved_questions_present(data, *, model=None) -> list[Finding]
    detect_compressible_chains(data, min_depth, *, model=None) -> list[Finding]
    detect_missing_evidence(data)                  -> list[Finding]
    detect_idless_landmines(data)                  -> list[Finding]
    entry_counts(data)                             -> Finding

Orchestrators:
    collect_findings(data, config, today, *, model=None) -> list[Finding]
    collect_prunable(data, config, today, *, model=None) -> list[PrunableEntry]
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from .schema import (
    SUPERSEDABLE_TYPES,
    VALID_QUESTION_STATUSES,
    active_entries,
)
from .supersede import (
    chain_backward,
    derive_status,
    entries_for,
    superseded_by_map,
)
from .tokens import count_entry_tokens

# ── Finding type constants ─────────────────────────────────────────────────────

SUPERSEDED_PRESENT          = "superseded_present"
RESOLVED_LANDMINE           = "resolved_landmine"
POSSIBLY_RESOLVED_LANDMINE  = "possibly_resolved_landmine"
STALE_DECISION              = "stale_decision"
STALE_QUESTION              = "stale_question"
RESOLVED_QUESTION_PRESENT   = "resolved_question_present"
COMPRESSIBLE_CHAIN          = "compressible_chain"
DECISION_MISSING_EVIDENCE   = "decision_missing_evidence"
IDLESS_LANDMINE             = "idless_landmine"
ENTRY_COUNTS                = "entry_counts"


def _make_finding(
    type_: str,
    severity: str,
    detail: str,
    entry_ids: list[str],
    token_cost: int,
) -> dict:
    """Construct a finding dict."""
    return {
        "type":      type_,
        "severity":  severity,  # info | warn | error
        "detail":    detail,
        "entry_ids": entry_ids,
        "token_cost": token_cost,
    }


# ── Shared predicates ─────────────────────────────────────────────────────────


def parse_date(s: Any) -> datetime.date | None:
    """Parse a 'YYYY-MM-DD' string into a date.  Returns None on failure."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.date.fromisoformat(s.strip())
    except (ValueError, AttributeError):
        return None


def question_age_days(
    entry: dict,
    today: datetime.date,
) -> int | None:
    """Return age in days from entry['raised'] to *today*.  None if unparseable."""
    raised = parse_date(entry.get("raised"))
    if raised is None:
        return None
    return (today - raised).days


def is_stale_question(
    entry: dict,
    today: datetime.date,
    max_age_days: int,
) -> bool:
    """Return True if the question is open and older than *max_age_days*."""
    if entry.get("status", "open") not in ("open", ""):
        return False
    age = question_age_days(entry, today)
    if age is None:
        return False
    return age > max_age_days


def chain_depth(data: dict, head_id: str) -> int:
    """Return the head-inclusive depth of the supersession chain ending at *head_id*.

    depth = 1 + max(len(branch) for branch in chain_backward(...))
    Minimum depth is 1 (an entry with no ancestors).
    """
    branches = chain_backward(data, head_id)
    if not branches:
        return 1
    return 1 + max(len(b) for b in branches)


def chain_heads(data: dict) -> list[str]:
    """Return ids of active entries that are the head of a supersession chain.

    A "head" is an active entry that itself has a non-empty ``supersedes`` list
    (i.e. it supersedes at least one predecessor).
    """
    heads: list[str] = []
    for type_key in SUPERSEDABLE_TYPES:
        for entry in entries_for(data, type_key):
            if not isinstance(entry, dict):
                continue
            eid = entry.get("id")
            if not eid:
                continue
            # Must be the current head (not itself superseded by anyone)
            if derive_status(data, eid) != "active":
                continue
            # Must have predecessors
            supersedes = entry.get("supersedes")
            if isinstance(supersedes, list) and supersedes:
                heads.append(eid)
    return heads


# ── Detectors ─────────────────────────────────────────────────────────────────


def detect_superseded_present(
    data: dict,
    *,
    model: str | None = None,
) -> list[dict]:
    """Find entries that are superseded but still present in the active lists.

    These do not affect drift/sync/score (only active_entries are used there),
    but they consume tokens in every BATON.md write.
    """
    findings: list[dict] = []
    sb_map = superseded_by_map(data)
    if not sb_map:
        return findings

    ids: list[str] = []
    total_cost = 0
    for type_key in SUPERSEDABLE_TYPES:
        for entry in entries_for(data, type_key):
            if not isinstance(entry, dict):
                continue
            eid = entry.get("id")
            if eid and eid in sb_map:
                ids.append(eid)
                total_cost += count_entry_tokens(entry, model=model)

    if ids:
        findings.append(_make_finding(
            SUPERSEDED_PRESENT,
            severity="warn",
            detail=(
                f"{len(ids)} superseded {'entry' if len(ids) == 1 else 'entries'} "
                f"still present in active lists (~{total_cost} tokens). "
                "Run: baton trim --compress"
            ),
            entry_ids=ids,
            token_cost=total_cost,
        ))
    return findings


def detect_resolved_landmines(
    data: dict,
    *,
    model: str | None = None,
) -> list[dict]:
    """Find landmines with status confirmed_resolved (warn) or possibly_resolved (info)."""
    findings: list[dict] = []
    landmines = data.get("landmines")
    if not isinstance(landmines, list):
        return findings

    confirmed_ids: list[str] = []
    confirmed_cost = 0
    possible_ids: list[str] = []
    possible_cost = 0

    for entry in landmines:
        if not isinstance(entry, dict):
            continue
        status = entry.get("status", "")
        eid = entry.get("id", "")
        cost = count_entry_tokens(entry, model=model)
        if status == "confirmed_resolved":
            confirmed_ids.append(eid)
            confirmed_cost += cost
        elif status == "possibly_resolved":
            possible_ids.append(eid)
            possible_cost += cost

    if confirmed_ids:
        findings.append(_make_finding(
            RESOLVED_LANDMINE,
            severity="warn",
            detail=(
                f"{len(confirmed_ids)} confirmed-resolved "
                f"{'landmine' if len(confirmed_ids) == 1 else 'landmines'} "
                f"(~{confirmed_cost} tokens). Safe to trim."
            ),
            entry_ids=confirmed_ids,
            token_cost=confirmed_cost,
        ))
    if possible_ids:
        findings.append(_make_finding(
            POSSIBLY_RESOLVED_LANDMINE,
            severity="info",
            detail=(
                f"{len(possible_ids)} possibly-resolved "
                f"{'landmine' if len(possible_ids) == 1 else 'landmines'} "
                f"(~{possible_cost} tokens). "
                "Confirm resolution before trimming."
            ),
            entry_ids=possible_ids,
            token_cost=possible_cost,
        ))
    return findings


def detect_stale_decisions(
    data: dict,
    *,
    model: str | None = None,
) -> list[dict]:
    """Find decisions with status 'stale' or 'contradicted'."""
    findings: list[dict] = []
    decisions = data.get("decisions")
    if not isinstance(decisions, list):
        return findings

    stale_ids: list[str] = []
    stale_cost = 0
    for entry in active_entries(decisions):
        if not isinstance(entry, dict):
            continue
        status = entry.get("status", "")
        if status in ("stale", "contradicted"):
            stale_ids.append(entry.get("id", ""))
            stale_cost += count_entry_tokens(entry, model=model)

    if stale_ids:
        findings.append(_make_finding(
            STALE_DECISION,
            severity="warn",
            detail=(
                f"{len(stale_ids)} stale/contradicted "
                f"{'decision' if len(stale_ids) == 1 else 'decisions'} "
                f"(~{stale_cost} tokens)."
            ),
            entry_ids=stale_ids,
            token_cost=stale_cost,
        ))
    return findings


def detect_stale_questions(
    data: dict,
    today: datetime.date,
    max_age_days: int,
    *,
    model: str | None = None,
) -> list[dict]:
    """Find open questions older than *max_age_days*."""
    findings: list[dict] = []
    questions = data.get("open_questions")
    if not isinstance(questions, list):
        return findings

    stale_ids: list[str] = []
    stale_cost = 0
    for entry in questions:
        if not isinstance(entry, dict):
            continue
        if is_stale_question(entry, today, max_age_days):
            stale_ids.append(entry.get("id", ""))
            stale_cost += count_entry_tokens(entry, model=model)

    if stale_ids:
        findings.append(_make_finding(
            STALE_QUESTION,
            severity="warn",
            detail=(
                f"{len(stale_ids)} open "
                f"{'question' if len(stale_ids) == 1 else 'questions'} "
                f"older than {max_age_days} days (~{stale_cost} tokens)."
            ),
            entry_ids=stale_ids,
            token_cost=stale_cost,
        ))
    return findings


def detect_resolved_questions_present(
    data: dict,
    *,
    model: str | None = None,
) -> list[dict]:
    """Find resolved open_questions still present (safe to trim)."""
    findings: list[dict] = []
    questions = data.get("open_questions")
    if not isinstance(questions, list):
        return findings

    resolved_ids: list[str] = []
    resolved_cost = 0
    for entry in questions:
        if not isinstance(entry, dict):
            continue
        if entry.get("status") == "resolved":
            resolved_ids.append(entry.get("id", ""))
            resolved_cost += count_entry_tokens(entry, model=model)

    if resolved_ids:
        findings.append(_make_finding(
            RESOLVED_QUESTION_PRESENT,
            severity="info",
            detail=(
                f"{len(resolved_ids)} resolved "
                f"{'question' if len(resolved_ids) == 1 else 'questions'} "
                f"still present (~{resolved_cost} tokens). Safe to trim."
            ),
            entry_ids=resolved_ids,
            token_cost=resolved_cost,
        ))
    return findings


def detect_compressible_chains(
    data: dict,
    min_depth: int,
    *,
    model: str | None = None,
) -> list[dict]:
    """Find supersession chain heads with depth >= *min_depth*."""
    findings: list[dict] = []
    heads = chain_heads(data)
    compressible: list[str] = []
    total_cost = 0

    for head_id in heads:
        depth = chain_depth(data, head_id)
        if depth >= min_depth:
            compressible.append(head_id)
            # Count the ancestor entries (all but the head)
            branches = chain_backward(data, head_id)
            seen: set[str] = set()
            for branch in branches:
                for entry in branch:
                    eid = entry.get("id") if isinstance(entry, dict) else None
                    if eid and eid not in seen:
                        seen.add(eid)
                        total_cost += count_entry_tokens(entry, model=model)

    if compressible:
        findings.append(_make_finding(
            COMPRESSIBLE_CHAIN,
            severity="info",
            detail=(
                f"{len(compressible)} supersession "
                f"{'chain' if len(compressible) == 1 else 'chains'} "
                f"with depth >= {min_depth} (~{total_cost} tokens in ancestors). "
                "Run: baton trim --compress"
            ),
            entry_ids=compressible,
            token_cost=total_cost,
        ))
    return findings


def detect_missing_evidence(data: dict) -> list[dict]:
    """Find decisions without an ``evidence`` field (not drift-checkable).

    Severity is info only -- these are not wrong, just unmonitored by drift.
    """
    decisions = data.get("decisions")
    if not isinstance(decisions, list):
        return []

    missing_ids: list[str] = []
    for entry in active_entries(decisions):
        if not isinstance(entry, dict):
            continue
        # Skip superseded entries (derive_status check is expensive; skip for this info-only check)
        if not entry.get("evidence"):
            missing_ids.append(entry.get("id", ""))

    if missing_ids:
        return [_make_finding(
            DECISION_MISSING_EVIDENCE,
            severity="info",
            detail=(
                f"{len(missing_ids)} "
                f"{'decision' if len(missing_ids) == 1 else 'decisions'} "
                "without an evidence field (not drift-checkable)."
            ),
            entry_ids=missing_ids,
            token_cost=0,
        )]
    return []


def detect_idless_landmines(data: dict) -> list[dict]:
    """Find landmines with no ``id`` field.

    Id-less landmines cannot be superseded or drift-matched.  Informational only.
    """
    landmines = data.get("landmines")
    if not isinstance(landmines, list):
        return []

    count = 0
    for entry in landmines:
        if isinstance(entry, dict) and not entry.get("id"):
            count += 1

    if count:
        return [_make_finding(
            IDLESS_LANDMINE,
            severity="info",
            detail=(
                f"{count} {'landmine' if count == 1 else 'landmines'} "
                "without an id field (cannot be superseded or drift-matched)."
            ),
            entry_ids=[],
            token_cost=0,
        )]
    return []


def entry_counts(data: dict) -> dict:
    """Return a summary finding with entry counts by type.

    Always severity='info'.
    """
    counts: dict[str, int] = {}
    for key in ("decisions", "anti_decisions", "landmines", "open_questions"):
        raw = data.get(key)
        lst = active_entries(raw) if isinstance(raw, list) else []
        counts[key] = len(lst)

    total = sum(counts.values())
    detail = (
        f"decisions={counts['decisions']} "
        f"anti_decisions={counts['anti_decisions']} "
        f"landmines={counts['landmines']} "
        f"open_questions={counts['open_questions']} "
        f"(total={total} active entries)"
    )
    return _make_finding(
        ENTRY_COUNTS,
        severity="info",
        detail=detail,
        entry_ids=[],
        token_cost=0,
    )


# ── Orchestrators ─────────────────────────────────────────────────────────────


def collect_findings(
    data: dict,
    config: Any,  # BatonConfig -- imported lazily to avoid circular deps
    today: datetime.date,
    *,
    model: str | None = None,
) -> list[dict]:
    """Run all detectors and return a combined finding list.

    Order: entry_counts first (info), then warn/error findings, then remaining info.
    """
    findings: list[dict] = []

    findings.append(entry_counts(data))
    findings.extend(detect_superseded_present(data, model=model))
    findings.extend(detect_resolved_landmines(data, model=model))
    findings.extend(detect_stale_decisions(data, model=model))
    findings.extend(detect_stale_questions(
        data, today,
        max_age_days=getattr(config, "staleness_question_days", 30),
        model=model,
    ))
    findings.extend(detect_resolved_questions_present(data, model=model))
    findings.extend(detect_compressible_chains(
        data,
        min_depth=getattr(config, "compress_min_depth", 3),
        model=model,
    ))
    findings.extend(detect_missing_evidence(data))
    findings.extend(detect_idless_landmines(data))

    return findings


# ── Prunable entry dataclass + collector ──────────────────────────────────────

@dataclass
class PrunableEntry:
    """A single entry that baton trim can delete."""
    type_key:   str
    entry:      dict   = field(repr=False)  # live ruamel CommentedMap ref
    reason:     str    = ""
    priority:   int    = 99   # lower = more expendable
    token_cost: int    = 0


def collect_prunable(
    data: dict,
    config: Any,
    today: datetime.date,
    *,
    model: str | None = None,
) -> list[PrunableEntry]:
    """Return entries eligible for deletion by baton trim, ordered by priority.

    Priority tiers (most expendable first):
      1 -- resolved open_questions
      2 -- confirmed_resolved landmines
      3 -- stale open_questions (open, age > threshold)
      4 -- stale/contradicted decisions
      5 -- possibly_resolved landmines

    Superseded ancestors are EXCLUDED (only --compress removes those).
    Ties broken by descending token_cost.
    """
    prunable: list[PrunableEntry] = []
    max_age = getattr(config, "staleness_question_days", 30)

    # 1. Resolved open_questions
    questions = data.get("open_questions")
    if isinstance(questions, list):
        for entry in questions:
            if not isinstance(entry, dict):
                continue
            if entry.get("status") == "resolved":
                prunable.append(PrunableEntry(
                    type_key="open_questions",
                    entry=entry,
                    reason="resolved question",
                    priority=1,
                    token_cost=count_entry_tokens(entry, model=model),
                ))

    # 2. Confirmed-resolved landmines
    landmines = data.get("landmines")
    if isinstance(landmines, list):
        for entry in landmines:
            if not isinstance(entry, dict):
                continue
            if entry.get("status") == "confirmed_resolved":
                prunable.append(PrunableEntry(
                    type_key="landmines",
                    entry=entry,
                    reason="confirmed_resolved landmine",
                    priority=2,
                    token_cost=count_entry_tokens(entry, model=model),
                ))

    # 3. Stale open_questions (open, age > threshold)
    if isinstance(questions, list):
        for entry in questions:
            if not isinstance(entry, dict):
                continue
            if is_stale_question(entry, today, max_age):
                # Don't double-add already-resolved ones
                if entry.get("status") != "resolved":
                    prunable.append(PrunableEntry(
                        type_key="open_questions",
                        entry=entry,
                        reason=f"open question older than {max_age} days",
                        priority=3,
                        token_cost=count_entry_tokens(entry, model=model),
                    ))

    # 4. Stale/contradicted decisions (active, not superseded)
    decisions = data.get("decisions")
    if isinstance(decisions, list):
        for entry in active_entries(decisions):
            if not isinstance(entry, dict):
                continue
            status = entry.get("status", "")
            if status in ("stale", "contradicted"):
                prunable.append(PrunableEntry(
                    type_key="decisions",
                    entry=entry,
                    reason=f"decision status={status}",
                    priority=4,
                    token_cost=count_entry_tokens(entry, model=model),
                ))

    # 5. Possibly-resolved landmines
    if isinstance(landmines, list):
        for entry in landmines:
            if not isinstance(entry, dict):
                continue
            if entry.get("status") == "possibly_resolved":
                prunable.append(PrunableEntry(
                    type_key="landmines",
                    entry=entry,
                    reason="possibly_resolved landmine (needs confirmation)",
                    priority=5,
                    token_cost=count_entry_tokens(entry, model=model),
                ))

    # Sort: priority asc, then token_cost desc (most tokens first within tier)
    prunable.sort(key=lambda p: (p.priority, -p.token_cost))
    return prunable
