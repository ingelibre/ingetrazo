# Development guide

## Setup

```bash
python3 -m venv venv
source venv/bin/activate          # Linux / macOS
.\venv\Scripts\Activate         # Windows (PowerShell)
pip install -r requirements.txt
python main.py
```

Requires Python 3.12+.

## Running tests

```bash
python -m pytest -m "not slow"     # the fast suite (~3,100 tests, ~5 min; what CI runs)
python -m pytest                   # everything (~3,900), including the slow fuzz sweeps
```

Every pull request runs the fast suite. A fix or a feature comes with its
test — ideally one that fails without the change. A test that paints
needs a real OpenGL context: guard it with a skip when there is none, or the
CI runner (no GPU) fails it.

## Style

- PEP 8, 100-character soft limit.
- All code, comments and commit messages in English.
- UI strings localized via `i18n/`. Never hardcode user-facing text.

## Submitting changes

See [../CONTRIBUTING.md](../CONTRIBUTING.md).
