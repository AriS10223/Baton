# Baton — Open Source Context Sync for Vibe Coders

> One living onboarding doc. Every agent. Every teammate. Always in sync.

---

## The Problem

When you switch between Claude Code, Cursor, and Codex mid-session — or collaborate with a friend on a different tool — each agent starts completely blind. It doesn't know you chose Streamlit over Flask, that auth is handled by Supabase, or that the filter sidebar is half-built. You re-explain. The agent makes wrong assumptions. Code breaks. Time is lost.

**Baton solves this by maintaining a single living onboarding document — `BATON.md` — that any agent can read to get up to speed instantly, the same way a new engineer would on day one.**

---

## What Makes Baton Different

| Feature | Caliber | claude-mem | **Baton** |
|---|---|---|---|
| Generates agent config files | ✅ | ❌ | ✅ |
| Syncs across Claude/Cursor/Codex | ✅ | ❌ | ✅ |
| Session-end auto-summary | ❌ | ✅ | ✅ |
| Human review gate before commit | ❌ | ❌ | ✅ |
| Token-limit trigger | ❌ | ❌ | ✅ |
| Onboarding doc framing | ❌ | ❌ | ✅ |
| Anti-decisions captured | ❌ | ❌ | ✅ |
| Open questions tracked | ❌ | ❌ | ✅ |
| Team collaboration / git-native PR | ❌ | ❌ | ✅ |

---

## Core Mental Model

```
Think of BATON.md as the onboarding doc you'd give a new engineer.
Not a session log. Not a config file. A living brief.

The test: could a new agent read only this file and start
contributing without breaking anything?
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                     Your Codebase                       │
│                                                         │
│  BATON.md  ←──── Single Source of Truth                 │
│      │                                                  │
│      ├──── sync ────► CLAUDE.md                         │
│      ├──── sync ────► AGENTS.md                         │
│      ├──── sync ────► .cursor/rules/*.mdc               │
│      ├──── sync ────► GEMINI.md                         │
│      └──── sync ────► .github/copilot-instructions.md   │
└─────────────────────────────────────────────────────────┘
         ▲
         │
┌────────┴────────┐
│   Baton CLI     │
│                 │
│  baton init     │   Sets up BATON.md + pre-commit hooks
│  baton sync     │   Pushes BATON.md → all agent files
│  baton end      │   Triggers session summary + review
│  baton status   │   Shows drift across agent files
└─────────────────┘
```

---

## The Session Flow

```
1. Session running (Claude Code / Cursor / Codex)
         │
         ▼
2. Tokens nearing limit → baton detects via git hook OR manual `baton end`
         │
         ▼
3. Pass 1: Structural parser scans git diff
   → files changed, deps added, dirs created
         │
         ▼
4. Pass 2: AI summarizer reads diff + existing BATON.md
   → generates YAML delta (decisions, state, open questions)
         │
         ▼
5. Human review: terminal diff view
   → approve / edit / reject each proposed change
         │
         ▼
6. On approval → BATON.md updated → baton sync runs
   → all agent files updated automatically
         │
         ▼
7. Next agent session reads CLAUDE.md / AGENTS.md / .cursorrules
   → picks up seamlessly
```

---

## Phases

---

### Phase 1 — Solo Vibe Coder (MVP)

**Target:** Individual developers switching between Claude Code, Cursor, Codex mid-session.

**Deliverable:** A Python CLI tool. No UI. No server. No dependencies beyond git and an LLM API key.

**Commands:**

```bash
baton init              # scaffold BATON.md + install pre-commit hooks
baton sync              # push BATON.md → all detected agent files
baton end               # trigger session summary + open review
baton status            # show which agent files are in sync vs drifted
baton score             # evaluate BATON.md quality (completeness check)
```

**Adapters (Phase 1):**
- `claude` → `CLAUDE.md`
- `codex` → `AGENTS.md`
- `cursor` → `.cursor/rules/baton.mdc`
- `gemini` → `GEMINI.md`
- `copilot` → `.github/copilot-instructions.md`

**Detection:** Baton scans your repo root for existing agent files to determine which adapters to activate. No config needed.

---

### Phase 2 — Small Collab Teams / Hackathons

**Target:** 2-5 person teams, each using different tools, pushing to a shared GitHub repo.

**New in Phase 2:**
- `BATON.md` is git-tracked and treated as code
- Session-end summary opens as a PR against `BATON.md` (not a direct commit)
- Teammates review the PR exactly like a code review
- On merge, CI automatically runs `baton sync` to propagate to all agent files
- `baton pull` — fetches latest `BATON.md` before starting a session

**GitHub Actions integration:**

```yaml
# .github/workflows/baton-sync.yml
on:
  push:
    paths:
      - 'BATON.md'
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: pip install baton-cli
      - run: baton sync --all
      - run: git commit -am "baton: sync agent files" && git push
```

---

### Phase 3 — Broader Teams (Future)

- Web dashboard for context drift visualization
- Conflict resolution UI when two teammates' summaries contradict
- Team analytics (which decisions get revisited most, where context breaks down)
- MCP server so agents can query BATON.md directly via tool calls

---

## Repository Structure

```
baton/
├── baton/
│   ├── cli.py              # entry point, command routing
│   ├── init.py             # baton init logic
│   ├── sync.py             # BATON.md → agent file sync
│   ├── end.py              # session end + review flow
│   ├── status.py           # drift detection
│   ├── score.py            # quality scoring
│   ├── core/
│   │   ├── parser.py       # Pass 1: git diff structural parser
│   │   ├── summarizer.py   # Pass 2: AI-powered delta generator
│   │   ├── reviewer.py     # terminal diff review UI
│   │   └── schema.py       # BATON.md schema + validation
│   └── adapters/
│       ├── base.py         # adapter interface
│       ├── claude.py       # → CLAUDE.md
│       ├── codex.py        # → AGENTS.md
│       ├── cursor.py       # → .cursor/rules/baton.mdc
│       ├── gemini.py       # → GEMINI.md
│       └── copilot.py      # → .github/copilot-instructions.md
├── tests/
│   ├── test_parser.py
│   ├── test_summarizer.py
│   └── test_adapters.py
├── docs/
│   ├── getting-started.md
│   ├── schema-reference.md
│   └── contributing.md
├── BATON.md                # baton eats its own dog food
├── pyproject.toml
├── README.md
└── CONTRIBUTING.md
```

The `adapters/` folder is the key to community extensibility. Adding a new agent = adding one file that implements the base adapter interface. A first-time contributor can add Windsurf support in under 50 lines.

---

## The BATON.md Schema

This is the full schema. Every field is documented with its purpose and how the summarizer should populate it.

```yaml
# ============================================================
# BATON.md — Living Onboarding Document
# Maintained by Baton CLI. Human-reviewed before every commit.
# Test: could a new agent read this and contribute without
# breaking anything?
# ============================================================

baton_version: "1.0"
last_updated: "2026-06-02"
last_session_tool: "claude-code"  # claude-code | cursor | codex | gemini

# ------------------------------------------------------------
# SECTION 1 — Project Brief
# What is this, who is it for, what problem does it solve.
# Agents use this for intent alignment — stops suggestions
# that don't fit the product's purpose.
# ------------------------------------------------------------
project:
  name: ""
  purpose: ""         # one sentence: what problem does this solve
  target_user: ""     # who uses this
  stage: ""           # idea | prototype | mvp | production

# ------------------------------------------------------------
# SECTION 2 — Architecture
# How the codebase is structured and why.
# Stops agents restructuring things that are intentional.
# ------------------------------------------------------------
architecture:
  overview: ""        # 2-3 sentences max
  key_directories:
    - path: "src/"
      purpose: ""
    - path: "tests/"
      purpose: ""
  entry_point: ""     # e.g. "app.py", "src/index.ts"
  data_flow: ""       # brief description of how data moves through the system

# ------------------------------------------------------------
# SECTION 3 — Stack
# Not just WHAT we use but WHY and at what version.
# The "why" is what stops agents switching frameworks.
# Gotchas stop agents breaking things by upgrading.
# ------------------------------------------------------------
stack:
  - tool: ""
    version: ""
    why: ""           # the reason this was chosen
    gotchas: ""       # things that will break if you're not careful
    # Example:
    # - tool: Streamlit
    #   version: "1.32.0"
    #   why: "Non-technical users need low-friction UI"
    #   gotchas: "Don't upgrade past 1.32 — breaks custom component"

# ------------------------------------------------------------
# SECTION 4 — Laws
# Hard constraints that never change regardless of what the
# agent thinks is a good idea.
# Written as imperative statements. Never deleted once added.
# ------------------------------------------------------------
laws:
  - ""
  # Examples:
  # - "Never use TypeScript. This is a Python-only project."
  # - "Auth is handled by Supabase only. Never implement custom auth."
  # - "All DB writes go through the service layer. Never write direct SQL in routes."
  # - "Do not add new dependencies without updating requirements.txt."

# ------------------------------------------------------------
# SECTION 5 — Current Sprint
# What we are building right now.
# Gives the agent immediate task context without needing
# a full project walkthrough.
# ------------------------------------------------------------
current_sprint:
  goal: ""            # the one-sentence objective of this sprint
  done:
    - feature: ""
      confidence: ""  # stable | fragile | untested
      notes: ""       # anything the next agent should know
  in_progress:
    - feature: ""
      owner: ""       # "Aryan on Claude Code" or "Ethan on Cursor"
      last_touched: ""
      context: ""     # what was being attempted
      blockers: []
  blocked:
    - feature: ""
      reason: ""
      workaround: ""  # what to do in the meantime
  next:
    - feature: ""
      priority: ""    # high | medium | low
      dependencies: []

# ------------------------------------------------------------
# SECTION 6 — Decisions
# Things explicitly chosen during a session.
# Append-only — never modify or delete existing decisions.
# Each decision needs evidence from the git diff to be added.
# ------------------------------------------------------------
decisions:
  - id: "d001"
    what: ""
    why: ""
    made: ""          # date: YYYY-MM-DD
    made_in: ""       # which tool/session
    # Example:
    # - id: "d001"
    #   what: "Using SQLite for local dev, Postgres in prod"
    #   why: "Simpler local setup, same SQL dialect"
    #   made: "2026-06-01"
    #   made_in: "claude-code"

# ------------------------------------------------------------
# SECTION 7 — Anti-Decisions
# Things explicitly ruled out and why.
# This is the most underbuilt section in the industry.
# Stops agents suggesting things you already rejected.
# Append-only — never modify or delete.
# ------------------------------------------------------------
anti_decisions:
  - id: "a001"
    rejected: ""      # what was ruled out
    why: ""           # the reason
    ruled_out: ""     # date: YYYY-MM-DD
    # Example:
    # - id: "a001"
    #   rejected: "TypeScript frontend"
    #   why: "Scope too large for MVP, team is Python-first"
    #   ruled_out: "2026-06-01"

# ------------------------------------------------------------
# SECTION 8 — Landmines
# Things that LOOK wrong but are intentional.
# Stops agents "fixing" things that aren't broken.
# ------------------------------------------------------------
landmines:
  - location: ""      # file path or component name
    looks_like: ""    # what it appears to be
    actually: ""      # what it really is and why it's correct
    # Example:
    # - location: "auth/callback.py"
    #   looks_like: "Broken redirect with missing return statement"
    #   actually: "Intentional for OAuth PKCE flow — the redirect happens via header"

# ------------------------------------------------------------
# SECTION 9 — Open Questions
# Unresolved things the next agent must know are unresolved.
# Three statuses: open | discussed | resolved
# "discussed" is the dangerous middle ground nobody captures —
# something was talked about but not decided.
# Agents must NEVER make unilateral decisions on open questions.
# ------------------------------------------------------------
open_questions:
  - id: "q001"
    question: ""
    context: ""       # why this is a question, what's at stake
    raised: ""        # date: YYYY-MM-DD
    raised_by: ""     # "Aryan" or "Claude Code session"
    status: ""        # open | discussed | resolved
    discussion: ""    # notes from any discussion so far
    resolution: ""    # only populated when status = resolved
    resolved_date: ""
    blocking: []      # features blocked until this is resolved
    # Example:
    # - id: "q001"
    #   question: "Should filters be multi-select or single select?"
    #   context: "Multi-select is more powerful but adds UI complexity"
    #   raised: "2026-06-01"
    #   raised_by: "Claude Code session"
    #   status: "discussed"
    #   discussion: "Leaning multi-select but need to test with real users"
    #   blocking: ["filter-sidebar"]

# ------------------------------------------------------------
# SECTION 10 — Session Log
# Auto-generated. Human-reviewed before appending.
# A record of what happened in each session.
# Not for agents to read in detail — the sections above
# are the extracted truth. This is audit history.
# ------------------------------------------------------------
sessions:
  - date: ""
    tool: ""          # claude-code | cursor | codex | gemini
    owner: ""         # who ran this session
    summary: ""       # one-sentence summary of what happened
    decisions_made: []   # ids of decisions added this session
    questions_raised: [] # ids of questions raised this session
    state_changes: []    # what moved between done/in_progress/blocked
```

---

## Summarizer Prompt (Pass 2)

This is the exact prompt used when generating a session delta:

```
You are maintaining a living onboarding document for a codebase.
A new engineer — human or AI — should be able to read BATON.md
and contribute without breaking anything.

CURRENT BATON.md:
{current_baton_content}

SESSION CHANGES (from git diff parser):
{pass1_structural_output}

SESSION TOOL: {tool}
SESSION OWNER: {owner}
SESSION DATE: {date}

Your job is to generate ONLY the delta — new entries to add
to BATON.md based on what happened this session.

Rules:
1. Only add decisions evidenced by actual code changes in the diff.
   Never infer a decision that isn't visible in the code.
2. Never modify or delete existing decisions or anti_decisions.
3. If something was ruled out, add it to anti_decisions with why.
4. Move features between state buckets based on diff evidence.
5. If you're unsure whether something is a decision or open question,
   mark it as open_question with status: discussed.
6. Add landmines for anything that looks wrong but appears intentional.
7. Add stack gotchas if a version was pinned or a dependency had issues.
8. If a law was established (e.g. "never do X" was said or coded around),
   add it to laws.

Output ONLY valid YAML matching the BATON.md schema.
Output ONLY the delta — new entries, not the full file.
No prose. No explanation. Just the YAML delta.
```

---

## Pass 1: Git Diff Parser — What It Extracts

```python
# core/parser.py — structural extraction from git diff
# No AI involved. Deterministic. Ground truth.

{
  "files_changed": ["src/app.py", "requirements.txt"],
  "files_added": ["src/filters.py"],
  "files_deleted": [],
  "functions_added": ["render_filter_sidebar", "apply_filters"],
  "functions_removed": [],
  "dependencies_added": ["streamlit-multiselect==0.3.1"],
  "dependencies_removed": [],
  "directories_created": ["src/components/"],
  "env_vars_referenced": ["SUPABASE_URL", "SUPABASE_KEY"],
  "imports_added": ["from supabase import create_client"],
  "diff_size_lines": 87,
  "commit_messages": ["feat: add filter sidebar component"]
}
```

Minimum threshold: diff must be >10 lines changed before triggering a summary. Smaller diffs produce noise.

---

## Human Review: Terminal Diff View

When `baton end` runs, the human sees:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  BATON SESSION SUMMARY — claude-code · 2026-06-02
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [PROPOSED CHANGES]

  + decisions:
      d003:
        what: "Using streamlit-multiselect for filter sidebar"
        why: "Native Streamlit component, avoids custom JS"
        made: 2026-06-02

  + state:
      in_progress → done:
        - "Filter sidebar component"
      done → in_progress:
        (none)

  + open_questions:
      q002:
        question: "Should filters persist between sessions via URL params?"
        status: open
        raised_by: "Claude Code session"
        blocking: []

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [a] Accept all    [e] Edit before accepting    [r] Reject all
  Or enter an item number to accept/reject individually: _
```

After approval → `baton sync` runs automatically → all agent files update.

---

## Adapter Interface

Every adapter implements the same two methods:

```python
# adapters/base.py
from abc import ABC, abstractmethod

class BaseAdapter(ABC):

    @abstractmethod
    def render(self, baton_content: dict) -> str:
        """
        Convert BATON.md content to this agent's file format.
        Returns the file content as a string.
        """
        pass

    @abstractmethod
    def file_path(self) -> str:
        """
        Return the path where this agent reads its context file.
        e.g. "CLAUDE.md", "AGENTS.md", ".cursor/rules/baton.mdc"
        """
        pass
```

Adding a new agent = implement these two methods. That's it. A first contribution.

---

## Quality Scoring (baton score)

Baton evaluates `BATON.md` completeness without any LLM calls — purely structural:

```
BATON.md Quality Score: 74/100

  ✅ project.purpose         present
  ✅ stack (3 entries)       present, all have why + version
  ⚠️  stack gotchas          missing on 2 of 3 entries
  ✅ laws (2 entries)        present
  ✅ decisions (4 entries)   present
  ❌ anti_decisions          empty — add things you ruled out
  ✅ current_sprint.goal     present
  ⚠️  in_progress items      2 items missing owner field
  ✅ open_questions          3 entries, statuses correct
  ❌ landmines               empty — any intentional weirdness?

  Tip: The biggest gap is anti_decisions. Think about what
  you explicitly decided NOT to do this sprint.
```

---

## Failure Modes & Mitigations

```
1. HALLUCINATED DECISIONS
   Risk: AI adds "decided to use Redis" with no evidence in diff
   Fix:  Pass 2 prompt explicitly requires diff evidence.
         Reviewer sees proposed changes before they commit.
         Users can reject any proposed entry.

2. OVERWRITING vs APPENDING
   Risk: AI rewrites the entire file instead of just the delta
   Fix:  Prompt says "output ONLY the delta".
         Schema enforces append-only on decisions + anti_decisions.
         Parser merges delta into existing file, never replaces.

3. NOISE FROM SMALL DIFFS
   Risk: Fixing a typo generates 5 spurious "decisions"
   Fix:  Minimum 10-line diff threshold before triggering summary.
         baton end --force to override.

4. STALE BATON.md
   Risk: Laws or stack entries go out of date as codebase evolves
   Fix:  baton score flags sections not updated in >30 days.
         baton status shows drift between BATON.md and agent files.

5. CONFLICTING TEAM SUMMARIES (Phase 2)
   Risk: Two teammates' sessions propose contradicting decisions
   Fix:  Both summaries open as PRs. Team reviews and resolves
         conflict in the PR, same as any code conflict.
         The later-merged PR wins; earlier must rebase.
```

---

## Tech Stack for Baton Itself

```
Language:     Python 3.11+
CLI:          Click or Typer
AI:           Anthropic Claude API (claude-sonnet-4-6) for Pass 2
Git:          GitPython for diff parsing
Review UI:    Rich (terminal formatting) for the diff review
Config:       TOML (.baton.toml in project root)
Tests:        pytest
Distribution: PyPI (pip install baton-cli)
              npx @baton/cli (npm wrapper for non-Python users)
```

`.baton.toml` — per-project config:

```toml
[baton]
llm_provider = "anthropic"         # anthropic | openai | vertex
model = "claude-sonnet-4-6"
min_diff_lines = 10                # threshold before triggering summary
auto_sync = true                   # sync on every BATON.md commit

[adapters]
enabled = ["claude", "codex", "cursor"]   # which agent files to maintain
```

---

## Open Source Structure & Contribution Ladder

```
Good first issue (1-2 hours):
  - Add a new adapter (e.g. Windsurf, Aider, OpenCode)
  - Add a new scoring check
  - Improve a parser extraction rule
  - Translate docs

Medium issue (half-day):
  - Improve summarizer prompt quality
  - Add a new CLI command
  - Build test fixtures from real session diffs

Hard issue (multi-day):
  - GitHub Actions integration (Phase 2)
  - Conflict resolution for team summaries
  - MCP server for direct agent querying (Phase 3)
```

**The adapters folder is the community entry point.** Anyone who uses a different agent tool can add support in ~50 lines. That's the flywheel.

---

## Dogfooding

Baton's own repository uses Baton. `BATON.md` at the repo root is maintained by the team using Baton itself. This is the proof-of-concept and the best documentation.

---

## What to Build First

Before writing any other code, validate the hardest part:

1. Take your last 3 real Claude Code sessions
2. Manually write what `BATON.md` should look like after each one
3. Look at the git diffs from those sessions
4. Run Pass 1 parser on those diffs
5. Ask: does Pass 2 produce the right delta from that output alone?

If yes — the core works. Build the CLI around it.
If no — iterate on the prompt and parser before touching anything else.

**The summarizer quality is the product. Everything else is plumbing.**
