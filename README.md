# Baton

**5 agent adapters · zero-cost session capture · 422 tests passing**

> Stop re-explaining your project to every AI. One file, every agent, always in sync.

[![PyPI](https://img.shields.io/badge/PyPI-v0.1.3.1-blue)](https://pypi.org/project/baton-pass/0.1.3.1/)
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
| `baton install-skill` | Install the Claude Code skill so Claude auto-captures sessions without an API key |
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

**Claude Code skill:** run `baton install-skill` once to write `.claude/skills/baton-end/SKILL.md` into your project. After that, Claude Code automatically runs the `--diff-only → --apply` loop when you say "wrap up", "ending session", or "switching tools" — no extra commands needed. Commit the skill file to git so your whole team gets it.

```bash
baton install-skill
git add .claude/skills/baton-end/SKILL.md
git commit -m "add baton-end skill for Claude Code"
```

**Codex, Gemini, Cursor, Copilot:** `baton sync` injects a Session-End Protocol block into each agent's managed config file, describing the same `--diff-only → --apply` workflow as plain instructions.

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
| Full-memory delta — decisions, anti-decisions, landmines, open questions captured by `baton end` | Done |
| Inline markers — `DECISION:` / `ANTI:` / `LANDMINE:` / `QUESTION:` in commits + diffs | Done |
| `baton install-skill` — Claude Code skill for automatic zero-cost session capture | Done |
| Session-end protocol injected into Codex / Gemini / Cursor / Copilot via `baton sync` | Done |
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

### 0.1.3.1 — 2026-06-19

**Full-memory session capture**

`baton end` now captures the full curated memory of a session — not just what changed, but what was decided, what was ruled out, what is intentionally weird, and what is still unresolved:

- **Decisions** — architectural choices made in this session
- **Anti-decisions** — approaches explicitly rejected (stops agents re-suggesting them)
- **Landmines** — code that looks wrong but is intentional (stops agents "fixing" it)
- **Open questions** — unresolved questions the human must decide (stops agents making unilateral calls)

All three modes (`baton end`, `baton end --apply`, `baton end --api`) now propose entries for these sections. The review UI shows them per-section so you can accept or reject each one independently before anything is written.

**Inline markers for the free heuristic**

In your commit messages or diff comments, prefix a line with one of these markers and the heuristic picks it up automatically — no API key, no model:

```
DECISION:  use managed blocks for all adapter writes
ANTI:      full-file sync -- destructive for hand-written content
LANDMINE:  the lambda in re.sub is intentional, not a bug
QUESTION:  should baton init auto-run baton sync?
```

Markers can also use `REJECTED:` (alias for `ANTI:`), `OPENQ:` (alias for `QUESTION:`). Curated sections only appear when markers are found — nothing is inferred from ordinary code changes.

**`baton install-skill` — Claude Code automatic session capture**

```bash
baton install-skill
git add .claude/skills/baton-end/SKILL.md
```

Installs a Claude Code skill at `.claude/skills/baton-end/SKILL.md`. After that, Claude automatically runs the `--diff-only → --apply` loop when you wrap up a session — capturing decisions, landmines, and open questions from the conversation, not just from the diff. No API key needed; uses Claude's own session quota.

The skill body is thin and schema-free: it instructs Claude to run `baton end --diff-only` to get the live contract, then pipe a drafted JSON to `baton end --apply`. When the schema changes in a future release, the installed skill auto-updates — no need to re-run `install-skill`.

**Session-end protocol in non-Claude agent files**

`baton sync` now injects a brief Session-End Protocol section into `AGENTS.md`, `GEMINI.md`, `.cursor/rules/baton.mdc`, and `.github/copilot-instructions.md`, describing the same `--diff-only → --apply` workflow as plain instructions for Codex, Gemini, Cursor, and Copilot. Not injected into `CLAUDE.md` — the real skill covers it.

**Tests: 422 passing** (58 new — marker extraction, ID assignment, curated-section round-trip, install-skill, protocol block presence/absence per adapter)

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
