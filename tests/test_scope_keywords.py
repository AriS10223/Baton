"""
test_scope_keywords.py -- Tests for core/scope_keywords.py
"""
from __future__ import annotations

from baton.core.scope_keywords import extract_keywords


def test_empty_input() -> None:
    assert extract_keywords("") == []


def test_short_tokens_dropped() -> None:
    result = extract_keywords("a bb ccc dddd")
    assert "a" not in result
    assert "bb" not in result
    assert "ccc" in result
    assert "dddd" in result


def test_stopwords_dropped() -> None:
    result = extract_keywords("fix the auth redirect bug")
    assert "the" not in result
    assert "fix" not in result  # 'fix' is in stopwords
    assert "auth" in result
    assert "redirect" in result
    assert "bug" in result


def test_deduplication_preserves_order() -> None:
    result = extract_keywords("auth token auth session auth")
    assert result.count("auth") == 1
    assert result.index("auth") < result.index("token")
    assert result.index("token") < result.index("session")


def test_case_insensitive() -> None:
    result = extract_keywords("Auth AUTH auth")
    assert result == ["auth"]


def test_non_alphanumeric_separators() -> None:
    result = extract_keywords("src/auth/redirect.py")
    # tokens: 'src', 'auth', 'redirect', 'py' -- 'src' and 'py' are short or kept
    assert "auth" in result
    assert "redirect" in result


def test_numbers_kept() -> None:
    result = extract_keywords("oauth2 fix")
    assert "oauth2" in result


def test_all_stopwords() -> None:
    result = extract_keywords("the and for")
    assert result == []
