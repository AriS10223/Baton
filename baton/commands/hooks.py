"""
hooks.py -- Baton git hook management.

Manages advisory (post-commit) and optional strict (pre-commit) drift-detection
hooks.  Each hook file uses the upsert_managed_block pattern so Baton can
update its own region without destroying user content or other tools' hooks.

Hook files live under .git/hooks/.  If .git is absent, a warning is printed.
"""
from __future__ import annotations

import stat
from pathlib import Path

from rich.console import Console

from ..adapters.base import upsert_managed_block

console = Console()

# ── Hook inner-content templates (go inside the managed block) ────────────────

# Advisory post-commit: runs drift check but NEVER blocks the commit.
_POST_COMMIT_INNER = """\
# Baton drift check (advisory, never blocks)
baton check --drift --quiet --fail-on warn 2>/dev/null || true"""

# Strict pre-commit: blocks commit if block-severity drift found.
_PRE_COMMIT_STRICT_INNER = """\
# Baton strict drift check (blocks commit on block-severity violations)
baton check --drift --staged --quiet --fail-on block; exit $?"""

# Reminder-only pre-commit (installed by baton init, non-blocking).
_PRE_COMMIT_REMINDER_INNER = """\
# Baton reminder (never blocks)
printf "\\n"
printf "  Baton: switching AI tools soon?\\n"
printf "  Run 'baton end' first to capture session context.\\n"
printf "\\n"
exit 0"""


def _write_hook(hooks_dir: Path, name: str, inner_content: str) -> str:
    """Install or update a managed block inside a git hook file.

    - If the hook file is absent: create it with #!/bin/sh + the managed block, chmod +x
    - If the hook file exists: upsert only the managed block region, preserve rest
    - Returns "created" | "updated" | "unchanged"
    """
    hook_path = hooks_dir / name
    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        updated = upsert_managed_block(existing, inner_content)
        if updated == existing:
            return "unchanged"
        hook_path.write_text(updated, encoding="utf-8")
        return "updated"
    else:
        content = "#!/bin/sh\n" + upsert_managed_block("", inner_content)
        hook_path.write_text(content, encoding="utf-8")
        mode = hook_path.stat().st_mode
        hook_path.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return "created"


def install_post_commit_hook(hooks_dir: Path) -> str:
    """Install the advisory post-commit drift-check hook. Returns "created"|"updated"|"unchanged"."""
    return _write_hook(hooks_dir, "post-commit", _POST_COMMIT_INNER)


def install_pre_commit_reminder(hooks_dir: Path) -> str:
    """Install the non-blocking pre-commit reminder hook. Returns "created"|"updated"|"unchanged"."""
    return _write_hook(hooks_dir, "pre-commit", _PRE_COMMIT_REMINDER_INNER)


def install_pre_commit_strict(hooks_dir: Path) -> str:
    """Install the blocking strict pre-commit hook (opt-in only). Returns "created"|"updated"|"unchanged"."""
    return _write_hook(hooks_dir, "pre-commit", _PRE_COMMIT_STRICT_INNER)


def run_hooks_install(repo_root: Path, strict: bool = False) -> None:
    """Install Baton drift-detection git hooks.

    Always (re)installs the advisory post-commit hook.
    With --strict, also installs the blocking pre-commit hook.
    """
    git_dir = repo_root / ".git"
    if not git_dir.is_dir():
        console.print("[hooks] No .git directory found. Run git init first.")
        return

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)

    result = install_post_commit_hook(hooks_dir)
    console.print(f"[hooks] post-commit: {result}")

    if strict:
        result = install_pre_commit_strict(hooks_dir)
        console.print(f"[hooks] pre-commit (strict): {result}")
