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
python scripts/pytest_batches.py -m "not slow" tests   # the fast suite (~8,900 tests; what CI runs)
python scripts/pytest_batches.py tests                 # everything (~9,700), including the slow fuzz sweeps
python -m pytest tests/test_materials.py               # one file, or a few, while you work
```

Run the whole suite through `scripts/pytest_batches.py`, not as one
`python -m pytest` process. About 170 test files build a main window that
stays alive until the process ends, so in a single process memory keeps
growing (past 11 GB a sixth of the way in), and every file that switches the
theme then repaints all those windows: on macOS such a test took more than
five minutes, and the run did not finish in over an hour. The script runs
the theme-switching files each in a process of their own and the rest in
six batches, prints a `batch i/n` line as each one ends, and sums them up in
one line at the end; a batch that crashes is reported by name.

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
