"""
config.py -- Read ``.baton.toml`` project configuration.

Falls back to sensible defaults when the file is absent or malformed.
Config is intentionally minimal for Phase 1 -- the LLM fields are
reserved for ``baton end`` (Increment 2).
"""
from __future__ import annotations

try:
    import tomllib          # stdlib >= 3.11
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]  # Python 3.10 fallback
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BatonConfig:
    """Project-level Baton settings, read from ``.baton.toml``."""

    # LLM (used by `baton end`)
    llm_provider: str = "anthropic"
    # Empty string means "use each provider's own default_model".
    model: str = ""

    # Summarizer thresholds (used by `baton end`)
    min_diff_lines: int = 10

    # Sync behaviour
    auto_sync: bool = True

    # Adapters
    # Empty list = auto-detect from existing files in the repo root.
    enabled_adapters: list[str] = field(default_factory=list)

    # Health / trim thresholds (used by `baton health` and `baton trim`)
    # Configured via [health] section in .baton.toml.
    token_warn:              int = 4000   # WARN when total tokens > this
    token_error:             int = 8000   # ERROR (exit 1) when total tokens > this
    staleness_question_days: int = 30     # open questions older than N days -> stale
    compress_min_depth:      int = 3      # supersession chains >= N -> suggest --compress

    # Factory

    @classmethod
    def load(cls, repo_root: Path) -> "BatonConfig":
        """Load ``.baton.toml`` from *repo_root*.

        Returns a default ``BatonConfig`` if the file is absent or unreadable.
        Never raises; config errors are silently ignored so the CLI keeps working.
        """
        config_path = repo_root / ".baton.toml"
        if not config_path.exists():
            return cls()

        try:
            with open(config_path, "rb") as fh:
                raw = tomllib.load(fh)
        except Exception:
            # Malformed TOML -> fall back to defaults.
            return cls()

        baton_section    = raw.get("baton", {})
        adapters_section = raw.get("adapters", {})
        health_section   = raw.get("health", {})

        return cls(
            llm_provider=baton_section.get("llm_provider", "anthropic"),
            model=baton_section.get("model", ""),
            min_diff_lines=int(baton_section.get("min_diff_lines", 10)),
            auto_sync=bool(baton_section.get("auto_sync", True)),
            enabled_adapters=list(adapters_section.get("enabled", [])),
            token_warn=int(health_section.get("token_warn", 4000)),
            token_error=int(health_section.get("token_error", 8000)),
            staleness_question_days=int(health_section.get("staleness_question_days", 30)),
            compress_min_depth=int(health_section.get("compress_min_depth", 3)),
        )
