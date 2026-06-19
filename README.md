# Baton

**5 agent adapters · zero-cost session capture · 422 tests passing**

> Stop re-explaining your project to every AI. One file, every agent, always in sync.

[![PyPI](https://img.shields.io/badge/PyPI-v0.1.4-blue)](https://pypi.org/project/baton-pass/0.1.4/)
[![Python](https://img.shields.io/pypi/pyversions/baton-pass)](https://pypi.org/project/baton-pass/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-422%20passing-brightgreen)](#)

**Baton** keeps structured project memory — your decisions, constraints, session history, and architectural context — alive across tool switches and session ends. Every agent you work with reads the same living document, so it never needs to ask what you already decided.

This is not about translating one file into five config formats. The sync is the transport. The value is that an agent picking up your project tomorrow knows what was ruled out last week, what is intentionally weird, and exactly where you left off — without you re-explaining any of it.

```
BATON.md  ←── the only file you edit (plain Markdown + YAML)
    │
    └── baton sync delivers it to every agent:
        ├── CLAUDE.md                          (Claude Code)
        ├── AGENTS.md                          (OpenAI Codex)
        ├── .cursor/rules/baton.mdc            (Cursor)
        ├── GEMINI.md                          (Gemini CLI)
        └── .github/copilot-instructions.md   (GitHub Copilot)
```

The generated files are **not source files** — gitignore them. They are recreated on demand from `BATON.md`.

---

## The problem

You switch from Claude Code to Cursor. Cursor has no idea what you decided yesterday. You switch back. Claude Code has no idea what Cursor just changed. You spend the first 10 minutes of every session rebuilding context that you already captured somewhere.

But the real problem isn't tool-switching. It's memory loss:

- **The agent re-suggests what you already rejected.** You ruled out TypeScript last week. The agent doesn't know — it suggests it again. You explain again.
- **The agent fixes things that are intentionally weird.** That auth callback looks like a bug. It isn't — it's the OAuth PKCE flow. The agent "fixes" it. You revert it.
- **Decisions vanish when sessions end.** You chose SQLite for local dev, Postgres in prod, for a specific reason. Three sessions later a new agent switches both to Postgres. The reasoning was never written down.

Baton fixes this by making you the curator of a single document that every agent reads. Your job shifts from re-explaining to maintaining — which is a much smaller, higher-leverage activity.

---

## Install

```bash
pip install baton-pass
```

Python 3.10+ required.

---

## Quickstart

```bash
# 1. In your project root
baton init

# 2. Fill in BATON.md — takes 5–10 minutes the first time
#    Add your project purpose, stack decisions, hard constraints, architectural choices

# 3. Push to all agent config files
baton sync

# 4. At the end of a session, capture what changed — no API key required
baton end
```

That's it. No API key for `baton end` — the default summarizer is free and runs entirely from your git history.

---

## Commands

| Command | What it does |
|---------|-------------|
| `baton init` | Scaffold `BATON.md`, `.baton.toml`, and a pre-commit reminder hook |
| `baton sync` | Push `BATON.md` → all enabled agent config files |
| `baton status` | Show which files are in-sync, drifted, or missing |
| `baton score` | Grade your `BATON.md` memory quality out of 100 — are decisions documented? laws set? landmines marked? |
| `baton end` | Capture the session into `BATON.md` — free by default, LLM optional |
| `baton doctor` | Diagnose your setup: BATON.md validity, adapters, agent files, API keys |

---

## How it works

### `baton sync` — deterministic, no LLM

Generates `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursor/rules/baton.mdc`, and `.github/copilot-instructions.md` from `BATON.md`. These are output files — commit only `BATON.md` and gitignore the rest:

```gitignore
CLAUDE.md
AGENTS.md
GEMINI.md
.cursor/rules/baton.mdc
.github/copilot-instructions.md
```

Baton never overwrites your existing agent files. It only updates a managed region between HTML comment markers, leaving all hand-written content untouched:

```
<!-- BATON:START — auto-generated, do not edit by hand -->
... rendered context from BATON.md ...
<!-- BATON:END -->
```

`baton status` detects drift without any LLM call.

### `baton end` — session capture with no API key required

At the end of a coding session, `baton end` reads your git diff since the last session and writes an update to `BATON.md`. It works across three tiers, from cheapest to most complete:

| Mode | Cost | How |
|------|------|-----|
| `baton end` *(default)* | **Free** | Heuristic: derives the summary from diff stats and commit subjects — no model, no key |
| `baton end --apply` | Free | Reads a pre-drafted delta JSON from stdin — designed for host-agent skills (see below) |
| `baton end --api` | API quota | Calls your configured LLM for a richer, model-authored summary |

The worst case is always "captured at reduced fidelity, easy to upgrade later" — never "session lost because a key wasn't set."

```bash
# Default: free, zero-cost, no setup
baton end

# Review each section before writing, or skip prompts entirely
baton end --yes

# Use an LLM if you want a richer summary (optional)
export ANTHROPIC_API_KEY=sk-ant-...
baton end --api

# Diff from a specific commit / record the tool you used
baton end --since main --tool cursor
```

#### For host-agent skills (Claude Code, Codex, Gemini, Cursor)

`--diff-only` prints the git diff and exact JSON contract. The host agent drafts the JSON from its own session context and pipes it to `--apply` — no separate API call, uses the agent's existing quota:

```bash
# Agent workflow
baton end --diff-only   # → prints context + JSON spec
# ... agent drafts the delta JSON ...
echo '<delta json>' | baton end --apply
```

If the agent produces nothing usable, `--apply` falls back to the heuristic automatically.

### `baton doctor` — setup diagnostics

```
baton doctor -- diagnosing your setup

── BATON.md ──────────────────────────────────
  PASS  BATON.md found
  PASS  Valid YAML block parsed

── Config (.baton.toml) ──────────────────────
  PASS  .baton.toml found
  llm_provider = anthropic
  min_diff_lines = 10

── Adapters ──────────────────────────────────
  PASS  3 adapter(s) enabled (auto-detected from repo root)

── Agent files (dry-run sync) ────────────────
  PASS  claude     CLAUDE.md               in-sync
  WARN  cursor     .cursor/rules/baton.mdc  drifted
        Fix: baton sync

── API keys ──────────────────────────────────
  WARN  ANTHROPIC_API_KEY    not set  (only needed for baton end --api)
  WARN  OPENAI_API_KEY       not set
  WARN  GOOGLE_APPLICATION_CREDENTIALS  not set
```

`baton doctor` always exits 0 — it tells you what to fix without blocking your workflow.

---

## What lives in BATON.md

BATON.md is a Markdown file with a single YAML block. The schema is designed around the sections agents most often get wrong without them:

| Section | What it prevents |
|---------|-----------------|
| `laws` | Agents violating hard constraints you've already set |
| `decisions` | Agents re-litigating choices that are already made |
| `anti_decisions` | Agents re-suggesting approaches you explicitly rejected |
| `landmines` | Agents "fixing" code that is intentionally weird |
| `open_questions` | Agents making unilateral calls on things you haven't decided yet |
| `stack` | Agents picking wrong library versions or missing known gotchas |
| `current_sprint` | Agents working on the wrong thing or duplicating done work |
| `sessions` | Agents starting blind — the running log of what actually happened |

`baton score` grades how well these sections are filled in, out of 100.

---

## LLM providers (optional, for `baton end --api`)

| Provider | Install | Auth |
|----------|---------|------|
| **Anthropic** (Claude) — default | *(included)* | `ANTHROPIC_API_KEY` |
| **OpenAI** (GPT-4o, o1, etc.) | `pip install "baton-pass[openai]"` | `OPENAI_API_KEY` |
| **Google Vertex AI** (Gemini) | `pip install "baton-pass[vertex]"` | `GOOGLE_APPLICATION_CREDENTIALS` + `BATON_VERTEX_PROJECT` |

```toml
# .baton.toml
[baton]
llm_provider = "openai"   # anthropic | openai | vertex
# model = "gpt-4o"        # leave empty to use each provider's default
```

A provider is only needed if you run `baton end --api`. The default heuristic mode has no dependency.

---

## Supported AI coding tools

| Tool | Config file synced | Auto-detected |
|------|--------------------|---------------|
| [Claude Code](https://claude.ai/code) | `CLAUDE.md` | Yes |
| [Cursor](https://cursor.com) | `.cursor/rules/baton.mdc` | Yes (`.cursor/` dir) |
| [GitHub Copilot](https://github.com/features/copilot) | `.github/copilot-instructions.md` | Yes |
| [OpenAI Codex](https://openai.com) | `AGENTS.md` | Yes |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `GEMINI.md` | Yes |

**Don't see your tool?** Adding an adapter is ~50 lines. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Configuration

```toml
# .baton.toml

[baton]
llm_provider = "anthropic"   # anthropic | openai | vertex  (only for --api)
# model = ""                 # empty = provider default
min_diff_lines = 10          # skip baton end if the diff is smaller than this
auto_sync = true             # re-sync agent files automatically after baton end

[adapters]
enabled = ["claude", "cursor", "copilot"]  # or omit to auto-detect
```

---

## Why open source

Your project memory belongs in your repo. `BATON.md` is a plain Markdown file you own, commit, and version-control. Context management for AI coding tools shouldn't be locked in a SaaS. Baton is MIT-licensed.

---

## Roadmap

| | |
|-|-|
| `baton init` / `sync` / `status` / `score` / `doctor` | Done |
| `baton end` — heuristic (free default) + stdin apply + LLM opt-in | Done |
| Host-agent skills (Claude Code, Codex, Gemini, Cursor) | In progress |
| Commit B: marker-driven decision / landmine capture (`DECISION:` / `LANDMINE:` inline) | Planned |
| Team sync — shared BATON.md, PR-time updates | Planned |
| GitHub Actions integration | Planned |
| MCP server — expose BATON.md to any MCP-compatible agent | Planned |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Good first contributions:

- **New agent adapter** — ~50 lines, well-documented pattern
- **New LLM provider** — ~30 lines, follows the existing base class
- **Bug reports and feedback** — open an issue

---

## License

MIT — see [LICENSE](LICENSE).

---

## Changelog

### 0.1.4 — 2026-06-19

**New**
- `baton end` now captures **decisions, anti-decisions, landmines, and open questions** — not just session + sprint. The full memory schema is the delta contract for all three modes (heuristic, `--apply`, `--api`).
- `baton end` heuristic mode supports inline markers in commit subjects and added diff lines: `DECISION:`, `ANTI:`/`REJECTED:`, `LANDMINE:`, `QUESTION:`/`OPENQ:`. Curated sections are proposed only when markers are found; never inferred from ordinary code.
- `baton install-skill` — new command that writes `.claude/skills/baton-end/SKILL.md` into your project. Claude Code then automatically captures session context (including curated memory) without an API key. The skill body defers to `baton end --diff-only` for the live JSON schema, so it never goes stale.
- Session-end protocol block injected into `AGENTS.md`, `GEMINI.md`, `.cursor/rules/baton.mdc`, and `.github/copilot-instructions.md` by `baton sync` — teaches Codex, Gemini, Cursor, and Copilot the `--diff-only` → draft → `--apply` workflow. Excluded from `CLAUDE.md` since the real skill covers it.

**Tests**
- 58 new tests: `test_heuristic.py` additions (marker extraction, heuristic_delta with markers), `test_end.py` additions (curated sections in parse_delta, _next_id, _merge_delta for all four sections, _review silent-drop guard, full round-trip), `test_adapters.py` additions (protocol block present/absent per tool), `test_install_skill.py` (22 tests) — **422 tests total**

---

### 0.1.3 — 2026-06-19

**New**
- `baton end` no longer requires an API key. The default mode is now a zero-cost heuristic summarizer derived from diff stats and commit subjects — no model, no setup.
- `baton end --apply` reads a pre-drafted delta JSON from stdin, designed for host-agent skills. Falls back to the heuristic automatically on empty or malformed input.
- `baton end --api` preserves the existing LLM provider path as an opt-in upgrade.
- `baton end --diff-only` prints the git diff and JSON contract for a host agent to use; no writes.
- New `baton/core/heuristic.py` — deterministic delta-source with `get_commit_log` helper.

**Tests**
- 50 new tests: `test_heuristic.py` (31), `test_gitdiff.py` additions (7), `test_end.py` additions (18 — covers all four modes, stdin fallback paths, backward-compat of `summarizer=` kwarg) — **364 tests total**

---

### 0.1.2 — 2026-06-13

**New**
- `baton doctor` — diagnoses your entire Baton setup: valid `BATON.md`, active config, detected adapters, per-file sync status, all three provider API keys. Prints `PASS / WARN / FAIL` with inline fix commands. Always exits 0.

**Tests**
- 130 new tests across `test_cli.py`, `test_summarizer.py`, `test_extended.py` — **314 tests total**

---

### 0.1.1 — 2026-06-05

**Bug fixes**
- `baton end` no longer crashes with a raw traceback on wrong/expired/rate-limited API keys — all three providers now surface a clean error message
- Fixed a parse error where a code example before the JSON block in the LLM response caused the fence-stripping regex to extract the wrong block

**Improvements**
- 184 tests total

---

### 0.1.0 — 2026-06-04

Initial release: `baton init`, `baton sync`, `baton status`, `baton score`, `baton end`.

---

## Related

`ai coding assistant` · `claude code` · `cursor ide` · `github copilot` · `gemini cli` · `codex` · `ai context management` · `vibe coding` · `ai pair programming` · `multi-agent workflow` · `llm context` · `ai developer tools` · `coding agent` · `ai session management` · `structured project memory` · `llm-agnostic` · `anthropic` · `openai` · `google gemini`
