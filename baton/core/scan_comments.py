"""
scan_comments.py -- Code comment scanner for ``baton init --scan``.

Scans source files for HACK, FIXME, WARNING, and TODO comment markers
and produces draft ``landmines`` entries.

Each found comment becomes a landmine with:
    location:    "<relative-file>:<line>"
    looks_like:  ""  (human fills in via baton review)
    actually:    <comment text, stripped of comment prefix and marker>
    source:      "scan:comment"
    confidence:  "high"
    status:      "pending_review"

Skips binary files, generated files (node_modules, __pycache__, .git,
dist, build, .venv, venv), and files larger than 256 KB.

Public API:
    scan_comments(repo_root, today=None) -> list[dict]
"""
from __future__ import annotations

import re
from pathlib import Path

from baton.core.schema import PENDING_REVIEW

# Directories to skip entirely
_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".git", ".hg", ".svn",
    "dist", "build", "target", ".venv", "venv", "env",
    ".mypy_cache", ".pytest_cache", ".tox", "coverage",
    ".claude", ".baton",
})

# File extensions to scan (text source files only)
_TEXT_EXTS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".kt", ".scala",
    ".rb", ".php", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".swift", ".dart",
    ".sh", ".bash", ".zsh", ".fish",
    ".yaml", ".yml", ".toml", ".json", ".md",
    ".html", ".css", ".scss", ".sass",
    ".sql", ".tf", ".hcl",
})

_MAX_FILE_BYTES = 256 * 1024  # 256 KB

# Match HACK / FIXME / WARNING / TODO in any common comment style.
# Group 1 captures the text after the marker.
_COMMENT_RE = re.compile(
    r"(?:#|//|/\*|<!--|--|;)\s*(?:HACK|FIXME|WARNING|TODO)[:\s]+(.+?)(?:\*/|-->)?$",
    re.IGNORECASE,
)


def scan_comments(repo_root: Path, today: str | None = None) -> list[dict]:
    """Scan source files for HACK/FIXME/WARNING/TODO comments.

    Args:
        repo_root: Project root directory.
        today:     Unused (kept for API consistency with other scanners).

    Returns:
        List of landmine draft dicts.
    """
    entries: list[dict] = []
    seen: set[tuple[str, str]] = set()  # (location, text)

    for path in _iter_source_files(repo_root):
        rel = path.relative_to(repo_root)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            m = _COMMENT_RE.search(line)
            if not m:
                continue
            comment_text = m.group(1).strip().rstrip("*/").strip()
            if not comment_text:
                continue

            location = f"{rel.as_posix()}:{lineno}"
            key = (location, comment_text)
            if key in seen:
                continue
            seen.add(key)

            entries.append({
                "location": location,
                "looks_like": "",
                "actually": comment_text,
                "source": "scan:comment",
                "confidence": "high",
                "status": PENDING_REVIEW,
            })

    return entries


def _iter_source_files(repo_root: Path):
    """Yield source files under repo_root, skipping generated dirs."""
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        # Skip any file inside a skip directory
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        # Extension filter
        if path.suffix.lower() not in _TEXT_EXTS:
            continue
        # Size guard
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path
