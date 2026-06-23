"""
test_drift.py -- Tests for baton/core/drift.py.

All tests use synthetic diff strings.  No filesystem reads, no git calls.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from baton.core.drift import detect_anti, detect_decisions, detect_landmines


# ── Diff helpers ──────────────────────────────────────────────────────────────


def _diff(
    filename: str,
    added: list[str] | None = None,
    removed: list[str] | None = None,
) -> str:
    """Build a minimal unified diff with explicit added and/or removed lines."""
    added = added or []
    removed = removed or []
    old_count = len(removed) + max(1, len(added))
    new_count = len(added) + max(1, len(removed))
    lines = [
        f"diff --git a/{filename} b/{filename}",
        f"--- a/{filename}",
        f"+++ b/{filename}",
        f"@@ -1,{old_count} +1,{new_count} @@",
    ]
    for r in removed:
        lines.append(f"-{r}")
    for a in added:
        lines.append(f"+{a}")
    return "\n".join(lines) + "\n"


def _deletion_diff(filename: str, removed_lines: list[str] | None = None) -> str:
    """Build a diff that represents a file deletion."""
    removed_lines = removed_lines or ["# deleted content"]
    lines = [
        f"diff --git a/{filename} b/{filename}",
        f"--- a/{filename}",
        "+++ /dev/null",
        f"@@ -1,{len(removed_lines)} +0,0 @@",
    ]
    for r in removed_lines:
        lines.append(f"-{r}")
    return "\n".join(lines) + "\n"


# ── detect_anti: regex ────────────────────────────────────────────────────────


def test_detect_anti_regex_match() -> None:
    diff = _diff("src/utils.py", added=["x = moment()"])
    entries = [{"id": "a001", "rejected": "moment.js", "why": "too heavy",
                "pattern": {"type": "regex", "value": "moment"}, "severity": "warn"}]
    alerts = detect_anti(diff, entries)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["id"] == "a001"
    assert alert["type"] == "anti_decision"
    assert alert["severity"] == "warn"
    assert alert["status"] == "violated"
    assert "moment" in alert["detail"]
    # matched field: full added diff line
    assert alert["matched"] == "x = moment()"


def test_detect_anti_regex_no_match() -> None:
    diff = _diff("src/utils.py", added=["x = axios()"])
    entries = [{"id": "a001", "rejected": "moment.js", "why": "too heavy",
                "pattern": {"type": "regex", "value": "moment"}, "severity": "warn"}]
    alerts = detect_anti(diff, entries)
    assert alerts == []


def test_detect_anti_import_match() -> None:
    diff = _diff("app.py", added=["import moment"])
    entries = [{"id": "a002", "rejected": "moment", "why": "use date-fns instead",
                "pattern": {"type": "import", "value": "moment"}}]
    alerts = detect_anti(diff, entries)
    assert len(alerts) == 1
    assert alerts[0]["status"] == "violated"
    assert alerts[0]["id"] == "a002"
    # matched field: the module name
    assert alerts[0]["matched"] == "moment"


def test_detect_anti_dependency_match() -> None:
    diff = _diff("requirements.txt", added=["moment==2.0"])
    entries = [{"id": "a003", "rejected": "moment", "why": "use pendulum",
                "pattern": {"type": "dependency", "value": "moment"}}]
    alerts = detect_anti(diff, entries)
    assert len(alerts) == 1
    assert alerts[0]["status"] == "violated"
    # matched field: the dep name as found (as parsed by added_dependency_names)
    assert alerts[0]["matched"] == "moment"


def test_detect_anti_missing_pattern_skipped() -> None:
    diff = _diff("src/utils.py", added=["import moment"])
    entries = [{"id": "a001", "rejected": "moment.js", "why": "too heavy"}]
    alerts = detect_anti(diff, entries)
    assert alerts == []


def test_detect_anti_severity_block() -> None:
    diff = _diff("app.py", added=["x = eval('something')"])
    entries = [{"id": "a004", "rejected": "eval", "why": "security",
                "pattern": {"type": "regex", "value": r"\beval\b"}, "severity": "block"}]
    alerts = detect_anti(diff, entries)
    assert len(alerts) >= 1
    assert alerts[0]["severity"] == "block"


def test_detect_anti_severity_default_warn() -> None:
    diff = _diff("app.py", added=["import moment"])
    entries = [{"id": "a005", "rejected": "moment", "why": "use date-fns",
                "pattern": {"type": "import", "value": "moment"}}]
    alerts = detect_anti(diff, entries)
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "warn"


def test_detect_anti_severity_invalid_defaults_warn() -> None:
    diff = _diff("app.py", added=["import moment"])
    entries = [{"id": "a006", "rejected": "moment", "why": "test",
                "pattern": {"type": "import", "value": "moment"},
                "severity": "critical"}]  # invalid severity
    alerts = detect_anti(diff, entries)
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "warn"


def test_detect_anti_deduplication() -> None:
    """Same (id, file, line) should not produce duplicate alerts."""
    # Two entries that could match the same line
    diff = _diff("app.py", added=["import moment"])
    entries = [
        {"id": "a001", "pattern": {"type": "import", "value": "moment"}},
        {"id": "a001", "pattern": {"type": "import", "value": "moment"}},
    ]
    alerts = detect_anti(diff, entries)
    # Deduplication is per (id, file, line) — same id matches same line twice
    # The dedup set uses (id, file, line), so duplicate entry should be deduped
    assert len(alerts) == 1


def test_detect_anti_pattern_type_not_in_pattern_types_skipped() -> None:
    diff = _diff("app.py", added=["import moment"])
    entries = [{"id": "a001", "pattern": {"type": "unknown", "value": "moment"}}]
    alerts = detect_anti(diff, entries)
    assert alerts == []


def test_detect_anti_dependency_case_insensitive() -> None:
    """Dependency matching should be case-insensitive."""
    diff = _diff("requirements.txt", added=["Flask==2.0.0"])
    entries = [{"id": "a007", "pattern": {"type": "dependency", "value": "flask"}}]
    alerts = detect_anti(diff, entries)
    assert len(alerts) == 1


# ── detect_decisions ──────────────────────────────────────────────────────────


def test_detect_decisions_dependency_removed() -> None:
    diff = _diff("requirements.txt", removed=["flask==2.0.0"])
    entries = [{"id": "d001", "what": "Use Flask", "why": "lightweight",
                "evidence": {"type": "dependency", "value": "flask"}}]
    alerts = detect_decisions(diff, entries)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["id"] == "d001"
    assert alert["type"] == "decision"
    assert alert["severity"] == "warn"
    assert alert["status"] == "contradicted"
    assert "flask" in alert["detail"].lower()
    # matched field: the dep name (evalue)
    assert alert["matched"] == "flask"


def test_detect_decisions_no_evidence_skipped() -> None:
    diff = _diff("requirements.txt", removed=["flask==2.0.0"])
    entries = [{"id": "d001", "what": "Use Flask", "why": "lightweight"}]
    alerts = detect_decisions(diff, entries)
    assert alerts == []


def test_detect_decisions_dependency_not_removed() -> None:
    """Dep still present in manifest -> no alert."""
    diff = _diff("requirements.txt", added=["flask==2.0.0"])
    entries = [{"id": "d001", "what": "Use Flask",
                "evidence": {"type": "dependency", "value": "flask"}}]
    alerts = detect_decisions(diff, entries)
    assert alerts == []


def test_detect_decisions_file_deleted() -> None:
    diff = _deletion_diff("auth/callback.py")
    entries = [{"id": "d002", "what": "Use auth/callback.py as auth entry",
                "evidence": {"type": "file", "value": "auth/callback.py"}}]
    alerts = detect_decisions(diff, entries)
    assert len(alerts) == 1
    assert alerts[0]["status"] == "contradicted"
    assert alerts[0]["file"] == "auth/callback.py"
    # matched field: the file path (evalue)
    assert alerts[0]["matched"] == "auth/callback.py"


def test_detect_decisions_file_not_deleted() -> None:
    """File modified (not deleted) -> no file-evidence alert."""
    diff = _diff("auth/callback.py", added=["# new line"])
    entries = [{"id": "d002", "what": "Keep auth/callback.py",
                "evidence": {"type": "file", "value": "auth/callback.py"}}]
    alerts = detect_decisions(diff, entries)
    assert alerts == []


def test_detect_decisions_config_key_removed() -> None:
    diff = _diff("config.toml", removed=["database_url = 'postgres://...'"])
    entries = [{"id": "d003", "what": "Always include database_url",
                "evidence": {"type": "config_key", "value": "database_url"}}]
    alerts = detect_decisions(diff, entries)
    assert len(alerts) == 1
    assert alerts[0]["status"] == "contradicted"
    # matched field: the config key (evalue)
    assert alerts[0]["matched"] == "database_url"


def test_detect_decisions_config_key_not_removed() -> None:
    diff = _diff("config.toml", added=["database_url = 'postgres://...'"])
    entries = [{"id": "d003", "what": "Always include database_url",
                "evidence": {"type": "config_key", "value": "database_url"}}]
    alerts = detect_decisions(diff, entries)
    assert alerts == []


def test_detect_decisions_evidence_type_invalid_skipped() -> None:
    diff = _diff("requirements.txt", removed=["flask==2.0.0"])
    entries = [{"id": "d001", "evidence": {"type": "unknown", "value": "flask"}}]
    alerts = detect_decisions(diff, entries)
    assert alerts == []


# ── detect_landmines ──────────────────────────────────────────────────────────


def test_detect_landmines_marker_deleted_strong_signal() -> None:
    """Removing a marker line -> possibly_resolved alert."""
    diff = _diff("auth/callback.py", removed=["# BATON-LANDMINE:l001 intentional"])
    entries = [{"id": "l001", "location": "auth/callback.py",
                "looks_like": "bug", "actually": "intentional"}]
    alerts = detect_landmines(diff, entries, Path("."))
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["id"] == "l001"
    assert alert["type"] == "landmine"
    assert alert["severity"] == "warn"
    assert alert["status"] == "possibly_resolved"
    # matched field: the marker token that was deleted
    assert alert["matched"] == "BATON-LANDMINE:l001"


def test_detect_landmines_file_touched_weak_signal() -> None:
    """File touched but marker NOT deleted -> touched alert."""
    diff = _diff("auth/callback.py", added=["# some new comment"])
    entries = [{"id": "l001", "location": "auth/callback.py",
                "looks_like": "bug", "actually": "intentional"}]
    alerts = detect_landmines(diff, entries, Path("."))
    assert len(alerts) == 1
    assert alerts[0]["status"] == "touched"
    # matched field: the file path (location)
    assert alerts[0]["matched"] == "auth/callback.py"


def test_detect_landmines_file_not_touched_no_alert() -> None:
    """Landmine file not in diff -> no alert."""
    diff = _diff("unrelated.py", added=["x = 1"])
    entries = [{"id": "l001", "location": "auth/callback.py",
                "looks_like": "bug", "actually": "intentional"}]
    alerts = detect_landmines(diff, entries, Path("."))
    assert alerts == []


def test_detect_landmines_no_location_skipped() -> None:
    """Entry without location field -> skipped."""
    diff = _diff("auth/callback.py", added=["x = 1"])
    entries = [{"id": "l001", "looks_like": "bug", "actually": "intentional"}]
    alerts = detect_landmines(diff, entries, Path("."))
    assert alerts == []


def test_detect_landmines_strong_signal_no_weak_duplicate() -> None:
    """When strong signal fires, weak signal must NOT also fire for same entry."""
    # The file is touched AND the marker line is deleted
    diff = (
        "diff --git a/auth/callback.py b/auth/callback.py\n"
        "--- a/auth/callback.py\n"
        "+++ b/auth/callback.py\n"
        "@@ -1,2 +1,1 @@\n"
        "-# BATON-LANDMINE:l001 keep this\n"
        "+# modified\n"
    )
    entries = [{"id": "l001", "location": "auth/callback.py",
                "looks_like": "bug", "actually": "intentional"}]
    alerts = detect_landmines(diff, entries, Path("."))
    # Should have exactly ONE alert (strong signal), not two
    statuses = [a["status"] for a in alerts]
    assert "possibly_resolved" in statuses
    assert "touched" not in statuses


def test_detect_landmines_custom_marker_field() -> None:
    """Entry with explicit 'marker' field should use BATON-LANDMINE:<marker>."""
    diff = _diff("src/tricky.py", removed=["# BATON-LANDMINE:no-retry-logic intentional"])
    entries = [{"id": "l002", "location": "src/tricky.py",
                "marker": "no-retry-logic",
                "looks_like": "missing retry", "actually": "intentional no-retry"}]
    alerts = detect_landmines(diff, entries, Path("."))
    assert len(alerts) == 1
    assert alerts[0]["status"] == "possibly_resolved"


def test_detect_landmines_no_id_no_marker_weak_signal() -> None:
    """Entry without id AND marker: file touched -> weak signal on location."""
    diff = _diff("src/weird.py", added=["# some change"])
    entries = [{"location": "src/weird.py", "looks_like": "bug", "actually": "ok"}]
    alerts = detect_landmines(diff, entries, Path("."))
    assert len(alerts) == 1
    assert alerts[0]["status"] == "touched"
    assert alerts[0]["id"] == ""


# ── matched field: dedicated coverage per detector + sub-type ─────────────────


def test_matched_present_on_all_alerts() -> None:
    """Every alert dict must contain the 'matched' key."""
    diff_anti = _diff("app.py", added=["import moment"])
    anti_alerts = detect_anti(
        diff_anti,
        [{"id": "a001", "pattern": {"type": "import", "value": "moment"}}],
    )
    for alert in anti_alerts:
        assert "matched" in alert, f"missing 'matched' key in alert: {alert}"

    diff_dec = _diff("requirements.txt", removed=["flask==2.0.0"])
    dec_alerts = detect_decisions(
        diff_dec,
        [{"id": "d001", "evidence": {"type": "dependency", "value": "flask"}}],
    )
    for alert in dec_alerts:
        assert "matched" in alert, f"missing 'matched' key in alert: {alert}"

    diff_lm = _diff("src/db.py", added=["# a change"])
    lm_alerts = detect_landmines(
        diff_lm,
        [{"id": "l001", "location": "src/db.py", "looks_like": "slow", "actually": "ok"}],
        Path("."),
    )
    for alert in lm_alerts:
        assert "matched" in alert, f"missing 'matched' key in alert: {alert}"


def test_matched_anti_regex_is_full_added_line() -> None:
    """detect_anti regex: matched == the full added diff line."""
    line = "x = use_moment_library()"
    diff = _diff("src/time.py", added=[line])
    entries = [{"id": "a001", "pattern": {"type": "regex", "value": "moment"}}]
    alerts = detect_anti(diff, entries)
    assert len(alerts) == 1
    assert alerts[0]["matched"] == line


def test_matched_anti_import_is_module_name() -> None:
    """detect_anti import: matched == imp['module'], not the full import line."""
    diff = _diff("app.py", added=["import moment"])
    entries = [{"id": "a001", "pattern": {"type": "import", "value": "moment"}}]
    alerts = detect_anti(diff, entries)
    assert len(alerts) == 1
    assert alerts[0]["matched"] == "moment"


def test_matched_anti_dependency_is_dep_name() -> None:
    """detect_anti dependency: matched == dep['dep'] as parsed (raw dep token)."""
    diff = _diff("requirements.txt", added=["Flask==2.0.0"])
    entries = [{"id": "a001", "pattern": {"type": "dependency", "value": "flask"}}]
    alerts = detect_anti(diff, entries)
    assert len(alerts) == 1
    # dep name as stored in added_dependency_names result (may be 'Flask' or 'flask')
    assert alerts[0]["matched"].lower() == "flask"


def test_matched_decision_dependency_is_evalue() -> None:
    """detect_decisions dependency: matched == the evidence value string."""
    diff = _diff("requirements.txt", removed=["requests==2.28.0"])
    entries = [{"id": "d001", "evidence": {"type": "dependency", "value": "requests"}}]
    alerts = detect_decisions(diff, entries)
    assert len(alerts) == 1
    assert alerts[0]["matched"] == "requests"


def test_matched_decision_file_is_file_path() -> None:
    """detect_decisions file: matched == the evidence value (file path)."""
    diff = _deletion_diff("core/auth.py")
    entries = [{"id": "d001", "evidence": {"type": "file", "value": "core/auth.py"}}]
    alerts = detect_decisions(diff, entries)
    assert len(alerts) == 1
    assert alerts[0]["matched"] == "core/auth.py"


def test_matched_decision_config_key_is_key_string() -> None:
    """detect_decisions config_key: matched == the evidence value (key name)."""
    diff = _diff("settings.json", removed=['"debug_mode": true'])
    entries = [{"id": "d001", "evidence": {"type": "config_key", "value": "debug_mode"}}]
    alerts = detect_decisions(diff, entries)
    assert len(alerts) == 1
    assert alerts[0]["matched"] == "debug_mode"


def test_matched_landmine_strong_is_marker_token() -> None:
    """detect_landmines strong signal: matched == the BATON-LANDMINE token."""
    diff = _diff("src/retry.py", removed=["# BATON-LANDMINE:l003 no-retry intentional"])
    entries = [{"id": "l003", "location": "src/retry.py",
                "looks_like": "missing retry", "actually": "intentional"}]
    alerts = detect_landmines(diff, entries, Path("."))
    assert len(alerts) == 1
    assert alerts[0]["status"] == "possibly_resolved"
    assert alerts[0]["matched"] == "BATON-LANDMINE:l003"


def test_matched_landmine_strong_custom_marker_token() -> None:
    """detect_landmines strong signal with custom marker field: matched uses marker."""
    diff = _diff("src/cache.py", removed=["# BATON-LANDMINE:no-evict intentional"])
    entries = [{"id": "l004", "location": "src/cache.py", "marker": "no-evict",
                "looks_like": "leak", "actually": "intentional"}]
    alerts = detect_landmines(diff, entries, Path("."))
    assert len(alerts) == 1
    assert alerts[0]["matched"] == "BATON-LANDMINE:no-evict"


def test_matched_landmine_weak_is_location() -> None:
    """detect_landmines weak signal: matched == the location file path."""
    diff = _diff("src/cache.py", added=["# minor change"])
    entries = [{"id": "l005", "location": "src/cache.py",
                "looks_like": "leak", "actually": "intentional"}]
    alerts = detect_landmines(diff, entries, Path("."))
    assert len(alerts) == 1
    assert alerts[0]["status"] == "touched"
    assert alerts[0]["matched"] == "src/cache.py"


def test_matched_empty_string_when_no_match() -> None:
    """Alerts from entries that don't fire have matched=''; zero alerts expected."""
    diff = _diff("app.py", added=["x = 1"])
    entries = [{"id": "a001", "pattern": {"type": "regex", "value": "moment"}}]
    alerts = detect_anti(diff, entries)
    # No match -> no alerts; matched default is only visible when an alert IS produced
    assert alerts == []
