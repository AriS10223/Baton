"""
checkfmt.py -- Output renderers for ``baton check --drift``.

Three public functions consume an enriched result envelope and produce output
in three formats:

  render_human(result, console)  -> None   Rich console, ASCII-safe
  render_json(result)            -> None   Plain print(json.dumps(...))
  render_github(result)          -> None   GitHub Actions workflow commands
"""
from __future__ import annotations

import json


# ── GHA escaping helpers ──────────────────────────────────────────────────────


def _escape_property(s: str) -> str:
    """Escape a string for use in a GHA workflow command property value.

    Order matters: replace ``%`` first to avoid double-escaping.
    Escapes: %->%25, \\r->%0D, \\n->%0A, :->%3A, ,->%2C
    """
    s = s.replace("%", "%25")
    s = s.replace("\r", "%0D")
    s = s.replace("\n", "%0A")
    s = s.replace(":", "%3A")
    s = s.replace(",", "%2C")
    return s


def _escape_data(s: str) -> str:
    """Escape a string for use in a GHA workflow command message (data) field.

    Order matters: replace ``%`` first to avoid double-escaping.
    Escapes: %->%25, \\r->%0D, \\n->%0A  (colon and comma are allowed in data)
    """
    s = s.replace("%", "%25")
    s = s.replace("\r", "%0D")
    s = s.replace("\n", "%0A")
    return s


# ── Renderers ─────────────────────────────────────────────────────────────────


def render_human(result: dict, console) -> None:
    """Print human-readable drift output to console (Rich Console object).

    All output uses ``markup=False`` for ASCII safety.
    """
    alerts = result.get("alerts") or []
    n = len(alerts)
    console.print(f"[drift] Reality drift check  ({n} alerts)", markup=False)

    if alerts:
        for a in alerts:
            alert_id = a.get("id", "")
            alert_type = a.get("type", "")
            severity = a.get("severity", "")
            status = a.get("status", "")
            file_ = a.get("file", "")
            line = a.get("line", 0)
            reason = a.get("reason", "")
            suggestion = a.get("suggestion", "")

            console.print(
                f"[{alert_id}] {alert_type}  {severity}  {status}  {file_}:{line}",
                markup=False,
            )
            console.print(f"  {reason}", markup=False)
            if suggestion:
                console.print(f"  {suggestion}", markup=False)

        console.print(
            '[drift] Run: baton check --drift --acknowledge <id> --reason "..." to suppress.',
            markup=False,
        )
    else:
        console.print("[drift] No drift detected.", markup=False)


def render_json(result: dict) -> None:
    """Print JSON envelope to stdout (plain print, not Rich)."""
    print(json.dumps(result, indent=2))


def render_github(result: dict) -> None:
    """Print GitHub Actions workflow commands to stdout (plain print).

    Block severity -> ``::error``; warn severity -> ``::warning``.
    File path uses ``_escape_property``; message uses ``_escape_data``.
    When file is empty and line is 0 the bare form ``::error::msg`` is emitted
    (no ``file=`` / ``line=`` properties).
    """
    alerts = result.get("alerts") or []

    for a in alerts:
        severity = a.get("severity", "warn")
        level = "error" if severity == "block" else "warning"

        file_ = a.get("file", "")
        line = a.get("line", 0)
        alert_id = a.get("id", "")
        reason = a.get("reason", "")
        suggestion = a.get("suggestion", "")

        message = f"{alert_id} -- {reason} Suggestion: {suggestion}"
        esc_message = _escape_data(message)

        if not file_ and not line:
            print(f"::{level}::{esc_message}")
        else:
            esc_file = _escape_property(file_)
            print(f"::{level} file={esc_file},line={line}::{esc_message}")
