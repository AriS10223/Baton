"""copilot.py — Adapter for .github/copilot-instructions.md (GitHub Copilot)."""
from .base import BaseAdapter, render_markdown_context


class CopilotAdapter(BaseAdapter):
    """Renders BATON.md into .github/copilot-instructions.md for Copilot."""

    def render(self, data: dict) -> str:
        return render_markdown_context(data, tool_name="copilot")

    def file_path(self) -> str:
        return ".github/copilot-instructions.md"
