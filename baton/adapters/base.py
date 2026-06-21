"""
adapters/base.py — BaseAdapter interface and shared utilities.

Every adapter must implement:
    render(data: dict) -> str          inner block content (no markers)
    file_path() -> str                 relative path to the agent config file

The managed-block pattern ensures ``baton sync`` never clobbers hand-written
content in CLAUDE.md, AGENTS.md, etc.  Only the region between the markers
is ever rewritten::

    <!-- BATON:START — auto-generated, do not edit by hand -->
    ... rendered content ...
    <!-- BATON:END -->

All five adapter classes call ``render_markdown_context()`` (defined below)
and may override ``prepare_file()`` for tool-specific file structure
(e.g. Cursor's MDC front-matter).

To add a new agent tool, create a file in adapters/, subclass ``BaseAdapter``,
implement ``render()`` and ``file_path()``.  That's ~50 lines of code.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod

# ── Managed-block markers ─────────────────────────────────────────────────────

MARKER_START = "<!-- BATON:START — auto-generated, do not edit by hand -->"
MARKER_END = "<!-- BATON:END -->"

def upsert_named_block(
    text: str, inner: str, start_marker: str, end_marker: str
) -> str:
    """Insert or replace a delimited block identified by *start_marker* / *end_marker*.

    Generic version of ``upsert_managed_block`` that accepts explicit markers.

    - If the block is already present, replaces only the inner content.
    - If not present, appends the block (with a blank-line separator when
      *text* is non-empty).

    ``re.sub`` replacement uses a lambda so that ``\\n`` in YAML-derived data
    is never misinterpreted as a regex back-reference escape.
    """
    block_re = re.compile(
        re.escape(start_marker) + r"\n(.*?)\n" + re.escape(end_marker),
        re.DOTALL,
    )
    block = f"{start_marker}\n{inner}\n{end_marker}"
    if block_re.search(text):
        return block_re.sub(lambda _m: block, text)
    separator = "\n\n" if text.strip() else ""
    return text.rstrip("\n") + separator + block + "\n"


def extract_named_block(
    text: str, start_marker: str, end_marker: str
) -> str | None:
    """Return the inner content between *start_marker* and *end_marker*, or None."""
    block_re = re.compile(
        re.escape(start_marker) + r"\n(.*?)\n" + re.escape(end_marker),
        re.DOTALL,
    )
    m = block_re.search(text)
    return m.group(1) if m else None


def upsert_managed_block(existing_text: str, inner_content: str) -> str:
    """Insert or replace the Baton-managed block inside *existing_text*.

    - If the block is already present, replaces the inner content.
    - If not present, appends the block (with a blank-line separator when
      *existing_text* is non-empty).

    The outer file content is never touched outside the marker region.
    """
    return upsert_named_block(existing_text, inner_content, MARKER_START, MARKER_END)


def extract_managed_block(text: str) -> str | None:
    """Return the inner content of the Baton-managed block, or None if absent."""
    return extract_named_block(text, MARKER_START, MARKER_END)


# ── Shared markdown renderer ──────────────────────────────────────────────────

def render_markdown_context(data: dict, tool_name: str = "") -> str:
    """Render a BATON.md data dict into a readable markdown context document.

    Called by all five adapters.  *tool_name* is shown in the header line
    (e.g. ``"claude-code"``, ``"cursor"``).
    """
    lines: list[str] = []

    # ── Helpers ───────────────────────────────────────────────────

    def _val(*keys, default=""):
        v = data
        for k in keys:
            if not isinstance(v, dict):
                return default
            v = v.get(k, default)
        return v if v is not None else default

    def _lst(*keys):
        v = _val(*keys, default=[])
        return v if isinstance(v, list) else []

    # ── Header ────────────────────────────────────────────────────
    tool_line = f" · via {tool_name}" if tool_name else ""
    last_updated = _val("last_updated")
    lines.append("# Baton — Project Context")
    lines.append("")
    if last_updated:
        lines.append(f"> Last synced: {last_updated}{tool_line}")
        lines.append(">")
    lines.append("> **Test:** could a new agent read this and contribute without breaking anything?")
    lines.append("")

    # ── Project brief ─────────────────────────────────────────────
    name = _val("project", "name")
    purpose = _val("project", "purpose")
    target_user = _val("project", "target_user")
    stage = _val("project", "stage")

    if name or purpose:
        header = f"## {name}" if name else "## Project"
        lines.append(header)
        if purpose:
            lines.append("")
            lines.append(str(purpose))
        meta = []
        if target_user:
            meta.append(f"**Who:** {target_user}")
        if stage:
            meta.append(f"**Stage:** {stage}")
        if meta:
            lines.append("")
            lines.append("  ".join(meta))
        lines.append("")

    # ── Architecture ──────────────────────────────────────────────
    overview = _val("architecture", "overview")
    entry_point = _val("architecture", "entry_point")
    data_flow = _val("architecture", "data_flow")
    key_dirs = _lst("architecture", "key_directories")

    if overview or entry_point or data_flow or key_dirs:
        lines.append("## Architecture")
        if overview:
            lines.append("")
            lines.append(str(overview))
        if entry_point:
            lines.append("")
            lines.append(f"**Entry point:** `{entry_point}`")
        if data_flow:
            lines.append(f"**Data flow:** {data_flow}")
        if key_dirs:
            lines.append("")
            lines.append("| Path | Purpose |")
            lines.append("|------|---------|")
            for d in key_dirs:
                if isinstance(d, dict):
                    lines.append(f"| `{d.get('path', '')}` | {d.get('purpose', '')} |")
        lines.append("")

    # ── Stack ─────────────────────────────────────────────────────
    stack = _lst("stack")
    if stack:
        lines.append("## Tech Stack")
        lines.append("")
        lines.append("| Tool | Version | Why | Gotchas |")
        lines.append("|------|---------|-----|---------|")
        for s in stack:
            if isinstance(s, dict):
                gotchas = s.get("gotchas") or "—"
                lines.append(
                    f"| {s.get('tool', '')} | {s.get('version', '')} "
                    f"| {s.get('why', '')} | {gotchas} |"
                )
        lines.append("")

    # ── Laws ──────────────────────────────────────────────────────
    laws = _lst("laws")
    if laws:
        lines.append("## Laws (Never Violate)")
        lines.append("")
        lines.append("> Hard constraints. Agents must not override these — ever.")
        lines.append("")
        for i, law in enumerate(laws, 1):
            lines.append(f"{i}. {law}")
        lines.append("")

    # ── Current sprint ────────────────────────────────────────────
    sprint_goal = _val("current_sprint", "goal")
    done = _lst("current_sprint", "done")
    in_progress = _lst("current_sprint", "in_progress")
    blocked = _lst("current_sprint", "blocked")
    next_up = _lst("current_sprint", "next")

    if sprint_goal or done or in_progress or blocked or next_up:
        goal_str = f": {sprint_goal}" if sprint_goal else ""
        lines.append(f"## Current Sprint{goal_str}")
        lines.append("")

        if done:
            lines.append("### ✅ Done")
            for item in done:
                if isinstance(item, dict):
                    conf = f" *(confidence: {item['confidence']})*" if item.get("confidence") else ""
                    notes = f" — {item['notes']}" if item.get("notes") else ""
                    lines.append(f"- {item.get('feature', '')}{conf}{notes}")
            lines.append("")

        if in_progress:
            lines.append("### 🔄 In Progress")
            for item in in_progress:
                if isinstance(item, dict):
                    owner = f" *(Owner: {item['owner']})*" if item.get("owner") else ""
                    lines.append(f"- **{item.get('feature', '')}**{owner}")
                    if item.get("context"):
                        lines.append(f"  - Context: {item['context']}")
                    if item.get("blockers"):
                        bs = item["blockers"]
                        bl = bs if isinstance(bs, list) else [bs]
                        if bl:
                            lines.append(f"  - Blockers: {', '.join(str(b) for b in bl)}")
            lines.append("")

        if blocked:
            lines.append("### 🚧 Blocked")
            for item in blocked:
                if isinstance(item, dict):
                    reason = f": {item['reason']}" if item.get("reason") else ""
                    workaround = f" (workaround: {item['workaround']})" if item.get("workaround") else ""
                    lines.append(f"- **{item.get('feature', '')}**{reason}{workaround}")
            lines.append("")

        if next_up:
            lines.append("### 📋 Up Next")
            for item in next_up:
                if isinstance(item, dict):
                    pri = f" *[{item['priority']}]*" if item.get("priority") else ""
                    lines.append(f"- {item.get('feature', '')}{pri}")
            lines.append("")

    # ── Decisions ─────────────────────────────────────────────────
    decisions = _lst("decisions")
    if decisions:
        lines.append("## Key Decisions")
        lines.append("")
        lines.append("| # | Decision | Why | When | Tool |")
        lines.append("|---|---------|-----|------|------|")
        for d in decisions:
            if isinstance(d, dict):
                lines.append(
                    f"| {d.get('id', '')} | {d.get('what', '')} "
                    f"| {d.get('why', '')} | {d.get('made', '')} | {d.get('made_in', '')} |"
                )
        lines.append("")

    # ── Anti-decisions ────────────────────────────────────────────
    anti = _lst("anti_decisions")
    if anti:
        lines.append("## Anti-Decisions (Rejected Approaches)")
        lines.append("")
        lines.append("> These were explicitly ruled out. Don't re-suggest them.")
        lines.append("")
        lines.append("| # | Rejected | Why | When |")
        lines.append("|---|---------|-----|------|")
        for a in anti:
            if isinstance(a, dict):
                lines.append(
                    f"| {a.get('id', '')} | {a.get('rejected', '')} "
                    f"| {a.get('why', '')} | {a.get('ruled_out', '')} |"
                )
        lines.append("")

    # ── Landmines ─────────────────────────────────────────────────
    landmines = _lst("landmines")
    if landmines:
        lines.append("## Landmines (Looks Wrong, But Intentional)")
        lines.append("")
        lines.append("> Do NOT 'fix' these. They are correct as-is.")
        lines.append("")
        for lm in landmines:
            if isinstance(lm, dict):
                lines.append(f"**`{lm.get('location', '')}`**")
                lines.append(f"- Looks like: {lm.get('looks_like', '')}")
                lines.append(f"- Actually: {lm.get('actually', '')}")
                lines.append("")

    # ── Open questions ────────────────────────────────────────────
    open_qs = _lst("open_questions")
    if open_qs:
        lines.append("## Open Questions")
        lines.append("")
        lines.append("> Do NOT make unilateral decisions on these. Surface them to the human first.")
        lines.append("")
        for q in open_qs:
            if isinstance(q, dict):
                icon = {"open": "🔴", "discussed": "🟡", "resolved": "🟢"}.get(
                    q.get("status", ""), "⚪"
                )
                lines.append(f"{icon} **[{q.get('id', '')}]** {q.get('question', '')}")
                if q.get("context"):
                    lines.append(f"  - Context: {q['context']}")
                if q.get("discussion"):
                    lines.append(f"  - Discussion: {q['discussion']}")
                blocking = q.get("blocking", [])
                if isinstance(blocking, list) and blocking:
                    lines.append(f"  - Blocking: {', '.join(str(b) for b in blocking)}")
                if q.get("resolution") and q.get("status") == "resolved":
                    lines.append(f"  - Resolution: {q['resolution']}")
                lines.append("")

    # ── Recent sessions ───────────────────────────────────────────
    sessions = _lst("sessions")
    if sessions:
        # Show the 3 most recent sessions, newest first.
        recent = list(sessions[-3:])
        recent.reverse()
        lines.append("## Recent Sessions")
        lines.append("")
        for s in recent:
            if isinstance(s, dict):
                date = s.get("date") or ""
                s_tool = s.get("tool") or ""
                summary = s.get("summary") or ""
                meta = date
                if s_tool:
                    meta += f" via {s_tool}"
                lines.append(f"- {meta} -- {summary}")
        lines.append("")

    # ── Session-end protocol (non-Claude agents only) ─────────────
    # Claude Code has a dedicated skill (.claude/skills/baton-end/SKILL.md)
    # that covers this protocol; injecting it here would be redundant.
    # All other agents (Codex, Gemini, Cursor, Copilot) receive these
    # instructions via this managed block since they lack native skill support.
    if tool_name and tool_name != "claude-code":
        lines.append("## Session-End Protocol")
        lines.append("")
        lines.append(
            "When wrapping up a session, switching AI tools, or running low on context, "
            "capture session memory into BATON.md using one of these methods:"
        )
        lines.append("")
        lines.append("**Preferred (zero API cost, highest fidelity):**")
        lines.append("")
        lines.append("1. Run `baton end --diff-only` to see the current git diff, project context,")
        lines.append("   and the exact JSON schema Baton expects.")
        lines.append("2. Draft a JSON delta matching that schema, incorporating decisions,")
        lines.append("   anti-decisions, landmines, and open questions from this session.")
        lines.append("3. Run `baton end --apply` and pipe your JSON to it:")
        lines.append("   `echo '<your JSON>' | baton end --apply`")
        lines.append("   or write to a temp file and: `baton end --apply < delta.json`")
        lines.append("")
        lines.append("**Fallback (zero cost, structural only):**")
        lines.append("")
        lines.append("Run bare `baton end` -- derives a summary from git stats alone. No API key needed.")
        lines.append("")
        lines.append("**API-backed summary (opt-in, requires key):**")
        lines.append("")
        lines.append("Run `baton end --api` with `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) set.")
        lines.append("")

    return "\n".join(lines)


# ── Abstract base class ───────────────────────────────────────────────────────

class BaseAdapter(ABC):
    """
    Interface every Baton adapter must implement.

    Adding support for a new agent tool is ~50 lines of code::

        class MyToolAdapter(BaseAdapter):
            def render(self, data: dict) -> str:
                return render_markdown_context(data, tool_name="mytool")

            def file_path(self) -> str:
                return "MYTOOL.md"
    """

    @abstractmethod
    def render(self, data: dict) -> str:
        """Convert parsed BATON.md data to this agent's context string.

        Returns only the *inner* content of the managed block (no START/END
        markers).  The caller (``sync.py``) wraps it in ``upsert_managed_block``.
        """

    @abstractmethod
    def file_path(self) -> str:
        """Relative path to the agent config file.

        Examples: ``"CLAUDE.md"``, ``"AGENTS.md"``, ``".cursor/rules/baton.mdc"``
        """

    def prepare_file(self, existing_content: str, rendered_inner: str) -> str:
        """Produce the full file content from the current file and the new block.

        Default implementation calls ``upsert_managed_block``.  Adapters that
        need special file structure (e.g. Cursor's MDC front-matter) override this.
        """
        return upsert_managed_block(existing_content, rendered_inner)
