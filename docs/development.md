# Development guide

## Setup

```bash
python3 -m venv venv
source venv/bin/activate          # Linux / macOS
# .\venv\Scripts\Activate         # Windows (PowerShell)
pip install -r requirements.txt
python main.py
```

Requires Python 3.12+.

## Running tests

```bash
python -m pytest -m "not slow"     # the fast suite (~40 s, what CI runs)
python -m pytest                   # everything, including the slow fuzz sweeps
```

The project has ~2,000 automated tests covering the geometry engine, tools,
import/export, the sheet composer and the plugin system. New features should
come with tests; bug fixes should come with a regression test that fails
without the fix.

## Style

- PEP 8, 100-character soft limit.
- All code, comments and commit messages in English.
- UI strings localized via `i18n/`. Never hardcode user-facing text.

## Submitting changes

See [../CONTRIBUTING.md](../CONTRIBUTING.md).

