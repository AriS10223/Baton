"""
tests/test_trim.py -- Tests for ``baton trim``.

Uses tmp_path + real git repos (no mocking).
Pattern mirrors test_check.py: build a git repo in tmp_path, write BATON.md,
commit it, then run trim operations.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from baton.commands.trim import run_trim


# ── Git + BATON.md helpers ────────────────────────────────────────────────────

def git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    git(["init"], tmp_path)
    git(["config", "user.email", "test@test.com"], tmp_path)
    git(["config", "user.name", "Test"], tmp_path)
    return tmp_path


def _write_baton(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _commit(repo: Path, msg: str = "initial") -> None:
    git(["add", "-A"], repo)
    git(["commit", "-m", msg], repo)


_BASE_BATON = """\
# BATON.md

```yaml
baton_version: "1.0"
last_updated: "2025-01-01"
project:
  name: TestProj
  purpose: Test project
decisions:
  - id: d001
    what: Use Python
    why: Familiarity
    made: "2025-01-01"
anti_decisions: []
landmines:
  - id: l001
    location: src/hack.py
    looks_like: broken
    actually: intentional
    status: confirmed_resolved
open_questions:
  - id: q001
    question: Which database?
    raised: "2024-01-01"
    status: resolved
    resolved_date: "2025-01-01"
sessions: []
```
"""

_BATON_WITH_STALE_DECISION = """\
# BATON.md

```yaml
baton_version: "1.0"
last_updated: "2025-01-01"
project:
  name: TestProj
  purpose: Test project
decisions:
  - id: d001
    what: Use PyYAML (stale approach)
    why: Was easy
    made: "2024-01-01"
    status: stale
  - id: d002
    what: Use ruamel.yaml (active)
    why: Better
    made: "2025-01-01"
anti_decisions: []
landmines: []
open_questions: []
sessions: []
```
"""

_BATON_WITH_SUPERSESSION = """\
# BATON.md

```yaml
baton_version: "1.0"
last_updated: "2025-01-01"
project:
  name: TestProj
  purpose: Test project
decisions:
  - id: d001
    what: Old approach
    why: First attempt
    made: "2024-01-01"
  - id: d002
    what: Better approach
    why: Improved
    made: "2024-06-01"
    supersedes:
      - d001
  - id: d003
    what: Latest approach
    why: Best
    made: "2025-01-01"
    supersedes:
      - d002
anti_decisions: []
landmines: []
open_questions: []
sessions: []
```

<!-- BATON:SUPERSEDED:START - auto-generated, do not edit by hand -->
## Superseded

- d001 -> d002 (2024-06-01): ""
- d002 -> d003 (2025-01-01): ""
<!-- BATON:SUPERSEDED:END -->
"""


# ── --dry-run ─────────────────────────────────────────────────────────────────

def test_dry_run_no_changes(repo):
    baton_path = repo / "BATON.md"
    _write_baton(baton_path, _BASE_BATON)
    _commit(repo)

    original = baton_path.read_text(encoding="utf-8")
    code = run_trim(repo, dry_run=True)
    assert code == 0
    assert baton_path.read_text(encoding="utf-8") == original


def test_dry_run_nothing_to_trim(repo):
    baton_path = repo / "BATON.md"
    content = """\
# BATON.md

```yaml
baton_version: "1.0"
project:
  name: Clean
  purpose: Nothing stale
decisions:
  - id: d001
    what: Good decision
anti_decisions: []
landmines: []
open_questions: []
sessions: []
```
"""
    _write_baton(baton_path, content)
    _commit(repo)
    code = run_trim(repo, dry_run=True)
    assert code == 0


# ── Clean-tree gate ───────────────────────────────────────────────────────────

def test_dirty_baton_md_halts(repo):
    """Uncommitted BATON.md changes should halt trim (exit 1)."""
    baton_path = repo / "BATON.md"
    _write_baton(baton_path, _BASE_BATON)
    _commit(repo)

    # Dirty the file without committing
    baton_path.write_text(_BASE_BATON + "\n<!-- dirty -->", encoding="utf-8")

    code = run_trim(repo, auto=True)  # auto mode to bypass interactive prompt
    assert code == 1


def test_dirty_baton_md_force_proceeds(repo):
    """--force should bypass the clean-tree gate."""
    baton_path = repo / "BATON.md"
    _write_baton(baton_path, _BASE_BATON)
    _commit(repo)

    baton_path.write_text(_BASE_BATON + "\n<!-- dirty -->", encoding="utf-8")

    # dry_run + force to avoid actually mutating
    code = run_trim(repo, dry_run=True, force=True)
    assert code == 0


# ── Interactive mode (simulated via --dry-run) ────────────────────────────────

def test_interactive_dry_run_finds_stale(repo):
    """With stale entries, interactive dry-run should return 0 and not change file."""
    baton_path = repo / "BATON.md"
    _write_baton(baton_path, _BASE_BATON)
    _commit(repo)

    original = baton_path.read_text(encoding="utf-8")
    code = run_trim(repo, dry_run=True)
    assert code == 0
    assert baton_path.read_text(encoding="utf-8") == original


# ── --auto mode ───────────────────────────────────────────────────────────────

def test_auto_dry_run_does_not_modify(repo):
    """--auto --dry-run should not modify the file."""
    baton_path = repo / "BATON.md"
    _write_baton(baton_path, _BASE_BATON)
    _commit(repo)

    original = baton_path.read_text(encoding="utf-8")
    code = run_trim(repo, auto=True, dry_run=True)
    assert code == 0
    assert baton_path.read_text(encoding="utf-8") == original


def test_auto_nothing_to_trim(repo):
    """--auto on a clean BATON.md should exit 0."""
    baton_path = repo / "BATON.md"
    content = """\
# BATON.md

```yaml
baton_version: "1.0"
project:
  name: Clean
  purpose: Nothing stale
decisions:
  - id: d001
    what: Good decision
anti_decisions: []
landmines: []
open_questions: []
sessions: []
```
"""
    _write_baton(baton_path, content)
    _commit(repo)
    code = run_trim(repo, auto=True)
    assert code == 0


# ── --budget mode ─────────────────────────────────────────────────────────────

def test_budget_already_under_target(repo):
    """If already under budget, should exit 0 without changes."""
    baton_path = repo / "BATON.md"
    _write_baton(baton_path, _BASE_BATON)
    _commit(repo)

    from baton.core.tokens import count_tokens
    total, _ = count_tokens(_BASE_BATON)
    big_budget = total + 10_000  # well above current size

    code = run_trim(repo, budget=big_budget, dry_run=True)
    assert code == 0


def test_budget_dry_run_no_changes(repo):
    baton_path = repo / "BATON.md"
    _write_baton(baton_path, _BASE_BATON)
    _commit(repo)

    original = baton_path.read_text(encoding="utf-8")
    code = run_trim(repo, budget=1, dry_run=True)
    # 1 token is unreachable but dry_run doesn't touch the file
    assert baton_path.read_text(encoding="utf-8") == original


def test_budget_unreachable_returns_1(repo):
    """An unreachable budget (1 token) should refuse and exit 1."""
    baton_path = repo / "BATON.md"
    _write_baton(baton_path, _BASE_BATON)
    _commit(repo)

    code = run_trim(repo, budget=1, force=True)
    assert code == 1


# ── --compress mode ───────────────────────────────────────────────────────────

def test_compress_dry_run_no_changes(repo):
    baton_path = repo / "BATON.md"
    _write_baton(baton_path, _BATON_WITH_SUPERSESSION)
    _commit(repo)

    original = baton_path.read_text(encoding="utf-8")
    code = run_trim(repo, compress=True, dry_run=True)
    assert code == 0
    assert baton_path.read_text(encoding="utf-8") == original


def test_compress_no_chains_exits_0(repo):
    """--compress on BATON.md with no compressible chains should exit 0."""
    baton_path = repo / "BATON.md"
    _write_baton(baton_path, _BASE_BATON)
    _commit(repo)

    code = run_trim(repo, compress=True, dry_run=True)
    assert code == 0


# ── Superseded ancestors refused (non-compress path) ─────────────────────────

def test_superseded_ancestor_not_in_prunable(repo):
    """Superseded ancestors must not appear in collect_prunable output."""
    baton_path = repo / "BATON.md"
    _write_baton(baton_path, _BATON_WITH_SUPERSESSION)
    _commit(repo)

    import datetime
    from baton.core.config import BatonConfig
    from baton.core.document import BatonDocument
    from baton.core.staleness import collect_prunable

    doc = BatonDocument.load(baton_path)
    config = BatonConfig()
    today = datetime.date.today()
    prunable = collect_prunable(doc.data, config, today)

    prunable_ids = [p.entry.get("id") for p in prunable]
    assert "d001" not in prunable_ids  # superseded ancestor
    assert "d002" not in prunable_ids  # superseded ancestor


# ── Post-trim state ───────────────────────────────────────────────────────────

def test_missing_baton_md_exits_1(tmp_path):
    code = run_trim(tmp_path, dry_run=True)
    assert code == 1


# ── Commit reminder (no auto-commit) ─────────────────────────────────────────

def test_no_git_commit_after_trim(repo):
    """Trim must never auto-commit -- HEAD SHA must be unchanged after --dry-run."""
    baton_path = repo / "BATON.md"
    _write_baton(baton_path, _BASE_BATON)
    _commit(repo)

    before_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    run_trim(repo, dry_run=True)

    after_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    assert before_sha == after_sha


# ── Mutually exclusive flags (tested via CLI-level guard in cli.py) ───────────

def test_run_trim_mutual_exclusion_auto_compress(repo):
    """run_trim is not responsible for the exclusive guard (cli.py does it).
    But we can verify it doesn't explode if only one mode is given.
    """
    baton_path = repo / "BATON.md"
    _write_baton(baton_path, _BASE_BATON)
    _commit(repo)

    code = run_trim(repo, compress=True, dry_run=True)
    assert code == 0
