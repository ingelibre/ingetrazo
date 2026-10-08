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
python -m pytest -m "not slow"     # the fast suite (~3,100 tests, ~5 min; what CI runs)
python -m pytest                   # everything (~3,900), including the slow fuzz sweeps
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

## What's planned / in progress

The **Project board** ([placeholder link](https://github.com/orgs/ingelibre/projects/REPLACE_ME)),
not the raw Issues tab, is the primary place to see what's already planned,
in review, or in progress — issues move through Triage → Main Development
or Extension as maintainers prioritize them. See
[docs/triage.md](docs/triage.md) for the full triage system: roles, labels,
and how issues flow from "just opened" to "done".

## Issue triage

- **Bug report** — use the Bug report issue template: version/build, OS, steps to reproduce, expected vs. actual behavior, screenshots when relevant. New issues are auto-labeled `status: needs-triage`.
- **Feature request** — use the Feature request issue template: problem being solved, proposed solution, alternatives considered.
- **Good first issue** — these are tagged for newcomers. Comment on the issue ("I'd like to work on this") to request assignment; a maintainer will assign you.
- Full details — roles, label meanings, how multi-feature and duplicate issues are handled — are in [docs/triage.md](docs/triage.md).

## Communication

- Open **issues** for bugs and proposals.
- Use **GitHub Discussions** for open-ended questions, architecture debates, and showcasing your projects built with IngeTrazo.

## Licensing of contributions

By submitting a contribution you agree it will be licensed under **GPL-3.0-or-later** (the project license).
