"""
alerts.py -- State I/O for drift-detection artefacts stored in .baton/.

Three files are managed here:
  .baton/alerts.json      -- current drift alerts (written by baton check --drift)
  .baton/last_check_sha   -- plain-text file with the last git SHA that was checked
  .baton/ack.json         -- list of acknowledged alert ids

All files are optional.  Absent or corrupt files return empty defaults; they
never raise.  Write functions create .baton/ if it does not yet exist.
"""
from __future__ import annotations

import json
from pathlib import Path

# ── Internal helpers ──────────────────────────────────────────────────────────

def _baton_dir(repo_root: Path) -> Path:
    return repo_root / ".baton"


def _ensure_baton_dir(repo_root: Path) -> Path:
    d = _baton_dir(repo_root)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Alert I/O ─────────────────────────────────────────────────────────────────

def load_alerts(repo_root: Path) -> dict:
    """Load .baton/alerts.json.

    Returns {"alerts": [], "since_sha": "", "generated_at": ""} if the file
    is absent or contains invalid JSON.
    """
    _empty: dict = {"alerts": [], "since_sha": "", "generated_at": ""}
    path = _baton_dir(repo_root) / "alerts.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _empty
        return data
    except Exception:
        return _empty


def save_alerts(repo_root: Path, data: dict) -> None:
    """Write .baton/alerts.json.  Creates .baton/ dir if needed."""
    d = _ensure_baton_dir(repo_root)
    (d / "alerts.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Ack I/O ───────────────────────────────────────────────────────────────────

def load_acks(repo_root: Path) -> list[dict]:
    """Load .baton/ack.json.

    Returns [] if the file is absent or contains invalid JSON.
    """
    path = _baton_dir(repo_root) / "ack.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return data
    except Exception:
        return []


def save_acks(repo_root: Path, acks: list[dict]) -> None:
    """Write .baton/ack.json.  Creates .baton/ dir if needed."""
    d = _ensure_baton_dir(repo_root)
    (d / "ack.json").write_text(json.dumps(acks, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Last-check SHA I/O ────────────────────────────────────────────────────────

def load_last_check_sha(repo_root: Path) -> str | None:
    """Read .baton/last_check_sha.  Returns None if the file is absent."""
    path = _baton_dir(repo_root) / "last_check_sha"
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def save_last_check_sha(repo_root: Path, sha: str) -> None:
    """Write sha to .baton/last_check_sha.  Creates .baton/ dir if needed."""
    d = _ensure_baton_dir(repo_root)
    (d / "last_check_sha").write_text(sha, encoding="utf-8")


# ── Appendix-notice hash I/O ──────────────────────────────────────────────────
# Stores a hash of the last appendix state that was shown to the user,
# so the heads-up only fires once per distinct drift state.

def load_appendix_notice(repo_root: Path) -> dict:
    """Load .baton/appendix_notice.json.

    Returns {} if the file is absent or contains invalid JSON.
    Schema: {"hash": "<sha256-hex-of-last-shown-on-disk-appendix>"}
    """
    path = _baton_dir(repo_root) / "appendix_notice.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def save_appendix_notice(repo_root: Path, notice: dict) -> None:
    """Write .baton/appendix_notice.json.  Creates .baton/ dir if needed."""
    d = _ensure_baton_dir(repo_root)
    (d / "appendix_notice.json").write_text(
        json.dumps(notice, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── Supersede-declined I/O ────────────────────────────────────────────────────
# Remembers which overlap pairs the user declined, so the nudge doesn't re-ask.
# Schema: [{"old_id": "d001", "new_id": "d002", "date": "2026-06-20"}]

def load_supersede_declined(repo_root: Path) -> list[dict]:
    """Load .baton/supersede_declined.json.

    Returns [] if the file is absent or contains invalid JSON.
    """
    path = _baton_dir(repo_root) / "supersede_declined.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return data
    except Exception:
        return []


def save_supersede_declined(repo_root: Path, declined: list[dict]) -> None:
    """Write .baton/supersede_declined.json.  Creates .baton/ dir if needed."""
    d = _ensure_baton_dir(repo_root)
    (d / "supersede_declined.json").write_text(
        json.dumps(declined, indent=2, ensure_ascii=False), encoding="utf-8"
    )
