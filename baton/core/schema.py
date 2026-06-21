"""
schema.py — Single source of truth for BATON.md structure and scoring.

All section definitions, field requirements, and score checks live here.
- ``score.py`` imports ``SCORE_CHECKS``.
- ``document.py`` imports ``TOP_LEVEL_KEYS`` for validation.

This prevents scoring logic from drifting from the actual schema.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

# ── Constants ─────────────────────────────────────────────────────────────────

BATON_SCHEMA_VERSION = "1.0"

VALID_STAGES = {"idea", "prototype", "mvp", "production"}
VALID_TOOLS = {"claude-code", "cursor", "codex", "gemini", "copilot", ""}
VALID_QUESTION_STATUSES = {"open", "discussed", "resolved"}

# ── Drift detection constants (baton check --drift) ───────────────────────────

EVIDENCE_TYPES    = frozenset({"dependency", "file", "config_key"})
PATTERN_TYPES     = frozenset({"regex", "import", "dependency"})
ANTI_SEVERITIES   = frozenset({"warn", "block"})
DECISION_STATUSES = frozenset({"active", "stale", "contradicted"})
LANDMINE_STATUSES = frozenset({"open", "touched", "possibly_resolved", "confirmed_resolved"})
# Maps severity string -> rank integer for --fail-on gating (higher = worse)
ALERT_SEVERITY_RANK: dict[str, int] = {"warn": 1, "block": 2}

# ── Supersession constants ────────────────────────────────────────────────────
# The three entry types that support supersession chains.
# prefix  - id prefix character used for new entries
# text    - primary human-readable text field (used for overlap detection)
# date    - date field used to sort appendix bullets (None for landmines)
SUPERSEDABLE_TYPES: dict[str, dict] = {
    "decisions":      {"prefix": "d", "text": "what",     "date": "made"},
    "anti_decisions": {"prefix": "a", "text": "rejected", "date": "ruled_out"},
    "landmines":      {"prefix": "l", "text": "actually", "date": None},
}

# Top-level keys expected in the BATON.md YAML block.
# Used by document.py to warn about unrecognised keys.
TOP_LEVEL_KEYS = frozenset({
    "baton_version",
    "last_updated",
    "last_session_tool",
    "project",
    "architecture",
    "stack",
    "laws",
    "current_sprint",
    "decisions",
    "anti_decisions",
    "landmines",
    "open_questions",
    "sessions",
})


# ── Score check dataclass ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScoreCheck:
    """A single scoring criterion used by ``baton score``."""
    id: str
    label: str            # Displayed in output, e.g. "project.purpose"
    points: int           # Full points when status == "pass"
    warn_points: int      # Partial points when status == "warn"
    severity: Literal["required", "recommended"]
    fn: Callable[[dict], tuple[Literal["pass", "warn", "fail"], str, str]]
    # fn returns: (status, detail, tip)
    #   status: "pass" | "warn" | "fail"
    #   detail: short string shown next to label (e.g. "present", "empty")
    #   tip:    actionable suggestion shown when status != "pass"


# ── Helper ────────────────────────────────────────────────────────────────────

def _get(data: dict, *keys, default=None):
    """Safe nested dict read. Returns *default* if any key is missing."""
    v = data
    for k in keys:
        if not isinstance(v, dict):
            return default
        v = v.get(k, default)
    return v if v is not None else default


def feature_label(item) -> str:
    """Return the feature string from a sprint item (dict with 'feature' key or plain string)."""
    if isinstance(item, dict):
        return item.get("feature") or str(item)
    return str(item)


# ── Individual check functions ────────────────────────────────────────────────

def _check_project_purpose(data: dict):
    purpose = _get(data, "project", "purpose", default="")
    if purpose and str(purpose).strip():
        return ("pass", "present", "")
    return ("fail", "empty",
            "Describe what problem this project solves in one sentence.")


def _check_stack_entries(data: dict):
    stack = _get(data, "stack", default=[]) or []
    if stack:
        n = len(stack)
        return ("pass", f"{n} {'entry' if n == 1 else 'entries'}", "")
    return ("fail", "empty",
            "Add at least one stack entry: tool, version, why you chose it.")


def _check_stack_why_version(data: dict):
    stack = _get(data, "stack", default=[]) or []
    if not stack:
        return ("fail", "no stack entries", "Add stack entries first.")
    missing = [
        str(e.get("tool", "?"))
        for e in stack
        if isinstance(e, dict) and (not e.get("why") or not e.get("version"))
    ]
    if not missing:
        return ("pass", "all have why + version", "")
    if len(missing) < len(stack):
        return ("warn",
                f"missing on {len(missing)} of {len(stack)} entries",
                f"Add why + version for: {', '.join(missing)}")
    return ("fail", "all entries missing why or version",
            "Add why + version to every stack entry.")


def _check_stack_gotchas(data: dict):
    stack = _get(data, "stack", default=[]) or []
    if not stack:
        return ("pass", "n/a (no stack entries)", "")
    missing = [
        str(e.get("tool", "?"))
        for e in stack
        if isinstance(e, dict) and not e.get("gotchas")
    ]
    if not missing:
        return ("pass", "all present", "")
    if len(missing) < len(stack):
        return ("warn",
                f"missing on {len(missing)} of {len(stack)} entries",
                f"Add gotchas for: {', '.join(missing)}")
    return ("fail", "all missing",
            "Add gotchas to every stack entry — what breaks if you're not careful?")


def _check_laws(data: dict):
    laws = _get(data, "laws", default=[]) or []
    if laws:
        n = len(laws)
        return ("pass", f"{n} {'entry' if n == 1 else 'entries'}", "")
    return ("fail", "empty",
            "Add at least one law — a hard constraint agents must never violate.")


def _check_decisions(data: dict):
    decisions = _get(data, "decisions", default=[]) or []
    if decisions:
        n = len(decisions)
        return ("pass", f"{n} {'entry' if n == 1 else 'entries'}", "")
    return ("fail", "empty",
            "Capture at least one architectural decision made so far.")


def _check_anti_decisions(data: dict):
    anti = _get(data, "anti_decisions", default=[]) or []
    if anti:
        n = len(anti)
        return ("pass", f"{n} {'entry' if n == 1 else 'entries'}", "")
    return ("fail", "empty — add things you ruled out",
            "Think about what you explicitly decided NOT to do. "
            "Add at least one anti-decision so agents stop re-suggesting it.")


def _check_sprint_goal(data: dict):
    goal = _get(data, "current_sprint", "goal", default="")
    if goal and str(goal).strip():
        return ("pass", "present", "")
    return ("fail", "empty",
            "Set a one-sentence sprint goal so agents know what you're building right now.")


def _check_inprogress_owners(data: dict):
    items = _get(data, "current_sprint", "in_progress", default=[]) or []
    if not items:
        return ("pass", "no in-progress items", "")
    missing = [
        str(i.get("feature", "?"))
        for i in items
        if isinstance(i, dict) and not i.get("owner")
    ]
    if not missing:
        return ("pass", "all have owner", "")
    if len(missing) < len(items):
        return ("warn",
                f"{len(missing)} items missing owner field",
                f"Add owner to: {', '.join(missing)}")
    return ("fail", "all items missing owner",
            "Add an owner to each in-progress item, e.g. 'Aryan on Claude Code'.")


def _check_open_question_statuses(data: dict):
    qs = _get(data, "open_questions", default=[]) or []
    if not qs:
        return ("pass", "no open questions (ok)", "")
    invalid = [
        str(q.get("id", "?"))
        for q in qs
        if isinstance(q, dict) and q.get("status") not in VALID_QUESTION_STATUSES
    ]
    if not invalid:
        n = len(qs)
        return ("pass", f"{n} {'entry' if n == 1 else 'entries'}, statuses correct", "")
    return ("warn",
            f"{len(invalid)} entries have invalid status",
            f"Fix status (must be open/discussed/resolved) for: {', '.join(invalid)}")


def _check_landmines(data: dict):
    landmines = _get(data, "landmines", default=[]) or []
    if landmines:
        n = len(landmines)
        return ("pass", f"{n} {'entry' if n == 1 else 'entries'}", "")
    return ("fail", "empty — any intentional weirdness?",
            "Add landmines for code that looks wrong but is intentional. "
            "Stops agents 'fixing' things that aren't broken.")


def _check_sessions(data: dict):
    sessions = _get(data, "sessions", default=[]) or []
    if sessions:
        n = len(sessions)
        return ("pass", f"{n} {'entry' if n == 1 else 'entries'}", "")
    return ("fail", "no sessions yet",
            "Run `baton end` at the end of a session to capture a summary.")


# ── Score checks list ─────────────────────────────────────────────────────────
# Points column must sum to exactly 100.

SCORE_CHECKS: list[ScoreCheck] = [
    #                          id                       label                   pts  warn  severity
    ScoreCheck("project_purpose",   "project.purpose",           10,  0, "required",    _check_project_purpose),
    ScoreCheck("stack_entries",     "stack (entries)",            5,   0, "required",    _check_stack_entries),
    ScoreCheck("stack_why_version", "stack why + version",       10,  5, "required",    _check_stack_why_version),
    ScoreCheck("stack_gotchas",     "stack gotchas",              5,   2, "recommended", _check_stack_gotchas),
    ScoreCheck("laws",              "laws",                      15,  0, "recommended", _check_laws),
    ScoreCheck("decisions",         "decisions",                 15,  0, "required",    _check_decisions),
    ScoreCheck("anti_decisions",    "anti_decisions",            10,  0, "recommended", _check_anti_decisions),
    ScoreCheck("sprint_goal",       "current_sprint.goal",       10,  0, "required",    _check_sprint_goal),
    ScoreCheck("inprogress_owners", "in_progress owners",         5,   2, "recommended", _check_inprogress_owners),
    ScoreCheck("open_q_statuses",   "open_questions",             5,   2, "recommended", _check_open_question_statuses),
    ScoreCheck("landmines",         "landmines",                  5,   0, "recommended", _check_landmines),
    ScoreCheck("sessions",          "sessions",                   5,   0, "recommended", _check_sessions),
]

# Enforce the invariant at import time — if you change point values, this fails loudly.
assert sum(c.points for c in SCORE_CHECKS) == 100, (
    f"SCORE_CHECKS must total 100 points, got {sum(c.points for c in SCORE_CHECKS)}"
)
