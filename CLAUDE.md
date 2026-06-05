# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

**Baton** is a Python CLI (`pip install baton-pass`) that solves context-loss for vibe coders switching between AI coding tools. It keeps a single `BATON.md` as the source of truth and syncs it into every agent's native config file (`CLAUDE.md`, `AGENTS.md`, `.cursor/rules/baton.mdc`, `GEMINI.md`, `.github/copilot-instructions.md`) so context survives tool switches.

## Development setup

```bash
pip install -e ".[dev]"   # installs typer, rich, ruamel.yaml, tomli, pytest
```

Python 3.10+ required. `tomllib` is stdlib on 3.11+; `tomli` is the conditional backport used on 3.10 (see `core/config.py`).

## Running tests

```bash
pytest tests/                         # full suite
pytest tests/test_adapters.py -v      # single file
pytest tests/ -k "test_upsert"        # by name pattern
```

Tests use `tmp_path` (pytest) for filesystem isolation — no mocking. The shared fixture is `tests/fixtures/sample_baton.md`.

## Running the CLI during development

After `pip install -e ".[dev]"`, both forms work:

```bash
baton score
baton sync
baton status
baton init --force
baton end --force --yes                  # --yes skips interactive prompts (good for testing)
baton end --since <sha-or-branch>        # override the base ref for the diff
# python -m baton.cli <cmd> works identically
```

`baton end` requires a provider API key:
```bash
# Anthropic (default)
$env:ANTHROPIC_API_KEY = "sk-ant-..."
# OpenAI  — also: pip install "baton-cli[openai]"
$env:OPENAI_API_KEY = "sk-..."
# Vertex  — also: pip install "baton-cli[vertex]"
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\path\to\key.json"
$env:BATON_VERTEX_PROJECT = "my-gcp-project"
```

On Windows with the default CP1252 console, all `console.print()` output must use basic ASCII only. Files written to disk are always UTF-8.

## Architecture

**Data flow for `baton sync`:**

```
cli.py (Typer entry point)
  -> commands/sync.py
    -> core/document.py      BatonDocument.load() extracts + parses the ```yaml fenced block
    -> core/config.py        reads .baton.toml; falls back to auto-detect if absent
    -> adapters/registry.py  detect_enabled() scans repo root for indicator files/dirs
    -> for each adapter:
         adapter.render(data)          returns inner block markdown (no markers)
         adapter.prepare_file(...)     upserts managed block into existing file content
         target.write_text(utf-8)
```

**Data flow for `baton end`:**

```
cli.py
  -> commands/end.py  run_end()
    -> core/gitdiff.py    head_sha / resolve_base_ref / get_diff / count_changed_lines
    -> core/summarizer.py build_prompt(diff, data) -> (system, user)
    -> llm/__init__.py    get_provider(config) -> LLMProvider
    -> llm/<provider>.py  provider.complete(system, user, model) -> raw text
    -> core/summarizer.py parse_delta(raw) -> dict
    -> [review UI]        per-section accept/reject in terminal
    -> _merge_delta()     append-only writes to ruamel CommentedMap
    -> BatonDocument.save()  ruamel round-trip preserves inline comments
    -> commands/sync.py   run_sync() if config.auto_sync
```

**`core/schema.py` is the single source of truth.** `SCORE_CHECKS` (12 checks, total 100 pts) lives here and is imported by `score.py`. A module-level `assert` enforces the total at import time — adding a check without rebalancing points fails immediately.

**LLM provider abstraction** (`llm/`): `LLMProvider` ABC with `complete(system, user, model) -> str`. Three implementations: `AnthropicProvider` (core dep, uses prompt caching on the static system block), `OpenAIProvider` (optional `[openai]` extra, lazy import), `VertexProvider` (optional `[vertex]` extra, lazy import). Factory: `get_provider(config)`.

**Diff strategy** (`core/gitdiff.py`): `resolve_base_ref` reads the `commit` SHA from the last session entry in BATON.md so each `baton end` diffs from where the previous session ended. Falls back to `git diff HEAD` on first run. Diffs are capped at 24k chars to avoid blowing the LLM token budget.

**Injectable summarizer seam**: `run_end()` accepts a `summarizer` keyword argument (`(system, user, config) -> str`). Tests pass a fake that returns canned JSON — no real LLM call needed. Do not remove or change this signature.

**Managed-block pattern** (`adapters/base.py`): `sync` never replaces a whole file. It only rewrites the region between `BATON:START` and `BATON:END` HTML comment markers via `upsert_managed_block()`. `status.py` uses `extract_managed_block()` + a fresh `adapter.render()` to detect drift without any LLM or git calls.

**Cursor adapter** (`adapters/cursor.py`) overrides `prepare_file()` because `.mdc` files require YAML frontmatter at the top of the file, outside the managed block.

## Non-obvious invariants

**`re.sub` replacements must use a lambda.** `re.sub(pattern, block, text)` interprets `\n` in a plain string replacement as an actual newline. When the replacement contains YAML-derived data (which may include literal `\n`), this silently corrupts the output. Always write: `re.sub(pattern, lambda _m: block, text)`. This applies to both `upsert_managed_block()` in `adapters/base.py` and `save()` in `core/document.py`.

**YAML fence regex** (`_YAML_FENCE_RE` in `document.py`): the pattern is `r"```yaml\n(.*?)\n```"`. The `\n` before the closing backticks is load-bearing — without it, triple-backticks inside a YAML string value terminate the match early.

**`detect_enabled` returns only found adapters.** If only `CLAUDE.md` exists in the target project, only the Claude adapter runs. A `.baton.toml` with `[adapters] enabled = [...]` overrides this. Users must run `baton init` (which writes `.baton.toml` with all five) to get all adapters on a fresh project.

**Never write the literal marker text** (`BATON:START` / `BATON:END`) inside code fences in any file Baton manages. The regex scans the full file and cannot distinguish examples from real markers.

## Adding a new adapter

Create `baton/adapters/mytool.py`, subclass `BaseAdapter`, implement `render()` and `file_path()`. Register in `ADAPTER_MAP` and `_DETECTION_RULES` in `registry.py`. See `CONTRIBUTING.md` for the full ~50-line pattern.

## Hard constraints

- **Never use PyYAML** — it drops inline `#` comments on round-trip. `ruamel.yaml` is mandatory.
- **`schema.py` owns all BATON.md field names.** Don't define section names in `score.py` or anywhere else.
- **`baton end` is the only LLM command.** `init`, `sync`, `status`, `score` are purely deterministic — no network calls.
- Git commits: identity `AriS10223 <220664302+AriS10223@users.noreply.github.com>`, no Claude attribution.

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
