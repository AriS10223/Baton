"""
gitignore.py -- Gitignore helpers for Baton state files.

``ensure_scope_committable`` makes .baton/scope.md trackable by git while
keeping the rest of .baton/ (alerts.json, last_check_sha, etc.) ignored.

VERIFIED MECHANIC: a bare ``.baton/`` line + an appended ``!.baton/scope.md``
does NOT un-ignore scope.md -- git will not descend into an ignored directory.
The directory line must first be transformed to ``.baton/*`` (ignores contents
but not the directory itself), then the negation is added.
"""
from __future__ import annotations

from pathlib import Path

_DIR_LINE = ".baton/"
_GLOB_LINE = ".baton/*"
_NEGATION_LINE = "!.baton/scope.md"


def ensure_scope_committable(repo_root: Path) -> None:
    """Make .baton/scope.md committable (not ignored) in the repo's .gitignore.

    Idempotent: calling multiple times produces the same result.

    Strategy:
    1. If ``.baton/*`` and ``!.baton/scope.md`` are already present -> no-op.
    2. Replace the first occurrence of ``.baton/`` with ``.baton/*``.
    3. Append ``!.baton/scope.md`` after the transformed line.
    4. If neither line exists, append both to the end.
    """
    gitignore_path = repo_root / ".gitignore"

    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding="utf-8")
    else:
        content = ""

    lines = content.splitlines(keepends=True)

    # Already configured -- no-op.
    bare_lines = [l.rstrip("\r\n") for l in lines]
    if _GLOB_LINE in bare_lines and _NEGATION_LINE in bare_lines:
        return

    new_lines: list[str] = []
    transformed = False
    negation_added = False

    for line in lines:
        stripped = line.rstrip("\r\n")
        if not transformed and stripped == _DIR_LINE:
            # Replace bare directory ignore with glob form.
            eol = line[len(stripped):]
            new_lines.append(_GLOB_LINE + eol)
            new_lines.append(_NEGATION_LINE + eol)
            transformed = True
            negation_added = True
        else:
            new_lines.append(line)

    if not negation_added:
        # .baton/ line absent -- append both lines.
        eol = "\n"
        if new_lines:
            last = new_lines[-1]
            if not last.endswith(("\n", "\r")):
                new_lines.append(eol)
        if not transformed:
            new_lines.append(_GLOB_LINE + eol)
        new_lines.append(_NEGATION_LINE + eol)

    gitignore_path.write_text("".join(new_lines), encoding="utf-8")
