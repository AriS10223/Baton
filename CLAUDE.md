# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

**Baton** is a Python CLI (`pip install baton-pass`) that solves context-loss for vibe coders switching between AI coding tools. It keeps a single `BATON.md` as the source of truth and syncs it into every agent's native config file (`CLAUDE.md`, `AGENTS.md`, `.cursor/rules/baton.mdc`, `GEMINI.md`, `.github/copilot-instructions.md`) so context survives tool switches and session ends.

## Development setup

```bash
pip install -e ".[dev]"   # installs typer, rich, ruamel.yaml, tomli, pytest
```

Python 3.10+ required. `tomllib` is stdlib on 3.11+; `tomli` is the conditional backport used on 3.10 (see `core/config.py`).

## Running tests

```bash
py -m pytest tests/                    # full suite (1024 tests) — use py, not python, on Windows
py -m pytest tests/test_adapters.py -v # single file
py -m pytest tests/ -k "test_upsert"  # by name pattern
```

Tests use `tmp_path` (pytest) for filesystem isolation — no mocking. The shared fixture is `tests/fixtures/sample_baton.md`.

## Running the CLI during development

After `pip install -e ".[dev]"`, both forms work:

```bash
baton init --force
baton sync
baton status
baton score
baton doctor                             # diagnose setup: BATON.md, config, adapters, files, API keys
baton install-skill                      # install .claude/skills/baton-end/SKILL.md for Claude Code
baton end                                # default: zero-cost heuristic (no API key needed)
baton end --api                          # use configured LLM provider (requires API key)
baton end --diff-only                    # print diff + JSON contract; no writes (for skills)
baton end --apply                        # read pre-drafted delta JSON from stdin, apply it
baton end --force --yes                  # --yes / -y skips interactive prompts (good for testing)
baton end --since <sha-or-branch>        # override the base ref for the diff
baton end --tool cursor                  # record which AI tool was used this session
baton check --drift                      # check if codebase still matches BATON.md claims (no API)
baton check --drift --staged             # check staged changes before committing
baton check --drift --since <sha>        # override base ref; accepts SHA, branch, tag, or date phrase ("yesterday")
baton check --drift --format json        # machine-readable JSON envelope (enriched alerts)
baton check --drift --format github      # GitHub Actions workflow commands (::error/::warning annotations)
baton check --drift --format human       # Rich terminal output (default)
baton check --drift --quiet              # deprecated alias for --format json
baton check --drift --fail-on block      # only exit non-zero on block-severity alerts
baton check --drift --acknowledge a001 --reason "intentional"  # suppress a known alert
baton hooks install                      # (re)install the advisory post-commit drift-check hook
baton hooks install --strict             # also add a blocking pre-commit hook (opt-in)
baton supersede d001 --with d002 --reason "why d001 is replaced"  # record supersession
baton history d002                       # show full supersession timeline for an entry
baton init --scan                        # scan codebase for decisions/landmines; no LLM, no API key
baton init --scan --exhaustive           # include medium/low-confidence entries (default: high only)
baton init --scan --skip-pr-history      # skip gh CLI calls (safe in CI or without GitHub remote)
baton init --scan --skip-docs            # skip README/ADR scanning
baton review                             # interactive accept/edit/delete/skip for pending_review drafts
baton scope "fix auth redirect"          # focus context on a task (keyword + path-token matching)
baton scope --clear                      # restore full context (also auto-runs on baton end)
baton health                             # report BATON.md token budget + staleness findings (read-only)
baton health --format json               # machine-readable health envelope
baton health --format github             # GitHub Actions annotations (::error/::warning)
baton health --model gpt-4o              # use tiktoken encoding for a specific model
baton trim                               # interactive prune: [d]elete/[s]kip/[q]uit stale entries
baton trim --dry-run                     # preview candidates, touch nothing
baton trim --auto                        # show list + single Y/n bulk delete
baton trim --budget 4000                 # delete stale entries until BATON.md is under 4000 tokens
baton trim --compress                    # collapse deep supersession chains (depth >= 3)
baton trim --force                       # skip clean-tree gate (useful when already dirty)
# py -m baton.cli <cmd> works identically
```

`baton end --api` requires a provider API key (default heuristic mode needs none):
```bash
# Anthropic (default provider)
$env:ANTHROPIC_API_KEY = "sk-ant-..."
# OpenAI  — also: pip install "baton-pass[openai]"
$env:OPENAI_API_KEY = "sk-..."
# Vertex  — also: pip install "baton-pass[vertex]"
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
    -> [scope filter]        if scope_active(): apply_scope(filtered_data, load_scope())
    -> for each adapter:
         adapter.render(data)          returns inner block markdown (no markers)
         adapter.prepare_file(...)     upserts managed block into existing file content
         target.write_text(utf-8)
```

**Data flow for `baton end`:**

```
cli.py  (--diff-only | --apply | --api | default)
  -> commands/end.py  run_end(mode=...)
    -> core/gitdiff.py    head_sha / resolve_base_ref / get_diff / count_changed_lines
                          get_commit_log (heuristic + apply modes)
    -> [mode branch]
         heuristic (default)  core/heuristic.py  heuristic_delta(diff, commits, data) -> dict
         apply (--apply)      read stdin_reader() -> parse_delta; fallback to heuristic
         api   (--api)        core/summarizer.py  build_prompt -> LLM -> parse_delta -> dict
         diff-only            print build_prompt user block + JSON_SPEC, return True
    -> [review UI]        per-section accept/reject in terminal (all 7 sections)
    -> _merge_delta()     append-only writes to ruamel CommentedMap
    -> BatonDocument.save()  ruamel round-trip preserves inline comments
    -> _run_supersession_nudge()  detect overlapping entries, offer to link (skipped under --yes)
    -> clear_scope()      if scope was active, clears it so next session starts unfiltered
    -> commands/sync.py   run_sync() if config.auto_sync
```

**Data flow for `baton check --drift`:**

```
cli.py  (--drift | --staged | --since | --format | --quiet | --fail-on | --acknowledge)
  -> commands/check.py  run_check(...)
    -> core/alerts.py     load_acks / load_last_check_sha (read .baton/ state)
    -> core/document.py   BatonDocument.load() (read BATON.md -- read-only)
    -> core/gitdiff.py    resolve_since() [if --since given] / get_diff / get_staged_diff
    -> core/drift.py      detect_anti / detect_decisions / detect_landmines -> alerts (with matched field)
    -> core/astscan.py    added_imports / added_dependency_names (for import/dep patterns)
    -> core/findings.py   enrich_alerts() -- adds reason/suggestion/fix_command to each alert
    -> core/checkfmt.py   render_human / render_json / render_github (format dispatch)
    -> core/alerts.py     save_alerts / save_last_check_sha (write .baton/ state only)
  NEVER writes BATON.md or any source file.
```

**`core/schema.py` is the single source of truth.** `SCORE_CHECKS` (12 checks, total 100 pts) lives here and is imported by `score.py`. A module-level `assert` enforces the total at import time — adding a check without rebalancing points fails immediately. Also defines `SUPERSEDABLE_TYPES` — the three entry types that support supersession chains and their text/date field names.

**LLM provider abstraction** (`llm/`): `LLMProvider` ABC with `complete(system, user, model) -> str`. Three implementations: `AnthropicProvider` (core dep, uses prompt caching on the static system block), `OpenAIProvider` (optional `[openai]` extra, lazy import), `VertexProvider` (optional `[vertex]` extra, lazy import). Factory: `get_provider(config)`.

**Diff strategy** (`core/gitdiff.py`): `resolve_base_ref` reads the `commit` SHA from the last session entry in BATON.md so each `baton end` diffs from where the previous session ended. Falls back to `git diff HEAD` on first run. Diffs are capped at 24k chars to avoid blowing the LLM token budget. `resolve_since(repo_root, since) -> str` resolves a user-supplied `--since` value in two steps: (1) literal `git rev-parse --verify <since>^{commit}` (handles SHAs, branches, tags, `HEAD~N`); (2) reflog date syntax `@{<since>}^{commit}` (handles `"yesterday"`, `"1 week ago"`). Both failing raises `GitError`. Date phrases are **local-only** — CI must always pass an explicit PR base SHA, never a date phrase.

**Heuristic delta-source** (`core/heuristic.py`): `heuristic_delta(diff_text, commit_log, doc_data) -> dict` is the zero-cost default for `baton end`. Returns the same dict shape as `parse_delta()`. Infers `session` summary/highlights and `sprint_done`/`sprint_next` from diff stats and commit subjects. Also extracts curated sections from **explicit inline markers** in commit subjects or added diff lines — `DECISION:`, `ANTI:`/`REJECTED:`, `LANDMINE:`, `QUESTION:`/`OPENQ:`. Curated sections (`decisions`, `anti_decisions`, `landmines`, `open_questions`) appear in the delta **only when markers are found** — they are NEVER inferred from ordinary code.

**Full-memory delta contract** (`core/summarizer.py`): `JSON_SPEC` defines the full schema for all three modes. All seven sections: `session`, `sprint_done`, `sprint_next`, `decisions`, `anti_decisions`, `landmines`, `open_questions`. `parse_delta()` coerces all seven with safe defaults; curated sections absent when list is empty.

**Injectable test seams in `run_end()`**: four test-only keyword arguments — `summarizer` (`(system, user, config) -> str`) bypasses the real LLM call and implies `mode='api'` (backward compat); `stdin_reader` (`() -> str`) injects a fake stdin for the `--apply` path; `auto_accept=True` skips interactive prompts; `nudge_accept: bool | None` controls the supersession nudge (True=accept-all, False=decline-all, None=interactive). Do not remove or change these signatures.

**`_merge_delta()` in `commands/end.py`**: append-only writes to all seven sections. Uses `_next_id(seq, prefix)` to assign gap-tolerant, zero-padded IDs (e.g. `d002`, `a001`, `l003`, `q003`) for all four curated types. Deduplicates by primary text field. A heuristic delta missing curated keys merges cleanly — `accepted.get(key) or []` handles absence.

**Managed-block pattern** (`adapters/base.py`): `sync` never replaces a whole file. It only rewrites the region between `BATON:START` and `BATON:END` HTML comment markers via `upsert_managed_block()`. `status.py` uses `extract_managed_block()` + a fresh `adapter.render()` to detect drift without any LLM or git calls. The underlying `upsert_named_block(text, inner, start_marker, end_marker)` and `extract_named_block(text, start_marker, end_marker)` are generic and reused by the supersession appendix region in BATON.md.

**Session-end protocol in `render_markdown_context()`** (`adapters/base.py`): appends a "Session-End Protocol" block describing the `--diff-only → --apply` workflow for all `tool_name` values **except `"claude-code"`**. Claude Code has a dedicated skill; injecting the block into `CLAUDE.md` would be redundant. All other adapters (codex, gemini, cursor, copilot) receive it.

**Cursor adapter** (`adapters/cursor.py`) overrides `prepare_file()` because `.mdc` files require YAML frontmatter at the top of the file, outside the managed block.

**`baton install-skill`** (`commands/install_skill.py`): writes `.claude/skills/baton-end/SKILL.md` from an embedded template string. Idempotent without `--force`. The skill body is thin and schema-free — it instructs Claude to run `baton end --diff-only` to get the live contract. Unlike adapter outputs, the skill is a **durable, user-committable** file and must NOT be gitignored.

**`baton doctor`** (`commands/doctor.py`): runs six check groups — BATON.md validity, `.baton.toml` config, adapter detection, per-file dry-run sync, all three provider API keys, and optional dependencies. Prints `PASS / WARN / FAIL` with inline fix hints. Always exits 0. The `ANTHROPIC_API_KEY` check emits `WARN` (never `FAIL`) — only `baton end --api` needs it. The tiktoken check emits `WARN` when absent with a `pip install "baton-pass[tokens]"` hint — `baton health` degrades to a word-count heuristic, never crashes.

**Data flow for `baton init --scan`:**

```
cli.py  (--scan | --exhaustive | --skip-pr-history | --skip-docs)
  -> commands/init.py  run_init(scan=True, ...)
    -> core/pr_template.py    write_pr_template()  (.github/pull_request_template.md, once)
    -> commands/scan.py       run_scan(repo_root, exhaustive, skip_pr_history, skip_docs)
      -> core/manifest.py       read_manifest_deps()     full-file manifest read (prod/dev split)
      -> core/scan_manifest.py  scan_manifests()         prod deps -> decision drafts
      -> core/scan_comments.py  scan_comments()          HACK/FIXME/WARNING/TODO -> landmine drafts
      -> core/scan_docs.py      scan_docs()              README sections + ADRs -> decision drafts
      -> core/scan_pr.py        scan_prs(runner=...)     gh PR history + WHY:/BATON: markers
      -> multi-source merge     manifest canonical; PR WHY: enriches why field
      -> confidence filter      default: high only; --exhaustive: all
      -> dedup against existing BATON.md entries (by what/rejected/location/question)
      -> _next_id(seq, prefix)  assign gap-tolerant IDs
      -> doc.save()             append-only; existing entries never touched
  All drafts: status=pending_review, excluded from drift/sync/score/supersession until accepted.
  NEVER infers decisions from ordinary code — only explicit manifest deps and markers.
```

**Data flow for `baton scope`:**

```
cli.py  (task | --clear)
  -> commands/scope.py  run_scope(repo_root, task, clear)
    --clear path:
      scope_active()? -> clear_scope() -> run_sync(quiet=True) -> done
    normal path:
      -> core/document.py     BatonDocument.load()
      -> _render_data(data)   active_entries() filter (never pending_review)
      -> core/scope_match.py  build_scope(task, data) -> ScopeResult
           core/scope_keywords.py  extract_keywords(task)  stopword-filtered tokens
           Tier-1: keyword overlap against entry text fields + tags
           Tier-2: file-path token overlap (e.g. "auth" from "src/auth/redirect.py")
           Always-include: entries with global: true bypass both tiers
      -> core/scope_io.py     save_scope() -> .baton/scope.json
      -> core/scope_render.py render_scope_md() -> .baton/scope.md  (committable)
      -> core/gitignore.py    ensure_scope_committable()  (negation line in .gitignore)
      -> commands/sync.py     run_sync(quiet=True)  (adapters now write SCOPED blocks)
```

**Data flow for `baton review`:**

```
cli.py
  -> commands/review.py  run_review(repo_root)
    -> _collect_pending(data)   all status==pending_review entries, sorted high->low confidence
    -> per entry: _display_entry() -> _prompt_action()
         [a] _accept_entry()   flip status to "active", doc.save()
         [e] click.edit()      open whole BATON.md in $EDITOR, reparse on close
         [d] _delete_entry()   remove from list, doc.save()
         [s]                   advance index, leave as pending_review
    -> empty queue: prints clear "Nothing to review" message, exit 0
```

**Data flow for `baton health`:**

```
cli.py  (--format | --model)
  -> commands/health.py  run_health(repo_root, fmt, model)
    -> core/document.py    BatonDocument.load() (read-only; BatonDocumentError -> exit 1)
    -> core/tokens.py      count_tokens(raw_text, model=model) -> (total, method)
    -> core/config.py      BatonConfig.load(); [health] section thresholds
    -> core/staleness.py   collect_findings(data, config, today, model=model) -> list[finding]
    -> core/healthfmt.py   render_human / render_json / render_github (format dispatch)
  Envelope: {generated_at, total_tokens, token_method, thresholds, token_status, counts, findings}
  exit 1 if token_status=="error" (total > token_error threshold), else 0.
  NEVER writes BATON.md or any source file.
```

**Data flow for `baton trim`:**

```
cli.py  (--dry-run | --auto | --budget | --compress | --force | --model)
  -> commands/trim.py  run_trim(repo_root, ...)
    -> core/document.py    BatonDocument.load()
    -> core/gitdiff.py     working_tree_dirty() -- clean-tree gate (unless --force)
    -> core/config.py      BatonConfig.load()
    -> core/staleness.py   collect_prunable(data, config, today, model) -> list[PrunableEntry]
                           -- superseded ancestors NEVER in list (only --compress removes those)
    -> [mode branch]
         interactive  display panel + [d]/[s]/[q] prompt per entry; reload doc each iteration
         --auto       print list + single Y/n; bulk delete
         --budget N   tier-ordered deletion until projected total <= N; refuse if unreachable
         --compress   chain_heads() -> for each head with depth >= min_depth:
                        chain_backward() -> collect ancestors -> del from doc
                        set head[HISTORY_COMPRESSED_FIELD]=True + head[ORIGINAL_DATE_FIELD]
    -> doc.save() FIRST
    -> [compress only] doc.upsert_markdown_region(SUPERSEDED_START, SUPERSEDED_END, ...)
    -> commands/sync.py   run_sync(repo_root, quiet=True)
    -> print commit reminder (never git add/commit)
```

**`pending_review` blast radius — `active_entries()` is the single choke-point.** `core/schema.py` defines `PENDING_REVIEW = "pending_review"` and `active_entries(entries) -> list` (drops `status == PENDING_REVIEW`). Six sites must call it — missing one means drafts leak into that operation:
1. **Drift** (`commands/check.py`): filter each list before the three detectors
2. **Sync rendering** (`commands/sync.py`): `_render_data(data)` shallow-copies with filtered lists before `adapter.render()`
3. **Status comparison** (`commands/status.py`): same `_render_data()` pattern
4. **Score counts** (`core/schema.py`): `_check_decisions` / `_check_anti_decisions` / `_check_landmines` call `active_entries()` internally
5. **Supersession** (`core/supersede.py` `detect_overlaps`): excludes pending entries from `active_existing`
6. **`_merge_delta` dedup** (`commands/end.py`): `existing_whats` / `existing_rejected` / `existing_locations` sets exclude pending entries so a real `baton end` entry isn't silently dropped against a draft with the same text
7. **Scope rendering** (`commands/scope.py`): `_render_data(data)` filters before `build_scope()` so scope matching never matches pending drafts

**`core/markers.py` — shared marker regex module.** Lifted out of `heuristic.py` so both `heuristic.py` and `scan_pr.py` import from the same place. Six regexes: `MARKER_DECISION`, `MARKER_ANTI`, `MARKER_LANDMINE`, `MARKER_QUESTION`, `MARKER_WHY`, `MARKER_BATON`. `MARKER_BATON` is anchored to NOT match `BATON:START` / `BATON:END` / `BATON:SUPERSEDED`. Public API: `parse_markers(lines: list[str]) -> dict` returns `{decisions, anti_decisions, landmines, open_questions, why, baton_ids}`. `heuristic.py` imports from here and is a thin wrapper.

**`core/manifest.py` — full-file manifest reader.** `read_manifest_deps(repo_root) -> list[{name, manifest, section}]`. Supports `package.json` (JSON by section), `pyproject.toml` (section-based), `requirements*.txt` (dev/test/lint → "dev"), `Pipfile`, `Cargo.toml`, `go.mod`. Names normalised: lowercase, underscores→hyphens. `scan_manifest.py` filters to `section=="prod"` only — dev/test/lint deps are never drafted.

**Supersession chains** (`core/supersede.py`): pure derivation module (no I/O, no git). Provides `find_entry`, `derive_status`, `resolve_head` (cycle-guarded), `chain_backward` (returns `list[list[dict]]` for fan-in), `validate_link` (enforces all 5 rules), `render_superseded_appendix`, and `detect_overlaps`. Constants `SUPERSEDED_START`/`SUPERSEDED_END` define the appendix region markers — import these everywhere rather than writing literal strings. All supersession state derives from the `supersedes: [...]` and `reason: ""` fields on **new** entries; old entries are never touched. The appendix (`## Superseded` section below the yaml fence) is written by `BatonDocument.upsert_markdown_region()` which delegates to `upsert_named_block`. `baton status` shows a one-time heads-up when the appendix is hand-edited (gated by sha256 hash in `.baton/appendix_notice.json`). `baton end` runs a supersession nudge after merge via `_run_supersession_nudge()`, which uses `detect_overlaps` and calls `run_supersede` on accept; declines stored in `.baton/supersede_declined.json`.

**`core/tokens.py`** — lazy tiktoken wrapper. `tiktoken_available() -> bool` (cached probe). `count_tokens(text, *, model=None) -> tuple[int, str]` returns `(count, method)` where method is `"tiktoken:<enc>"` or `"heuristic"`. Falls back to `round(words * 1.3)` on any exception — never raises. `count_entry_tokens(entry, *, model=None) -> int` serializes one entry via ruamel then counts. `DEFAULT_ENCODING = "cl100k_base"`. Install tiktoken: `pip install "baton-pass[tokens]"`.

**`core/staleness.py`** — pure module (no I/O, no git). Finding model: `{type, severity∈{info,warn,error}, detail, entry_ids: list[str], token_cost: int}`. Type constants: `SUPERSEDED_PRESENT`, `RESOLVED_LANDMINE`, `POSSIBLY_RESOLVED_LANDMINE`, `STALE_DECISION`, `STALE_QUESTION`, `RESOLVED_QUESTION_PRESENT`, `COMPRESSIBLE_CHAIN`, `DECISION_MISSING_EVIDENCE`, `IDLESS_LANDMINE`, `ENTRY_COUNTS`. Exported predicates: `parse_date`, `question_age_days`, `is_stale_question`, `chain_depth`, `chain_heads`. Orchestrators: `collect_findings(data, config, today) -> list[finding]` (health); `collect_prunable(data, config, today) -> list[PrunableEntry]` (trim — priority-ordered, superseded ancestors excluded). `@dataclass PrunableEntry`: `type_key, entry (live ruamel ref), reason, priority, token_cost`.

**`core/healthfmt.py`** — mirrors `core/checkfmt.py`. Three renderers: `render_human(result, console)`, `render_json(result)`, `render_github(result)`. Re-exports `_escape_data` / `_escape_property` from `checkfmt`. GitHub output: `::error` once at ERROR threshold; `::warning` per warn finding; info findings omitted.

## Non-obvious invariants

**`re.sub` replacements must use a lambda.** `re.sub(pattern, block, text)` interprets `\n` in a plain string replacement as an actual newline. When the replacement contains YAML-derived data (which may include literal `\n`), this silently corrupts the output. Always write: `re.sub(pattern, lambda _m: block, text)`. This applies to both `upsert_managed_block()` in `adapters/base.py` and `save()` in `core/document.py`.

**YAML fence regex** (`_YAML_FENCE_RE` in `document.py`): the pattern is `r"```yaml\n(.*?)\n```"`. The `\n` before the closing backticks is load-bearing — without it, triple-backticks inside a YAML string value terminate the match early.

**`_review()` return dict must include all seven keys.** The function currently returns `session`, `sprint_done`, `sprint_next`, `decisions`, `anti_decisions`, `landmines`, `open_questions`. If any curated key is missing from the return dict, `_merge_delta` silently skips it — the agent's work is lost with no error. Expanding `JSON_SPEC` without expanding `_review`'s return is a silent data-loss bug.

**Heuristic curated sections: absent ≠ empty.** The heuristic omits curated keys entirely when no markers are found (not `[]`). Every consumer of the delta dict must use `.get(key) or []`, never `delta[key]`. The test `test_heuristic_delta_no_markers_means_curated_sections_absent` guards this invariant.

**`open_questions` from `scan_pr.py` use `status: "open"`, not `PENDING_REVIEW`.** The `status` field on open questions means "open / discussed / resolved" — it has a different vocabulary from the pending_review lifecycle. Questions scanned from PR history are written directly to BATON.md with `status: "open"` (their normal state) and do NOT appear in `baton review`. Only decisions, anti_decisions, and landmines from scan use `PENDING_REVIEW`.

**`detect_enabled` returns only found adapters.** If only `CLAUDE.md` exists in the target project, only the Claude adapter runs. A `.baton.toml` with `[adapters] enabled = [...]` overrides this.

**`_make_alert()` `matched` field is required for `findings.py` to work.** Every `_make_alert(...)` call in `drift.py` must pass a correct `matched=` value: the raw matched string (diff line for regex, module name for import, dep name for dependency, evidence value for decision, marker token for landmine). `findings.py` uses `matched` to build `reason` without re-parsing `detail` prose. A missing or wrong `matched` silently degrades the output quality. The `matched` field defaults to `""` (backward-compatible) but every detector must populate it.

**`--quiet` is a deprecated alias** for `--format json`. When `quiet=True` and `fmt == "human"` (the default), `run_check` sets `fmt = "json"` and prints a deprecation note to **stderr**. If `fmt` is already `"json"` (user passed both flags), no deprecation is printed. Stdout stays pure JSON in both cases — hooks that read stdout are unaffected.

**Never write the literal marker text** (`BATON:START` / `BATON:END`) inside code fences in any file Baton manages. The regex scans the full file and cannot distinguish examples from real markers.

**`baton check --drift` is read-only on BATON.md and all source files.** It writes only `.baton/alerts.json`, `.baton/last_check_sha`, and `.baton/ack.json`. Entry `status` transitions (active/stale/contradicted) surface to the human through `baton status` and the `baton end` wrap-up prompt — they are NEVER auto-written by a hook or the check command.

**Hook managed-block pattern.** `baton init` and `baton hooks install` use `upsert_managed_block()` from `adapters/base.py` to own a delimited region inside `.git/hooks/pre-commit` and `.git/hooks/post-commit`. This lets Baton update its own hook lines without destroying user content or other tools' hook content. Do not write raw hook files that bypass this pattern. `baton init` automatically installs both hooks (non-blocking pre-commit reminder + advisory post-commit drift check). `baton hooks install --strict` replaces the pre-commit reminder with a blocking strict hook that exits non-zero on `block`-severity alerts.

**New optional drift fields on BATON.md entries are backward compatible.** Any decision/anti_decision/landmine entry lacking the new fields (`evidence`, `pattern`, `severity`, `marker`, `id`, `status`) is silently skipped by `baton check --drift` — never an error, never a migration required. Valid values (all from `core/schema.py`):
- `anti_decision.pattern.type`: `"regex"` | `"import"` | `"dependency"` — matched against added (+) diff lines, Python/JS imports, or manifest deps respectively
- `anti_decision.severity`: `"warn"` | `"block"` (controls `--fail-on` exit code)
- `decision.evidence.type`: `"dependency"` | `"file"` | `"config_key"` — fires when the anchoring artifact is removed

**`BATON-LANDMINE:<id>` in-source comment convention.** Place a comment like `# BATON-LANDMINE:l001` (or `BATON-LANDMINE:<marker>` using the `marker` field) in source code near intentional weirdness. `detect_landmines` uses this: if the comment line is *deleted* in the diff → `"possibly_resolved"` alert; if the file is merely *touched* → `"touched"` alert. The `id`/`marker` field on the BATON.md landmine entry must match the token in the comment.

**`astscan.py` uses `tree_sitter_languages` optionally.** JS/TS import extraction prefers `tree_sitter_languages` if installed; falls back to regex. Install it with `pip install tree-sitter-languages` for higher accuracy. Python import extraction always uses `stdlib ast`.

**Three-layer detect → template → render architecture** (`baton check --drift`): detectors (`core/drift.py`) produce raw alert dicts with a `matched` field; `core/findings.py` enriches them with `reason`/`suggestion`/`fix_command` (pure string templates, no LLM); `core/checkfmt.py` renders the enriched result in the requested format. Adding a new drift type = one detector function + one `findings.py` template function; renderers never change.

**`core/findings.py`**: single public function `enrich_alerts(alerts, doc_data) -> list[dict]`. Builds an id→entry index from `anti_decisions`, `decisions`, `landmines` in `doc.data`, then dispatches to `_enrich_anti_decision`, `_enrich_decision`, or `_enrich_landmine` per alert type. Guarantees `reason`, `suggestion`, `fix_command` are present on every alert after the call (falls back to `detail` for unknown types). The "no X — use Y" extraction from `rejected` text lives only here.

**`core/checkfmt.py`**: three public renderers — `render_human(result, console)`, `render_json(result)`, `render_github(result)`. GHA escaping helpers `_escape_property` and `_escape_data` replace `%` **first** (before `:`, `,`, `\n`) to prevent double-encoding. `render_github` emits bare `::error::msg` form when `file` is empty and `line` is 0.

**`baton check --drift` exit codes:** 0=clean (no alerts >= threshold), 1=warn-level alerts present, 2=block-level alerts present. Controlled by `--fail-on warn|block` (default: `warn`). All `--format` branches fall through to exit-code gating — no format branch may early-return before it.

**Supersession is append-only on old entries.** `baton supersede` may only write `supersedes: [...]` and `reason:` onto the *new* (`--with`) entry. The old entry's dict must never be touched. `validate_link` enforces: (1) reason non-empty, (2) no cycles, (3) single-claim (each old id claimed by at most one new), (4) same type, (5) shared-reason consistency (conflicting non-empty `--reason` on a second link to same new entry is rejected).

**`doc.data.get(section) or []` disconnects from ruamel on empty sections.** An empty `CommentedSeq` is falsy, so `or []` replaces the live document node with a disconnected plain list — `doc.save()` then writes the original empty section while the caller thinks it saved entries. Always use `is not None`:
```python
lst = doc.data.get("decisions")
if lst is None:
    doc.data["decisions"] = lst = []
```
This applies anywhere you append to a BATON.md section list. `_merge_delta` in `end.py` already uses the correct pattern. `scan.py` was the location of this bug (now fixed).

**`detect_overlaps` needs the `new_ids` exclusion set.** After `_merge_delta`, the newly merged entries are already in `doc.data`. Pass `new_ids` (the ids assigned in this merge) to `detect_overlaps` so a new entry doesn't fuzzy-match itself against the existing pool.

**`baton trim` requires a clean working tree** (unless `--force`). `working_tree_dirty(repo_root, path)` in `core/gitdiff.py` uses `git status --porcelain -- <path>` via the existing `_run` chokepoint. Raises `GitError` when not a git repo (trim catches it, notes reminder, proceeds). Never call this with a hard-coded path — always pass `"BATON.md"`.

**Superseded ancestors are never in `collect_prunable`.** Plain `trim`/`--budget` cannot delete an entry that appears in another entry's `supersedes` list — doing so would dangle the reference. Only `--compress` removes superseded ancestors, and it simultaneously removes the head's `supersedes` list to keep the document consistent. `collect_prunable` enforces this by calling `derive_status` and filtering out any entry where the result is `"superseded"`.

**`--compress` sets `history_compressed: true` + `original_date` on the surviving head.** After deleting ancestors and removing the head's `supersedes` list, set `head[HISTORY_COMPRESSED_FIELD] = True` and `head[ORIGINAL_DATE_FIELD] = oldest_ancestor_date.isoformat()`. The constants live in `core/schema.py`. This marks the entry as having lost ancestors so future readers know history was pruned. After `doc.save()`, re-render the superseded appendix via `doc.upsert_markdown_region(SUPERSEDED_START, SUPERSEDED_END, render_superseded_appendix(doc.data))` — with `supersedes` removed, the chain's bullets vanish cleanly.

**`apply_scope` must be called AFTER `active_entries()`.** `sync.py` and `status.py` both call `_render_data()` first (which runs `active_entries()`), then call `apply_scope()` on the result. Reversing the order would let `apply_scope` snapshot pending_review IDs into the scope, which then survive `active_entries()` in subsequent calls.

**`global: true` on an entry bypasses scope filtering entirely.** Mark an entry `global: true` in BATON.md to make it always-include in any active scope. This is the correct way to pin cross-cutting decisions (e.g. "never use PyYAML") that should always be visible regardless of task. `is_global(entry)` in `core/schema.py` is the single check — import it rather than reading the field directly.

**`.gitignore` negation for `scope.md` requires directory-level rewrite.** A bare `.baton/` ignore line + appended `!.baton/scope.md` negation does NOT work — git will not descend into an ignored directory. `core/gitignore.py:ensure_scope_committable()` handles this by rewriting `.baton/` to `.baton/*` before appending the negation line. Do not simplify this to a bare append.

## `.baton/` state files

Most `.baton/` files are gitignored (`.baton/` in `.gitignore`). Exception: `.baton/scope.md` is **committable** — `baton scope` rewrites `.gitignore` to add a negation line so teammates can read the active scope.

- `.baton/alerts.json` — current drift alerts (schema: `{generated_at, since_sha, alerts: [{id, type, severity, status, file, line, detail}]}`)
- `.baton/last_check_sha` — plain text, last HEAD SHA that was checked
- `.baton/ack.json` — acknowledged alerts: `[{id, reason, sha, date}]`
- `.baton/appendix_notice.json` — sha256 hash of the last shown appendix-drift heads-up (`{"hash": "..."}`)
- `.baton/supersede_declined.json` — pairs the user declined to supersede during `baton end` nudge (`[{old_id, new_id, date}]`)
- `.baton/scope.json` — active scope state: `{task, keywords, entry_ids, generated_at}`; absent means no active scope
- `.baton/scope.md` — committable rendered scope artifact; lists matched entries by section; regenerate with `baton scope "<task>"`

All files are loaded with safe defaults (`{}` / `[]` / `None`) when absent or corrupt — never raise. Alerts I/O is in `core/alerts.py`; scope I/O is in `core/scope_io.py`.

## Adding a new adapter

Create `baton/adapters/mytool.py`, subclass `BaseAdapter`, implement `render()` and `file_path()`. Register in `ADAPTER_MAP` and `_DETECTION_RULES` in `registry.py`. See `CONTRIBUTING.md` for the full ~50-line pattern. The session-end protocol block is injected automatically by `render_markdown_context()` for any `tool_name` other than `"claude-code"`.

## Adding a new drift detector

Drift detectors are pure functions in `core/drift.py` with signature `detect_<name>(diff_text, entries, **kwargs) -> list[dict]`. Add the function, call it from `commands/check.py` in the detection pipeline, add any new optional BATON.md field names to `core/schema.py`, add an enrichment branch in `core/findings.py`, and add tests in `tests/test_drift.py` using synthetic diff strings — no real git or filesystem needed. Renderers in `core/checkfmt.py` never change for new detector types.

## Scan confidence levels

`baton init --scan` assigns confidence by source:
- `scan_manifest.py` (prod deps): always `"high"`
- `scan_comments.py` (HACK/FIXME/WARNING/TODO): always `"high"`
- `scan_docs.py` (README sections): `"medium"`; ADRs with an explicit `Decision:` section: `"high"`
- `scan_pr.py` (PR `WHY:`/`BATON:` markers): `"high"`

Default run includes only `"high"` entries. `--exhaustive` adds `"medium"` and `"low"`.

## `.baton.toml` config fields

All fields live under `[baton]` or `[adapters]` sections. `BatonConfig.load()` silently falls back to defaults on missing file or malformed TOML — the CLI never raises on config errors.

```toml
[baton]
llm_provider = "anthropic"   # "anthropic" | "openai" | "vertex"
model        = ""            # "" = provider default; e.g. "claude-opus-4-8"
min_diff_lines = 10          # skip baton end if diff is smaller than this
auto_sync    = true          # run baton sync automatically after baton end

[adapters]
enabled = []                 # [] = auto-detect; or list e.g. ["claude", "cursor"]

[health]
token_warn              = 4000   # baton health: WARN threshold (tokens)
token_error             = 8000   # baton health: ERROR threshold; exit 1 (tokens)
staleness_question_days = 30     # open questions older than this = stale
compress_min_depth      = 3      # chain depth >= this is flagged as compressible
```

## `baton-action/` directory

Contains deliverable files for the **separate** `AriS10223/baton-action` GitHub repo (the composite GitHub Action for the Marketplace). These files are not part of the pip package — they are dropped into the root of a new public repo and published separately. Do not move or import from this directory within the main package.

## Hard constraints

- **Never use PyYAML** — it drops inline `#` comments on round-trip. `ruamel.yaml` is mandatory.
- **`schema.py` owns all BATON.md field names.** Don't define section names in `score.py` or anywhere else.
- **`baton end` is the only LLM command.** `init`, `sync`, `status`, `score`, `doctor`, `install-skill`, `check`, `hooks`, `supersede`, `history`, `review`, `scan` (via `init --scan`), `scope`, `health`, and `trim` are purely deterministic — no network calls, no API key. (`scan_pr.py` calls the `gh` CLI, not an LLM; and only when `--skip-pr-history` is not set.)
- **Curated memory is never inferred from code.** `decisions`/`anti_decisions`/`landmines`/`open_questions` in the heuristic come only from explicit markers. Never add inference logic.
- Git commits: identity `AriS10223 <220664302+AriS10223@users.noreply.github.com>`, no Claude attribution.
