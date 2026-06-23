"""
scan_pr.py -- PR history scanner for ``baton init --scan``.

Calls ``gh pr list`` to fetch closed PR descriptions and extracts
curated-memory markers using ``core/markers.parse_markers``.

Graceful degradation: if ``gh`` is not installed or the repo has no GitHub
remote, returns ([], "skipped: <reason>") silently -- never errors.

Confidence rules for extracted entries:
  - Default: "medium" (PR description is human-written, but not ratified)
  - Downgraded to "low" when WHY: text is:
      * Fewer than 15 characters
      * References external context ("see Slack", "per meeting", "as discussed",
        "per call", "in thread")
      * A bare URL (starts with http:// or https://)
  - Anti-decisions from explicit ANTI:/REJECTED: markers only.
    Never infer anti-decisions from absence of a package.

BATON: ids in PR description -> attempt to enrich the matched entries' why
field in the returned draft list.

Public API:
    scan_prs(repo_root, today=None, runner=None) -> tuple[list[dict], str]

    Returns:
        (entries, summary_note)
        entries:      list of draft dicts across all entry types
        summary_note: human-readable note for the scan summary output
                      e.g. "skipped: gh not found" or "19 PRs scanned"
"""
from __future__ import annotations

import datetime
import json
import re
import subprocess
from pathlib import Path
from typing import Callable

from baton.core.markers import parse_markers
from baton.core.schema import PENDING_REVIEW

# WHY: confidence downgrade patterns
_EXTERNAL_REF_RE = re.compile(
    r"\b(see\s+slack|per\s+meeting|as\s+discussed|per\s+call|in\s+thread|"
    r"see\s+email|per\s+email|discussed\s+offline)\b",
    re.IGNORECASE,
)
_BARE_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)

# Type alias for the injectable runner
Runner = Callable[[list[str]], tuple[int, str, str]]  # (args) -> (returncode, stdout, stderr)


def _default_runner(args: list[str]) -> tuple[int, str, str]:
    """Run a subprocess command; return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return -1, "", f"{args[0]}: command not found"
    except subprocess.TimeoutExpired:
        return -1, "", "gh: timed out"
    except Exception as exc:
        return -1, "", str(exc)


def scan_prs(
    repo_root: Path,
    today: str | None = None,
    runner: Runner | None = None,
) -> tuple[list[dict], str]:
    """Fetch closed PR descriptions and extract curated-memory markers.

    Args:
        repo_root: Project root (used to detect GitHub remote via git remote).
        today:     ISO date for entry date fields (default: today).
        runner:    Injectable subprocess runner for testing. When None, uses
                   the real ``gh`` CLI.

    Returns:
        (entries, summary_note) where entries is a list of draft dicts and
        summary_note describes what happened (for the scan summary table).
    """
    if today is None:
        today = datetime.date.today().isoformat()
    if runner is None:
        runner = _default_runner

    # 1. Check gh is available
    rc, _, stderr = runner(["gh", "--version"])
    if rc != 0:
        return [], "skipped: gh not found"

    # 2. Check there is a GitHub remote
    rc, stdout, _ = runner(["git", "-C", str(repo_root), "remote", "-v"])
    if rc != 0 or "github.com" not in stdout:
        return [], "skipped: no GitHub remote"

    # 3. Fetch PRs
    rc, stdout, stderr = runner([
        "gh", "pr", "list",
        "--state", "closed",
        "--json", "number,title,body,mergedAt",
        "--limit", "200",
        "-R", ".",  # current repo; gh resolves from git remote
    ])
    if rc != 0:
        return [], f"skipped: gh error: {stderr.strip()[:80]}"

    try:
        prs: list[dict] = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError:
        return [], "skipped: gh returned invalid JSON"

    # 4. Parse each PR
    entries: list[dict] = []
    seen_decisions:  set[str] = set()
    seen_anti:       set[str] = set()
    seen_landmines:  set[str] = set()
    seen_questions:  set[str] = set()

    for pr in prs:
        body = (pr.get("body") or "").strip()
        title = (pr.get("title") or "").strip()

        if not body and not title:
            continue

        # Parse body lines for markers
        lines = (title + "\n" + body).splitlines()
        parsed = parse_markers(lines)

        why = parsed.get("why", "")
        confidence = _why_confidence(why)

        # Process decisions
        for d in parsed.get("decisions", []):
            val = d["what"]
            if val in seen_decisions:
                continue
            seen_decisions.add(val)
            entries.append({
                "what": val,
                "why": why if why else d.get("why", ""),
                "made": today,
                "made_in": "",
                "source": "scan:pr_history",
                "confidence": confidence,
                "status": PENDING_REVIEW,
            })

        # Process anti_decisions (only from explicit markers)
        for a in parsed.get("anti_decisions", []):
            val = a["rejected"]
            if val in seen_anti:
                continue
            seen_anti.add(val)
            entries.append({
                "rejected": val,
                "why": why if why else a.get("why", ""),
                "ruled_out": today,
                "source": "scan:pr_history",
                "confidence": confidence,
                "status": PENDING_REVIEW,
            })

        # Process landmines
        for lm in parsed.get("landmines", []):
            val = lm["actually"]
            if val in seen_landmines:
                continue
            seen_landmines.add(val)
            entries.append({
                "location": lm.get("location", ""),
                "looks_like": lm.get("looks_like", ""),
                "actually": val,
                "source": "scan:pr_history",
                "confidence": confidence,
                "status": PENDING_REVIEW,
            })

        # Process open questions
        for q in parsed.get("open_questions", []):
            val = q["question"]
            if val in seen_questions:
                continue
            seen_questions.add(val)
            entries.append({
                "question": val,
                "context": q.get("context", ""),
                "status": "open",        # question status (open/discussed/resolved), NOT pending_review
                "source": "scan:pr_history",
                "confidence": confidence,
                # No "pending_review" status -- open_questions don't participate in drift
            })

    n = len(prs)
    note = f"{n} PR{'s' if n != 1 else ''} scanned"
    return entries, note


def _why_confidence(why: str) -> str:
    """Return confidence level based on WHY: text quality.

    Returns "low" when WHY: is:
    - Absent (empty): use "medium" as the base (no WHY doesn't mean low quality --
      the marker alone carries meaning)
    - Fewer than 15 characters
    - References external context
    - A bare URL
    """
    if not why:
        return "medium"
    if len(why) < 15:
        return "low"
    if _EXTERNAL_REF_RE.search(why):
        return "low"
    if _BARE_URL_RE.match(why.strip()):
        return "low"
    return "medium"
