"""gemini.py — Adapter for GEMINI.md (Google Gemini CLI / Gemini Code Assist)."""
from .base import BaseAdapter, render_markdown_context


class GeminiAdapter(BaseAdapter):
    """Renders BATON.md into GEMINI.md for Gemini sessions."""

    def render(self, data: dict) -> str:
        return render_markdown_context(data, tool_name="gemini")

    def file_path(self) -> str:
        return "GEMINI.md"
