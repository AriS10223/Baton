"""
pr_template.py -- PR template writer for ``baton init``.

Creates ``.github/pull_request_template.md`` with WHY: and BATON:
markers so PR descriptions feed into ``baton init --scan --skip-pr-history``.

Called from ``baton init`` (all runs, not just --scan).

If the file already exists, it is NEVER modified or overwritten --
a clear warning is printed instead.

Public API:
    write_pr_template(repo_root, console=None) -> bool
    Returns True if the file was written, False if it already existed.
"""
from __future__ import annotations

from pathlib import Path

from rich.console import Console

_TEMPLATE_CONTENT = """\
## What changed
<!-- Brief description of the change -->

## Why (intent)
WHY:

## BATON entries touched
<!-- Decision/landmine/anti-decision IDs this PR relates to, if any -->
<!-- Example: d001, l003 -->
BATON:

## Checklist
- [ ] Ran `baton check --drift`
- [ ] Acknowledged any alerts (`baton check --drift --acknowledge <id> --reason "..."`)
"""

_TARGET = ".github/pull_request_template.md"


def write_pr_template(repo_root: Path, console: Console | None = None) -> bool:
    """Write the PR template if it doesn't already exist.

    Args:
        repo_root: Project root.
        console:   Rich Console for output (uses stdout Console if None).

    Returns:
        True if the file was written (created fresh).
        False if the file already existed (no changes made).
    """
    if console is None:
        console = Console(highlight=False)

    target = repo_root / _TARGET

    if target.exists():
        console.print(
            f"[yellow]WARN[/yellow]  {_TARGET} already exists -- not modified.",
            markup=True,
        )
        console.print(
            "      To enable WHY:/BATON: intent capture, add these sections manually:",
            markup=False,
        )
        console.print("        WHY:", markup=False)
        console.print("        BATON:", markup=False)
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_TEMPLATE_CONTENT, encoding="utf-8")
    console.print(f"[green]OK[/green]    Created {_TARGET}", markup=True)
    return True
