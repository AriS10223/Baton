"""
document.py -- BatonDocument: load and save BATON.md files.

BATON.md is a Markdown file that contains the project schema inside a single
fenced code block (triple-backtick yaml).  This module:

- Extracts and parses that YAML block (preserving comments via ruamel.yaml)
- Saves it back in place, rewriting **only** the YAML block
- Validates the top-level keys against the schema

Example::

    doc = BatonDocument.load(Path("BATON.md"))
    doc.data["project"]["purpose"] = "Solve X for Y"
    doc.save()
"""
from __future__ import annotations

import re
from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from .schema import TOP_LEVEL_KEYS

# Matches a ```yaml fenced block.
# The closing ``` MUST be at the start of a line (\n before ```) so that
# triple-backticks appearing inside YAML string values don't prematurely
# terminate the match.
_YAML_FENCE_RE = re.compile(r"```yaml\n(.*?)\n```", re.DOTALL)


class BatonDocumentError(Exception):
    """Raised when BATON.md cannot be found or parsed."""


class BatonDocument:
    """
    Parsed representation of a BATON.md file.

    Load with ``BatonDocument.load(path)``.  Mutate ``doc.data``.
    Persist with ``doc.save()``.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._raw_text: str = ""
        self._data: Any = {}

    # ── Construction ──────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: Path) -> "BatonDocument":
        """Load and parse a BATON.md file.

        Raises:
            BatonDocumentError: if the file does not exist or contains no
                triple-backtick yaml block.
        """
        if not path.exists():
            raise BatonDocumentError(
                f"BATON.md not found at {path}. "
                "Run `baton init` to create one."
            )

        doc = cls(path)
        raw = path.read_text(encoding="utf-8")
        doc._raw_text = raw

        match = _YAML_FENCE_RE.search(raw)
        if not match:
            raise BatonDocumentError(
                f"No ```yaml block found in {path}. "
                "BATON.md must contain exactly one ```yaml fenced block. "
                "Run `baton init --force` to recreate a valid template."
            )

        yaml_src = match.group(1)
        yaml = YAML()
        yaml.preserve_quotes = True
        doc._data = yaml.load(yaml_src) or {}
        return doc

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def data(self) -> dict:
        """The parsed YAML data (ruamel CommentedMap — supports inline comments)."""
        return self._data

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        """Write updated data back to BATON.md, preserving surrounding Markdown."""
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.default_flow_style = False
        yaml.indent(mapping=2, sequence=4, offset=2)
        yaml.width = 120

        stream = StringIO()
        yaml.dump(self._data, stream)
        new_yaml_content = stream.getvalue()

        # Replace only the first ```yaml block (there should be exactly one).
        # Pattern is ```yaml\n(.*?)\n``` so the replacement must also include
        # the surrounding ```yaml\n ... \n``` wrappers.
        yaml_body = new_yaml_content.rstrip("\n")
        replacement = "```yaml\n" + yaml_body + "\n```"
        # Use a callable so re.sub does NOT interpret \n, \1, etc. in the replacement.
        new_text = _YAML_FENCE_RE.sub(lambda _m: replacement, self._raw_text, count=1)
        self.path.write_text(new_text, encoding="utf-8")
        self._raw_text = new_text

    # ── Helpers ───────────────────────────────────────────────────────────────

    def get(self, *keys: str, default: Any = None) -> Any:
        """Safe nested access.  E.g. ``doc.get("project", "purpose")``."""
        v = self._data
        for k in keys:
            if not isinstance(v, dict):
                return default
            v = v.get(k)
            if v is None:
                return default
        return v

    def validate_keys(self) -> list[str]:
        """Return a list of unrecognised top-level keys (informational warnings)."""
        if not isinstance(self._data, dict):
            return []
        return [k for k in self._data if k not in TOP_LEVEL_KEYS]

    def is_initialized(self) -> bool:
        """Return True if the document has at least a non-empty project.purpose."""
        purpose = self.get("project", "purpose", default="")
        return bool(purpose and str(purpose).strip())
