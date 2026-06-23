"""
test_manifest.py -- Tests for baton/core/manifest.py.

All tests use tmp_path for filesystem isolation — no mocking.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from baton.core.manifest import read_manifest_deps


# ── package.json ──────────────────────────────────────────────────────────────


def test_package_json_prod_deps(tmp_path: Path) -> None:
    pkg = {
        "name": "my-app",
        "dependencies": {
            "react": "^18.0.0",
            "axios": "^1.0.0",
        },
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    deps = read_manifest_deps(tmp_path)
    names = {d["name"] for d in deps}
    assert "react" in names
    assert "axios" in names
    for d in deps:
        if d["name"] in ("react", "axios"):
            assert d["section"] == "prod"
            assert d["manifest"] == "package.json"


def test_package_json_dev_deps(tmp_path: Path) -> None:
    pkg = {
        "dependencies": {"lodash": "^4.0.0"},
        "devDependencies": {"jest": "^29.0.0", "eslint": "^8.0.0"},
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    deps = read_manifest_deps(tmp_path)
    by_name = {d["name"]: d for d in deps}
    assert by_name["lodash"]["section"] == "prod"
    assert by_name["jest"]["section"] == "dev"
    assert by_name["eslint"]["section"] == "dev"


def test_package_json_optional_deps(tmp_path: Path) -> None:
    pkg = {
        "optionalDependencies": {"fsevents": "^2.0.0"},
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    deps = read_manifest_deps(tmp_path)
    by_name = {d["name"]: d for d in deps}
    assert by_name["fsevents"]["section"] == "optional"


def test_package_json_scoped_package(tmp_path: Path) -> None:
    pkg = {
        "dependencies": {"@types/node": "^20.0.0"},
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    deps = read_manifest_deps(tmp_path)
    names = {d["name"] for d in deps}
    assert "@types/node" in names


def test_package_json_invalid_json_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("not valid json", encoding="utf-8")
    deps = read_manifest_deps(tmp_path)
    assert deps == []


def test_package_json_empty_sections(tmp_path: Path) -> None:
    pkg = {"name": "empty-app", "version": "1.0.0"}
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    deps = read_manifest_deps(tmp_path)
    assert deps == []


# ── requirements.txt ─────────────────────────────────────────────────────────


def test_requirements_txt_basic(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "requests>=2.28.0\nflask==2.3.0\n# comment line\n\n",
        encoding="utf-8",
    )
    deps = read_manifest_deps(tmp_path)
    names = {d["name"] for d in deps}
    assert "requests" in names
    assert "flask" in names
    for d in deps:
        if d["name"] in ("requests", "flask"):
            assert d["section"] == "prod"
            assert d["manifest"] == "requirements.txt"


def test_requirements_txt_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "# this is a comment\n\nrequests>=2.0\n-r other.txt\n",
        encoding="utf-8",
    )
    deps = read_manifest_deps(tmp_path)
    names = {d["name"] for d in deps}
    assert "requests" in names
    assert len(deps) == 1  # comment, blank, -r line all skipped


def test_requirements_dev_txt_section_is_dev(tmp_path: Path) -> None:
    (tmp_path / "requirements-dev.txt").write_text(
        "pytest>=7.0\npytest-cov\n",
        encoding="utf-8",
    )
    deps = read_manifest_deps(tmp_path)
    for d in deps:
        assert d["section"] == "dev"


def test_requirements_test_txt_section_is_dev(tmp_path: Path) -> None:
    (tmp_path / "requirements-test.txt").write_text("pytest\n", encoding="utf-8")
    deps = read_manifest_deps(tmp_path)
    assert deps[0]["section"] == "dev"


def test_requirements_missing_file_returns_empty(tmp_path: Path) -> None:
    # No requirements.txt written — should return empty
    deps = read_manifest_deps(tmp_path)
    assert deps == []


# ── Cargo.toml ────────────────────────────────────────────────────────────────


def test_cargo_toml_prod_deps(tmp_path: Path) -> None:
    cargo_content = """\
[package]
name = "my-app"
version = "0.1.0"

[dependencies]
serde = { version = "1.0", features = ["derive"] }
tokio = "1.0"

[dev-dependencies]
mockall = "0.11"
"""
    (tmp_path / "Cargo.toml").write_text(cargo_content, encoding="utf-8")
    deps = read_manifest_deps(tmp_path)
    by_name = {d["name"]: d for d in deps}
    assert by_name["serde"]["section"] == "prod"
    assert by_name["tokio"]["section"] == "prod"
    assert by_name["mockall"]["section"] == "dev"
    for d in deps:
        assert d["manifest"] == "Cargo.toml"


def test_cargo_toml_no_deps_returns_empty(tmp_path: Path) -> None:
    cargo_content = "[package]\nname = \"empty\"\nversion = \"0.1.0\"\n"
    (tmp_path / "Cargo.toml").write_text(cargo_content, encoding="utf-8")
    deps = read_manifest_deps(tmp_path)
    assert deps == []


def test_cargo_toml_missing_file_returns_empty(tmp_path: Path) -> None:
    deps = read_manifest_deps(tmp_path)
    assert deps == []


# ── go.mod ────────────────────────────────────────────────────────────────────


def test_go_mod_require_block(tmp_path: Path) -> None:
    gomod = """\
module github.com/example/myapp

go 1.21

require (
    github.com/gin-gonic/gin v1.9.0
    github.com/stretchr/testify v1.8.0 // indirect
)
"""
    (tmp_path / "go.mod").write_text(gomod, encoding="utf-8")
    deps = read_manifest_deps(tmp_path)
    by_name = {d["name"]: d for d in deps}
    assert "github.com/gin-gonic/gin" in by_name
    assert by_name["github.com/gin-gonic/gin"]["section"] == "prod"
    assert "github.com/stretchr/testify" in by_name
    assert by_name["github.com/stretchr/testify"]["section"] == "dev"
    for d in deps:
        assert d["manifest"] == "go.mod"


def test_go_mod_single_line_require(tmp_path: Path) -> None:
    gomod = "module example.com/app\n\ngo 1.21\n\nrequire github.com/pkg/errors v0.9.1\n"
    (tmp_path / "go.mod").write_text(gomod, encoding="utf-8")
    deps = read_manifest_deps(tmp_path)
    names = {d["name"] for d in deps}
    assert "github.com/pkg/errors" in names


def test_go_mod_missing_file_returns_empty(tmp_path: Path) -> None:
    deps = read_manifest_deps(tmp_path)
    assert deps == []


# ── Missing / unknown files ───────────────────────────────────────────────────


def test_no_manifest_files_returns_empty(tmp_path: Path) -> None:
    """Empty project directory — no manifests — returns empty list without crash."""
    deps = read_manifest_deps(tmp_path)
    assert deps == []


def test_nonexistent_repo_root_returns_empty(tmp_path: Path) -> None:
    """Passing a non-existent path does not crash."""
    fake_root = tmp_path / "does_not_exist"
    deps = read_manifest_deps(fake_root)
    assert deps == []


# ── name normalisation ────────────────────────────────────────────────────────


def test_name_normalised_to_lowercase(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("Flask>=2.0\n", encoding="utf-8")
    deps = read_manifest_deps(tmp_path)
    assert deps[0]["name"] == "flask"


def test_name_normalised_underscores_to_hyphens(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("my_package>=1.0\n", encoding="utf-8")
    deps = read_manifest_deps(tmp_path)
    assert deps[0]["name"] == "my-package"
