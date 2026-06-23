"""
test_astscan.py -- Tests for baton/core/astscan.py.

All tests use synthetic diff strings.  No mocking, no filesystem, no git calls.
"""
from __future__ import annotations

import pytest

from baton.core.astscan import added_dependency_names, added_imports


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_diff(filename: str, added_lines: list[str], removed_lines: list[str] | None = None) -> str:
    """Build a minimal unified diff with the given added lines in one file."""
    removed_lines = removed_lines or []
    total_old = len(removed_lines) + 1
    total_new = len(added_lines) + 1
    lines = [
        f"diff --git a/{filename} b/{filename}",
        f"--- a/{filename}",
        f"+++ b/{filename}",
        f"@@ -{1},{total_old} +{1},{total_new} @@",
    ]
    for r in removed_lines:
        lines.append(f"-{r}")
    for i, a in enumerate(added_lines):
        lines.append(f"+{a}")
    return "\n".join(lines) + "\n"


# ── added_imports: Python ──────────────────────────────────────────────────────


def test_added_imports_python_simple() -> None:
    diff = make_diff("app.py", ["import os"])
    result = added_imports(diff)
    modules = [r["module"] for r in result]
    assert "os" in modules
    # All results must be from app.py
    for r in result:
        assert r["file"] == "app.py"


def test_added_imports_python_from_import() -> None:
    diff = make_diff("utils.py", ["from collections import OrderedDict"])
    result = added_imports(diff)
    modules = [r["module"] for r in result]
    assert "collections" in modules


def test_added_imports_python_submodule() -> None:
    """import os.path should produce top-level module 'os'."""
    diff = make_diff("helpers.py", ["import os.path"])
    result = added_imports(diff)
    modules = [r["module"] for r in result]
    assert "os" in modules
    assert "os.path" not in modules


def test_added_imports_context_lines_ignored() -> None:
    """Context lines (no + prefix) must not be returned as imports."""
    diff = (
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " import os\n"   # context line (space prefix)
        "+import sys\n"
    )
    result = added_imports(diff)
    modules = [r["module"] for r in result]
    assert "sys" in modules
    # os may or may not appear; the important thing is it's not a context import
    # Count how many 'os' entries we have
    os_entries = [r for r in result if r["module"] == "os"]
    # os comes from context line only -> should NOT be present
    assert len(os_entries) == 0


def test_added_imports_removed_lines_ignored() -> None:
    """Removed lines (-) must not be returned as imports."""
    diff = make_diff("app.py", ["import sys"], removed_lines=["import os"])
    result = added_imports(diff)
    modules = [r["module"] for r in result]
    assert "sys" in modules
    assert "os" not in modules


def test_added_imports_js_regex_fallback() -> None:
    """JS file with import ... from 'module' should use regex fallback."""
    diff = make_diff("index.js", ["import moment from 'moment'"])
    result = added_imports(diff)
    modules = [r["module"] for r in result]
    assert "moment" in modules
    for r in result:
        assert r["file"] == "index.js"


def test_added_imports_js_require() -> None:
    """require('lodash') in a JS file should return module 'lodash'."""
    diff = make_diff("util.js", ['const _ = require("lodash")'])
    result = added_imports(diff)
    modules = [r["module"] for r in result]
    assert "lodash" in modules


def test_added_imports_ts_scoped_package() -> None:
    """@scope/pkg imports should preserve the full scoped name."""
    diff = make_diff("src/app.ts", ["import { foo } from '@scope/pkg/sub'"])
    result = added_imports(diff)
    modules = [r["module"] for r in result]
    assert "@scope/pkg" in modules


def test_added_imports_line_numbers_present() -> None:
    """Each result must have a non-negative integer 'line' field."""
    diff = make_diff("app.py", ["import os", "import sys"])
    result = added_imports(diff)
    for r in result:
        assert isinstance(r["line"], int)
        assert r["line"] >= 0


# ── added_dependency_names ────────────────────────────────────────────────────


def test_added_dependency_names_requirements_txt() -> None:
    diff = make_diff("requirements.txt", ["moment>=1.0"])
    result = added_dependency_names(diff)
    deps = [r["dep"] for r in result]
    assert "moment" in deps
    for r in result:
        assert r["file"] == "requirements.txt"


def test_added_dependency_names_package_json() -> None:
    diff = make_diff("package.json", ['  "moment": "^2.0.0"'])
    result = added_dependency_names(diff)
    deps = [r["dep"] for r in result]
    assert "moment" in deps


def test_added_dependency_names_pyproject_toml() -> None:
    diff = make_diff("pyproject.toml", ['    "flask[async]==3.0.0"'])
    result = added_dependency_names(diff)
    deps = [r["dep"] for r in result]
    assert "flask" in deps


def test_added_dependency_names_ignored_in_source() -> None:
    """Dependency-like strings in .py files must not be returned."""
    diff = make_diff("setup.py", ['    "flask[async]==3.0.0"'])
    result = added_dependency_names(diff)
    deps = [r["dep"] for r in result]
    assert "flask" not in deps
    assert result == []


def test_added_dependency_names_requirements_subdir() -> None:
    """requirements/dev.txt should also be scanned."""
    diff = make_diff("requirements/dev.txt", ["pytest==7.0.0"])
    result = added_dependency_names(diff)
    deps = [r["dep"] for r in result]
    assert "pytest" in deps


def test_added_dependency_names_pipfile() -> None:
    diff = make_diff("Pipfile", ["requests = \"*\""])
    result = added_dependency_names(diff)
    deps = [r["dep"] for r in result]
    assert "requests" in deps


def test_added_dependency_names_line_number_present() -> None:
    diff = make_diff("requirements.txt", ["flask==2.0.0"])
    result = added_dependency_names(diff)
    for r in result:
        assert isinstance(r["line"], int)
        assert r["line"] >= 0
