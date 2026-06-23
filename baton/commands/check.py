"""
check.py -- Reality-drift detection for ``baton check --drift``.

Orchestrates:
  - Git diff retrieval (HEAD, staged, or since a base ref)
  - Three drift detectors: detect_anti, detect_decisions, detect_landmines
  - Alert I/O: load/save alerts.json, ack.json, last_check_sha
  - Output: human (Rich), json, or github (GHA workflow commands)
  - Exit-code gating via --fail-on threshold
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

from rich.console import Console

from baton.core.alerts import (
    load_acks,
    load_alerts,
    load_last_check_sha,
    save_acks,
    save_alerts,
    save_last_check_sha,
)
from baton.core.checkfmt import render_github, render_human, render_json
from baton.core.document import BatonDocument, BatonDocumentError
from baton.core.drift import detect_anti, detect_decisions, detect_landmines
from baton.core.findings import enrich_alerts
from baton.core.gitdiff import GitError, get_diff, get_staged_diff, head_sha, resolve_since
from baton.core.schema import ALERT_SEVERITY_RANK, active_entries

_console = Console(highlight=False)


def run_check(
    repo_root: Path,
    *,
    since: str | None = None,
    staged: bool = False,
    quiet: bool = False,
    fmt: str = "human",
    fail_on: str = "warn",
    acknowledge: str | None = None,
    reason: str | None = None,
) -> int:
    """Run reality-drift detection and return the appropriate exit code.

    Returns:
        0  -- no alerts at or above the --fail-on threshold
        1  -- warn-level alerts present (and fail_on == "warn")
        2  -- block-level alerts present
    """
    # ── Acknowledge path (runs before detection) ───────────────────────────────
    if acknowledge is not None:
        if not reason:
            _console.print("[drift] --reason is required with --acknowledge", markup=False)
            return 1
        acks = load_acks(repo_root)
        acks.append({
            "id": acknowledge,
            "reason": reason,
            "sha": head_sha(repo_root) or "",
            "date": datetime.date.today().isoformat(),
        })
        save_acks(repo_root, acks)
        # Remove matching alert from alerts.json
        current = load_alerts(repo_root)
        current["alerts"] = [
            a for a in current.get("alerts", []) if a.get("id") != acknowledge
        ]
        save_alerts(repo_root, current)
        _console.print(f"[drift] Acknowledged {acknowledge}.", markup=False)
        return 0

    # ── Detection path ─────────────────────────────────────────────────────────

    # 1. Load BATON.md
    baton_path = repo_root / "BATON.md"
    try:
        doc = BatonDocument.load(baton_path)
        data = doc.data
    except BatonDocumentError as exc:
        _console.print(f"[drift] Error loading BATON.md: {exc}", markup=False)
        return 1

    # --quiet deprecation: force fmt=json and warn to stderr
    if quiet and fmt == "human":
        fmt = "json"
        print("[drift] --quiet is deprecated; use --format json instead.", file=sys.stderr)

    # 2. Get diff text
    try:
        if staged:
            diff_text = get_staged_diff(repo_root)
        elif since:
            diff_text = get_diff(repo_root, resolve_since(repo_root, since))
        else:
            base_ref = load_last_check_sha(repo_root)
            diff_text = get_diff(repo_root, base_ref)
    except GitError as exc:
        _console.print(f"[drift] Git error: {exc}", markup=False)
        return 1

    # 3. Run three detectors (exclude pending_review draft entries from scan)
    alerts: list[dict] = []
    alerts += detect_anti(diff_text, active_entries(data.get("anti_decisions") or []))
    alerts += detect_decisions(diff_text, active_entries(data.get("decisions") or []))
    alerts += detect_landmines(diff_text, active_entries(data.get("landmines") or []), repo_root)

    # 4. Filter out acknowledged alerts
    acks = load_acks(repo_root)
    ack_ids = {a["id"] for a in acks}
    alerts = [a for a in alerts if a["id"] not in ack_ids]

    # 4a. Enrich alerts with reason/suggestion/fix_command
    enrich_alerts(alerts, data)

    # 5. Build result dict and save
    result = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "since_sha": since or load_last_check_sha(repo_root) or "",
        "alerts": alerts,
    }
    save_alerts(repo_root, result)

    # 6. Update last_check_sha (only when not --staged)
    if not staged:
        sha = head_sha(repo_root)
        if sha:
            save_last_check_sha(repo_root, sha)

    # 7. Output (all branches fall through to exit-code gating below)
    if fmt == "json":
        render_json(result)
    elif fmt == "github":
        render_github(result)
    else:
        render_human(result, _console)

    # 8. Determine exit code
    threshold = ALERT_SEVERITY_RANK.get(fail_on, 1)
    max_severity = max(
        (ALERT_SEVERITY_RANK.get(a["severity"], 0) for a in alerts), default=0
    )
    if max_severity >= 2:
        return 2
    if max_severity >= threshold:
        return 1
    return 0
