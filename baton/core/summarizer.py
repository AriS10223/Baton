"""
summarizer.py -- Provider-agnostic prompt builder and delta parser for baton end.

``build_prompt`` returns (system, user) separately so the Anthropic provider
can mark the static system block with cache_control for prompt caching.

``summarize`` is the default LLM seam injected into run_end(); tests
replace it with a fake that returns canned JSON.

``parse_delta`` tolerates code-fenced JSON, prose-wrapped JSON, and clean JSON.
"""
from __future__ import annotations

import json
import re

from ..core.config import BatonConfig
from ..core.schema import feature_label

# ── Static system block ───────────────────────────────────────────────────────
# This text is identical on every baton end run, so the Anthropic provider
# marks it with cache_control=ephemeral for cross-run prompt caching.

JSON_SPEC = """\
Respond with ONLY a valid JSON object -- no prose, no markdown fences.
Required shape:

{
  "session": {
    "summary": "<one-sentence summary of what was accomplished>",
    "highlights": ["<key achievement 1>", "<key achievement 2>"]
  },
  "sprint_done": [
    "<feature or task now complete>",
    "..."
  ],
  "sprint_next": [
    {"feature": "<what to do next>", "priority": "high|medium|low"},
    "..."
  ]
}

Rules:
- sprint_done: strings naming things clearly finished in this session
- sprint_next: objects with "feature" (string) and "priority" (high|medium|low)
- Both lists may be empty ([]) if nothing fits
- session.highlights: 1-3 short strings on the most significant changes
- Do NOT invent features not visible in the diff
"""

SYSTEM_INSTRUCTIONS = (
    "You are a developer tool that analyses git diffs and generates structured "
    "context updates for an AI agent onboarding document called BATON.md.\n\n"
    "Given a project brief and a git diff, produce a short accurate summary of "
    "what was accomplished, which sprint items are now done, and what should come "
    "next. Be concise. Use plain English.\n\n"
    + JSON_SPEC
)


# ── Prompt builder ────────────────────────────────────────────────────────────

def build_prompt(diff_text: str, data: dict) -> tuple[str, str]:
    """Return ``(system, user)`` strings for the LLM call.

    ``system`` is the static instruction block -- cacheable by the provider.
    ``user``   contains per-run context: project brief, current sprint, diff.
    """
    project = data.get("project") or {}
    name = project.get("name") or "Unknown project"
    purpose = project.get("purpose") or "(no purpose set)"
    stage = project.get("stage") or ""

    brief_lines = [f"Project: {name}", f"Purpose: {purpose}"]
    if stage:
        brief_lines.append(f"Stage: {stage}")

    sprint = data.get("current_sprint") or {}
    sprint_goal = sprint.get("goal") or "(no sprint goal set)"
    sprint_lines = [f"Goal: {sprint_goal}"]

    for key, label in [("done", "Done"), ("in_progress", "In progress"), ("next", "Up next")]:
        items = sprint.get(key) or []
        if items:
            sprint_lines.append(f"{label}: {', '.join(feature_label(i) for i in items)}")

    diff_section = diff_text.strip() if diff_text.strip() else "(no diff -- working tree is clean)"

    user = "\n".join([
        "=== PROJECT BRIEF ===",
        "\n".join(brief_lines),
        "",
        "=== CURRENT SPRINT ===",
        "\n".join(sprint_lines),
        "",
        "=== GIT DIFF (this session) ===",
        diff_section,
    ])

    return SYSTEM_INSTRUCTIONS, user


# ── Default LLM seam ─────────────────────────────────────────────────────────

def summarize(system: str, user: str, config: BatonConfig) -> str:
    """Dispatch to the configured LLM provider.

    This is the callable injected into run_end() by default; tests replace
    it with a fake that returns canned JSON without making a network call.

    Signature must match: ``(system: str, user: str, config: BatonConfig) -> str``
    """
    from ..llm import get_provider
    provider = get_provider(config)
    model = config.model or provider.default_model
    return provider.complete(system, user, model)


# ── Response parser ───────────────────────────────────────────────────────────

def parse_delta(raw: str) -> dict:
    """Extract and parse the JSON delta from a raw LLM response string.

    Tolerates:
    - Pure JSON
    - JSON inside triple-backtick code fences (```json ... ```)
    - Prose text before/after the JSON object

    Raises:
        ValueError: if no valid JSON object can be extracted.
    """
    text = raw.strip()

    # Strip markdown fences if present.  Prefer an explicit ```json fence;
    # fall back to any fence.  If the extracted content has no '{', it's not
    # the JSON block (e.g. a diff example) — skip it and scan the full text.
    fence_match = re.search(r"```json\s*([\s\S]*?)```", text)
    if not fence_match:
        fence_match = re.search(r"```\s*([\s\S]*?)```", text)
    if fence_match:
        candidate = fence_match.group(1).strip()
        if "{" in candidate:
            text = candidate

    # Extract the outermost {...} block in case there's surrounding prose.
    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        text = brace_match.group(0)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Could not parse JSON from LLM response: {exc}\n"
            f"Raw response (first 500 chars):\n{raw[:500]}"
        ) from exc

    # Coerce to the expected shape with safe defaults.
    session_raw = data.get("session") or {}
    return {
        "session": {
            "summary": str(session_raw.get("summary") or ""),
            "highlights": [str(h) for h in (session_raw.get("highlights") or [])],
        },
        "sprint_done": [str(x) for x in (data.get("sprint_done") or [])],
        "sprint_next": [
            {
                "feature": (
                    str(x.get("feature") or x)
                    if isinstance(x, dict)
                    else str(x)
                ),
                "priority": (
                    str(x.get("priority") or "medium")
                    if isinstance(x, dict)
                    else "medium"
                ),
            }
            for x in (data.get("sprint_next") or [])
        ],
    }
