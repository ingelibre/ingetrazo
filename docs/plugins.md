# Writing an IngeTrazo plugin

The plugin API is **not stable yet** — expect breaking changes during the
0.x series.

A plugin is a Python file (or a package directory) that defines one or more
tools. Drop it in either of the two places IngeTrazo scans at startup:

- `<app>/plugins/` — plugins bundled with the application (read-only in an
  installed build);
- your per-user directory — `~/.local/share/ingetrazo/plugins/` on Linux
  (honouring `$XDG_DATA_HOME`), `%APPDATA%\ingetrazo\plugins\` on Windows.
  **Extensions ▸ Open plugins folder** creates and opens it for you.

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
    # Optional: what it does, in the status bar and the F3 search.
    description = "Say hello in the status bar."

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

On failure, `SnapshotImport` restores the original membership and order of
groups, layers, saved views, dimensions, text labels and sheets, including
objects removed by the failed mutation. These collections are restored in
place so existing scripting-scope references stay valid.

Useful, honest data points (what the app itself uses — see the bundled
`plugins/model_info.py` for a worked example):

- geometry: `scene.loose_mesh` (NOT `scene.mesh`, which is swapped while a
  group is open for editing), `scene.groups`;
- materials: per-face `attrs["color"]` (floats 0–1) and `attrs["texture"]`
  are the render truth; named identity lives in the registry
  (`scene.materials`, `attrs["mat"]` on faces — see `core/materials.py`);
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

## Building on the AI layer (`core/ai.py`)

The two AI plugins share a reusable layer that any plugin can import:

- `ai.run_transactional(viewport, code, scope)` — execute Python against
  the live document with the Python Console's guarantees: ONE undo step,
  whole rollback on error, no undo entry for inspect-only runs. This is
  the canonical way for generated or scripted code to mutate the model.
- A provider layer following the IngePresupuestos convention: one API
  key, provider detected by its prefix (`ai.detect_provider`), seven
  providers over two wire formats (Anthropic native + OpenAI-compatible),
  stdlib `urllib` only. `ai.chat(...)` does one blocking turn (run it on
  a worker thread), `ai.list_models(...)` returns what the key can
  actually use, `ai.probar_conexion(...)` validates credentials, and
  `ai.PROVIDERS` / `ai.DEFAULT_MODELS` / `ai.PROVIDER_INFO` feed a UI.

So "an assistant that speaks my domain" is a small plugin: your own
system prompt + `ai.chat` + `ai.run_transactional`. See
`plugins/ai_assistant.py` for the full worked example (agent loop with
screenshot feedback) and `docs/ai-bridge.md` for the MCP route.

Threading rule for any plugin doing network or background work: never
touch the document off the main thread. Relay results with a
`Signal(object)` on a queued connection to a bound method —
`Signal(dict)` would hand the slot a COPY of the payload, and a lambda
receiver runs on the WRONG thread (both bugs were hunted in these very
plugins; the details are in the AI plugins' comments).

## Beyond tools: `setup(app)`

A plugin that needs more than a menu entry defines a module-level
`setup(app)`. It is called once, when the main window is built, with an
`ExtensionApp` (`views/extension_api.py`, `API_VERSION` 2). A plugin may
have tools, a `setup`, or both; if `setup` raises, the plugin shows as a
load error and the application opens regardless.

```python
def setup(app):
    app.key                       # this plugin's name (its file stem)
    app.window, app.viewport, app.scene

    # Data IN THE DOCUMENT: one JSON-safe value per plugin, saved in the
    # .igz, reset by New/Open. Each set is one undo step.
    data = app.document_data(default={})
    app.set_document_data({"levels": [...]})
    app.on_document_changed(refresh)      # edits, undo, New, Open

    # A tab in the side tray, beside Properties / BIM / Terrain. It goes
    # back where the user left it and is listed in Window ▸ Panels (the
    # user may hide it there); `name` tells apart several panels of one
    # extension, `panel=` puts several extensions in ONE tab.
    dock = app.add_panel("Levels", my_widget)
    # A panel few users need open all the time: closed the first time,
    # opened from Window ▸ Panels (and remembered from then on).
    app.add_panel("Levels — help", help_widget, name="help",
                  start_hidden=True)
    app.add_panel("AI", chat, panel="ai", stretch=1)
    app.show_panel(dock)                  # to the front, shown again if hidden

    # Several commands? A submenu of your own: Extensions ▸ Windowizer ▸ …
    sub = app.add_menu("Windowizer")
    sub.addAction("Edit window…", edit)

    # Entries in the viewport's right-click menu, after the selection's own
    # (open dialogs from them with QTimer.singleShot(0, …)):
    app.add_context_menu(lambda menu, selection: ...)

    # What YOUR container groups are, in the Browser: the type in
    # the Type column (the filter finds it), the properties in its tooltip.
    # Asked for every row: keep it cheap; None for groups that are not yours.
    app.add_outliner_kind(lambda group: {
        "type": "Window", "props": [("Panes", "3 × 2"), ("Width", "1.20 m")]}
        if app.key in (group.ext or {}) else None)

    # Parameters of YOUR container groups (a parametric window, a stair):
    # group.ext[app.key] — kept with copies, saved in the .igz, and apart
    # from group.ifc, which the BIM panel replaces when it retags.
    group.ext = {app.key: {"rows": 2, "cols": 3}}

    # An entry in the Extensions menu (a shortcut already taken is left off;
    # `tip` says what it does, in the status bar and in F3).
    app.add_menu_action("Levels…", lambda: app.show_panel(dock), "Ctrl+Shift+L",
                        tip="Show the levels of the building.")

    # Another .igz as ONE component, with no file dialog: it follows the
    # mouse and a click drops it, or `at=` puts its origin at a point now
    # (one undo step). Returns the component; None = no geometry.
    app.import_igz("/path/to/bench.igz")
    comp = app.import_igz("/path/to/bench.igz", at=(4.0, 2.0, 0.0))

    # Drawn with a QPainter over every frame, whatever the active tool;
    # world points (metres) to pixels, thousands at a time:
    app.add_overlay(lambda viewport, painter: ...)
    px, py, in_front = app.world_to_pixels(points_n_by_3)

    # Your own items, selectable with the Select tool and deleted with
    # Supr (moving them comes later): `pick` says which item is under a
    # pixel (asked before the model's geometry), `on_select(id)` hears the
    # pick and `on_select(None)` its release, `delete(id)` removes it —
    # through set_document_data, so it is one undo step.
    app.add_pickable(pick=lambda viewport, px, py: None,
                     on_select=lambda item: ..., delete=lambda item: ...)

    # Offered the snap engine's answer on every hover and click; return a
    # core.snap.SnapResult (its `label` is the ScreenTip) or None.
    app.add_snap_provider(lambda viewport, snap, px, py: None)
```

Rules the host enforces: a snap provider never overrides a named point
(endpoint, midpoint, centre, intersection, on edge…) — the user aimed at
it; a provider that raises is logged and skipped, an overlay that raises
is logged once and removed, never breaking the frame or the cursor; the
painter state is saved and restored around every overlay; document data
that is not JSON-safe is dropped on save rather than failing it.

### Toolbars created after startup

A worker can publish its toolbars after `setup(app)` and the window's initial
layout restoration have finished. Give every toolbar a stable `objectName`.
Then call `app.restore_toolbar_layout()` from the worker's queued GUI-thread
ready handler, after adding all its toolbars:

```python
def on_worker_ready(self):             # a slot on the GUI-thread host QObject
    self.create_toolbars()             # stable object names, including their actions
    self.app.restore_toolbar_layout()
```

The call restores saved docking areas, rows, order and visibility. Repeated
ready notifications on the same `ExtensionApp` do nothing after restoration,
so they cannot undo a subsequent user rearrangement. A fresh profile keeps
the extension's default placement. This hook is for startup completion;
do not create a new `ExtensionApp` and restore the layout on every command.

### Managing community extensions

**Extensions ▸ Manage extensions…** reads the community catalog from
[`ingetrazo-extensions`](https://github.com/ingelibre/ingetrazo-extensions),
downloads individual Python files or ZIP packages, and installs them in the
per-user plugins directory. The manager separates browsing from the list of
installed catalog extensions; both views support text and tag filtering.
Catalog data is cached locally: the manager shows the last cached catalog
immediately and refreshes it in the background. If GitHub is unavailable, the
last valid cache remains usable and its refresh time is shown. Catalog sorting
includes name, reviewed status, installed state, and available updates; sorting
by update date is available only when the catalog supplies per-extension
dates. The manager shows installed and available versions for updates, and
warns when an extension's tested IngeTrazo version is substantially older.
Each entry shows its license and links to the author's repository before
installation. Entries not in the maintainer-reviewed hash list are labelled
as Community; assume that exact catalog version has not been reviewed by an
IngeTrazo maintainer.
Extensions requiring a newer IngeTrazo version cannot be installed or enabled.

Each download is checked against the catalog's SHA-256 before it is installed.
The manager marks an extension as reviewed only when its hash matches the
maintainer's entry in `reviewed.toml`.

Installed catalog extensions can be updated, enabled, disabled, or uninstalled
from the manager. Update availability is shown as soon as the catalog is
loaded; extension package files are downloaded only after choosing Download or
Update. These changes take effect after restarting IngeTrazo because
extensions register tools and UI during startup. Extensions are Python code:
install only extensions whose source and publisher you trust. The checksum
detects content that differs from the catalog; it is not a sandbox or a
guarantee that code is safe.

If an installed extension fails to load at startup, its manager entry shows
the load error and offers actions to disable it, open its folder, and open
IngeTrazo's log folder for the full traceback.

### Where your interface goes

The side tray is one place, not the only one. Pick by how the user works
with it:

- **A tray tab** (`add_panel`) — for what stays open *while modelling* and
  works on the viewport: placing things with a click, settings you tweak
  and look at the model again. Render with Blender and Levels live here.
  Keep it narrow-friendly: controls that shrink, sections that fold
  (`views/fold_section.py`), no fixed widths.
- **A dialog or a window of your own** (a `QDialog`, any Qt window, from a
  tool or a menu entry) — for what is opened, used and closed, or needs
  room: a report, a console, an image. Model Info, the Python Console and
  the render's image viewer do this. Parent it to `app.window`, make it
  non-modal unless it must block, and reuse one instance.
- **Only a menu entry or a tool** — for one-shot commands.
- **A workspace** (below) — when the extension has a document of its own
  that replaces the model for a while.

Nothing forces the tray: an extension may mix these (Render has its tab
and opens the image in a window).

### A document type of its own, and workspaces (API 2)

**Provisional while IngeTrazo is 0.x:** this protocol (`add_file_opener`,
`enter_workspace`/`leave_workspace`, the `workspace` object's shape) may
still change in a later 0.x release without a major-version bump. Pin to
a specific IngeTrazo version if you rely on it.

A bigger extension may have documents of its own — a CAM job, say, with
its drawing on the stock and its operations:

```python
def setup(app):
    def open_job(path):
        job = load(path)                  # an object with a Scene + History
        return app.enter_workspace(job)   # shown instead of the model

    # Files ending in .xyz are this extension's: opened from Open Recent,
    # the command line or a double-click, they go to open_job(path) (True
    # when it opened). The file dialog stays IngeTrazo's own; offer an
    # «Open…» in the extension's panel. A core suffix (.igz, .dae, .skp,
    # .dxf, .dwg, .obj, .stl, .glb), or one another extension already
    # claimed, is refused — logged, not raised.
    app.add_file_opener(".xyz", open_job)
```

`enter_workspace(workspace)` parks the model — its scene, undo history,
camera, file and saved state wait untouched — and shows the workspace's
`scene` with its `history`. Meanwhile New / Open / Save / Save As, the
title, the unsaved-changes prompts and quitting go to the workspace, the
model's autosave pauses, and only the tools in `workspace.allowed_tools`
(`None` = all) can be picked. `leave_workspace()` brings the model back
exactly as it was; opening an `.igz` does so first. The workspace object
provides `scene`, `history`, `title()`, `is_dirty()`, `save()`,
`save_as()` and `confirm_leave()` (True when it may go: saved, discarded,
or nothing to lose); optionally `new()`, `open()`, `allowed_tools`,
`camera` and `left()`, called once it is gone. Every swap is a document
boundary for the viewport (`reset_document_caches()`), like New or Open.

**Worked example:** `examples/extensions/niveles.py` — building levels
(PB, PA…) kept in the document, a side panel to edit them, dashed guides in
parallel elevations and sections, and the cursor snapping to their heights
(«PA» on the tip). Idea and first version by José Castro Basso (FADU–UDELAR)
for teaching architectural representation. It ships with the app but is not loaded:
**Extensions ▸ Manage extensions…** installs it (and disables or uninstalls
it again); restart to load it. Features only some users need
belong in extensions like this one, not in the core.

**A second one:** `examples/extensions/windowizer.py` — parametric windows
from faces drawn on a wall: one container group per window (`IfcWindow`,
with a Frame and its Glass panes), the wall opened through or with reveals,
Edit window rebuilding it in place from `group.ext`, and Erase window
closing the wall again; all in a submenu (`add_menu`) and the right-click
menu (`add_context_menu`), each command one undo step. A port of Rick
Wilson's Windowizer 3 by Bane Andreev, an architect, written with AI help.

## Bundled reference plugins

- `plugins/model_info.py` — Model Info dialog (geometry / materials /
  layers / BIM statistics). A read-only, dialog-based plugin.
- `plugins/python_console.py` — the Python Console. A stateful,
  command-layer-integrated plugin.
- `plugins/solid_inspector.py` — Solid Inspector: per-edge watertightness
  diagnosis with viewport highlighting, step-by-step navigation and a
  one-undo-step repair (`RepairSolidsCommand`, snapshot undo over several
  meshes). A side-tray tab (`setup(app)` + `add_panel`) with a viewport
  overlay that paints each problem in its colour.
- `plugins/ai_assistant.py` — the in-app AI assistant (Ctrl+Shift+A): a
  multi-provider chat agent that models through `core.ai`, in the «AI»
  tray tab. The reference for worker threads, per-provider settings and a
  menu entry that brings a tab forward.
- `plugins/ai_bridge.py` — the MCP bridge: a localhost TCP server that
  lets an external agent (Claude Code/Desktop) drive the document; a
  section of the same «AI» tab (`panel="ai"`). The reference for socket
  servers and main-thread relays.
- `plugins/render_blender.py` — Render with Blender: a tray tab with
  folding sections, lights placed with a click and drawn over the
  viewport, document data, a child process, and the image in a window of
  its own. The reference for a full panel extension.

## Roadmap

- Tool registration — **done** (Extensions menu, this page).
- Importer / exporter registration.
- Side-panel registration, document data, viewport overlays and snap
  providers — **done** (`setup(app)`, above).
- Plugin manifest (`plugin.toml`) for metadata and dependencies.
- Plugin manager UI (install, enable, disable, update) — **done**; it uses
  the community catalog without imposing a package format on the extension
  API.
