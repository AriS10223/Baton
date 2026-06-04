"""
llm/base.py -- Abstract base class for LLM providers used by ``baton end``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Interface that every LLM provider must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short provider identifier, e.g. 'anthropic'."""

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model ID used when config.model is empty."""

    @abstractmethod
    def complete(self, system: str, user: str, model: str) -> str:
        """Call the LLM with a system and user message; return the response text.

        Raises:
            RuntimeError: on API errors or auth failures, with an actionable message.
        """
