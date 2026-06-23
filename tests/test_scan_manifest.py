"""
test_scan_manifest.py -- Tests for baton/core/scan_manifest.py.

All tests use tmp_path for filesystem isolation -- no mocking.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from baton.core.scan_manifest import scan_manifests


# ── Basic package.json behaviour ──────────────────────────────────────────────


def test_package_json_prod_deps(tmp_path: Path) -> None:
    pkg = {
        "dependencies": {"react": "^18.0.0", "axios": "^1.0.0"},
        "devDependencies": {"jest": "^29.0.0"},
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    results = scan_manifests(tmp_path)
    names = [r["evidence"]["value"] for r in results]
    assert "react" in names
    assert "axios" in names
    assert "jest" not in names  # dev dep skipped
    assert all(r["status"] == "pending_review" for r in results)
    assert all(r["source"] == "scan:manifest" for r in results)


def test_package_json_dev_deps_skipped(tmp_path: Path) -> None:
    pkg = {
        "dependencies": {"express": "^4.0.0"},
        "devDependencies": {"mocha": "^10.0.0", "eslint": "^8.0.0"},
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    results = scan_manifests(tmp_path)
    names = {r["evidence"]["value"] for r in results}
    assert "express" in names
    assert "mocha" not in names
    assert "eslint" not in names


def test_package_json_empty_dependencies(tmp_path: Path) -> None:
    pkg = {"name": "empty-app", "version": "1.0.0"}
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    results = scan_manifests(tmp_path)
    assert results == []


def test_package_json_scoped_packages(tmp_path: Path) -> None:
    pkg = {"dependencies": {"@org/pkg": "^1.0.0", "@types/node": "^20.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    results = scan_manifests(tmp_path)
    names = {r["evidence"]["value"] for r in results}
    assert "@org/pkg" in names
    assert "@types/node" in names


# ── Deduplication ─────────────────────────────────────────────────────────────


def test_deduplication_across_manifests(tmp_path: Path) -> None:
    """Same dep in package.json and requirements.txt -> only one entry."""
    pkg = {"dependencies": {"requests": "^2.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests>=2.28.0\n", encoding="utf-8")
    results = scan_manifests(tmp_path)
    names = [r["evidence"]["value"] for r in results]
    assert names.count("requests") == 1


def test_no_manifest_files_returns_empty(tmp_path: Path) -> None:
    """Empty directory - no manifests - returns empty list without crash."""
    results = scan_manifests(tmp_path)
    assert results == []


# ── Entry shape ───────────────────────────────────────────────────────────────


def test_entry_has_required_keys(tmp_path: Path) -> None:
    pkg = {"dependencies": {"lodash": "^4.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    results = scan_manifests(tmp_path)
    assert len(results) == 1
    entry = results[0]
    for key in ("what", "why", "made", "made_in", "evidence", "source", "confidence", "status"):
        assert key in entry, f"Missing key: {key}"


def test_entry_evidence_type_and_value(tmp_path: Path) -> None:
    pkg = {"dependencies": {"vue": "^3.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    results = scan_manifests(tmp_path)
    assert len(results) == 1
    assert results[0]["evidence"]["type"] == "dependency"
    assert results[0]["evidence"]["value"] == "vue"


def test_entry_source_confidence_status(tmp_path: Path) -> None:
    pkg = {"dependencies": {"svelte": "^4.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    results = scan_manifests(tmp_path)
    assert len(results) == 1
    assert results[0]["source"] == "scan:manifest"
    assert results[0]["confidence"] == "high"
    assert results[0]["status"] == "pending_review"


def test_entry_what_field_format(tmp_path: Path) -> None:
    pkg = {"dependencies": {"fastapi": "^0.100.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    results = scan_manifests(tmp_path)
    assert len(results) == 1
    assert results[0]["what"] == "Uses fastapi"


def test_entry_why_and_made_in_are_empty(tmp_path: Path) -> None:
    pkg = {"dependencies": {"angular": "^16.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    results = scan_manifests(tmp_path)
    assert results[0]["why"] == ""
    assert results[0]["made_in"] == ""


# ── today parameter ───────────────────────────────────────────────────────────


def test_today_parameter_sets_made_field(tmp_path: Path) -> None:
    pkg = {"dependencies": {"django": "^4.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    results = scan_manifests(tmp_path, today="2024-01-15")
    assert results[0]["made"] == "2024-01-15"


def test_today_default_is_iso_date(tmp_path: Path) -> None:
    import datetime
    pkg = {"dependencies": {"flask": "^2.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    results = scan_manifests(tmp_path)
    # Should be a valid ISO date
    made = results[0]["made"]
    datetime.date.fromisoformat(made)  # raises ValueError if not ISO format


# ── Optional / unknown section skipping ──────────────────────────────────────


def test_optional_deps_skipped(tmp_path: Path) -> None:
    pkg = {
        "dependencies": {"react": "^18.0.0"},
        "optionalDependencies": {"fsevents": "^2.0.0"},
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    results = scan_manifests(tmp_path)
    names = {r["evidence"]["value"] for r in results}
    assert "react" in names
    assert "fsevents" not in names


# ── requirements.txt prod vs dev ──────────────────────────────────────────────


def test_requirements_txt_prod_becomes_entry(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests>=2.28.0\nflask==2.3.0\n", encoding="utf-8")
    results = scan_manifests(tmp_path)
    names = {r["evidence"]["value"] for r in results}
    assert "requests" in names
    assert "flask" in names


def test_requirements_dev_txt_skipped(tmp_path: Path) -> None:
    (tmp_path / "requirements-dev.txt").write_text("pytest>=7.0\npytest-cov\n", encoding="utf-8")
    results = scan_manifests(tmp_path)
    assert results == []
