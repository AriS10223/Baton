"""codex.py — Adapter for AGENTS.md (OpenAI Codex / OpenAI Agents)."""
from .base import BaseAdapter, render_markdown_context


class CodexAdapter(BaseAdapter):
    """Renders BATON.md into AGENTS.md for Codex / OpenAI Agents sessions."""

    def render(self, data: dict) -> str:
        return render_markdown_context(data, tool_name="codex")

    def file_path(self) -> str:
        return "AGENTS.md"
