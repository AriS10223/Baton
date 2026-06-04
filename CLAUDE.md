# CLAUDE.md — Baton Project: Codebase Instructions & Lessons

> This file serves two purposes:
> 1. Instructions for AI agents working on the Baton codebase.
> 2. A running log of mistakes and lessons so they are not repeated.

---

## Project Summary

**Baton** is a Python CLI tool that maintains a single living onboarding document (`BATON.md`) as the source of truth for a codebase, and syncs it into every AI agent's native config file (`CLAUDE.md`, `AGENTS.md`, `.cursor/rules/baton.mdc`, etc.). This lets vibe coders switch between Claude Code, Cursor, and Codex without losing momentum.

- **Repo:** https://github.com/AriS10223/baton
- **Entry point:** `baton/cli.py` → `main()`
- **Language:** Python 3.10+
- **CLI framework:** Typer (not Click)
- **Terminal output:** Rich
- **YAML parsing:** ruamel.yaml (round-trip, preserves inline `#` comments)
- **Config format:** `.baton.toml` (TOML, read with stdlib `tomllib` or `tomli` backport)

---

## Approved Phase 1 — Increment 1 Plan

**Scope:** Four no-LLM commands: `init`, `sync`, `status`, `score`.
**Increment 2** (deferred): `baton end` — git-diff parser + Anthropic summarizer + Rich review UI.

### Key design decisions (locked)
- **Managed block markers** — never clobber existing user content. Sync only modifies the region
  between the BATON:START and BATON:END HTML comment markers. (Note: never write the literal
  markers inside code fences in files Baton manages — they will be treated as real markers.)
- **`schema.py` is the single source of truth** for sections, fields, and score checks.
- **`document.py` round-trip fidelity** — extracts the triple-backtick yaml fenced block,
  parses with ruamel.yaml, writes it back in place.
- **`status` = re-render + compare** — no LLM, no git diff.
- **Score totals exactly 100 points** across 11 checks in `SCORE_CHECKS`.
- **Token-limit trigger is manual + pre-commit hook reminder.** Baton cannot auto-detect
  another tool's token state.

---

## Mistakes & Lessons

> Append to this section whenever something breaks or a wrong assumption is made.
> Format: **[date] — Mistake -> Lesson**

**[2026-06-04] — Folder was not a git repo**
- Mistake: Started building without `git init`. The pre-commit hook installation, Pass-1 parser (Increment 2), and dogfooding all require `.git` to exist.
- Lesson: `baton init` must check for `.git` before installing the pre-commit hook. Print a clear message if `.git` is absent: "Run `git init` first, then re-run `baton init` to install the hook." Never silently skip the hook installation.

**[2026-06-04] — Token-trigger is NOT auto-detection**
- Mistake: The marketing copy implies Baton auto-senses token limits. No external tool exposes its token state to a CLI.
- Lesson: Phase 1 trigger = manual `baton end` + a non-blocking pre-commit hook reminder. Never add code or docs claiming auto-detection in Phase 1.

**[2026-06-04] — BATON.md format is fenced YAML in markdown, not pure YAML**
- Mistake: Treating BATON.md as a pure YAML file.
- Lesson: `document.py` must find and parse the triple-backtick yaml fenced block inside the markdown. The rest of the markdown must be preserved on save.

**[2026-06-04] — Never overwrite existing agent files**
- Mistake: Writing the entire `CLAUDE.md` file on `sync`.
- Lesson: Always use BATON:START / BATON:END managed-block markers. `upsert_managed_block()` replaces only the block, leaving hand-written prose intact. This is the #1 safety property of `sync`.

**[2026-06-04] — `score.py` must reuse `schema.py`**
- Mistake: Hardcoding field names inside `score.py`.
- Lesson: `SCORE_CHECKS` is defined in `schema.py` and imported by `score.py`. The assertion `sum(c.points for c in SCORE_CHECKS) == 100` enforces the total. Never duplicate field lists.

**[2026-06-04] — Python 3.11 law vs. machine reality**
- Mistake: Plan said "Python 3.11+ only" but the development machine has only Python 3.10.
- Root cause: `tomllib` was added to stdlib in 3.11; `tomli` is the 3.10-compatible backport.
- Fix: `requires-python = ">=3.10"` in pyproject.toml; `tomli>=2.0; python_version < '3.11'` as a conditional dep; `config.py` uses `try: import tomllib except ImportError: import tomli as tomllib`.
- Lesson: Check the target machine's Python before writing hard version constraints into laws.

**[2026-06-04] — Unicode emoji breaks Windows CP1252 terminal (Rich tables)**
- Mistake: Used Unicode icons (checkmarks, emoji) as status indicators in Rich tables. These aren't in Windows CP1252 → `UnicodeEncodeError`.
- Fix: Replace with ASCII alternatives (`OK`, `!!`, `--`). The YAML files written by sync are UTF-8 (fine). Only Rich `console.print()` strings need to be CP1252-safe.
- Lesson: On Windows with the default console, treat all Rich output strings as ASCII-only. Or force UTF-8 via `PYTHONUTF8=1` env var.

**[2026-06-04] — detect_enabled returns only found adapters, not all five by default**
- Mistake: Expected `baton sync` in a project with just CLAUDE.md to sync all five adapters.
- Lesson: `detect_enabled` returns only found adapters (correct behavior). Users must either run `baton init` first (creates `.baton.toml` with all five) or manually create `.baton.toml` with `enabled = [...]`.

**[2026-06-04] — Regex for YAML fence must anchor closing ``` to start of line**
- Mistake: Used `r"```yaml\n(.*?)```"`. Terminates prematurely on triple-backticks inside YAML string values.
- Fix: `r"```yaml\n(.*?)\n```"` — the `\n` before closing ``` ensures it only matches at line start.

**[2026-06-04] — Never write the literal BATON:START/END markers inside code fences in managed files**
- Mistake: The original CLAUDE.md had a code block showing the managed-block marker format literally. When `baton sync` ran, it found the example marker inside the code fence and treated it as the real marker, corrupting the file.
- Root cause: `upsert_managed_block` uses a regex that scans the ENTIRE file, including code fences. It cannot distinguish "example of a marker" from "actual marker".
- Fix (for now): Never write the literal BATON:START text in any file Baton manages. Use different notation in documentation (e.g. `BATON-START` with a hyphen, or a prose description).
- Future fix: `extract_managed_block` should skip content inside triple-backtick fences.

**[2026-06-04] — Git identity**
- Always commit as `AriS10223 <220664302+AriS10223@users.noreply.github.com>`. Never add Co-Authored-By: Claude or any Anthropic attribution to commit messages.

---

## Laws (hard constraints for this codebase)

1. **Python 3.10+ (3.11+ preferred).** Use tomllib/tomli conditional import.
2. **Typer for CLI, not Click directly.** Typer wraps Click; use Typer's patterns.
3. **ruamel.yaml for all BATON.md parsing.** Never use PyYAML — it drops inline comments.
4. **`schema.py` owns field definitions.** Never define the schema's section/field names elsewhere.
5. **Managed-block markers are sacred.** `sync` never writes a full file without the managed-block markers.
6. **No LLM calls in Increment 1.** `init`, `sync`, `status`, `score` are purely deterministic.
7. **Score must total exactly 100 points.** The assertion in `schema.py` enforces this.
8. **Rich output strings must be CP1252-safe.** No Unicode beyond basic Latin in console.print() calls.

<!-- BATON:START — auto-generated, do not edit by hand -->
# Baton — Project Context

> Last synced: 2026-06-04 · via claude-code
>
> **Test:** could a new agent read this and contribute without breaking anything?

## Baton

Maintain a single living onboarding document (BATON.md) that syncs to every AI agent's config file, so vibe coders never lose context when switching between Claude Code, Cursor, and Codex.

**Who:** Independent developers who use multiple AI coding tools in a single session  **Stage:** prototype

## Architecture

Python CLI tool with a plugin-style adapter system. BATON.md is the single source of truth. The adapters/ folder converts it into each agent's native file format. Core logic is split into document.py (parse/save), schema.py (definitions), config.py (settings), and the four command modules.

**Entry point:** `baton/cli.py`
**Data flow:** baton sync -> cli.py -> commands/sync.py -> BatonDocument.load(BATON.md) -> adapter.render(data) -> upsert_managed_block -> write agent file

| Path | Purpose |
|------|---------|
| `baton/` | Main package: CLI, commands, core logic, adapters |
| `baton/core/` | BatonDocument, schema definitions, config reader |
| `baton/adapters/` | One file per supported agent tool. Each implements BaseAdapter. |
| `baton/commands/` | One file per CLI command (init, sync, status, score) |
| `tests/` | pytest test suite with fixtures/ |

## Tech Stack

| Tool | Version | Why | Gotchas |
|------|---------|-----|---------|
| Python | 3.10+ | Target audience is Python developers. tomllib (stdlib) available 3.11+; tomli backport for 3.10. | Use try/except tomllib import for 3.10 compat. Never add shims beyond this. |
| Typer | >=0.12 | Declarative CLI with rich help text and type inference. Wraps Click. | Entry point is baton.cli:main (not :app). All console.print strings must be CP1252-safe on Windows. |
| Rich | >=13 | Coloured terminal output for sync/status/score tables. | Import Rich directly. Never use Unicode outside basic Latin in console.print() calls on Windows CP1252. |
| ruamel.yaml | >=0.18 | Round-trip YAML parser that preserves inline # comments on save. PyYAML drops them. | Never switch to PyYAML. YAML fence regex must use \n before closing ``` to avoid false match inside string values. |
| tomllib/tomli | stdlib 3.11+ / tomli>=2.0 for 3.10 | Read .baton.toml config. No extra dependency on 3.11+. | Open files in binary mode: open(path, 'rb'). |

## Laws (Never Violate)

> Hard constraints. Agents must not override these — ever.

1. Never use PyYAML. All BATON.md parsing uses ruamel.yaml to preserve inline comments.
2. schema.py is the single source of truth for section/field names. Never hardcode them in score.py or anywhere else.
3. sync must never overwrite the full content of an agent file. Always use managed-block markers.
4. SCORE_CHECKS in schema.py must total exactly 100 points. The assert enforces this at import time.
5. No LLM calls in Increment 1. init, sync, status, score are purely deterministic.
6. All Rich console.print() output must use only CP1252-safe (basic ASCII) characters.

## Current Sprint: Ship Phase 1 Increment 1: init + sync + status + score (no LLM)

### ✅ Done
- pyproject.toml, package skeleton, LICENSE, .gitignore *(confidence: stable)*
- core/schema.py with SCORE_CHECKS totalling 100 points *(confidence: stable)* — Assert at import time enforces the total.
- core/document.py: BatonDocument load/save round-trip *(confidence: stable)* — Extracts the yaml fenced block, parses with ruamel.yaml.
- core/config.py: .baton.toml reader *(confidence: stable)*
- adapters/base.py: BaseAdapter + managed-block utilities *(confidence: stable)* — upsert_managed_block / extract_managed_block are the core safety primitives.
- All five adapters (claude, codex, cursor, gemini, copilot) *(confidence: stable)* — Cursor overrides prepare_file() to handle MDC frontmatter.
- adapters/registry.py: detect_enabled + get_adapters *(confidence: stable)*
- commands/sync.py + commands/status.py + commands/score.py + commands/init.py *(confidence: stable)*
- cli.py wiring all four commands + stub for baton end *(confidence: stable)*
- Full test suite: 107 tests passing *(confidence: stable)*
- README.md, CONTRIBUTING.md, BATON.md dogfood, CLAUDE.md lessons log *(confidence: stable)*
- git init + pre-commit hook installed *(confidence: stable)*

### 📋 Up Next
- Push to GitHub repo (URL from user) *[high]*
- Increment 2: baton end (git-diff parser + Anthropic summariser + Rich review UI) *[medium]*

## Key Decisions

| # | Decision | Why | When | Tool |
|---|---------|-----|------|------|
| d001 | Managed-block markers (BATON-START/END) instead of full-file ownership | Users already have hand-written CLAUDE.md content. Overwriting it would be a critical UX failure. | 2026-06-04 | claude-code |
| d002 | Embed BATON.md template as a Python string in init.py | More reliable than importlib.resources for initial releases. No template file packaging needed. | 2026-06-04 | claude-code |
| d003 | schema.py defines SCORE_CHECKS; score.py imports them | Prevents scoring logic from drifting from the actual schema when fields change. | 2026-06-04 | claude-code |
| d004 | BATON.md format: markdown with schema inside a yaml fenced block | Human-readable as a GitHub markdown file, machine-parseable via regex fence extraction. | 2026-06-04 | claude-code |
| d005 | Pre-commit hook is non-blocking (exits 0, just prints a reminder) | Phase 1 trigger is manual. A blocking hook would annoy users committing unrelated code. | 2026-06-04 | claude-code |
| d006 | Increment 1 scope: init + sync + status + score (no LLM) | Ship the deterministic core first. Validate value before adding AI complexity. | 2026-06-04 | claude-code |

## Anti-Decisions (Rejected Approaches)

> These were explicitly ruled out. Don't re-suggest them.

| # | Rejected | Why | When |
|---|---------|-----|------|
| a001 | Auto-detecting token limits in other tools | Claude Code, Cursor, and Codex do not expose their token state to external CLIs. Physically impossible in Phase 1. | 2026-06-04 |
| a002 | PyYAML for BATON.md parsing | PyYAML drops inline # comments on round-trip. ruamel.yaml preserves them. | 2026-06-04 |
| a003 | Separate template file (baton/templates/BATON.md.template) | importlib.resources is finicky for installable packages in Phase 1. Embedding the template as a string is simpler. | 2026-06-04 |
| a004 | Full-file sync (replacing the entire CLAUDE.md) | Users have hand-written content in these files. Full replacement would be destructive. | 2026-06-04 |

## Landmines (Looks Wrong, But Intentional)

> Do NOT 'fix' these. They are correct as-is.

**`baton/core/schema.py (end of file)`**
- Looks like: Redundant assert after a list definition
- Actually: Enforces that SCORE_CHECKS always sums to exactly 100. If you add/remove a check and forget to rebalance points, this fails at import time.

**`baton/adapters/cursor.py: prepare_file()`**
- Looks like: Overcomplicated file-write logic vs. the four simpler adapters
- Actually: Cursor .mdc files require YAML frontmatter at the top. The frontmatter must be outside the managed block so it survives re-syncs.

**`baton/core/document.py: _YAML_FENCE_RE`**
- Looks like: Unnecessary \n before closing ``` in the regex
- Actually: Required. Without it, triple-backticks inside YAML string values prematurely terminate the match.

## Open Questions

> Do NOT make unilateral decisions on these. Surface them to the human first.

🔴 **[q001]** Should baton init auto-run baton sync immediately after scaffolding?
  - Context: The template BATON.md has all empty values. Syncing empty content produces a mostly-empty context file.
  - Discussion: Current: init does NOT auto-sync. User fills in BATON.md first, then runs baton sync.

🔴 **[q002]** Should extract_managed_block skip content inside triple-backtick fences?
  - Context: Currently, if a user writes the literal managed-block marker inside a code fence example, sync corrupts the file. See mistake log entry [2026-06-04].
  - Discussion: Low priority for Phase 1 since it only affects files that document Baton itself.

<!-- BATON:END -->
