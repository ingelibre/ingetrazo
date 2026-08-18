# Contributing to IngeTrazo

Thank you for your interest in IngeTrazo! Contributions of any kind are welcome — code, documentation, translations, bug reports, design feedback.

## Development setup

```bash
git clone https://github.com/<your-user>/ingetrazo.git
cd ingetrazo
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Requires Python 3.12+.

## Tests and CI

```bash
python -m pytest -m "not slow"     # the fast suite (~40 s, what CI runs)
python -m pytest                   # everything, including the slow fuzz sweeps
```

**Every pull request runs the fast suite automatically** — your PR gets a
green check or a red cross within a few minutes, no maintainer needed. New
features should come with tests; bug fixes should come with a regression
test that fails without the fix.

## Code style

- **Language**: all code, comments, commit messages and pull request descriptions in **English**, so anyone in the world can contribute.
- **PEP 8** with a soft 100-character line limit.
- **Type hints** encouraged for public functions, not enforced.
- **Docstrings** for public APIs (short and clear).
- **Spanish UI strings** live in `i18n/es.json`; English in `i18n/en.json`. Never hardcode user-facing text.

## Folder layout

See [docs/architecture.md](docs/architecture.md) for a tour. Briefly:

- `core/` — the engine: shared-vertex mesh, scene, camera, snapping,
  topology, undo/history (`Command`), BIM tagging, i18n, plugin discovery.
- `views/` — Qt widgets (main window, viewport, side tray, panels).
- `tools/` — built-in modeling tools (line, rectangle, push/pull, select, ...).
- `plugins/` — runtime-discovered plugins; the bundled Model Info and
  Python Console live here and double as reference implementations.
- `georef/` — real-world location: datum, tiles, DEM terrain, geo-paths,
  survey points, photogrammetric meshes.
- `formats/` — import / export (`.igz` native, `.skp`, OBJ, COLLADA,
  glTF/GLB, STL, IFC).
- `i18n/` — UI translations (flat English → Spanish map).
- `resources/` — shaders, icons, textures, components.
- `scripts/` — dev utilities and console demo scripts.
- `docs/` — architecture and contributor documentation.
- `tests/` — automated tests (`pytest`).

## Writing a plugin

The lowest-friction way to extend IngeTrazo — no fork needed. Drop a Python
file in your user plugins folder and its tools appear in the **Extensions**
menu; prototype live with **Extensions → Python Console** (`Ctrl+Shift+P`),
where every run is one undoable step. The contract (discovery rules, failure
isolation, and the `SnapshotImport` recipe for modifying the model) is in
[docs/plugins.md](docs/plugins.md). The plugin API is **not stable yet**
(0.x): plugins you publish today may need updates between minor versions.

## Workflow

1. **Fork** the repository.
2. Create a feature branch: `git checkout -b feature/short-description`.
3. Commit small, focused changes with descriptive messages.
4. Run the fast suite locally: `python -m pytest -m "not slow"`.
5. Push to your fork and open a **Pull Request** — CI will run the suite
   on it automatically.
6. A maintainer will review. We try to respond within a week.

## Issue triage

- **Bug report** — describe the bug, steps to reproduce, expected vs. actual behavior, screenshots when relevant.
- **Feature request** — what you want, why it matters, alternative tools that do it today.
- **Good first issue** — these are tagged for newcomers. Comment on the issue to claim one.

## Communication

- Open **issues** for bugs and proposals.
- Use **GitHub Discussions** for open-ended questions, architecture debates, and showcasing your projects built with IngeTrazo.

## Licensing of contributions

By submitting a contribution you agree it will be licensed under **GPL-3.0-or-later** (the project license).
