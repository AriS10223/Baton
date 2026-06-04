# BATON.md — Living Project Onboarding Document

> Maintained by Baton CLI. Human-reviewed before every update.
> **Test:** could a new agent read this file and contribute without breaking anything?
>
> This is Baton dogfooding itself.

```yaml
baton_version: "1.0"
last_updated: "2026-06-04"
last_session_tool: "claude-code"

# -- Project Brief -----------------------------------------------------------
project:
  name: "Baton"
  purpose: "Maintain a single living onboarding document (BATON.md) that syncs to every AI agent's config file, so vibe coders never lose context when switching between Claude Code, Cursor, and Codex."
  target_user: "Independent developers who use multiple AI coding tools in a single session"
  stage: "prototype"

# -- Architecture ------------------------------------------------------------
architecture:
  overview: "Python CLI tool with a plugin-style adapter system. BATON.md is the single source of truth. The adapters/ folder converts it into each agent's native file format. Core logic is split into document.py (parse/save), schema.py (definitions), config.py (settings), and the four command modules."
  key_directories:
    - path: "baton/"
      purpose: "Main package: CLI, commands, core logic, adapters"
    - path: "baton/core/"
      purpose: "BatonDocument, schema definitions, config reader"
    - path: "baton/adapters/"
      purpose: "One file per supported agent tool. Each implements BaseAdapter."
    - path: "baton/commands/"
      purpose: "One file per CLI command (init, sync, status, score)"
    - path: "tests/"
      purpose: "pytest test suite with fixtures/"
  entry_point: "baton/cli.py"
  data_flow: "baton sync -> cli.py -> commands/sync.py -> BatonDocument.load(BATON.md) -> adapter.render(data) -> upsert_managed_block -> write agent file"

# -- Stack -------------------------------------------------------------------
stack:
  - tool: "Python"
    version: "3.10+"
    why: "Target audience is Python developers. tomllib (stdlib) available 3.11+; tomli backport for 3.10."
    gotchas: "Use try/except tomllib import for 3.10 compat. Never add shims beyond this."
  - tool: "Typer"
    version: ">=0.12"
    why: "Declarative CLI with rich help text and type inference. Wraps Click."
    gotchas: "Entry point is baton.cli:main (not :app). All console.print strings must be CP1252-safe on Windows."
  - tool: "Rich"
    version: ">=13"
    why: "Coloured terminal output for sync/status/score tables."
    gotchas: "Import Rich directly. Never use Unicode outside basic Latin in console.print() calls on Windows CP1252."
  - tool: "ruamel.yaml"
    version: ">=0.18"
    why: "Round-trip YAML parser that preserves inline # comments on save. PyYAML drops them."
    gotchas: "Never switch to PyYAML. YAML fence regex must use \\n before closing ``` to avoid false match inside string values."
  - tool: "tomllib/tomli"
    version: "stdlib 3.11+ / tomli>=2.0 for 3.10"
    why: "Read .baton.toml config. No extra dependency on 3.11+."
    gotchas: "Open files in binary mode: open(path, 'rb')."

# -- Laws --------------------------------------------------------------------
laws:
  - "Never use PyYAML. All BATON.md parsing uses ruamel.yaml to preserve inline comments."
  - "schema.py is the single source of truth for section/field names. Never hardcode them in score.py or anywhere else."
  - "sync must never overwrite the full content of an agent file. Always use managed-block markers."
  - "SCORE_CHECKS in schema.py must total exactly 100 points. The assert enforces this at import time."
  - "No LLM calls in Increment 1. init, sync, status, score are purely deterministic."
  - "All Rich console.print() output must use only CP1252-safe (basic ASCII) characters."

# -- Current Sprint ----------------------------------------------------------
current_sprint:
  goal: "Ship Phase 1 Increment 1: init + sync + status + score (no LLM)"
  done:
    - feature: "pyproject.toml, package skeleton, LICENSE, .gitignore"
      confidence: "stable"
      notes: ""
    - feature: "core/schema.py with SCORE_CHECKS totalling 100 points"
      confidence: "stable"
      notes: "Assert at import time enforces the total."
    - feature: "core/document.py: BatonDocument load/save round-trip"
      confidence: "stable"
      notes: "Extracts the yaml fenced block, parses with ruamel.yaml."
    - feature: "core/config.py: .baton.toml reader"
      confidence: "stable"
      notes: ""
    - feature: "adapters/base.py: BaseAdapter + managed-block utilities"
      confidence: "stable"
      notes: "upsert_managed_block / extract_managed_block are the core safety primitives."
    - feature: "All five adapters (claude, codex, cursor, gemini, copilot)"
      confidence: "stable"
      notes: "Cursor overrides prepare_file() to handle MDC frontmatter."
    - feature: "adapters/registry.py: detect_enabled + get_adapters"
      confidence: "stable"
      notes: ""
    - feature: "commands/sync.py + commands/status.py + commands/score.py + commands/init.py"
      confidence: "stable"
      notes: ""
    - feature: "cli.py wiring all four commands + stub for baton end"
      confidence: "stable"
      notes: ""
    - feature: "Full test suite: 107 tests passing"
      confidence: "stable"
      notes: ""
    - feature: "README.md, CONTRIBUTING.md, BATON.md dogfood, CLAUDE.md lessons log"
      confidence: "stable"
      notes: ""
    - feature: "git init + pre-commit hook installed"
      confidence: "stable"
      notes: ""
  in_progress: []
  blocked: []
  next:
    - feature: "Push to GitHub repo (URL from user)"
      priority: "high"
      dependencies: []
    - feature: "Increment 2: baton end (git-diff parser + Anthropic summariser + Rich review UI)"
      priority: "medium"
      dependencies: ["Increment 1 shipped and dogfooded"]

# -- Decisions ---------------------------------------------------------------
decisions:
  - id: "d001"
    what: "Managed-block markers (BATON-START/END) instead of full-file ownership"
    why: "Users already have hand-written CLAUDE.md content. Overwriting it would be a critical UX failure."
    made: "2026-06-04"
    made_in: "claude-code"
  - id: "d002"
    what: "Embed BATON.md template as a Python string in init.py"
    why: "More reliable than importlib.resources for initial releases. No template file packaging needed."
    made: "2026-06-04"
    made_in: "claude-code"
  - id: "d003"
    what: "schema.py defines SCORE_CHECKS; score.py imports them"
    why: "Prevents scoring logic from drifting from the actual schema when fields change."
    made: "2026-06-04"
    made_in: "claude-code"
  - id: "d004"
    what: "BATON.md format: markdown with schema inside a yaml fenced block"
    why: "Human-readable as a GitHub markdown file, machine-parseable via regex fence extraction."
    made: "2026-06-04"
    made_in: "claude-code"
  - id: "d005"
    what: "Pre-commit hook is non-blocking (exits 0, just prints a reminder)"
    why: "Phase 1 trigger is manual. A blocking hook would annoy users committing unrelated code."
    made: "2026-06-04"
    made_in: "claude-code"
  - id: "d006"
    what: "Increment 1 scope: init + sync + status + score (no LLM)"
    why: "Ship the deterministic core first. Validate value before adding AI complexity."
    made: "2026-06-04"
    made_in: "claude-code"

# -- Anti-Decisions ----------------------------------------------------------
anti_decisions:
  - id: "a001"
    rejected: "Auto-detecting token limits in other tools"
    why: "Claude Code, Cursor, and Codex do not expose their token state to external CLIs. Physically impossible in Phase 1."
    ruled_out: "2026-06-04"
  - id: "a002"
    rejected: "PyYAML for BATON.md parsing"
    why: "PyYAML drops inline # comments on round-trip. ruamel.yaml preserves them."
    ruled_out: "2026-06-04"
  - id: "a003"
    rejected: "Separate template file (baton/templates/BATON.md.template)"
    why: "importlib.resources is finicky for installable packages in Phase 1. Embedding the template as a string is simpler."
    ruled_out: "2026-06-04"
  - id: "a004"
    rejected: "Full-file sync (replacing the entire CLAUDE.md)"
    why: "Users have hand-written content in these files. Full replacement would be destructive."
    ruled_out: "2026-06-04"

# -- Landmines ---------------------------------------------------------------
landmines:
  - location: "baton/core/schema.py (end of file)"
    looks_like: "Redundant assert after a list definition"
    actually: "Enforces that SCORE_CHECKS always sums to exactly 100. If you add/remove a check and forget to rebalance points, this fails at import time."
  - location: "baton/adapters/cursor.py: prepare_file()"
    looks_like: "Overcomplicated file-write logic vs. the four simpler adapters"
    actually: "Cursor .mdc files require YAML frontmatter at the top. The frontmatter must be outside the managed block so it survives re-syncs."
  - location: "baton/core/document.py: _YAML_FENCE_RE"
    looks_like: "Unnecessary \\n before closing ``` in the regex"
    actually: "Required. Without it, triple-backticks inside YAML string values prematurely terminate the match."

# -- Open Questions ----------------------------------------------------------
open_questions:
  - id: "q001"
    question: "Should baton init auto-run baton sync immediately after scaffolding?"
    context: "The template BATON.md has all empty values. Syncing empty content produces a mostly-empty context file."
    raised: "2026-06-04"
    raised_by: "Claude Code session"
    status: "open"
    discussion: "Current: init does NOT auto-sync. User fills in BATON.md first, then runs baton sync."
    resolution: ""
    resolved_date: ""
    blocking: []
  - id: "q002"
    question: "Should extract_managed_block skip content inside triple-backtick fences?"
    context: "Currently, if a user writes the literal managed-block marker inside a code fence example, sync corrupts the file. See mistake log entry [2026-06-04]."
    raised: "2026-06-04"
    raised_by: "Claude Code session"
    status: "open"
    discussion: "Low priority for Phase 1 since it only affects files that document Baton itself."
    resolution: ""
    resolved_date: ""
    blocking: []

# -- Session Log -------------------------------------------------------------
sessions:
  - date: "2026-06-04"
    tool: "claude-code"
    owner: "Aryan"
    summary: "Built all Phase 1 Increment 1 code: package skeleton, schema, document, adapters, registry, four commands, CLI, 107 tests, README, CONTRIBUTING, BATON.md dogfood, CLAUDE.md lessons log. Resolved 9 runtime bugs during dogfooding."
    decisions_made: ["d001", "d002", "d003", "d004", "d005", "d006"]
    questions_raised: ["q001", "q002"]
    state_changes:
      - "All Increment 1 features moved to done"
```

---

*Run `baton sync` to push context to all agent config files.*
*Run `baton score` to check completeness.*
*Run `baton status` to see which files are up to date.*
