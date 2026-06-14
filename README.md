# Baton

> Stop re-explaining your project to every AI. One file, every agent, always in sync.

[![PyPI](https://img.shields.io/pypi/v/baton-pass)](https://pypi.org/project/baton-pass/)
[![Python](https://img.shields.io/pypi/pyversions/baton-pass)](https://pypi.org/project/baton-pass/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-314%20passing-brightgreen)](#)

**Baton** is an open-source CLI that solves context-loss when switching between AI coding tools. It keeps a single `BATON.md` as your project's source of truth and syncs it into every agent's native config file — so Claude Code, Cursor, Copilot, Codex, and Gemini all start with full context, no matter which one you used last.

```
BATON.md  ←── one file to rule them all
    ├── CLAUDE.md                          (Claude Code)
    ├── AGENTS.md                          (OpenAI Codex / ChatGPT)
    ├── .cursor/rules/baton.mdc            (Cursor)
    ├── GEMINI.md                          (Gemini CLI)
    └── .github/copilot-instructions.md   (GitHub Copilot)
```

---

## The problem

You're building something with Claude Code. You switch to Cursor to try its inline edit. You come back to Claude Code. It has no idea what Cursor just did. You re-explain the architecture. The agent makes wrong assumptions about your stack. You spend 20 minutes getting it back up to speed.

Multiply that by every tool switch, every new session, every collaborator.

**Baton fixes this by maintaining a single living document that every agent reads.**

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
#    Add your project purpose, stack (with why + gotchas), laws, decisions

# 3. Push context to all agent files
baton sync

# 4. Switch to any AI tool — it reads its native config and knows your project

# 5. At the end of a session, let the LLM capture what changed
baton end
```

---

## Commands

| Command | What it does |
|---------|-------------|
| `baton init` | Scaffold `BATON.md`, `.baton.toml`, and a pre-commit reminder hook |
| `baton sync` | Push `BATON.md` → all enabled agent config files |
| `baton status` | Show which files are in-sync, drifted, or missing |
| `baton score` | Score your `BATON.md` completeness out of 100 (no LLM — structural only) |
| `baton end` | Summarise the session into `BATON.md` via your configured LLM |

---

## How it works

### `baton sync` — deterministic, no LLM

Baton never overwrites your existing agent files. It only updates a managed region between HTML comment markers, leaving all your hand-written content untouched:

```
<!-- BATON:START — auto-generated, do not edit by hand -->
... rendered context from BATON.md ...
<!-- BATON:END -->
```

`baton status` detects drift between `BATON.md` and your agent files without any LLM call.

### `baton end` — LLM-powered session capture

At the end of a coding session, `baton end`:

1. Reads your git diff since the last `baton end` (commit-aware — captures all mid-session commits)
2. Sends it to your configured LLM with the current project context
3. Proposes sprint updates and a session log entry for your review
4. Writes your approved changes back to `BATON.md` and re-syncs all agent files

```bash
# Anthropic Claude (default)
export ANTHROPIC_API_KEY=sk-ant-...
baton end

# Review what the LLM proposes, accept/reject per section
# Or skip prompts entirely
baton end --yes

# Diff from a specific commit
baton end --since main

# Record which tool you used this session
baton end --tool cursor
```

---

## LLM-agnostic

Baton works with whichever LLM you use. Set `llm_provider` in `.baton.toml`:

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

The model is also configurable — use whatever you have access to.

---

## What lives in BATON.md

BATON.md is a Markdown file with a single YAML block inside. The schema is designed to give agents everything they need to contribute without breaking things:

| Section | Why agents need it |
|---------|-------------------|
| `project` | Name, purpose, target user, stage |
| `stack` | Tool + version + **why you chose it** + **gotchas to avoid** |
| `laws` | Hard constraints agents must never violate |
| `decisions` | Architectural choices — append-only, so agents know the reasoning |
| `anti_decisions` | Things explicitly ruled out — stops agents re-suggesting rejected ideas |
| `landmines` | Code that looks wrong but is intentional — stops agents "fixing" it |
| `current_sprint` | Done, in-progress, blocked, up-next |
| `open_questions` | Unresolved decisions agents must not make unilaterally |
| `sessions` | Running log of what happened each session (written by `baton end`) |

`baton score` grades your BATON.md out of 100 based on how complete these sections are.

---

## Supported AI coding tools

| Tool | Config file synced | Auto-detected |
|------|--------------------|---------------|
| [Claude Code](https://claude.ai/code) | `CLAUDE.md` | Yes |
| [Cursor](https://cursor.com) | `.cursor/rules/baton.mdc` | Yes (`.cursor/` dir) |
| [GitHub Copilot](https://github.com/features/copilot) | `.github/copilot-instructions.md` | Yes |
| [OpenAI Codex / ChatGPT](https://openai.com) | `AGENTS.md` | Yes |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `GEMINI.md` | Yes |

**Don't see your tool?** Adding a new adapter is ~50 lines. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Configuration

```toml
# .baton.toml

[baton]
llm_provider = "anthropic"   # anthropic | openai | vertex
# model = ""                 # empty = use provider default (claude-sonnet-4-6, gpt-4o, gemini-1.5-pro)
min_diff_lines = 10          # skip baton end if the diff is smaller than this

[adapters]
enabled = ["claude", "cursor", "copilot"]  # explicit list, or omit to auto-detect
```

Baton auto-detects which agents you use by scanning for their config files in the repo root. You only need `.baton.toml` if you want to override the defaults.

---

## Why open source

Context management for AI coding tools shouldn't be a SaaS lock-in. Your project context belongs in your repo. `BATON.md` is a plain Markdown file you own, commit, and version-control like any other file. Baton is MIT-licensed and designed to stay that way.

---

## Roadmap

| | |
|-|-|
| `baton init` / `sync` / `status` / `score` | Done |
| `baton end` — LLM session summariser, multi-provider | Done |
| Team sync — shared BATON.md, PR-time updates | Planned |
| GitHub Actions integration | Planned |
| MCP server — expose BATON.md to any MCP-compatible agent | Planned |
| Web dashboard | Future |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Good first contributions:

- **New agent adapter** — add support for a new AI coding tool (~50 lines, well-documented pattern)
- **New LLM provider** — add a new backend to `baton/llm/` (~30 lines, follows the existing pattern)
- **Bug reports and feedback** — open an issue

---

## License

MIT — see [LICENSE](LICENSE).

---

## Changelog

### 0.1.1 — 2026-06-05

**Bug fixes**
- `baton end` no longer crashes with a raw traceback when an API key is wrong, expired, or rate-limited — all three LLM providers (Anthropic, OpenAI, Vertex) now catch SDK exceptions and surface a clean error message
- `baton end` now returns a clean error if saving `BATON.md` fails (e.g. permission denied) instead of raising an unhandled exception
- Fixed a parse error in `baton end` where a code example before the JSON block in the LLM response (e.g. a diff snippet) caused the fence-stripping regex to extract the wrong block — the parser now prefers ```` ```json ```` fences and skips fences with no `{`
- `baton end` now prints a warning if auto-sync fails after writing `BATON.md`, instead of silently exiting 0

**Improvements**
- 34 new tests covering `BatonConfig`, `baton end` error paths, LLM provider edge cases, and adapter safety — 184 tests total
- 130 additional tests for CLI routing, summarizer prompt-building, and extended edge cases (parse_delta, merge_delta, gitdiff, BatonConfig) — **314 tests total**
- Renamed PyPI package from `baton-cli` (name was taken) to `baton-pass`

### 0.1.0 — 2026-06-04

Initial release.

- `baton init` — scaffold `BATON.md`, `.baton.toml`, pre-commit hook
- `baton sync` — push context to Claude Code, Cursor, Copilot, Codex, Gemini
- `baton status` — detect drift between `BATON.md` and agent files
- `baton score` — grade `BATON.md` completeness out of 100
- `baton end` — summarise a coding session into `BATON.md` via LLM (Anthropic, OpenAI, Vertex)

---

## Related

If you're building with AI coding tools and hitting the context problem, these keywords might have brought you here:

`ai coding assistant` · `claude code` · `cursor ide` · `github copilot` · `gemini cli` · `codex` · `ai context management` · `vibe coding` · `ai pair programming` · `multi-agent workflow` · `llm context` · `ai developer tools` · `prompt engineering` · `coding agent` · `ai session management` · `llm-agnostic` · `anthropic` · `openai` · `google gemini`
