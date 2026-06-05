"""
test_llm.py -- Tests for baton/llm/__init__.py (get_provider factory) and
provider lazy-import behavior.

No real network calls.
"""
from __future__ import annotations

import builtins
import importlib
from unittest.mock import patch

import pytest

from baton.core.config import BatonConfig
from baton.llm import get_provider
from baton.llm.anthropic_provider import AnthropicProvider
from baton.llm.openai_provider import OpenAIProvider
from baton.llm.vertex_provider import VertexProvider


# ── Provider factory ──────────────────────────────────────────────────────────

def test_get_provider_anthropic() -> None:
    config = BatonConfig(llm_provider="anthropic")
    provider = get_provider(config)
    assert isinstance(provider, AnthropicProvider)
    assert provider.name == "anthropic"


def test_get_provider_openai() -> None:
    config = BatonConfig(llm_provider="openai")
    provider = get_provider(config)
    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "openai"


def test_get_provider_vertex() -> None:
    config = BatonConfig(llm_provider="vertex")
    provider = get_provider(config)
    assert isinstance(provider, VertexProvider)
    assert provider.name == "vertex"


def test_get_provider_unknown_raises() -> None:
    config = BatonConfig(llm_provider="foobar")
    with pytest.raises(ValueError) as exc_info:
        get_provider(config)
    msg = str(exc_info.value)
    assert "foobar" in msg
    # Should list valid options.
    assert "anthropic" in msg
    assert "openai" in msg
    assert "vertex" in msg


# ── Model resolution ──────────────────────────────────────────────────────────

def test_model_resolution_uses_config_model() -> None:
    config = BatonConfig(llm_provider="anthropic", model="claude-opus-4-6")
    provider = get_provider(config)
    # The resolved model should be the config value (not the provider default).
    resolved = config.model or provider.default_model
    assert resolved == "claude-opus-4-6"


def test_model_resolution_falls_back_to_default() -> None:
    config = BatonConfig(llm_provider="anthropic", model="")
    provider = get_provider(config)
    resolved = config.model or provider.default_model
    assert resolved == provider.default_model
    assert resolved  # non-empty


def test_anthropic_default_model() -> None:
    provider = AnthropicProvider()
    assert provider.default_model == "claude-sonnet-4-6"


def test_openai_default_model() -> None:
    provider = OpenAIProvider()
    assert provider.default_model == "gpt-4o"


def test_vertex_default_model() -> None:
    provider = VertexProvider()
    assert provider.default_model == "gemini-1.5-pro"


# ── Missing SDK behavior ──────────────────────────────────────────────────────

def test_openai_provider_missing_sdk_raises() -> None:
    """Simulate 'openai' package not installed; complete() must raise RuntimeError."""
    provider = OpenAIProvider()
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "openai":
            raise ImportError("No module named 'openai'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        with pytest.raises(RuntimeError, match="openai"):
            provider.complete("system", "user", "gpt-4o")


def test_vertex_provider_missing_sdk_raises() -> None:
    """Simulate 'vertexai' package not installed; complete() must raise RuntimeError."""
    provider = VertexProvider()
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ("vertexai", "vertexai.generative_models"):
            raise ImportError("No module named 'vertexai'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        with pytest.raises(RuntimeError, match="google-cloud-aiplatform"):
            provider.complete("system", "user", "gemini-1.5-pro")


# ── Provider name case-insensitivity ─────────────────────────────────────────

def test_get_provider_uppercase_name() -> None:
    config = BatonConfig(llm_provider="ANTHROPIC")
    provider = get_provider(config)
    assert isinstance(provider, AnthropicProvider)


def test_get_provider_mixed_case_name() -> None:
    config = BatonConfig(llm_provider="OpenAI")
    provider = get_provider(config)
    assert isinstance(provider, OpenAIProvider)


def test_get_provider_uppercase_vertex() -> None:
    config = BatonConfig(llm_provider="VERTEX")
    provider = get_provider(config)
    assert isinstance(provider, VertexProvider)


def test_anthropic_provider_missing_api_key_raises() -> None:
    """AnthropicProvider.complete() must raise RuntimeError when key is absent.

    If the anthropic SDK itself is not installed, the provider raises RuntimeError
    about the missing package instead -- both are acceptable RuntimeErrors.
    """
    import os
    provider = AnthropicProvider()
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        with pytest.raises(RuntimeError):
            provider.complete("system", "user", "claude-sonnet-4-6")
