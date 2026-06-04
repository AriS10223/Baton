"""
test_document.py — Tests for BatonDocument (load / save / round-trip).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from baton.core.document import BatonDocument, BatonDocumentError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_path(tmp_path: Path) -> Path:
    """Copy sample_baton.md into a temp directory and return its path."""
    src = FIXTURES / "sample_baton.md"
    dst = tmp_path / "BATON.md"
    shutil.copy(src, dst)
    return dst


# ── Load ──────────────────────────────────────────────────────────────────────

def test_load_parses_project_fields(sample_path: Path) -> None:
    doc = BatonDocument.load(sample_path)
    assert doc.data["project"]["name"] == "TestProject"
    assert "vibe coders" in doc.data["project"]["purpose"]
    assert doc.data["project"]["stage"] == "prototype"


def test_load_parses_stack(sample_path: Path) -> None:
    doc = BatonDocument.load(sample_path)
    stack = doc.data["stack"]
    assert len(stack) == 2
    assert stack[0]["tool"] == "Flask"
    assert stack[0]["version"] == "3.0.0"


def test_load_parses_lists(sample_path: Path) -> None:
    doc = BatonDocument.load(sample_path)
    assert len(doc.data["laws"]) == 2
    assert len(doc.data["decisions"]) == 1
    assert len(doc.data["anti_decisions"]) == 1
    assert len(doc.data["open_questions"]) == 1


def test_load_raises_if_file_missing(tmp_path: Path) -> None:
    with pytest.raises(BatonDocumentError, match="not found"):
        BatonDocument.load(tmp_path / "BATON.md")


def test_load_raises_if_no_yaml_block(tmp_path: Path) -> None:
    bad = tmp_path / "BATON.md"
    bad.write_text("# No YAML block here\n\nJust plain markdown.", encoding="utf-8")
    with pytest.raises(BatonDocumentError, match="yaml"):
        BatonDocument.load(bad)


# ── get() helper ─────────────────────────────────────────────────────────────

def test_get_nested(sample_path: Path) -> None:
    doc = BatonDocument.load(sample_path)
    assert doc.get("project", "purpose") == "Solve the context-loss problem for vibe coders"


def test_get_missing_key_returns_default(sample_path: Path) -> None:
    doc = BatonDocument.load(sample_path)
    assert doc.get("project", "nonexistent_field") is None
    assert doc.get("project", "nonexistent_field", default="fallback") == "fallback"


# ── Round-trip ────────────────────────────────────────────────────────────────

def test_save_round_trips_data(sample_path: Path) -> None:
    """Load → mutate → save → reload should reflect the mutation."""
    doc = BatonDocument.load(sample_path)
    doc.data["project"]["purpose"] = "Updated purpose"
    doc.save()

    doc2 = BatonDocument.load(sample_path)
    assert doc2.data["project"]["purpose"] == "Updated purpose"


def test_save_preserves_surrounding_markdown(sample_path: Path) -> None:
    """The markdown header/footer outside the yaml block must survive a save."""
    original_text = sample_path.read_text(encoding="utf-8")
    doc = BatonDocument.load(sample_path)
    doc.data["project"]["name"] = "ChangedName"
    doc.save()

    saved_text = sample_path.read_text(encoding="utf-8")
    # The header comment above the yaml block should still be present.
    assert "Living Project Onboarding Document" in saved_text
    # The yaml block should contain the mutated value.
    assert "ChangedName" in saved_text


def test_save_preserves_non_yaml_sections(sample_path: Path) -> None:
    """Text outside the ```yaml block must not be altered."""
    doc = BatonDocument.load(sample_path)
    doc.data["baton_version"] = "1.0"  # no-op change
    doc.save()

    saved = sample_path.read_text(encoding="utf-8")
    assert "Test fixture for the Baton test suite" in saved


# ── is_initialized / validate_keys ────────────────────────────────────────────

def test_is_initialized_true_for_sample(sample_path: Path) -> None:
    doc = BatonDocument.load(sample_path)
    assert doc.is_initialized() is True


def test_is_initialized_false_for_empty_purpose(tmp_path: Path) -> None:
    empty = tmp_path / "BATON.md"
    empty.write_text('# X\n```yaml\nproject:\n  purpose: ""\n```\n', encoding="utf-8")
    doc = BatonDocument.load(empty)
    assert doc.is_initialized() is False


def test_validate_keys_empty_for_valid_doc(sample_path: Path) -> None:
    doc = BatonDocument.load(sample_path)
    unknown = doc.validate_keys()
    assert unknown == []


def test_validate_keys_flags_unknown(tmp_path: Path) -> None:
    bad = tmp_path / "BATON.md"
    bad.write_text('# X\n```yaml\nunknown_section: true\n```\n', encoding="utf-8")
    doc = BatonDocument.load(bad)
    assert "unknown_section" in doc.validate_keys()
