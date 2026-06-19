"""
install_skill.py -- ``baton install-skill``: install the baton-end Claude Code skill.

Writes ``.claude/skills/baton-end/SKILL.md`` from an embedded template into the
user's project.  This is a durable, user-committable file (unlike adapter outputs
which are gitignored and regenerated on every sync).

The skill body is intentionally thin and schema-free: it instructs the agent to
run ``baton end --diff-only`` and draft JSON matching *the contract that command
prints*.  Because the contract is emitted live, the installed skill never goes
stale when the delta schema changes -- no need to re-install after upgrades.

Idempotent: skips if the skill file already exists unless --force is given.
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()

# ── Skill template ─────────────────────────────────────────────────────────────
# Embedded as a string for reliable installation (no importlib.resources needed).
# The body deliberately references `baton end --diff-only` and `--apply` rather
# than hard-coding the JSON schema -- the schema is printed by --diff-only at
# runtime, so the skill auto-updates as the schema evolves.

_SKILL_TEMPLATE = """\
---
name: baton-end
description: >
  Capture session context into BATON.md at the end of a coding session.
  Use when: wrapping up / ending a session / switching AI tools /
  running low on context / before /compact / the user says "save context"
  or "baton end" or "capture session".
when_to_use: >
  Trigger automatically when the user is clearly wrapping up (e.g. "ok I'm
  done for now", "switching to Cursor", "save what we did", "before I run
  /compact"). Also invoke if the conversation is nearing its context limit.
---

Capture this session's work into BATON.md using the Baton CLI.

## Steps

1. **Get the diff and JSON contract** -- run this command and read its output:

   ```
   baton end --diff-only
   ```

   This prints the current git diff, project context, and the exact JSON
   schema Baton expects.

2. **Draft the delta JSON** -- using this session's conversation (decisions
   made, approaches rejected, landmines discovered, open questions raised),
   plus the diff output, write a JSON object matching the schema printed above.

   Guidelines:
   - `session.summary`: one sentence summarising what was accomplished.
   - `session.highlights`: 1-3 most significant achievements.
   - `sprint_done`: features clearly finished (use commit subjects as a guide).
   - `sprint_next`: TODOs or next steps visible in the diff or discussion.
   - `decisions`: architectural choices made in this session. Empty if none.
   - `anti_decisions`: approaches explicitly ruled out. Empty if none.
   - `landmines`: code that looks wrong but is intentional. Empty if none.
   - `open_questions`: unresolved questions the human must decide. Empty if none.
   - Prefer empty lists over guessing. Do NOT invent entries.

3. **Apply the delta** -- pipe your JSON to Baton:

   ```
   echo '<your JSON here>' | baton end --apply
   ```

   Or write to a temp file first:
   ```
   baton end --apply < delta.json
   ```

   Baton will show a per-section review UI. If the piped JSON is empty or
   malformed, it automatically falls back to a structural heuristic summary.

4. Confirm `BATON.md` was updated and synced to all agent files.
"""


def run_install_skill(repo_root: Path, force: bool = False) -> None:
    """Install the baton-end Claude Code skill into *.repo_root*/.claude/skills/."""
    skill_dir = repo_root / ".claude" / "skills" / "baton-end"
    skill_path = skill_dir / "SKILL.md"

    if skill_path.exists() and not force:
        console.print(
            f"[yellow]Skill already installed:[/yellow] {skill_path.relative_to(repo_root)}"
        )
        console.print("Use [bold]--force[/bold] to overwrite.")
        return

    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(_SKILL_TEMPLATE, encoding="utf-8")

    console.print(
        f"[green]+[/green] Installed [bold]{skill_path.relative_to(repo_root)}[/bold]"
    )
    console.print()
    console.print("[bold]Next steps:[/bold]")
    console.print(
        "  1. Commit this file: [cyan]git add .claude/skills/baton-end/SKILL.md[/cyan]"
    )
    console.print(
        "     (This is a durable project file -- unlike adapter outputs, it is NOT gitignored.)"
    )
    console.print(
        "  2. In Claude Code, say 'wrap up session' or run [cyan]/baton-end[/cyan]"
    )
    console.print(
        "     to capture session context without any API key."
    )
