"""
healthfmt.py -- Output renderers for ``baton health``.

Three public functions consume a health result envelope and produce output:

  render_human(result, console)  -> None   Rich console, ASCII-safe
  render_json(result)            -> None   Plain print(json.dumps(...))
  render_github(result)          -> None   GitHub Actions workflow commands

Result envelope schema (built by commands/health.py):
  {
    generated_at:   str  (ISO 8601 UTC),
    total_tokens:   int,
    token_method:   str  ("tiktoken:<enc>" | "heuristic"),
    thresholds:     {warn: int, error: int},
    token_status:   str  ("ok" | "warn" | "error"),
    counts:         {decisions: int, anti_decisions: int, landmines: int, open_questions: int},
    findings:       list[Finding dict],
  }

GHA escaping helpers are re-exported from checkfmt to avoid divergence.
"""
from __future__ import annotations

import json

from .checkfmt import _escape_data, _escape_property  # noqa: F401 (re-exported)
from .staleness import ENTRY_COUNTS
from .tokens import tiktoken_available, DEFAULT_ENCODING


# ── Human renderer ────────────────────────────────────────────────────────────

_SEVERITY_PREFIX = {
    "error": "[ERROR]",
    "warn":  "[WARN] ",
    "info":  "[INFO] ",
}

_TOKEN_STATUS_LABEL = {
    "ok":    "OK",
    "warn":  "WARN",
    "error": "ERROR",
}


def render_human(result: dict, console) -> None:
    """Print human-readable health output to *console* (Rich Console).

    All output uses ``markup=False`` for ASCII safety (Windows CP1252).
    """
    total       = result.get("total_tokens", 0)
    method      = result.get("token_method", "unknown")
    token_status = result.get("token_status", "ok")
    thresholds  = result.get("thresholds", {})
    warn_t      = thresholds.get("warn", 4000)
    error_t     = thresholds.get("error", 8000)
    findings    = result.get("findings") or []

    status_label = _TOKEN_STATUS_LABEL.get(token_status, token_status.upper())
    console.print(
        f"[health] BATON.md  {total} tokens  [{status_label}]  ({method})",
        markup=False,
    )
    console.print(
        f"         thresholds: warn>{warn_t}  error>{error_t}",
        markup=False,
    )

    # Warn when heuristic is in use
    if method == "heuristic" or (method and method.startswith("heuristic")):
        console.print(
            "[health] [WARN] Token count is approximate (tiktoken not installed). "
            'Install: pip install "baton-pass[tokens]"',
            markup=False,
        )

    console.print("", markup=False)

    # Filter out entry_counts (printed separately as a summary line)
    counts_findings = [f for f in findings if f.get("type") == ENTRY_COUNTS]
    other_findings  = [f for f in findings if f.get("type") != ENTRY_COUNTS]

    if counts_findings:
        console.print(f"         {counts_findings[0].get('detail', '')}", markup=False)
        console.print("", markup=False)

    if other_findings:
        for f in other_findings:
            sev    = f.get("severity", "info")
            prefix = _SEVERITY_PREFIX.get(sev, "[INFO] ")
            detail = f.get("detail", "")
            cost   = f.get("token_cost", 0)
            ids    = f.get("entry_ids") or []
            id_str = f"  ids: {', '.join(str(i) for i in ids)}" if ids else ""
            tok_str = f"  (~{cost} tokens)" if cost else ""
            console.print(
                f"  {prefix} {detail}{tok_str}{id_str}",
                markup=False,
            )
        console.print("", markup=False)
    else:
        console.print("  [INFO]  No staleness issues detected.", markup=False)
        console.print("", markup=False)

    # Footer
    if token_status == "ok" and not any(
        f.get("severity") in ("warn", "error") for f in other_findings
    ):
        console.print("[health] PASS", markup=False)
    elif token_status == "error" or any(
        f.get("severity") == "error" for f in other_findings
    ):
        console.print("[health] FAIL -- run baton trim to reduce token cost", markup=False)
    else:
        console.print("[health] WARN -- consider running baton trim", markup=False)


# ── JSON renderer ─────────────────────────────────────────────────────────────


def render_json(result: dict) -> None:
    """Print the full health result envelope as JSON to stdout."""
    print(json.dumps(result, indent=2))


# ── GitHub Actions renderer ───────────────────────────────────────────────────


def render_github(result: dict) -> None:
    """Print GitHub Actions workflow commands to stdout.

    Emits:
      ::error  when token_status == "error"
      ::warning per warn-severity finding
      info findings are omitted.
    """
    token_status = result.get("token_status", "ok")
    thresholds   = result.get("thresholds", {})
    total        = result.get("total_tokens", 0)
    findings     = result.get("findings") or []

    # One error annotation for exceeding the token budget
    if token_status == "error":
        error_t = thresholds.get("error", 8000)
        msg = (
            f"BATON.md exceeds the {error_t}-token error threshold "
            f"({total} tokens). Run: baton trim"
        )
        print(f"::error::{_escape_data(msg)}")

    # One warning annotation per warn-severity finding
    for f in findings:
        sev = f.get("severity", "info")
        if sev == "error":
            # Already emitted above as a single error; skip per-finding duplication
            continue
        if sev == "warn":
            detail = f.get("detail", "")
            msg = f"baton health: {detail}"
            print(f"::warning::{_escape_data(msg)}")
        # info findings are omitted from GHA output
