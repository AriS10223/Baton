"""
drift.py -- Drift detection engine for ``baton check --drift``.

Three pure detector functions (no I/O, no git calls, no filesystem reads):

  detect_anti(diff_text, entries)          -> list[dict]  anti-decision violations
  detect_decisions(diff_text, entries)     -> list[dict]  decision contradictions
  detect_landmines(diff_text, entries, repo_root) -> list[dict]  landmine signals

Each function returns a list of Alert dicts with the shape:
  {
    "id":       str,   # entry id (e.g. "a001")
    "type":     str,   # "anti_decision" | "decision" | "landmine"
    "severity": str,   # "warn" | "block"
    "status":   str,   # "violated" | "contradicted" | "possibly_resolved" | "touched"
    "file":     str,   # source file where the violation was found (empty if unknown)
    "line":     int,   # 1-based line number (0 if unknown)
    "detail":   str,   # human-readable one-line description
    "matched":  str,   # raw matched value (diff line, module name, dep name, file path, etc.)
  }
"""
from __future__ import annotations

import re
from pathlib import Path

from baton.core.astscan import added_dependency_names, added_imports, _iter_diff
from baton.core.schema import ANTI_SEVERITIES, EVIDENCE_TYPES, PATTERN_TYPES

# ── Manifest filenames for dependency evidence ────────────────────────────────

_MANIFEST_NAMES_LOWER = frozenset(
    {"package.json", "pyproject.toml", "pipfile"}
)
_REQUIREMENTS_RE = re.compile(r"^requirements.*\.txt$", re.IGNORECASE)
_CONFIG_EXTS = frozenset({".json", ".toml", ".yaml", ".yml", ".env"})


def _is_manifest_file(filename: str) -> bool:
    name = filename.split("/")[-1].lower()
    return name in _MANIFEST_NAMES_LOWER or bool(_REQUIREMENTS_RE.match(name))


def _is_config_file(filename: str) -> bool:
    if not filename:
        return False
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in _CONFIG_EXTS


# ── Internal helpers ──────────────────────────────────────────────────────────


def _files_in_diff(diff_text: str) -> set[str]:
    """Return the set of file paths mentioned in the diff (from diff --git headers)."""
    files: set[str] = set()
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"^diff --git a/.+ b/(.+)$", line)
            if m:
                files.add(m.group(1).strip())
    return files


def _deleted_files(diff_text: str) -> set[str]:
    """Return paths that are being deleted (--- a/<path> with +++ /dev/null)."""
    deleted: set[str] = set()
    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- a/"):
            old_path = line[6:].strip()
            # Look ahead for the +++ line
            if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                next_line = lines[i + 1]
                new_path = next_line[4:].strip()
                if new_path == "/dev/null":
                    deleted.add(old_path)
        i += 1
    return deleted


def _make_alert(
    entry_id: str,
    alert_type: str,
    severity: str,
    status: str,
    file: str,
    line: int,
    detail: str,
    matched: str = "",
) -> dict:
    return {
        "id": entry_id,
        "type": alert_type,
        "severity": severity,
        "status": status,
        "file": file,
        "line": line,
        "detail": detail,
        "matched": matched,
    }


# ── detect_anti ───────────────────────────────────────────────────────────────


def detect_anti(diff_text: str, entries: list[dict]) -> list[dict]:
    """Detect anti-decision violations in a diff.

    For each anti-decision entry with a pattern field, checks:
    - pattern.type == "regex"      : re.search on each added (+) line
    - pattern.type == "import"     : added_imports() module name (exact)
    - pattern.type == "dependency" : added_dependency_names() dep name (case-insensitive)

    Returns one alert per matched occurrence (not per entry).
    Deduplicates by (id, file, line).
    """
    alerts: list[dict] = []
    seen: set[tuple[str, str, int]] = set()

    for entry in entries:
        entry_id = entry.get("id", "")

        pattern = entry.get("pattern")
        if not isinstance(pattern, dict):
            continue
        ptype = pattern.get("type")
        pvalue = pattern.get("value", "")
        if ptype not in PATTERN_TYPES or not pvalue:
            continue

        raw_severity = entry.get("severity", "warn")
        severity = raw_severity if raw_severity in ANTI_SEVERITIES else "warn"

        if ptype == "regex":
            for fname, kind, content, lineno in _iter_diff(diff_text):
                if kind != "add":
                    continue
                if re.search(pvalue, content):
                    key = (entry_id, fname, lineno)
                    if key not in seen:
                        seen.add(key)
                        alerts.append(
                            _make_alert(
                                entry_id,
                                "anti_decision",
                                severity,
                                "violated",
                                fname,
                                lineno,
                                f"Anti-decision '{entry_id}' violated: pattern '{pvalue}' "
                                f"matched in {fname}:{lineno}",
                                matched=content,
                            )
                        )

        elif ptype == "import":
            imports = added_imports(diff_text)
            for imp in imports:
                if imp["module"] == pvalue:
                    key = (entry_id, imp["file"], imp["line"])
                    if key not in seen:
                        seen.add(key)
                        alerts.append(
                            _make_alert(
                                entry_id,
                                "anti_decision",
                                severity,
                                "violated",
                                imp["file"],
                                imp["line"],
                                f"Anti-decision '{entry_id}' violated: import of "
                                f"'{pvalue}' detected in {imp['file']}:{imp['line']}",
                                matched=imp["module"],
                            )
                        )

        elif ptype == "dependency":
            deps = added_dependency_names(diff_text)
            for dep in deps:
                if dep["dep"].lower() == pvalue.lower():
                    key = (entry_id, dep["file"], dep["line"])
                    if key not in seen:
                        seen.add(key)
                        alerts.append(
                            _make_alert(
                                entry_id,
                                "anti_decision",
                                severity,
                                "violated",
                                dep["file"],
                                dep["line"],
                                f"Anti-decision '{entry_id}' violated: dependency "
                                f"'{pvalue}' added in {dep['file']}:{dep['line']}",
                                matched=dep["dep"],
                            )
                        )

    return alerts


# ── detect_decisions ──────────────────────────────────────────────────────────


def detect_decisions(diff_text: str, entries: list[dict]) -> list[dict]:
    """Detect decision contradictions in a diff.

    For each decision entry with an evidence field, checks:
    - evidence.type == "dependency" : dep removed from manifest (-) lines
    - evidence.type == "file"       : file deleted in diff
    - evidence.type == "config_key" : key removed from config (-) lines

    Always returns "warn" severity, status "contradicted".
    """
    alerts: list[dict] = []

    deleted_file_set = _deleted_files(diff_text)

    for entry in entries:
        entry_id = entry.get("id", "")

        evidence = entry.get("evidence")
        if not isinstance(evidence, dict):
            continue
        etype = evidence.get("type")
        evalue = evidence.get("value", "")
        if etype not in EVIDENCE_TYPES or not evalue:
            continue

        if etype == "dependency":
            # Check if dep name appears on removed (-) lines in manifest files
            for fname, kind, content, lineno in _iter_diff(diff_text):
                if kind != "del":
                    continue
                if not _is_manifest_file(fname):
                    continue
                # Simple substring check (case-insensitive) for the dep name
                if evalue.lower() in content.lower():
                    alerts.append(
                        _make_alert(
                            entry_id,
                            "decision",
                            "warn",
                            "contradicted",
                            fname,
                            lineno,
                            f"Decision '{entry_id}' may be contradicted: dependency "
                            f"'{evalue}' removed from {fname}:{lineno}",
                            matched=evalue,
                        )
                    )

        elif etype == "file":
            # Check if the file is being deleted in the diff
            if evalue in deleted_file_set:
                alerts.append(
                    _make_alert(
                        entry_id,
                        "decision",
                        "warn",
                        "contradicted",
                        evalue,
                        0,
                        f"Decision '{entry_id}' may be contradicted: file "
                        f"'{evalue}' is being deleted",
                        matched=evalue,
                    )
                )

        elif etype == "config_key":
            # Check if config key appears on removed lines in config files
            for fname, kind, content, lineno in _iter_diff(diff_text):
                if kind != "del":
                    continue
                if not _is_config_file(fname):
                    continue
                if evalue in content:
                    alerts.append(
                        _make_alert(
                            entry_id,
                            "decision",
                            "warn",
                            "contradicted",
                            fname,
                            lineno,
                            f"Decision '{entry_id}' may be contradicted: config key "
                            f"'{evalue}' removed from {fname}:{lineno}",
                            matched=evalue,
                        )
                    )

    return alerts


# ── detect_landmines ──────────────────────────────────────────────────────────


def detect_landmines(
    diff_text: str,
    entries: list[dict],
    repo_root: Path,  # reserved for future use; not read this phase
) -> list[dict]:
    """Detect landmine signals in a diff.

    For each landmine entry with a location field:
    - Strong signal: marker line DELETED in diff -> status "possibly_resolved"
    - Weak signal: file TOUCHED in diff (but marker NOT deleted) -> status "touched"

    repo_root is reserved for future source-file reading; this phase uses diff only.
    """
    alerts: list[dict] = []

    touched_files = _files_in_diff(diff_text)

    for entry in entries:
        location = entry.get("location")
        if not location:
            continue

        entry_id = entry.get("id", "")

        # Build marker token
        marker_field = entry.get("marker")
        if marker_field:
            marker_token = f"BATON-LANDMINE:{marker_field}"
        elif entry_id:
            marker_token = f"BATON-LANDMINE:{entry_id}"
        else:
            marker_token = "BATON-LANDMINE:"

        # Strong signal: marker line removed in diff
        strong = False
        for fname, kind, content, lineno in _iter_diff(diff_text):
            if kind != "del":
                continue
            if marker_token in content:
                strong = True
                alerts.append(
                    _make_alert(
                        entry_id,
                        "landmine",
                        "warn",
                        "possibly_resolved",
                        fname,
                        lineno,
                        f"Landmine '{entry_id}' marker '{marker_token}' was removed "
                        f"from {fname}:{lineno} -- possibly resolved",
                        matched=marker_token,
                    )
                )

        # Weak signal: file touched but marker not deleted
        if not strong and location in touched_files:
            alerts.append(
                _make_alert(
                    entry_id,
                    "landmine",
                    "warn",
                    "touched",
                    location,
                    0,
                    f"Landmine '{entry_id}' file '{location}' was modified -- "
                    f"check that the landmine is still in place",
                    matched=location,
                )
            )

    return alerts
