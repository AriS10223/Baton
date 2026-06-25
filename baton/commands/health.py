"""
health.py -- ``baton health``: BATON.md token-budget + staleness diagnostic.

Read-only: never writes BATON.md or any source file.

Public API:
    run_health(repo_root, *, fmt="human", model=None) -> int

Exit codes:
    0 -- no issues, or only warn/info-severity issues
    1 -- token count exceeds the ERROR threshold (configurable in .baton.toml)
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

from rich.console import Console

from ..core.config import BatonConfig
from ..core.document import BatonDocument, BatonDocumentError
from ..core.healthfmt import render_github, render_human, render_json
from ..core.staleness import ENTRY_COUNTS, collect_findings
from ..core.tokens import count_tokens

_console = Console(highlight=False)


def run_health(
    repo_root: Path,
    *,
    fmt: str = "human",
    model: str | None = None,
) -> int:
    """Run the BATON.md health diagnostic.

    Args:
        repo_root: Project root (where BATON.md lives).
        fmt:       Output format: "human" (default), "json", or "github".
        model:     Optional tiktoken model/encoding name for token counting.

    Returns:
        0 when token budget is OK or WARN.
        1 when token budget exceeds the ERROR threshold.
    """
    # 1. Load BATON.md (read-only, mirror check.py:80-86)
    baton_path = repo_root / "BATON.md"
    try:
        doc = BatonDocument.load(baton_path)
        data = doc.data
    except BatonDocumentError as exc:
        _console.print(f"[health] Error loading BATON.md: {exc}", markup=False)
        return 1

    raw_text = baton_path.read_text(encoding="utf-8")

    # 2. Count tokens over the full raw text (canonical, adapter-neutral)
    total, method = count_tokens(raw_text, model=model)

    # 3. Load config + thresholds
    config = BatonConfig.load(repo_root)
    warn_t  = getattr(config, "token_warn",  4000)
    error_t = getattr(config, "token_error", 8000)

    # 4. Determine token status
    if total > error_t:
        token_status = "error"
    elif total > warn_t:
        token_status = "warn"
    else:
        token_status = "ok"

    # 5. Collect all staleness findings
    today = datetime.date.today()
    findings = collect_findings(data, config, today, model=model)

    # 6. Extract counts from the entry_counts finding
    counts_finding = next((f for f in findings if f.get("type") == ENTRY_COUNTS), None)
    counts: dict[str, int] = {}
    if counts_finding:
        detail = counts_finding.get("detail", "")
        # Parse counts from detail string for the JSON envelope
        for key in ("decisions", "anti_decisions", "landmines", "open_questions"):
            import re
            m = re.search(rf"{key}=(\d+)", detail)
            counts[key] = int(m.group(1)) if m else 0

    # 7. Build envelope
    result = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_tokens":  total,
        "token_method":  method,
        "thresholds":    {"warn": warn_t, "error": error_t},
        "token_status":  token_status,
        "counts":        counts,
        "findings":      findings,
    }

    # 8. Dispatch to renderer
    if fmt == "json":
        render_json(result)
    elif fmt == "github":
        render_github(result)
    else:
        render_human(result, _console)

    # 9. Exit code: 1 only on ERROR token status (staleness never changes exit)
    return 1 if token_status == "error" else 0
