"""
test_checkfmt.py -- Tests for baton/core/checkfmt.py

Covers all three renderers: render_human, render_json, render_github.
"""
from __future__ import annotations

import io
import json

import pytest
from rich.console import Console

from baton.core.checkfmt import (
    _escape_data,
    _escape_property,
    render_github,
    render_human,
    render_json,
)


# ── Fixtures / helpers ────────────────────────────────────────────────────────


def _make_result(alerts: list[dict]) -> dict:
    return {
        "generated_at": "2026-06-21T00:00:00Z",
        "since_sha": "abc1234",
        "alerts": alerts,
    }


def _make_alert(
    *,
    id: str = "a001",
    type: str = "anti_decision",
    severity: str = "warn",
    status: str = "violated",
    file: str = "src/utils.ts",
    line: int = 14,
    detail: str = "some detail",
    matched: str = "some match",
    reason: str = "This violates the anti-decision.",
    suggestion: str = "Remove the import.",
    fix_command: str = "baton check --drift --acknowledge a001 --reason ...",
) -> dict:
    return {
        "id": id,
        "type": type,
        "severity": severity,
        "status": status,
        "file": file,
        "line": line,
        "detail": detail,
        "matched": matched,
        "reason": reason,
        "suggestion": suggestion,
        "fix_command": fix_command,
    }


def _capture_human(result: dict) -> str:
    """Render human output and return as plain string (no ANSI codes)."""
    buf = io.StringIO()
    console = Console(file=buf, highlight=False, no_color=True)
    render_human(result, console)
    return buf.getvalue()


# ── render_human tests ────────────────────────────────────────────────────────


class TestRenderHuman:
    def test_zero_alerts_no_drift_message(self) -> None:
        out = _capture_human(_make_result([]))
        assert "[drift] No drift detected." in out
        # No alert-like lines
        assert "[a" not in out

    def test_zero_alerts_no_suppress_hint(self) -> None:
        out = _capture_human(_make_result([]))
        assert "acknowledge" not in out

    def test_zero_alerts_has_header(self) -> None:
        out = _capture_human(_make_result([]))
        assert "[drift] Reality drift check  (0 alerts)" in out

    def test_one_alert_header_line(self) -> None:
        alert = _make_alert()
        out = _capture_human(_make_result([alert]))
        assert "[drift] Reality drift check  (1 alerts)" in out
        assert "[a001] anti_decision  warn  violated  src/utils.ts:14" in out

    def test_one_alert_reason_line(self) -> None:
        alert = _make_alert(reason="This violates the anti-decision.")
        out = _capture_human(_make_result([alert]))
        assert "  This violates the anti-decision." in out

    def test_one_alert_suggestion_line(self) -> None:
        alert = _make_alert(suggestion="Remove the import.")
        out = _capture_human(_make_result([alert]))
        assert "  Remove the import." in out

    def test_alert_with_empty_suggestion_no_blank_suggestion_line(self) -> None:
        alert = _make_alert(suggestion="")
        out = _capture_human(_make_result([alert]))
        lines = out.splitlines()
        # reason line should be present (indented)
        assert any(l.startswith("  ") and "This violates" in l for l in lines)
        # No empty indented line after reason
        reason_idx = next(i for i, l in enumerate(lines) if "This violates" in l)
        # The next non-empty line should be the suppress hint, not an empty suggestion
        next_content = next(
            (l for l in lines[reason_idx + 1:] if l.strip()), ""
        )
        assert "acknowledge" in next_content or next_content == ""

    def test_multiple_alerts_all_printed(self) -> None:
        alerts = [
            _make_alert(id="a001", reason="Reason A"),
            _make_alert(id="a002", type="decision", reason="Reason B"),
        ]
        out = _capture_human(_make_result(alerts))
        assert "[drift] Reality drift check  (2 alerts)" in out
        assert "[a001]" in out
        assert "[a002]" in out
        assert "Reason A" in out
        assert "Reason B" in out

    def test_suppress_hint_only_when_alerts(self) -> None:
        alert = _make_alert()
        out = _capture_human(_make_result([alert]))
        assert 'baton check --drift --acknowledge <id> --reason "..." to suppress.' in out

    def test_no_drift_detected_not_shown_when_alerts(self) -> None:
        alert = _make_alert()
        out = _capture_human(_make_result([alert]))
        assert "No drift detected" not in out


# ── render_json tests ─────────────────────────────────────────────────────────


class TestRenderJson:
    def test_output_is_valid_json(self, capsys) -> None:
        render_json(_make_result([]))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, dict)

    def test_envelope_keys_present(self, capsys) -> None:
        render_json(_make_result([]))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "generated_at" in data
        assert "since_sha" in data
        assert "alerts" in data

    def test_alerts_contain_enriched_fields(self, capsys) -> None:
        alert = _make_alert()
        render_json(_make_result([alert]))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["alerts"]) == 1
        a = data["alerts"][0]
        assert "reason" in a
        assert "suggestion" in a
        assert "fix_command" in a

    def test_nothing_else_printed(self, capsys) -> None:
        render_json(_make_result([]))
        captured = capsys.readouterr()
        # stderr should be empty
        assert captured.err == ""
        # stdout should be purely the JSON
        json.loads(captured.out)  # would raise if extra text present

    def test_multiple_alerts_in_json(self, capsys) -> None:
        alerts = [_make_alert(id="a001"), _make_alert(id="a002")]
        render_json(_make_result(alerts))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["alerts"]) == 2


# ── render_github tests ───────────────────────────────────────────────────────


class TestRenderGithub:
    def test_block_severity_gives_error_level(self, capsys) -> None:
        alert = _make_alert(severity="block")
        render_github(_make_result([alert]))
        captured = capsys.readouterr()
        assert captured.out.startswith("::error ")

    def test_warn_severity_gives_warning_level(self, capsys) -> None:
        alert = _make_alert(severity="warn")
        render_github(_make_result([alert]))
        captured = capsys.readouterr()
        assert captured.out.startswith("::warning ")

    def test_file_and_line_in_properties(self, capsys) -> None:
        alert = _make_alert(file="src/utils.ts", line=14)
        render_github(_make_result([alert]))
        captured = capsys.readouterr()
        line = captured.out.strip()
        assert "file=src/utils.ts" in line
        assert "line=14" in line

    def test_escaping_percent_in_reason(self, capsys) -> None:
        """Alert where reason contains %, :, comma, newline -- assert literal escaped output."""
        alert = _make_alert(
            id="a001",
            reason="100% done, don't: break\nthis",
            suggestion="No fix%needed",
        )
        render_github(_make_result([alert]))
        captured = capsys.readouterr()
        line = captured.out.strip()

        # % in message -> %25 (data escaping)
        assert "%25" in line
        # \n in message -> %0A (data escaping)
        assert "%0A" in line
        # colon and comma in message data are NOT escaped
        # Verify the message section after '::' contains literal : and ,
        # Split on last '::' to get message part
        msg_part = line.split("::")[-1]
        assert "," in msg_part or "%2C" not in msg_part  # commas left as-is in data
        # % was double-escaped correctly: original "%" -> "%25", not "%2525"
        assert "%2525" not in line

    def test_file_path_colon_escaped_in_property(self, capsys) -> None:
        """File path with special chars uses _escape_property."""
        alert = _make_alert(file="src/path:with:colons.ts", line=5)
        render_github(_make_result([alert]))
        captured = capsys.readouterr()
        line = captured.out.strip()
        # colons in file= property should be escaped
        assert "file=src/path%3Awith%3Acolons.ts" in line

    def test_empty_file_zero_line_bare_form(self, capsys) -> None:
        alert = _make_alert(file="", line=0)
        render_github(_make_result([alert]))
        captured = capsys.readouterr()
        line = captured.out.strip()
        # Should be bare form: ::error::message (no file= or line=)
        assert "file=" not in line
        assert "line=" not in line
        # Should start with ::error:: or ::warning::
        assert "::" in line
        parts = line.split("::")
        # parts[0]='', parts[1]='error' or 'warning', parts[2]=message
        assert parts[1] in ("error", "warning")
        assert parts[2] != ""

    def test_zero_alerts_no_output(self, capsys) -> None:
        render_github(_make_result([]))
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_multiline_suggestion_uses_percent0a(self, capsys) -> None:
        alert = _make_alert(suggestion="Line 1\nLine 2")
        render_github(_make_result([alert]))
        captured = capsys.readouterr()
        line = captured.out.strip()
        # Newline in message -> %0A, not a literal newline
        assert "%0A" in line
        # No literal newline in the GHA command itself (except the trailing one)
        assert line.count("\n") == 0


# ── Escape helper unit tests ──────────────────────────────────────────────────


class TestEscapeHelpers:
    def test_escape_property_percent_first(self) -> None:
        # If % is replaced first, a colon won't become %253A
        result = _escape_property("%:")
        assert result == "%25%3A"
        assert "%253A" not in result

    def test_escape_property_all_chars(self) -> None:
        assert _escape_property("%") == "%25"
        assert _escape_property("\r") == "%0D"
        assert _escape_property("\n") == "%0A"
        assert _escape_property(":") == "%3A"
        assert _escape_property(",") == "%2C"

    def test_escape_data_percent_first(self) -> None:
        result = _escape_data("%\n")
        assert result == "%25%0A"
        assert "%2525" not in result

    def test_escape_data_colon_comma_not_escaped(self) -> None:
        assert _escape_data(":") == ":"
        assert _escape_data(",") == ","

    def test_escape_data_all_chars(self) -> None:
        assert _escape_data("%") == "%25"
        assert _escape_data("\r") == "%0D"
        assert _escape_data("\n") == "%0A"
