"""
test_adapters.py — Tests for adapter rendering and managed-block logic.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from baton.adapters.base import (
    MARKER_END,
    MARKER_START,
    extract_managed_block,
    render_markdown_context,
    upsert_managed_block,
)
from baton.adapters.claude import ClaudeAdapter
from baton.adapters.codex import CodexAdapter
from baton.adapters.copilot import CopilotAdapter
from baton.adapters.cursor import CursorAdapter
from baton.adapters.gemini import GeminiAdapter
from baton.adapters.registry import ADAPTER_MAP, detect_enabled, get_adapters
from baton.core.document import BatonDocument

FIXTURES = Path(__file__).parent / "fixtures"

ALL_ADAPTERS = [
    ClaudeAdapter(),
    CodexAdapter(),
    CursorAdapter(),
    GeminiAdapter(),
    CopilotAdapter(),
]


@pytest.fixture
def sample_data() -> dict:
    path = FIXTURES / "sample_baton.md"
    return BatonDocument.load(path).data


# ── Managed-block utilities ───────────────────────────────────────────────────

def test_upsert_fresh_file() -> None:
    result = upsert_managed_block("", "# Content")
    assert MARKER_START in result
    assert MARKER_END in result
    assert "# Content" in result


def test_upsert_appends_to_existing_text() -> None:
    existing = "# My existing notes\n\nSome hand-written prose."
    result = upsert_managed_block(existing, "# Baton content")
    assert "My existing notes" in result
    assert "hand-written prose" in result
    assert "# Baton content" in result


def test_upsert_replaces_existing_block() -> None:
    first = upsert_managed_block("", "# First version")
    second = upsert_managed_block(first, "# Second version")
    assert "# First version" not in second
    assert "# Second version" in second
    # Only one BATON:START marker
    assert second.count(MARKER_START) == 1


def test_upsert_idempotent_on_same_content() -> None:
    text = upsert_managed_block("", "# Same")
    result = upsert_managed_block(text, "# Same")
    assert result == text


def test_extract_returns_inner_content() -> None:
    text = upsert_managed_block("", "# Inner")
    extracted = extract_managed_block(text)
    assert extracted is not None
    assert "# Inner" in extracted


def test_extract_returns_none_when_no_block() -> None:
    assert extract_managed_block("# Plain markdown") is None


def test_extract_does_not_include_markers() -> None:
    text = upsert_managed_block("", "# Inner")
    extracted = extract_managed_block(text)
    assert MARKER_START not in extracted
    assert MARKER_END not in extracted


# ── render_markdown_context ───────────────────────────────────────────────────

def test_render_includes_project_name(sample_data: dict) -> None:
    rendered = render_markdown_context(sample_data)
    assert "TestProject" in rendered


def test_render_includes_purpose(sample_data: dict) -> None:
    rendered = render_markdown_context(sample_data)
    assert "vibe coders" in rendered


def test_render_includes_laws(sample_data: dict) -> None:
    rendered = render_markdown_context(sample_data)
    assert "Never use TypeScript" in rendered


def test_render_includes_decisions(sample_data: dict) -> None:
    rendered = render_markdown_context(sample_data)
    assert "d001" in rendered


def test_render_includes_anti_decisions(sample_data: dict) -> None:
    rendered = render_markdown_context(sample_data)
    assert "TypeScript frontend" in rendered


def test_render_includes_landmines(sample_data: dict) -> None:
    rendered = render_markdown_context(sample_data)
    assert "auth/callback.py" in rendered


def test_render_includes_open_questions(sample_data: dict) -> None:
    rendered = render_markdown_context(sample_data)
    assert "multi-select" in rendered


def test_render_tool_name_in_header(sample_data: dict) -> None:
    rendered = render_markdown_context(sample_data, tool_name="claude-code")
    assert "claude-code" in rendered


def test_render_empty_data_does_not_crash() -> None:
    rendered = render_markdown_context({})
    assert isinstance(rendered, str)


def test_render_skips_empty_sections(sample_data: dict) -> None:
    # Blocked list is empty in the fixture — section header should not appear.
    rendered = render_markdown_context(sample_data)
    assert "🚧 Blocked" not in rendered


# ── Individual adapter render + file_path ─────────────────────────────────────

@pytest.mark.parametrize("adapter", ALL_ADAPTERS, ids=lambda a: type(a).__name__)
def test_adapter_render_returns_string(adapter, sample_data: dict) -> None:
    result = adapter.render(sample_data)
    assert isinstance(result, str)
    assert len(result) > 0


def test_claude_adapter_file_path() -> None:
    assert ClaudeAdapter().file_path() == "CLAUDE.md"


def test_codex_adapter_file_path() -> None:
    assert CodexAdapter().file_path() == "AGENTS.md"


def test_cursor_adapter_file_path() -> None:
    assert CursorAdapter().file_path() == ".cursor/rules/baton.mdc"


def test_gemini_adapter_file_path() -> None:
    assert GeminiAdapter().file_path() == "GEMINI.md"


def test_copilot_adapter_file_path() -> None:
    assert CopilotAdapter().file_path() == ".github/copilot-instructions.md"


# ── Cursor prepare_file (MDC front-matter) ────────────────────────────────────

def test_cursor_fresh_file_has_frontmatter(sample_data: dict) -> None:
    adapter = CursorAdapter()
    result = adapter.prepare_file("", adapter.render(sample_data))
    assert result.startswith("---")
    assert "alwaysApply: true" in result


def test_cursor_preserves_existing_frontmatter(sample_data: dict) -> None:
    adapter = CursorAdapter()
    existing = "---\ndescription: Custom\nalwaysApply: false\n---\n# My notes\n"
    result = adapter.prepare_file(existing, adapter.render(sample_data))
    assert "description: Custom" in result
    assert "alwaysApply: false" in result


def test_cursor_has_baton_block(sample_data: dict) -> None:
    adapter = CursorAdapter()
    result = adapter.prepare_file("", adapter.render(sample_data))
    assert MARKER_START in result
    assert MARKER_END in result


# ── Registry ──────────────────────────────────────────────────────────────────

def test_registry_returns_all_five_for_new_project(tmp_path: Path) -> None:
    enabled = detect_enabled(tmp_path)
    assert set(enabled) == set(ADAPTER_MAP.keys())


def test_registry_detects_claude(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# Notes", encoding="utf-8")
    enabled = detect_enabled(tmp_path)
    assert "claude" in enabled


def test_registry_detects_cursor(tmp_path: Path) -> None:
    (tmp_path / ".cursor").mkdir()
    enabled = detect_enabled(tmp_path)
    assert "cursor" in enabled


def test_registry_detects_copilot(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "copilot-instructions.md").write_text("", encoding="utf-8")
    enabled = detect_enabled(tmp_path)
    assert "copilot" in enabled


def test_get_adapters_instantiates_correct_types() -> None:
    adapters = get_adapters(["claude", "codex"])
    assert len(adapters) == 2
    assert any(isinstance(a, ClaudeAdapter) for a in adapters)
    assert any(isinstance(a, CodexAdapter) for a in adapters)


def test_get_adapters_skips_unknown_names() -> None:
    adapters = get_adapters(["claude", "nonexistent_tool"])
    assert len(adapters) == 1


# ── upsert_managed_block with regex-special content ──────────────────────────

def test_upsert_content_with_backslashes() -> None:
    content = "# Path: C:\\Users\\aryan\\project\\\nresult = re.sub(r'\\n', '', text)"
    result = upsert_managed_block("", content)
    extracted = extract_managed_block(result)
    assert "C:\\Users\\aryan" in extracted


def test_upsert_content_with_dollar_signs() -> None:
    content = "price = $100\nvariable = $HOME/bin"
    result = upsert_managed_block("", content)
    extracted = extract_managed_block(result)
    assert "$100" in extracted
    assert "$HOME" in extracted


# ── render_markdown_context with sessions ────────────────────────────────────

def test_render_includes_session_history(sample_data: dict) -> None:
    sample_data["sessions"] = [
        {"date": "2026-06-05", "tool": "claude-code", "summary": "Built the login flow", "highlights": []}
    ]
    rendered = render_markdown_context(sample_data)
    assert "Built the login flow" in rendered


def test_render_with_empty_sessions_does_not_crash(sample_data: dict) -> None:
    sample_data["sessions"] = []
    rendered = render_markdown_context(sample_data)
    assert isinstance(rendered, str)
