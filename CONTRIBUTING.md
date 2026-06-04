# Contributing to Baton

Thanks for contributing! The easiest entry point is adding a new agent adapter.

---

## Adding a new adapter (~50 lines)

To add support for a new AI coding tool (e.g. Windsurf, Aider, OpenCode):

**1. Create `baton/adapters/mytool.py`:**

```python
"""mytool.py — Adapter for MyTool (generates MYTOOL.md)."""
from .base import BaseAdapter, render_markdown_context


class MyToolAdapter(BaseAdapter):

    def render(self, data: dict) -> str:
        return render_markdown_context(data, tool_name="mytool")

    def file_path(self) -> str:
        return "MYTOOL.md"
```

**2. Register it in `baton/adapters/registry.py`:**

```python
from .mytool import MyToolAdapter

ADAPTER_MAP: dict[str, type[BaseAdapter]] = {
    ...
    "mytool": MyToolAdapter,
}

_DETECTION_RULES = [
    ...
    ("mytool", "MYTOOL.md"),  # trigger auto-detection when this file exists
]
```

**3. Add tests in `tests/test_adapters.py`:**

```python
from baton.adapters.mytool import MyToolAdapter

def test_mytool_file_path() -> None:
    assert MyToolAdapter().file_path() == "MYTOOL.md"

def test_mytool_render(sample_data: dict) -> None:
    result = MyToolAdapter().render(sample_data)
    assert "TestProject" in result
```

**4. Run the tests:**

```bash
pytest tests/
```

That's it. Open a PR with your adapter and a test.

---

## Contribution ladder

| Effort | Examples |
|--------|---------|
| **1–2 hours** | New adapter, new `baton score` check, improve parser rule, translate docs |
| **Half day** | Improve summariser prompt, add a CLI command, build test fixtures from real diffs |
| **Multi-day** | GitHub Actions integration (Phase 2), conflict resolution, MCP server (Phase 3) |

---

## Development setup

```bash
git clone https://github.com/AriS10223/baton
cd baton
python -m venv .venv
.venv\Scripts\activate    # Windows
source .venv/bin/activate  # Unix
pip install -e ".[dev]"
```

## Running tests

```bash
pytest tests/ -v
```

## Code style

- Match the surrounding code's comment density and naming conventions.
- No type-ignore comments without an explanation.
- `schema.py` is the single source of truth for field names — never duplicate them.

---

## Project laws (hard constraints)

1. **Python 3.11+ only.**
2. **`ruamel.yaml` for BATON.md parsing** — never PyYAML (drops inline comments).
3. **`schema.py` owns field definitions** — don't hardcode section names elsewhere.
4. **Managed-block markers are sacred** — `sync` never rewrites a full file without `BATON:START/END`.
5. **No LLM calls in Increment 1** — `init`, `sync`, `status`, `score` are purely deterministic.
6. **Score must total exactly 100 points** — the `assert` in `schema.py` enforces this.

---

## Opening an issue

Please include:
- Your Baton version (`baton --version`)
- OS and Python version
- The command you ran
- The error or unexpected output
