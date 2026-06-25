"""
scope_keywords.py -- Lightweight keyword extraction for ``baton scope``.

Stdlib only; no NLTK or external deps.  Uses a simple heuristic:
lowercase -> tokenise on non-alphanumeric -> drop stopwords and short tokens ->
deduplicate preserving first-seen order.
"""
from __future__ import annotations

import re

# Common English words that add no signal for BATON.md entry matching.
_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "that", "this", "with", "are", "was", "were",
    "has", "have", "had", "not", "but", "can", "will", "all", "from",
    "they", "them", "their", "its", "our", "you", "your", "his", "her",
    "use", "used", "using", "add", "adds", "adding", "get", "set", "put",
    "fix", "run", "make", "need", "want", "also", "when", "then", "than",
    "into", "out", "new", "any", "some", "more", "most", "only", "just",
    "how", "why", "what", "who", "which", "where", "now", "like", "via",
    "per", "etc", "ing", "tion", "able", "ent", "ous",
})

_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def extract_keywords(text: str) -> list[str]:
    """Return a deduplicated, filtered keyword list from *text*.

    Tokens shorter than 3 characters and common stopwords are dropped.
    Order of first occurrence is preserved.
    """
    lowered = text.lower()
    tokens = _TOKEN_RE.split(lowered)
    seen: set[str] = set()
    result: list[str] = []
    for tok in tokens:
        if len(tok) < 3:
            continue
        if tok in _STOPWORDS:
            continue
        if tok not in seen:
            seen.add(tok)
            result.append(tok)
    return result
