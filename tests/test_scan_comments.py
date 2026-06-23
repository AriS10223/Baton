"""
test_scan_comments.py -- Tests for baton/core/scan_comments.py.

All tests use tmp_path for filesystem isolation -- no mocking.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from baton.core.scan_comments import scan_comments


# ── Basic marker detection ────────────────────────────────────────────────────


def test_python_todo(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("# normal comment\n# TODO: fix the auth bug\nx = 1\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 1
    assert results[0]["actually"] == "fix the auth bug"
    assert results[0]["location"] == "app.py:2"
    assert results[0]["status"] == "pending_review"
    assert results[0]["source"] == "scan:comment"


def test_python_fixme(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("x = 1\n# FIXME: broken calculation\ny = 2\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 1
    assert results[0]["actually"] == "broken calculation"
    assert results[0]["location"] == "main.py:2"


def test_python_hack(tmp_path: Path) -> None:
    (tmp_path / "utils.py").write_text("# HACK: workaround for upstream bug\npass\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 1
    assert results[0]["actually"] == "workaround for upstream bug"


def test_python_warning(tmp_path: Path) -> None:
    (tmp_path / "db.py").write_text("# WARNING: dangerous operation\npass\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 1
    assert results[0]["actually"] == "dangerous operation"


def test_js_fixme(tmp_path: Path) -> None:
    (tmp_path / "index.js").write_text("const x = 1;\n// FIXME: broken\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 1
    assert results[0]["actually"] == "broken"
    assert results[0]["location"] == "index.js:2"


def test_no_markers_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "clean.py").write_text("# normal comment\nx = 1\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert results == []


# ── Skip directories ──────────────────────────────────────────────────────────


def test_node_modules_skipped(tmp_path: Path) -> None:
    nm = tmp_path / "node_modules" / "lib"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("// FIXME: this is in node_modules\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert results == []


def test_pycache_skipped(tmp_path: Path) -> None:
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "mod.pyc").write_text("# TODO: cached file\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert results == []


def test_git_dir_skipped(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("# TODO: git config\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert results == []


def test_dist_dir_skipped(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "bundle.js").write_text("// FIXME: minified\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert results == []


def test_venv_dir_skipped(tmp_path: Path) -> None:
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "site.py").write_text("# HACK: venv internals\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert results == []


# ── Entry shape ───────────────────────────────────────────────────────────────


def test_entry_has_required_keys(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("# TODO: do something\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 1
    entry = results[0]
    for key in ("location", "looks_like", "actually", "source", "confidence", "status"):
        assert key in entry, f"Missing key: {key}"


def test_entry_looks_like_is_empty(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("# TODO: check this\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert results[0]["looks_like"] == ""


def test_entry_location_format(tmp_path: Path) -> None:
    """Location is '<relative-path>:<lineno>' using forward slashes."""
    subdir = tmp_path / "src"
    subdir.mkdir()
    (subdir / "module.py").write_text("x = 1\n# FIXME: fix me\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 1
    assert results[0]["location"] == "src/module.py:2"


def test_entry_source_confidence_status(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("# HACK: workaround\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert results[0]["source"] == "scan:comment"
    assert results[0]["confidence"] == "high"
    assert results[0]["status"] == "pending_review"


# ── Case insensitivity ────────────────────────────────────────────────────────


def test_case_insensitive_todo(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("# todo: lowercase\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 1
    assert results[0]["actually"] == "lowercase"


def test_case_insensitive_fixme(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("# fixme: lowercase fixme\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 1


def test_case_insensitive_hack(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("# hack: lowercase hack\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 1


def test_case_insensitive_warning(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("# warning: lowercase warning\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 1


# ── Deduplication ─────────────────────────────────────────────────────────────


def test_deduplication_same_location_and_text(tmp_path: Path) -> None:
    """Same location+text should not produce duplicate entries."""
    # This would only happen if somehow the same line was scanned twice,
    # which shouldn't occur, but the dedup guard should handle it.
    (tmp_path / "app.py").write_text("# TODO: fix this\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 1


def test_multiple_markers_in_one_file(tmp_path: Path) -> None:
    content = "# TODO: first thing\nx = 1\n# FIXME: second thing\ny = 2\n"
    (tmp_path / "app.py").write_text(content, encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 2
    locations = {r["location"] for r in results}
    assert "app.py:1" in locations
    assert "app.py:3" in locations


# ── Multiple file types ───────────────────────────────────────────────────────


def test_js_and_py_files_both_scanned(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("# TODO: python todo\n", encoding="utf-8")
    (tmp_path / "app.js").write_text("// FIXME: js fixme\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 2


def test_typescript_file_scanned(tmp_path: Path) -> None:
    (tmp_path / "component.ts").write_text("// TODO: typescript todo\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 1
    assert "component.ts:1" == results[0]["location"]


def test_yaml_file_scanned(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("# TODO: yaml todo\nkey: value\n", encoding="utf-8")
    results = scan_comments(tmp_path)
    assert len(results) == 1


# ── today parameter (API consistency) ────────────────────────────────────────


def test_today_parameter_accepted(tmp_path: Path) -> None:
    """scan_comments accepts today= for API consistency but doesn't use it."""
    (tmp_path / "app.py").write_text("# TODO: something\n", encoding="utf-8")
    results = scan_comments(tmp_path, today="2024-01-01")
    assert len(results) == 1


# ── Empty directory ───────────────────────────────────────────────────────────


def test_empty_directory_returns_empty(tmp_path: Path) -> None:
    results = scan_comments(tmp_path)
    assert results == []
