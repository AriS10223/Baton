"""
findings.py -- Reason/suggestion templating for drift alerts.

Provides ``enrich_alerts(alerts, doc_data)`` which adds ``reason``,
``suggestion``, and ``fix_command`` to each alert dict in-place so that
renderers (human, JSON, GitHub) can display actionable output without
re-parsing ``detail``.
"""
from __future__ import annotations

import re

# ── Section / field mappings ──────────────────────────────────────────────────
# Mirror SUPERSEDABLE_TYPES from core/schema.py without importing it here so
# that this module stays dependency-light and testable in isolation.

# alert["type"] -> (doc_data section key, primary text field)
_TYPE_MAP: dict[str, tuple[str, str]] = {
    "anti_decision": ("anti_decisions", "rejected"),
    "decision":      ("decisions",      "what"),
    "landmine":      ("landmines",      "actually"),
}

# Regex for the "no X -- use Y instead" pattern in anti_decision.rejected text.
# Matches: "no <token> -- use <Y>", "no <token> - use <Y>", "no <token>, use <Y>"
_NO_USE_RE = re.compile(r"(?i)no\s+\S.*?[-—,]\s*use\s+(\S+)")


# ── Private template functions ────────────────────────────────────────────────


def _enrich_anti_decision(alert: dict, entry: dict | None) -> None:
    alert_id = alert.get("id", "")
    matched  = alert.get("matched", "")
    file_    = alert.get("file", "")
    line_    = alert.get("line", 0)

    # reason
    if matched:
        alert["reason"] = (
            f"Introduces '{matched}', matching the pattern banned by {alert_id}."
        )
    else:
        alert["reason"] = (
            f"Pattern banned by {alert_id} was matched in {file_}:{line_}."
        )

    # fix_command (same regardless of suggestion shape)
    fix_cmd = (
        f'baton check --drift --acknowledge {alert_id} --reason "<your reason>"'
    )
    alert["fix_command"] = fix_cmd

    if entry is None:
        alert["suggestion"] = ""
        return

    rejected_text = str(entry.get("rejected", "") or "")
    ack_hint = (
        f"If intentional: baton check --drift --acknowledge {alert_id}"
        f' --reason "<your reason>"'
    )

    m = _NO_USE_RE.search(rejected_text)
    if m:
        alt = m.group(1).rstrip(".,;")
        alert["suggestion"] = f"Use {alt} instead. {ack_hint}"
    else:
        alert["suggestion"] = (
            f'anti_decision {alert_id} says: "{rejected_text}". {ack_hint}'
        )


def _enrich_decision(alert: dict, entry: dict | None) -> None:
    alert_id = alert.get("id", "")
    matched  = alert.get("matched", "")

    # reason
    if matched:
        alert["reason"] = (
            f"Decision {alert_id} may be contradicted: '{matched}' was removed."
        )
    else:
        alert["reason"] = alert.get("detail", "")

    # fix_command
    fix_cmd = (
        f'baton supersede {alert_id} --with <new_id> --reason "<why>"'
    )
    alert["fix_command"] = fix_cmd

    if entry is None:
        alert["suggestion"] = ""
        return

    what_text = str(entry.get("what", "") or "")
    alert["suggestion"] = (
        f'Decision {alert_id} says: "{what_text}". '
        f"If this change is intentional, supersede the decision: "
        f'baton supersede {alert_id} --with <new_id> --reason "<why>"'
    )


def _enrich_landmine(alert: dict, entry: dict | None) -> None:
    alert_id = alert.get("id", "")
    matched  = alert.get("matched", "")
    file_    = alert.get("file", "")
    line_    = alert.get("line", 0)
    status   = alert.get("status", "")

    actually_text = ""
    if entry is not None:
        actually_text = str(entry.get("actually", "") or "")

    # reason
    if status == "possibly_resolved":
        base_reason = (
            f"Landmine {alert_id} marker '{matched}' was removed from "
            f"{file_}:{line_} -- may be resolved."
        )
    else:
        # "touched" or anything else
        base_reason = (
            f"Landmine {alert_id} file '{matched}' was modified -- "
            f"verify the landmine is still in place."
        )

    if actually_text:
        alert["reason"] = base_reason + f' (landmine: "{actually_text}")'
    else:
        alert["reason"] = base_reason

    # fix_command
    fix_cmd = f'baton supersede {alert_id} --with <new_id> --reason "<why>"'
    alert["fix_command"] = fix_cmd

    alert["suggestion"] = (
        f"If resolved: baton supersede {alert_id} --with <new_id>"
        f' --reason "<why>". '
        f"If not: review {file_} before merging."
    )


def _enrich_missing(alert: dict) -> None:
    """Fallback when no source entry is found in doc_data."""
    alert["reason"]      = alert.get("detail", "")
    alert["suggestion"]  = ""
    alert["fix_command"] = ""


# ── Public API ────────────────────────────────────────────────────────────────


def enrich_alerts(alerts: list[dict], doc_data: dict) -> list[dict]:
    """Add reason, suggestion, fix_command to each alert in-place.

    Looks up the source BATON.md entry for each alert by ``alert["id"]``
    and calls the appropriate per-type template function.  Returns the
    same list (modified in-place).

    Parameters
    ----------
    alerts:
        List of alert dicts as produced by ``baton/core/drift.py``.
    doc_data:
        Parsed BATON.md YAML data (``BatonDocument.data``).

    Returns
    -------
    The same *alerts* list with ``reason``, ``suggestion``, and
    ``fix_command`` keys added to every element.
    """
    # Build id -> entry index for each supersedable section.
    index: dict[str, dict] = {}
    for section in ("anti_decisions", "decisions", "landmines"):
        for entry in (doc_data.get(section) or []):
            if isinstance(entry, dict) and entry.get("id"):
                index[entry["id"]] = entry

    for alert in alerts:
        alert_type = alert.get("type", "")
        alert_id   = alert.get("id", "")

        entry = index.get(alert_id)  # may be None

        if alert_type == "anti_decision":
            _enrich_anti_decision(alert, entry)
        elif alert_type == "decision":
            _enrich_decision(alert, entry)
        elif alert_type == "landmine":
            _enrich_landmine(alert, entry)
        else:
            _enrich_missing(alert)

        # Guarantee all three keys are always present.
        for key in ("reason", "suggestion", "fix_command"):
            if key not in alert:
                alert[key] = ""

    return alerts
