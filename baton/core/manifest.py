"""
manifest.py -- Full-file manifest reader for ``baton init --scan``.

Reads package manifests from disk (not from git diffs) so that:
- Production and dev/test dependencies can be split by section
- Cargo.toml and go.mod (not covered by astscan.py) are supported

Public API:
    read_manifest_deps(repo_root) -> list[dict]

Each returned dict has keys:
    name     str  -- dependency name (normalised: lowercase, hyphens)
    manifest str  -- relative path to the manifest file (e.g. "package.json")
    section  str  -- "prod" | "dev" | "optional" | "unknown"
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# ── Reused regexes from astscan (same patterns, applied to full file lines) ──

_PKG_JSON_DEP        = re.compile(r"""^\s*"([^"@][^"]*?)"\s*:\s*["^~\d*]""")
_PKG_JSON_DEP_SCOPED = re.compile(r"""^\s*"(@[^"]+?)"\s*:\s*["^~\d*]""")
_REQ_NAME            = re.compile(r"""^([A-Za-z0-9_.\-]+)(?:\[.*?\])?(?:[>=<!~^ ]|$)""")
_PYPROJECT_DEP       = re.compile(r"""["\s]*([A-Za-z0-9_.\-]+)(?:\[.*?\])?(?:[>=<!~^,; ]|$)""")
_CARGO_DEP           = re.compile(r"""^\s*([A-Za-z0-9_\-]+)\s*=\s*""")
_GO_REQUIRE          = re.compile(r"""^\s*([\w./\-]+)\s+v[\d.]""")

# Keys in package.json that are not dependency names
_PKG_JSON_SKIP = frozenset({
    "dependencies", "devDependencies", "peerDependencies",
    "optionalDependencies", "bundledDependencies", "bundleDependencies",
    "name", "version", "description", "main", "module", "types",
    "scripts", "license", "author", "homepage", "repository", "bugs",
    "keywords", "files", "bin", "engines", "exports", "browser",
})


def read_manifest_deps(repo_root: Path) -> list[dict]:
    """Scan the repo root for known manifests and extract dependency names.

    Only reads files in ``repo_root`` (not subdirectories) except for
    requirements files which may live one level down (e.g. requirements/).

    Args:
        repo_root: Project root directory (where BATON.md lives).

    Returns:
        List of dicts: [{name, manifest, section}]
        section is "prod", "dev", "optional", or "unknown".
    """
    results: list[dict] = []

    # package.json (Node/JS/TS)
    pkg_json = repo_root / "package.json"
    if pkg_json.exists():
        results.extend(_read_package_json(pkg_json))

    # pyproject.toml (Python)
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        results.extend(_read_pyproject_toml(pyproject))

    # requirements*.txt (Python, also requirements/ subdir)
    for req_file in sorted(repo_root.glob("requirements*.txt")):
        results.extend(_read_requirements_txt(req_file))
    req_dir = repo_root / "requirements"
    if req_dir.is_dir():
        for req_file in sorted(req_dir.glob("*.txt")):
            section = "dev" if any(k in req_file.stem for k in ("dev", "test", "lint")) else "prod"
            results.extend(_read_requirements_txt(req_file, section_hint=section))

    # Pipfile (Python)
    pipfile = repo_root / "Pipfile"
    if pipfile.exists():
        results.extend(_read_pipfile(pipfile))

    # setup.py / setup.cfg  -- minimal: just flag "python" ecosystem
    # (too variable to parse reliably; skip for now)

    # Cargo.toml (Rust)
    cargo = repo_root / "Cargo.toml"
    if cargo.exists():
        results.extend(_read_cargo_toml(cargo))

    # go.mod (Go)
    gomod = repo_root / "go.mod"
    if gomod.exists():
        results.extend(_read_go_mod(gomod))

    return results


# ── Per-manifest readers ──────────────────────────────────────────────────────


def _read_package_json(path: Path) -> list[dict]:
    """Parse package.json; split prod / dev / optional / peer by section."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    results: list[dict] = []
    manifest = str(path.name)

    section_map = {
        "dependencies":         "prod",
        "peerDependencies":     "prod",    # treat peer as prod for intent purposes
        "optionalDependencies": "optional",
        "devDependencies":      "dev",
    }

    for json_key, section in section_map.items():
        block = data.get(json_key) or {}
        for name in block:
            if name in _PKG_JSON_SKIP:
                continue
            results.append({"name": _normalise(name), "manifest": manifest, "section": section})

    return results


def _read_pyproject_toml(path: Path) -> list[dict]:
    """Parse pyproject.toml [project].dependencies and [project.optional-dependencies]."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []

    results: list[dict] = []
    manifest = str(path.name)
    section = "unknown"
    in_deps = False
    in_optional = False

    for line in text.splitlines():
        stripped = line.strip()

        # Section headers
        if stripped.startswith("["):
            in_deps = stripped in ("[project.dependencies]", "[tool.poetry.dependencies]")
            in_optional = (
                stripped.startswith("[project.optional-dependencies")
                or stripped.startswith("[tool.poetry.dev-dependencies")
                or stripped.startswith("[tool.poetry.group.")
            )
            if in_optional:
                section = "dev" if any(k in stripped for k in ("dev", "test", "lint")) else "optional"
            elif in_deps:
                section = "prod"
            else:
                in_deps = False
                in_optional = False
            continue

        # [project] dependencies = [...] inline array (PEP 621)
        if not in_deps and not in_optional:
            if "dependencies" in stripped and "=" in stripped:
                in_deps = True
                section = "prod"

        if not (in_deps or in_optional):
            continue
        if stripped.startswith("#") or not stripped:
            continue

        # Skip TOML keys that aren't dep names
        if stripped.startswith("[") or "=" in stripped.split('"')[0]:
            continue

        m = _PYPROJECT_DEP.match(stripped.lstrip('"').lstrip("'").lstrip())
        if m:
            name = m.group(1).strip()
            if name and not name.startswith("#") and len(name) > 1:
                results.append({"name": _normalise(name), "manifest": manifest, "section": section})

    return results


def _read_requirements_txt(path: Path, section_hint: str = "prod") -> list[dict]:
    """Parse a requirements*.txt file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    results: list[dict] = []
    manifest = path.name
    # If filename contains dev/test/lint, treat as dev
    section = section_hint
    if any(k in path.stem.lower() for k in ("dev", "test", "lint")):
        section = "dev"

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-r"):
            continue
        m = _REQ_NAME.match(line)
        if m:
            name = m.group(1).strip()
            if name:
                results.append({"name": _normalise(name), "manifest": manifest, "section": section})

    return results


def _read_pipfile(path: Path) -> list[dict]:
    """Parse Pipfile [packages] and [dev-packages]."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []

    results: list[dict] = []
    manifest = "Pipfile"
    section = "unknown"

    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "[packages]":
            section = "prod"
            continue
        if stripped in ("[dev-packages]", "[packages.dev]"):
            section = "dev"
            continue
        if stripped.startswith("["):
            section = "unknown"
            continue
        if not stripped or stripped.startswith("#"):
            continue
        # Pipfile line: requests = "*"  or  requests = {version = "..."}
        m = re.match(r"""^([A-Za-z0-9_.\-]+)\s*=""", stripped)
        if m and section in ("prod", "dev"):
            name = m.group(1).strip()
            results.append({"name": _normalise(name), "manifest": manifest, "section": section})

    return results


def _read_cargo_toml(path: Path) -> list[dict]:
    """Parse Cargo.toml [dependencies] and [dev-dependencies]."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []

    results: list[dict] = []
    manifest = "Cargo.toml"
    section = "unknown"

    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "[dependencies]":
            section = "prod"
            continue
        if stripped in ("[dev-dependencies]", "[build-dependencies]"):
            section = "dev"
            continue
        if stripped.startswith("["):
            section = "unknown"
            continue
        if not stripped or stripped.startswith("#"):
            continue
        m = _CARGO_DEP.match(stripped)
        if m and section in ("prod", "dev"):
            name = m.group(1).strip()
            results.append({"name": _normalise(name), "manifest": manifest, "section": section})

    return results


def _read_go_mod(path: Path) -> list[dict]:
    """Parse go.mod require block."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    results: list[dict] = []
    manifest = "go.mod"
    in_require = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("require ("):
            in_require = True
            continue
        if in_require and stripped == ")":
            in_require = False
            continue
        if stripped.startswith("require "):
            # single-line require
            m = _GO_REQUIRE.match(stripped[len("require "):].strip())
            if m:
                results.append({"name": _normalise(m.group(1)), "manifest": manifest, "section": "prod"})
            continue
        if in_require:
            m = _GO_REQUIRE.match(stripped)
            if m:
                name = m.group(1)
                # Indirect deps are usually stdlib wrappers — mark but keep
                section = "dev" if "// indirect" in stripped else "prod"
                results.append({"name": _normalise(name), "manifest": manifest, "section": section})

    return results


def _normalise(name: str) -> str:
    """Lowercase and replace underscores with hyphens (PEP 503 normalisation)."""
    return name.lower().replace("_", "-")
