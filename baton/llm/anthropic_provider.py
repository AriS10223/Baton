"""
llm/anthropic_provider.py -- Anthropic (Claude) backend for baton end.

Prompt caching: the static system-instruction block (the fixed summariser
role + JSON-output spec) is marked with cache_control so repeated
``baton end`` runs within the 5-minute cache TTL reuse the cached prefix.
The per-run project brief + diff go in the uncached user message.

Auth: ANTHROPIC_API_KEY environment variable.
"""
from __future__ import annotations

import os

from .base import LLMProvider


class AnthropicProvider(LLMProvider):
    """Anthropic Claude backend.  ``anthropic`` package is a core dependency."""

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return "claude-sonnet-4-6"

    def complete(self, system: str, user: str, model: str) -> str:
        """Call the Anthropic Messages API and return the response text.

        The system block is marked cache_control=ephemeral so the static
        instruction prefix is reused across runs within the 5-min cache TTL.
        """
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "The 'anthropic' package is required for baton end. "
                "Install it: pip install anthropic"
            ) from exc

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY environment variable is not set.\n"
                "Export it before running baton end:\n"
                "  export ANTHROPIC_API_KEY=sk-ant-..."
            )

        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model=model,
            max_tokens=2048,
            # System block with cache_control so the static instruction prefix
            # is cached. The per-run user message (project brief + diff) is not
            # marked for caching since it changes every run.
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        )

        for block in response.content:
            if block.type == "text":
                return block.text

        raise RuntimeError(
            "Anthropic API returned no text content in the response."
        )
