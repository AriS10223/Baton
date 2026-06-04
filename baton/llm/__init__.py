"""
llm/__init__.py -- Provider factory for baton end.

Usage::

    from baton.llm import get_provider
    provider = get_provider(config)
    text = provider.complete(system, user, model)
"""
from __future__ import annotations

from ..core.config import BatonConfig
from .base import LLMProvider

_VALID_PROVIDERS = ("anthropic", "openai", "vertex")


def get_provider(config: BatonConfig) -> LLMProvider:
    """Return the LLMProvider for config.llm_provider.

    Raises:
        ValueError: for unknown provider names, listing valid options.
    """
    name = (config.llm_provider or "anthropic").lower()

    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()

    if name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider()

    if name == "vertex":
        from .vertex_provider import VertexProvider
        return VertexProvider()

    raise ValueError(
        f"Unknown llm_provider '{name}' in .baton.toml. "
        f"Valid options: {', '.join(_VALID_PROVIDERS)}"
    )


__all__ = ["get_provider", "LLMProvider"]
