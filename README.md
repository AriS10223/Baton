# Baton

> One living onboarding doc. Every agent. Every teammate. Always in sync.

Baton solves the **context-loss problem** for vibe coders: every time you switch between Claude Code, Cursor, and Codex, each agent starts completely blind. It doesn't know you chose Flask over FastAPI, that auth is Supabase-only, or that the filter sidebar is half-built. You re-explain. The agent makes wrong assumptions. Momentum dies.

**Baton maintains a single living document — `BATON.md` — and syncs it into every AI agent's native config file automatically.**

```
BATON.md  ←── single source of truth
    ├── CLAUDE.md
    ├── AGENTS.md
    ├── .cursor/rules/baton.mdc
    ├── GEMINI.md
    └── .github/copilot-instructions.md
```

---

## Install

```bash
pip install baton-cli
```

Or for development:

```bash
git clone https://github.com/AriS10223/baton
cd baton
pip install -e ".[dev]"
```

---

## Quickstart

```bash
# 1. Initialise in your project root
cd my-project
baton init

# 2. Fill in BATON.md — your project name, purpose, stack, laws
#    (takes 5–10 minutes the first time)

# 3. Push to all agent config files
baton sync

# 4. Check completeness
baton score

# 5. See which files are in sync
baton status
```

Now open Claude Code, Cursor, or Codex — each tool reads its native config file and picks up your full project context instantly.

---

## Commands

| Command | Description |
|---------|-------------|
| `baton init` | Scaffold `BATON.md`, `.baton.toml`, and a pre-commit reminder hook |
| `baton sync` | Push `BATON.md` → all enabled agent config files |
| `baton status` | Show which files are in-sync, drifted, or missing |
| `baton score` | Evaluate `BATON.md` completeness (no LLM — purely structural) |
| `baton end` | *(Increment 2)* Summarise the current session into `BATON.md` |

---

## BATON.md

The schema has 10 sections. The most important ones:

| Section | Why it matters |
|---------|---------------|
| `project` | Name, purpose, target user, stage |
| `stack` | Tool + version + **why** + **gotchas** |
| `laws` | Hard constraints agents must never violate |
| `decisions` | Things explicitly chosen — append-only |
| `anti_decisions` | Things explicitly ruled out — stops re-suggestions |
| `landmines` | Code that looks wrong but is intentional |
| `current_sprint` | What's done, in progress, blocked, up next |
| `open_questions` | Unresolved items — agents must not decide these unilaterally |

The `why` in `stack` stops agents switching frameworks. The `anti_decisions` stops them re-suggesting approaches you already rejected. The `landmines` stops them "fixing" things that aren't broken.

---

## Supported agents

| Adapter | File |
|---------|------|
| Claude Code | `CLAUDE.md` |
| OpenAI Codex | `AGENTS.md` |
| Cursor | `.cursor/rules/baton.mdc` |
| Gemini CLI | `GEMINI.md` |
| GitHub Copilot | `.github/copilot-instructions.md` |

**Adding a new agent tool takes ~50 lines.** See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## How sync works

`baton sync` **never overwrites** your existing agent files. It only updates a managed region between HTML comment markers:

```
<!-- BATON:START — auto-generated, do not edit by hand -->
... rendered content ...
<!-- BATON:END -->
```

Any hand-written content outside this region is preserved exactly.

---

## Configuration

`.baton.toml` in your project root:

```toml
[baton]
min_diff_lines = 10    # minimum diff lines before triggering a summary

[adapters]
enabled = ["claude", "codex", "cursor"]  # which adapters to sync
```

Omit `[adapters]` and Baton auto-detects from existing files in the repo root.

---

## Roadmap

| Phase | Status |
|-------|--------|
| Phase 1 Increment 1: `init`, `sync`, `status`, `score` | ✅ Current |
| Phase 1 Increment 2: `baton end` (AI summariser + review UI) | 🔜 Next |
| Phase 2: Team collaboration, PR flow, GitHub Actions | 📅 Planned |
| Phase 3: Web dashboard, MCP server | 📅 Future |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The best first contribution is adding a new agent adapter (~50 lines).

---

## License

MIT
