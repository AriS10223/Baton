"""
astscan.py -- Import/dependency extraction from unified diff text.

Provides two public functions:
  added_imports(diff_text)         -> list of {file, module, line} dicts
  added_dependency_names(diff_text)-> list of {file, dep, line}    dicts

Python files use stdlib ast for accuracy.
JS/TS files try optional tree_sitter_languages, fall back to regex.
All other extensions use regex.
"""
from __future__ import annotations

import ast
import re
from typing import Generator

# ── Optional tree-sitter (JS/TS) ─────────────────────────────────────────────
try:
    import tree_sitter_languages as _tsl  # type: ignore

    _TREE_SITTER_OK = True
except Exception:
    _tsl = None  # type: ignore
    _TREE_SITTER_OK = False

# ── Regex patterns ────────────────────────────────────────────────────────────

# JS/TS: import ... from 'module' / import 'module' / require('module')
_JS_IMPORT_FROM = re.compile(
    r"""(?:import\s+.*?from\s+|import\s+)['"]([^'"]+)['"]""",
    re.DOTALL,
)
_JS_REQUIRE = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""")

# Manifest: package.json line like  "moment": "^2.0.0"
_PKG_JSON_DEP = re.compile(r"""^\s*"([^"@][^"]*?)"\s*:\s*["^~\d*]""")
_PKG_JSON_DEP_SCOPED = re.compile(r"""^\s*"(@[^"]+?)"\s*:\s*["^~\d*]""")

# requirements.txt / Pipfile: package name before version specifier or extras
# Allow space after name (Pipfile uses "requests = '*'")
_REQ_NAME = re.compile(r"""^([A-Za-z0-9_.\-]+)(?:\[.*?\])?(?:[>=<!~^ ]|$)""")

# pyproject.toml dependency lines: may be quoted or unquoted
_PYPROJECT_DEP = re.compile(
    r"""["\s]*([A-Za-z0-9_.\-]+)(?:\[.*?\])?(?:[>=<!~^,; ]|$)"""
)

# Manifest filenames
_MANIFEST_NAMES = frozenset({"package.json", "pyproject.toml", "pipfile"})
_REQUIREMENTS_RE = re.compile(r"^requirements.*\.txt$", re.IGNORECASE)

# Extensions treated as JS/TS
_JS_EXTS = frozenset({".js", ".ts", ".tsx", ".jsx"})


# ── Shared diff walker ────────────────────────────────────────────────────────


def _iter_diff(
    diff_text: str,
) -> Generator[tuple[str, str, str, int], None, None]:
    """Yield (file, kind, content, lineno) for each body line in a unified diff.

    kind is one of: "add", "del", "context".
    content is the line text with the leading +/-/space stripped.
    lineno is the 1-based line number in the *new* file for "add"/"context"
    lines, and in the *old* file for "del" lines.  Returns 0 when the hunk
    header cannot be parsed (graceful degradation).

    File names come from "diff --git a/<f> b/<f>" and "+++ b/<path>" headers.
    """
    current_file = ""
    new_lineno = 0
    old_lineno = 0

    _hunk_re = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for raw in diff_text.splitlines():
        # File header from diff --git
        if raw.startswith("diff --git "):
            # Try to extract the b/ path
            m = re.match(r"^diff --git a/.+ b/(.+)$", raw)
            if m:
                current_file = m.group(1).strip()
            new_lineno = 0
            old_lineno = 0
            continue

        # +++ b/<path>  (also handles +++ /dev/null for deleted files)
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            if path.startswith("b/"):
                current_file = path[2:]
            elif path == "/dev/null":
                pass  # deletion — keep current_file from diff --git
            new_lineno = 0
            continue

        # --- a/<path>
        if raw.startswith("--- "):
            continue

        # Hunk header
        m = _hunk_re.match(raw)
        if m:
            old_lineno = int(m.group(1))
            new_lineno = int(m.group(2))
            continue

        # Body lines
        if raw.startswith("+"):
            yield current_file, "add", raw[1:], new_lineno
            new_lineno += 1
        elif raw.startswith("-"):
            yield current_file, "del", raw[1:], old_lineno
            old_lineno += 1
        else:
            # Context line (starts with space or is empty)
            new_lineno += 1
            old_lineno += 1


# ── JS/TS module name normalisation ──────────────────────────────────────────


def _js_module_name(raw: str) -> str:
    """Return the top-level (or scoped) package name from an import path.

    "@scope/pkg/sub" -> "@scope/pkg"
    "moment/locale"  -> "moment"
    "moment"         -> "moment"
    """
    raw = raw.strip()
    if raw.startswith("@"):
        parts = raw.split("/")
        if len(parts) >= 2:
            return parts[0] + "/" + parts[1]
        return raw
    return raw.split("/")[0]


# ── Python AST import extraction ──────────────────────────────────────────────


def _extract_py_imports(lines: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Given [(source_line, lineno), ...], return [(top_module, lineno)] pairs.

    Strategy:
    1. Try ast.parse on all lines joined (works for complete Python blocks).
    2. On SyntaxError, try each line individually (handles fragments).
    In both cases, strip leading whitespace so indented imports don't trigger
    IndentationError.
    """
    results: list[tuple[str, int]] = []

    def _nodes_from_source(src: str, base_lineno: int) -> list[tuple[str, int]]:
        found: list[tuple[str, int]] = []
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return found
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    found.append((top, base_lineno + node.lineno - 1))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    found.append((top, base_lineno + node.lineno - 1))
        return found

    # Attempt 1: parse all lines as a block
    joined = "\n".join(line for line, _ in lines)
    stripped_joined = "\n".join(line.strip() for line, _ in lines)
    block_results = _nodes_from_source(stripped_joined, lines[0][1] if lines else 0)
    if block_results:
        return block_results

    # Attempt 2: parse each line individually
    for src_line, lineno in lines:
        stripped = src_line.strip()
        if not stripped:
            continue
        line_results = _nodes_from_source(stripped, lineno)
        results.extend(line_results)

    return results


# ── JS/TS import extraction ───────────────────────────────────────────────────


def _extract_js_imports_regex(line: str) -> list[str]:
    """Extract module names from a JS/TS line using regex."""
    modules: list[str] = []
    for m in _JS_IMPORT_FROM.finditer(line):
        modules.append(_js_module_name(m.group(1)))
    for m in _JS_REQUIRE.finditer(line):
        modules.append(_js_module_name(m.group(1)))
    return modules


def _extract_js_imports_tree_sitter(content: str) -> list[str]:
    """Extract module names using tree-sitter (when available).

    Falls back to regex on any error.
    """
    if not _TREE_SITTER_OK or _tsl is None:
        return _extract_js_imports_regex(content)
    try:
        lang = _tsl.get_language("javascript")
        parser = _tsl.get_parser("javascript")
        tree = parser.parse(bytes(content, "utf-8"))
        modules: list[str] = []
        # Walk tree for import_statement / call_expression (require)
        cursor = tree.walk()
        reached = True
        while reached:
            node = cursor.node
            if node.type in ("import_statement", "import_declaration"):
                for child in node.children:
                    if child.type == "string":
                        raw = child.text.decode().strip("'\"")
                        modules.append(_js_module_name(raw))
            elif node.type == "call_expression":
                fn = node.child_by_field_name("function")
                args = node.child_by_field_name("arguments")
                if fn and fn.text == b"require" and args:
                    for arg in args.children:
                        if arg.type == "string":
                            raw = arg.text.decode().strip("'\"")
                            modules.append(_js_module_name(raw))
            if not cursor.goto_first_child():
                while not cursor.goto_next_sibling():
                    if not cursor.goto_parent():
                        reached = False
                        break
        return modules
    except Exception:
        return _extract_js_imports_regex(content)


# ── Manifest file detection ───────────────────────────────────────────────────


def _is_manifest(filename: str) -> bool:
    """Return True if the file is a known dependency manifest."""
    name = filename.split("/")[-1].lower()
    full = filename.lower()
    return (
        name in _MANIFEST_NAMES
        or bool(_REQUIREMENTS_RE.match(name))
        or bool(_REQUIREMENTS_RE.match(full))
        or full.endswith("/pipfile")
    )


def _is_requirements(filename: str) -> bool:
    name = filename.split("/")[-1].lower()
    # Also check the full path for patterns like "requirements/dev.txt"
    full = filename.lower()
    return (
        bool(_REQUIREMENTS_RE.match(name))
        or bool(_REQUIREMENTS_RE.match(full))
        or name == "pipfile"
        or full.endswith("/pipfile")
    )


def _is_pyproject(filename: str) -> bool:
    return filename.split("/")[-1].lower() == "pyproject.toml"


def _is_package_json(filename: str) -> bool:
    return filename.split("/")[-1].lower() == "package.json"


# ── Public API ────────────────────────────────────────────────────────────────


def added_imports(diff_text: str) -> list[dict]:
    """Extract imported module names from added (+) lines in a unified diff.

    Returns list of dicts: [{"file": "...", "module": "moment", "line": 14}, ...]

    Uses stdlib ast for .py files, optional tree-sitter for JS/TS,
    regex fallback for everything else.
    Each returned dict has "file" (str), "module" (str top-level module name),
    "line" (int).
    """
    # Group added lines by file
    by_file: dict[str, list[tuple[str, int]]] = {}
    for fname, kind, content, lineno in _iter_diff(diff_text):
        if kind != "add":
            continue
        if fname not in by_file:
            by_file[fname] = []
        by_file[fname].append((content, lineno))

    results: list[dict] = []

    for fname, lines in by_file.items():
        ext = "." + fname.rsplit(".", 1)[-1].lower() if "." in fname else ""

        if ext == ".py":
            for top_module, lineno in _extract_py_imports(lines):
                results.append({"file": fname, "module": top_module, "line": lineno})

        elif ext in _JS_EXTS:
            for content, lineno in lines:
                if _TREE_SITTER_OK and _tsl is not None:
                    mods = _extract_js_imports_tree_sitter(content)
                else:
                    mods = _extract_js_imports_regex(content)
                for mod in mods:
                    results.append({"file": fname, "module": mod, "line": lineno})

        else:
            # Regex fallback for all other extensions
            for content, lineno in lines:
                mods = _extract_js_imports_regex(content)
                for mod in mods:
                    results.append({"file": fname, "module": mod, "line": lineno})

    return results


def added_dependency_names(diff_text: str) -> list[dict]:
    """Extract dependency names added in manifest diffs.

    Scans added (+) lines in files matching: package.json, pyproject.toml,
    requirements.txt, requirements/*.txt, Pipfile.
    Returns list of dicts: [{"file": "...", "dep": "moment", "line": 14}, ...]
    """
    results: list[dict] = []

    for fname, kind, content, lineno in _iter_diff(diff_text):
        if kind != "add":
            continue
        if not _is_manifest(fname):
            continue

        stripped = content.strip()
        if not stripped:
            continue

        if _is_package_json(fname):
            # "moment": "^2.0.0"
            m = _PKG_JSON_DEP.match(content)
            if not m:
                m = _PKG_JSON_DEP_SCOPED.match(content)
            if m:
                dep = m.group(1).strip()
                # Filter out JSON structural keys that are not package names
                if dep and not dep.startswith("{") and dep not in (
                    "dependencies", "devDependencies", "peerDependencies",
                    "optionalDependencies", "name", "version", "description",
                    "main", "scripts", "license", "author",
                ):
                    results.append({"file": fname, "dep": dep, "line": lineno})

        elif _is_pyproject(fname):
            # Lines like: "flask[async]==3.0.0" or flask>=1.0 or "moment>=1.0"
            # Only match lines that look like dependency declarations
            cleaned = stripped.strip('"').strip("'")
            m = _PYPROJECT_DEP.match(cleaned)
            if m:
                dep = m.group(1).strip()
                if dep and re.match(r"^[A-Za-z][A-Za-z0-9_.\-]*$", dep):
                    results.append({"file": fname, "dep": dep, "line": lineno})

        elif _is_requirements(fname):
            # moment>=1.0, flask[async]==3.0.0, # comment lines skipped
            if stripped.startswith("#") or stripped.startswith("-"):
                continue
            m = _REQ_NAME.match(stripped)
            if m:
                dep = m.group(1).strip()
                if dep:
                    results.append({"file": fname, "dep": dep, "line": lineno})

    return results
