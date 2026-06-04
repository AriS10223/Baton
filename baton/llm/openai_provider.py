"""
llm/openai_provider.py -- OpenAI (GPT) backend for baton end.

Lazy-imports ``openai`` so the package is not required unless the user
sets ``llm_provider = "openai"`` in .baton.toml.

OpenAI performs automatic server-side prompt caching -- no explicit
cache_control markers are needed.

Install with: pip install "baton-cli[openai]"
Auth: OPENAI_API_KEY environment variable.
"""
from __future__ import annotations

import os

from .base import LLMProvider


class OpenAIProvider(LLMProvider):
    """OpenAI GPT backend.  ``openai`` package is an optional extra."""

    @property
    def name(self) -> str:
        return "openai"

    @property
    def default_model(self) -> str:
        return "gpt-4o"

    def complete(self, system: str, user: str, model: str) -> str:
        """Call the OpenAI Chat Completions API and return the response text."""
        try:
            import openai
        except ImportError as exc:
            raise RuntimeError(
                "The 'openai' package is required for the OpenAI provider.\n"
                "Install it: pip install \"baton-cli[openai]\""
            ) from exc

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY environment variable is not set.\n"
                "Export it before running baton end:\n"
                "  export OPENAI_API_KEY=sk-..."
            )

        client = openai.OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model=model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )

        text = response.choices[0].message.content
        if text is None:
            raise RuntimeError(
                "OpenAI API returned no text content in the response."
            )
        return text
