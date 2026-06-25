"""
tokens.py -- Standalone token counter for BATON.md content.

Uses tiktoken when available; falls back to a word-count heuristic
(words * 1.3) with a visible warning.  Never crashes on missing tiktoken.

Public API:
    tiktoken_available() -> bool
    count_tokens(text, *, model=None) -> tuple[int, str]
    count_entry_tokens(entry, *, model=None) -> int
"""
from __future__ import annotations

import functools
from io import StringIO
from typing import Any

DEFAULT_ENCODING = "cl100k_base"

# ── Optional tiktoken (lazy import) ──────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def tiktoken_available() -> bool:
    """Return True if tiktoken is importable.  Result is cached."""
    try:
        import tiktoken  # noqa: F401
        return True
    except Exception:
        return False


def _get_encoding(model: str | None):
    """Return a tiktoken encoding for *model* (or DEFAULT_ENCODING).

    Returns None if tiktoken is unavailable or the model/encoding is unknown.
    """
    if not tiktoken_available():
        return None
    try:
        import tiktoken
        if model:
            try:
                return tiktoken.encoding_for_model(model)
            except KeyError:
                pass  # unknown model name -- fall through to named encoding
        return tiktoken.get_encoding(DEFAULT_ENCODING)
    except Exception:
        return None


# ── Public functions ──────────────────────────────────────────────────────────


def count_tokens(text: str, *, model: str | None = None) -> tuple[int, str]:
    """Count tokens in *text*.

    Args:
        text:  The raw string to count tokens in.
        model: Optional tiktoken model name or encoding name.  Defaults to
               ``cl100k_base`` when tiktoken is available.

    Returns:
        ``(count, method)`` where *method* is one of:
        - ``"tiktoken:<encoding>"`` when tiktoken is used.
        - ``"heuristic"`` when tiktoken is absent or fails.

    Never raises.
    """
    try:
        enc = _get_encoding(model)
        if enc is not None:
            count = len(enc.encode(text))
            enc_name = getattr(enc, "name", DEFAULT_ENCODING)
            return (count, f"tiktoken:{enc_name}")
    except Exception:
        pass

    # Fallback: word-count heuristic
    count = round(len(text.split()) * 1.3)
    return (count, "heuristic")


def count_entry_tokens(entry: Any, *, model: str | None = None) -> int:
    """Estimate the token cost of a single BATON.md entry dict.

    Round-trips the entry through ruamel.yaml using the same dump settings as
    ``BatonDocument.save()`` (width=120, indent 2/4/2) to produce an accurate
    estimate of how many tokens the entry contributes to BATON.md.

    Returns 0 on any error.
    """
    if not isinstance(entry, dict):
        return 0
    try:
        from ruamel.yaml import YAML
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.default_flow_style = False
        yaml.indent(mapping=2, sequence=4, offset=2)
        yaml.width = 120

        buf = StringIO()
        yaml.dump(dict(entry), buf)
        text = buf.getvalue()
        count, _ = count_tokens(text, model=model)
        return count
    except Exception:
        return 0
