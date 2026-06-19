"""
test_install_skill.py -- Tests for baton/commands/install_skill.py.

All tests are deterministic: no git calls, no LLM, no network.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from baton.commands.install_skill import run_install_skill

EXPECTED_SKILL_PATH = ".claude/skills/baton-end/SKILL.md"


# ── Basic install ─────────────────────────────────────────────────────────────


def test_install_skill_creates_file(tmp_path: Path) -> None:
    run_install_skill(tmp_path)
    skill_path = tmp_path / EXPECTED_SKILL_PATH
    assert skill_path.exists()


def test_install_skill_creates_parent_directories(tmp_path: Path) -> None:
    run_install_skill(tmp_path)
    assert (tmp_path / ".claude" / "skills" / "baton-end").is_dir()


def test_install_skill_file_is_utf8(tmp_path: Path) -> None:
    run_install_skill(tmp_path)
    skill_path = tmp_path / EXPECTED_SKILL_PATH
    # Should be readable as UTF-8 without errors.
    content = skill_path.read_text(encoding="utf-8")
    assert len(content) > 0


# ── Frontmatter ───────────────────────────────────────────────────────────────


def test_install_skill_has_name_field(tmp_path: Path) -> None:
    run_install_skill(tmp_path)
    content = (tmp_path / EXPECTED_SKILL_PATH).read_text(encoding="utf-8")
    assert "name: baton-end" in content


def test_install_skill_has_description_field(tmp_path: Path) -> None:
    run_install_skill(tmp_path)
    content = (tmp_path / EXPECTED_SKILL_PATH).read_text(encoding="utf-8")
    assert "description:" in content


def test_install_skill_description_names_session_triggers(tmp_path: Path) -> None:
    run_install_skill(tmp_path)
    content = (tmp_path / EXPECTED_SKILL_PATH).read_text(encoding="utf-8")
    # The description must mention session-end triggers so the model self-invokes.
    assert "session" in content.lower()
    assert "context" in content.lower()


def test_install_skill_frontmatter_delimited(tmp_path: Path) -> None:
    run_install_skill(tmp_path)
    content = (tmp_path / EXPECTED_SKILL_PATH).read_text(encoding="utf-8")
    assert content.startswith("---")
    # Must have a closing --- for the frontmatter block.
    lines = content.splitlines()
    closing = [i for i, ln in enumerate(lines) if ln.strip() == "---" and i > 0]
    assert closing, "No closing --- found for frontmatter"


# ── Body content ──────────────────────────────────────────────────────────────


def test_install_skill_body_references_diff_only(tmp_path: Path) -> None:
    run_install_skill(tmp_path)
    content = (tmp_path / EXPECTED_SKILL_PATH).read_text(encoding="utf-8")
    assert "baton end --diff-only" in content


def test_install_skill_body_references_apply(tmp_path: Path) -> None:
    run_install_skill(tmp_path)
    content = (tmp_path / EXPECTED_SKILL_PATH).read_text(encoding="utf-8")
    assert "baton end --apply" in content or "--apply" in content


def test_install_skill_body_does_not_embed_json_schema(tmp_path: Path) -> None:
    """The skill body must NOT hardcode the JSON schema -- it defers to --diff-only output."""
    run_install_skill(tmp_path)
    content = (tmp_path / EXPECTED_SKILL_PATH).read_text(encoding="utf-8")
    # The JSON schema uses specific field names in a combined block; check a distinctive fragment.
    assert '"sprint_done"' not in content
    assert '"anti_decisions"' not in content


# ── Idempotency ───────────────────────────────────────────────────────────────


def test_install_skill_idempotent_without_force(tmp_path: Path) -> None:
    """Re-running without --force must not overwrite an existing skill file."""
    run_install_skill(tmp_path)
    skill_path = tmp_path / EXPECTED_SKILL_PATH
    original_mtime = skill_path.stat().st_mtime

    # Modify the file manually.
    skill_path.write_text("# Custom content\n", encoding="utf-8")

    run_install_skill(tmp_path)  # no force -- should skip

    # File must still have our custom content.
    assert skill_path.read_text(encoding="utf-8") == "# Custom content\n"


def test_install_skill_force_overwrites(tmp_path: Path) -> None:
    """--force must overwrite an existing skill file."""
    run_install_skill(tmp_path)
    skill_path = tmp_path / EXPECTED_SKILL_PATH
    skill_path.write_text("# Custom content\n", encoding="utf-8")

    run_install_skill(tmp_path, force=True)

    content = skill_path.read_text(encoding="utf-8")
    assert content != "# Custom content\n"
    assert "name: baton-end" in content


# ── Not gitignored ────────────────────────────────────────────────────────────


def test_install_skill_not_in_gitignore(tmp_path: Path) -> None:
    """The skill file must NOT appear in the project .gitignore."""
    # Check the actual project .gitignore (not tmp_path).
    import os
    project_root = Path(__file__).parent.parent
    gitignore_path = project_root / ".gitignore"
    if not gitignore_path.exists():
        pytest.skip(".gitignore not found in project root")

    gitignore_text = gitignore_path.read_text(encoding="utf-8")
    # The skill path must not appear.
    assert ".claude/skills/baton-end" not in gitignore_text
    assert "baton-end/SKILL.md" not in gitignore_text
