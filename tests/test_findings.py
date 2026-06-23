"""
tests/test_findings.py -- Tests for baton.core.findings.enrich_alerts().

All tests use synthetic alert dicts and doc_data dicts.
No filesystem access, no git calls, no LLM calls.
"""
from __future__ import annotations

import pytest

from baton.core.findings import enrich_alerts


# ── Helpers ───────────────────────────────────────────────────────────────────


def _anti_alert(alert_id="a001", matched="requests", file="app.py", line=10):
    return {
        "id": alert_id,
        "type": "anti_decision",
        "severity": "warn",
        "status": "violated",
        "file": file,
        "line": line,
        "detail": f"Anti-decision '{alert_id}' violated in {file}:{line}",
        "matched": matched,
    }


def _decision_alert(alert_id="d001", matched="pytest", file="pyproject.toml", line=5):
    return {
        "id": alert_id,
        "type": "decision",
        "severity": "warn",
        "status": "contradicted",
        "file": file,
        "line": line,
        "detail": f"Decision '{alert_id}' may be contradicted",
        "matched": matched,
    }


def _landmine_alert(alert_id="l001", matched="BATON-LANDMINE:l001",
                    file="core/weird.py", line=42, status="possibly_resolved"):
    return {
        "id": alert_id,
        "type": "landmine",
        "severity": "warn",
        "status": status,
        "file": file,
        "line": line,
        "detail": f"Landmine '{alert_id}' signal in {file}",
        "matched": matched,
    }


def _doc(anti_decisions=None, decisions=None, landmines=None):
    return {
        "anti_decisions": anti_decisions or [],
        "decisions": decisions or [],
        "landmines": landmines or [],
    }


# ── 1. Anti-decision with matched populated ───────────────────────────────────

def test_anti_decision_with_matched_reason_mentions_id_and_matched():
    alert = _anti_alert(alert_id="a001", matched="requests")
    doc = _doc(anti_decisions=[{"id": "a001", "rejected": "No requests -- use httpx"}])
    enrich_alerts([alert], doc)
    assert "requests" in alert["reason"]
    assert "a001" in alert["reason"]


# ── 2. Anti-decision "no X -- use Y" extraction ──────────────────────────────

def test_anti_decision_no_use_pattern_extracts_alternative():
    alert = _anti_alert(alert_id="a002", matched="requests")
    doc = _doc(anti_decisions=[{
        "id": "a002",
        "rejected": "No requests -- use httpx instead",
    }])
    enrich_alerts([alert], doc)
    assert "httpx" in alert["suggestion"]
    assert alert["suggestion"].startswith("Use httpx")


# ── 3. Anti-decision plain text rejected -- quotes verbatim ──────────────────

def test_anti_decision_plain_rejected_quoted_verbatim():
    alert = _anti_alert(alert_id="a003", matched="yaml")
    doc = _doc(anti_decisions=[{
        "id": "a003",
        "rejected": "Never use PyYAML; use ruamel.yaml for round-trip safety",
    }])
    enrich_alerts([alert], doc)
    assert "Never use PyYAML; use ruamel.yaml for round-trip safety" in alert["suggestion"]
    assert f'anti_decision a003 says:' in alert["suggestion"]


# ── 4. Anti-decision matched empty -- falls back to file:line form ────────────

def test_anti_decision_empty_matched_falls_back_to_file_line():
    alert = _anti_alert(alert_id="a004", matched="", file="src/foo.py", line=99)
    doc = _doc(anti_decisions=[{"id": "a004", "rejected": "some rule"}])
    enrich_alerts([alert], doc)
    assert "src/foo.py:99" in alert["reason"]
    assert "a004" in alert["reason"]


# ── 5. Decision -- reason mentions matched, suggestion quotes what, fix supersede

def test_decision_reason_and_suggestion_and_fix_command():
    alert = _decision_alert(alert_id="d001", matched="pytest")
    doc = _doc(decisions=[{
        "id": "d001",
        "what": "Use pytest as the only test runner",
        "made": "2024-01-01",
    }])
    enrich_alerts([alert], doc)
    # reason mentions matched and id
    assert "pytest" in alert["reason"]
    assert "d001" in alert["reason"]
    # suggestion quotes what and has supersede command
    assert "Use pytest as the only test runner" in alert["suggestion"]
    assert "baton supersede d001" in alert["suggestion"]
    # fix_command has supersede
    assert "baton supersede d001" in alert["fix_command"]


# ── 6. Landmine possibly_resolved -- reason mentions marker ──────────────────

def test_landmine_possibly_resolved_reason_mentions_marker():
    alert = _landmine_alert(
        alert_id="l001",
        matched="BATON-LANDMINE:l001",
        file="core/weird.py",
        line=42,
        status="possibly_resolved",
    )
    doc = _doc(landmines=[{
        "id": "l001",
        "actually": "This looks wrong but the order matters for thread safety",
        "location": "core/weird.py",
    }])
    enrich_alerts([alert], doc)
    assert "BATON-LANDMINE:l001" in alert["reason"]
    assert "possibly" in alert["reason"].lower() or "resolved" in alert["reason"].lower()
    # also appends the actually text
    assert "thread safety" in alert["reason"]


# ── 7. Landmine touched -- reason mentions file ───────────────────────────────

def test_landmine_touched_reason_mentions_file():
    alert = _landmine_alert(
        alert_id="l002",
        matched="core/weird.py",
        file="core/weird.py",
        line=0,
        status="touched",
    )
    doc = _doc(landmines=[{
        "id": "l002",
        "actually": "Intentional singleton bypass",
        "location": "core/weird.py",
    }])
    enrich_alerts([alert], doc)
    assert "core/weird.py" in alert["reason"]
    assert "modified" in alert["reason"] or "touched" in alert["reason"].lower()


# ── 8. Missing entry -- falls back to detail, empty suggestion ───────────────

def test_missing_entry_falls_back_to_detail():
    alert = {
        "id": "a999",
        "type": "anti_decision",
        "severity": "warn",
        "status": "violated",
        "file": "x.py",
        "line": 1,
        "detail": "Something happened",
        "matched": "foo",
    }
    doc = _doc()  # no entries at all
    enrich_alerts([alert], doc)
    # reason still set (from matched since matched is non-empty)
    assert "reason" in alert
    # suggestion empty because entry missing
    assert alert["suggestion"] == ""
    # fix_command set to ack command (matched anti_decision path)
    assert "fix_command" in alert


def test_missing_entry_unknown_type_falls_back_to_detail():
    alert = {
        "id": "x001",
        "type": "unknown_type",
        "severity": "warn",
        "status": "violated",
        "file": "x.py",
        "line": 1,
        "detail": "Fallback detail text",
        "matched": "something",
    }
    doc = _doc()
    enrich_alerts([alert], doc)
    assert alert["reason"] == "Fallback detail text"
    assert alert["suggestion"] == ""
    assert alert["fix_command"] == ""


# ── 9. enrich_alerts is in-place ─────────────────────────────────────────────

def test_enrich_alerts_modifies_in_place_and_returns_same_list():
    alerts = [_anti_alert()]
    doc = _doc(anti_decisions=[{"id": "a001", "rejected": "No requests -- use httpx"}])
    result = enrich_alerts(alerts, doc)
    # same list object
    assert result is alerts
    # same dict object
    assert result[0] is alerts[0]
    # modified in place
    assert "reason" in alerts[0]


# ── 10. All three fields present on every enriched alert ─────────────────────

def test_all_three_fields_present_on_every_alert():
    alerts = [
        _anti_alert(alert_id="a001"),
        _decision_alert(alert_id="d001"),
        _landmine_alert(alert_id="l001", status="possibly_resolved"),
        _landmine_alert(alert_id="l002", status="touched",
                        matched="core/weird.py", file="core/weird.py", line=0),
    ]
    doc = _doc(
        anti_decisions=[{"id": "a001", "rejected": "No requests -- use httpx"}],
        decisions=[{"id": "d001", "what": "Use pytest"}],
        landmines=[
            {"id": "l001", "actually": "intentional", "location": "core/weird.py"},
            {"id": "l002", "actually": "also intentional", "location": "core/weird.py"},
        ],
    )
    enrich_alerts(alerts, doc)
    for alert in alerts:
        assert "reason" in alert, f"Missing 'reason' on {alert['id']}"
        assert "suggestion" in alert, f"Missing 'suggestion' on {alert['id']}"
        assert "fix_command" in alert, f"Missing 'fix_command' on {alert['id']}"
        # all must be strings
        assert isinstance(alert["reason"], str)
        assert isinstance(alert["suggestion"], str)
        assert isinstance(alert["fix_command"], str)


# ── Bonus: ack hint always present in anti_decision suggestion ────────────────

def test_anti_decision_suggestion_always_ends_with_ack_hint():
    """The acknowledge command must always appear in suggestion."""
    alert = _anti_alert(alert_id="a001", matched="requests")
    doc = _doc(anti_decisions=[{"id": "a001", "rejected": "plain text, no pattern"}])
    enrich_alerts([alert], doc)
    assert "--acknowledge a001" in alert["suggestion"]


def test_anti_decision_no_use_suggestion_ends_with_ack_hint():
    alert = _anti_alert(alert_id="a001", matched="requests")
    doc = _doc(anti_decisions=[{"id": "a001", "rejected": "No requests -- use httpx"}])
    enrich_alerts([alert], doc)
    assert "--acknowledge a001" in alert["suggestion"]


# ── Decision: matched empty falls back to detail ──────────────────────────────

def test_decision_empty_matched_falls_back_to_detail():
    alert = _decision_alert(alert_id="d001", matched="")
    alert["detail"] = "Custom detail for d001"
    doc = _doc(decisions=[{"id": "d001", "what": "Some decision"}])
    enrich_alerts([alert], doc)
    assert alert["reason"] == "Custom detail for d001"


# ── Landmine without 'actually' text ─────────────────────────────────────────

def test_landmine_without_actually_no_parenthetical():
    alert = _landmine_alert(alert_id="l001", status="possibly_resolved")
    doc = _doc(landmines=[{"id": "l001", "location": "core/weird.py"}])
    enrich_alerts([alert], doc)
    # No parenthetical since 'actually' is absent
    assert "(landmine:" not in alert["reason"]
    assert "BATON-LANDMINE:l001" in alert["reason"]
