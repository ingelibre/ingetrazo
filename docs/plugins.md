# Writing an IngeTrazo plugin

The plugin API is **not stable yet** — expect breaking changes during the
0.x series.

A plugin is a Python file (or a package directory) that defines one or more
tools. Drop it in either of the two places IngeTrazo scans at startup:

- `<app>/plugins/` — plugins bundled with the application (read-only in an
  installed build);
- your per-user directory — `~/.local/share/ingetrazo/plugins/` on Linux
  (honouring `$XDG_DATA_HOME`), `%APPDATA%\ingetrazo\plugins\` on Windows.

Every `Tool` subclass **defined in the file** gets an entry in the
**Extensions** menu. (Classes a plugin merely imports are ignored, so
importing `LineTool` to reuse it does not duplicate the built-in.)

## Minimal example

```python
# ~/.local/share/ingetrazo/plugins/hello_tool.py
from tools.base import Tool


class HelloTool(Tool):
    name = "Hello"
    shortcut = None      # or "Ctrl+Shift+H" — silently dropped if taken

    def on_activate(self, viewport):
        viewport.flash_status("Hello from a plugin!", 3000)

    def on_deactivate(self, viewport):
        pass
```

Rules of the road:

- **A broken plugin cannot break IngeTrazo.** If your file raises on import
  or your tool raises in its constructor, the app still starts; the menu
  shows a disabled `⚠ name (load error)` entry with the exception in its
  tooltip, and the full traceback goes to the `ingetrazo.plugins` logger.
- Menu plugin tools are **one-shot**: `on_activate` runs (typically opening
  a dialog) and the viewport's active drawing tool is left untouched.
- Plugins are imported by file path under a private module name — never
  rely on being importable as `plugins.yourname`, and never assume the
  plugin directory is on `sys.path`.

## Mutating the document

Read anything you like. To **modify** the model, go through the command
layer so your changes are undoable and mark the document dirty — the
Python Console (below) does this for you; a dialog-based plugin does it
explicitly:

```python
from core.history import SnapshotImport

def on_activate(self, viewport):
    def mutate(scene):
        scene.mesh.add_face([...])          # any mesh/group/layer edits
    viewport.history.execute(SnapshotImport(mutate))
    viewport.notify_scene_changed()
```

Useful, honest data points (what the app itself uses — see the bundled
`plugins/model_info.py` for a worked example):

- geometry: `scene.loose_mesh` (NOT `scene.mesh`, which is swapped while a
  group is open for editing), `scene.groups`;
- materials: per-face `attrs["color"]` (floats 0–1) and `attrs["texture"]`
  — there is no material registry;
- BIM: `core.bim` (`tag_faces`, `tag_group`, `collect_objects`) — the same
  calls behind the BIM tray and the IFC export;
- lengths for display: `scene.dimension_style` + the viewport's
  `_format_dim_value`.

## Developing interactively

**Extensions → Python Console** (`Ctrl+Shift+P`) is a live REPL over the
open document — the fastest way to prototype a plugin. Everything a run
creates is one undo step; a run that raises is rolled back whole. "Run
script file…" executes a `.py` against the model the same way
(`scripts/create_architectural_showcase.py` is a worked example that
builds a small BIM-tagged pavilion).

## Bundled reference plugins

- `plugins/model_info.py` — Model Info dialog (geometry / materials /
  layers / BIM statistics). A read-only, dialog-based plugin.
- `plugins/python_console.py` — the Python Console. A stateful,
  command-layer-integrated plugin.

## Roadmap

- Tool registration — **done** (Extensions menu, this page).
- Importer / exporter registration.
- Side-panel registration.
- Plugin manifest (`plugin.toml`) for metadata and dependencies.
- Plugin manager UI (install, enable, disable, update) — after the API
  stabilises; a package format would freeze the API too early (see the
  discussion in PR #1).
