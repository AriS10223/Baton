"""claude.py — Adapter for CLAUDE.md (Claude Code)."""
from .base import BaseAdapter, render_markdown_context


class ClaudeAdapter(BaseAdapter):
    """Renders BATON.md into CLAUDE.md for Claude Code sessions."""

    def render(self, data: dict) -> str:
        return render_markdown_context(data, tool_name="claude-code")

    def file_path(self) -> str:
        return "CLAUDE.md"
