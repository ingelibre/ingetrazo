# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What an extension can reach beyond its tools — ``setup(app)``.

A plugin module that defines ``setup(app)`` gets it called once, when the
main window is built, with an :class:`ExtensionApp`. Through it the plugin
can keep data IN THE DOCUMENT, add a panel to the side tray, draw over the
viewport and offer the cursor an inference — whatever tool is active. That
is enough to build a whole feature outside the core (the Levels plugin is
the worked example), which is the point: what only some users need lives
in an extension they choose, not in everyone's IngeTrazo.

Contract (``API_VERSION`` 2; still 0.x — see docs/plugins.md). Version 2
adds, without changing anything version 1 did: named panels that keep
their place and have a Window-menu entry, the projection an overlay needs,
opening an extension's own file type, and workspaces.

- **Document data** is ONE JSON-safe value per extension (its key: the
  plugin's file name). It is saved in the .igz, reset by New/Open, and every
  change through :meth:`ExtensionApp.set_document_data` is one undo step.
- **Overlays** draw with a ``QPainter`` over the finished frame, after the
  active tool's own; each call is wrapped in save/restore.
- **Snap providers** see the snap engine's answer and may return another
  :class:`core.snap.SnapResult` (with a ``label``) — but never over a named
  point (endpoint, midpoint, centre, intersection…), which the user aimed at.
- A provider that raises is logged and skipped; an overlay that raises is
  logged once and removed: an extension cannot break painting or the
  cursor.
- **Panels** have a stable object name (``extension_<key>`` or
  ``extension_<key>_<name>``), so the window layout remembers where the
  user put them.
- **File openers** take a suffix for the extension: a document of that
  type opened from Open Recent, the command line or a double-click goes to
  the extension, never to the .igz reader. A core suffix, or one another
  extension already claimed, is refused (logged, not raised).
- A **workspace** shows the extension's own document instead of the model,
  which waits untouched ("parked") until the workspace is left.
"""
from __future__ import annotations

import logging

log = logging.getLogger("ingetrazo.plugins")

API_VERSION = 2

#: Suffixes the core itself reads (natively, or as an import): an extension
#: claiming one would never actually see it, since ``open_path`` consults
#: ``file_openers`` first — it's the extension's own opener that would
#: silently steal Open Recent / CLI / double-click from the core reader.
CORE_FILE_SUFFIXES = frozenset({
    ".igz", ".dae", ".skp", ".dxf", ".dwg", ".obj", ".stl", ".glb",
})


class ExtensionApp:
    """One plugin's handle on the running application."""

    api_version = API_VERSION

    def __init__(self, window, key: str) -> None:
        self._window = window
        self.key = str(key)

    # ---- Where things are ------------------------------------------------
    @property
    def window(self):
        return self._window

    @property
    def viewport(self):
        return self._window.viewport

    @property
    def scene(self):
        return self._window.viewport.scene

    # ---- Document data -----------------------------------------------------
    def document_data(self, default=None):
        """This extension's value in the open document (a copy: change it
        with :meth:`set_document_data`, never in place)."""
        import json
        data = getattr(self.scene, "plugin_data", {}) or {}
        if self.key not in data:
            return default
        return json.loads(json.dumps(data[self.key]))

    def set_document_data(self, value) -> None:
        """Store ``value`` (JSON-safe; ``None`` removes it) in the document,
        as one undo step — the document is then unsaved, like any edit."""
        from core.history import SetPluginDataCommand
        vp = self.viewport
        vp.history.execute(SetPluginDataCommand(self.key, value))
        notify = getattr(vp, "notify_scene_changed", None)
        if callable(notify):
            notify()
        vp.update()

    def import_igz(self, path, at=None):
        """Insert the IngeTrazo document at ``path`` as one component, with
        no file dialog. ``at=None``: it follows the mouse and a click drops
        it; ``at=(x, y, z)`` (metres) or a ``QVector3D``: inserted with its
        origin there, one undo step. Returns the component, or ``None``
        when the file has no geometry; an unreadable file raises."""
        return self._window.import_igz_path(path, at=at)

    def on_document_changed(self, fn) -> None:
        """Call ``fn()`` whenever the document changes — an edit, an undo,
        New, Open — so a panel can show the current data."""
        self.viewport.sceneVersionChanged.connect(lambda _v: fn())

    # ---- Side panel ----------------------------------------------------------
    def add_panel(self, title: str, widget, name: str | None = None, *,
                  panel: str | None = None, stretch: int = 0):
        """Put ``widget`` in the side tray as a tab of its own, beside
        Properties / BIM / Terrain. Returns the dock.

        ``name`` tells apart several panels of one extension; the dock's
        object name (``extension_<key>`` or ``extension_<key>_<name>``) is
        what the window layout remembers it by, so keep it stable. The panel
        goes back where the user left it last session and is listed in
        Window ▸ Panels. Asking again for a panel that exists returns it
        (the new ``widget`` is not used), so an extension may call this
        whenever its tool runs.

        With ``panel`` several extensions share ONE tab (object name
        ``extension_<panel>``): the first call creates it, named ``title``;
        the next ones stack their widget under the previous (``stretch`` as
        in ``QBoxLayout.addWidget``) — the assistant and the MCP bridge both
        live in the «AI» tab."""
        from PySide6.QtWidgets import QDockWidget, QVBoxLayout, QWidget
        win = self._window
        shared = getattr(win, "_shared_panels", None)
        if shared is None:
            shared = win._shared_panels = {}
        if panel is not None and panel in shared:
            dock, box = shared[panel]
            box.addWidget(widget, stretch)
            return dock
        if panel is not None:
            object_name = f"extension_{panel}"
        else:
            object_name = f"extension_{self.key}" + (f"_{name}" if name else "")
            existing = win.extension_panels().get(object_name)
            if existing is not None:
                return existing
        if panel is not None:
            holder = QWidget()
            box = QVBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(4)
            box.addWidget(widget, stretch)
            widget = holder
        dock = QDockWidget(title, win)
        dock.setObjectName(object_name)
        dock.setWidget(widget)
        dock.setTitleBarWidget(QWidget(dock))   # the tab already names it
        win._register_extension_dock(dock)
        if panel is not None:
            shared[panel] = (dock, box)
        tray = getattr(win, "tray", None)
        if tray is not None:
            tray.raise_()                   # Properties stays the one in front
        return dock

    def show_panel(self, dock) -> None:
        """Bring a tab from :meth:`add_panel` to the front — shown again
        if the user hid it from Window ▸ Panels."""
        self._window.set_tray_shown(dock, True)

    def add_menu_action(self, text: str, fn, shortcut: str | None = None,
                        tip: str | None = None):
        """An entry in the Extensions menu that calls ``fn()``; a
        ``shortcut`` already taken by the app is left off, and ``tip`` —
        what it does, in a sentence — shows in the status bar and in F3.
        Returns the QAction (``None`` outside a window with that menu)."""
        from PySide6.QtGui import QAction, QKeySequence
        win = self._window
        menu = getattr(win, "_ext_menu", None)
        if menu is None:
            return None
        action = QAction(text, win)
        if tip:
            action.setStatusTip(tip)
        if shortcut:
            seq = QKeySequence(shortcut).toString()
            taken = getattr(win, "_ext_taken_keys", set())
            if seq and seq not in taken:
                action.setShortcut(QKeySequence(shortcut))
                taken.add(seq)
        action.triggered.connect(lambda _c=False: fn())
        menu.addAction(action)
        return action

    def add_menu(self, title: str):
        """A submenu of its own in the Extensions menu («Windowizer ▸»),
        for an extension with several commands; returns the QMenu to fill
        (``None`` outside a window with that menu)."""
        menu = getattr(self._window, "_ext_menu", None)
        return menu.addMenu(title) if menu is not None else None

    def add_context_menu(self, fn) -> None:
        """``fn(menu, selection)`` adds entries to the viewport's
        right-click menu (a QMenu), after the ones for the selection and
        before Paste and Undo; ``selection`` is a list of what is
        selected. Open dialogs from the entries with
        ``QTimer.singleShot(0, …)``, after the menu has closed."""
        win = self._window
        if not hasattr(win, "_ext_context_menus"):
            win._ext_context_menus = []
        win._ext_context_menus.append(fn)

    # ---- Viewport ------------------------------------------------------------
    def add_overlay(self, fn) -> None:
        """``fn(viewport, painter)`` draws over every frame, in the widget's
        logical pixels (project world points with :meth:`world_to_pixels`).
        The painter state is saved and restored around each call."""
        self.viewport._ext_overlays.append(fn)
        self.viewport.update()

    def world_to_pixels(self, points):
        """World points (metres; anything shaped ``(N, 3)``) → ``(px, py,
        in_front)`` NumPy arrays: one call for thousands of points, the same
        projection the viewport's own overlays use. Skip the points whose
        ``in_front`` is False (behind the camera)."""
        return self.viewport.world_to_pixels(points)

    def add_snap_provider(self, fn) -> None:
        """``fn(viewport, snap, px, py)`` → a ``SnapResult`` to use instead,
        or ``None`` to leave the engine's answer."""
        self.viewport._ext_snap_providers.append(fn)

    def add_pickable(self, pick, on_select=None, delete=None) -> None:
        """Let the user SELECT this extension's own items with the Select
        tool and DELETE them with Supr (issue #205; moving comes later).

        ``pick(viewport, px, py)`` → an item id (any value) under that
        pixel, or ``None``. It is asked before the model's geometry, so an
        item drawn over the model wins the click. ``on_select(item_id)``
        is told what was selected, and ``on_select(None)`` when it is let
        go (a click elsewhere, Esc). ``delete(item_id)`` removes it — do
        it with :meth:`set_document_data`, so it is one undo step. After
        any change to the document the pick is dropped, so Supr never
        deletes by a stale id."""
        vp = self.viewport
        if not hasattr(vp, "_ext_pickables"):
            vp._ext_pickables = []
        vp._ext_pickables.append(
            {"key": self.key, "pick": pick, "on_select": on_select,
             "delete": delete})

    def release_pick(self) -> None:
        """Let go of this extension's selected item, without telling it
        back (it already knows): after it changed its own data, say."""
        vp = self.viewport
        pick = getattr(vp, "extension_pick", None)
        if pick is not None and pick[0]["key"] == self.key:
            vp.clear_extension_pick(notify=False)
            vp.update()

    # ---- Documents of the extension's own -----------------------------------------
    def add_file_opener(self, suffix: str, fn) -> None:
        """Documents ending in ``suffix`` (``".xyz"``) are the extension's:
        opened from Open Recent, the command line or a double-click (once
        the system associates the type with IngeTrazo), they go to
        ``fn(path)``, which returns True when it opened the document.

        Refused, with a warning logged, for one of the core's own suffixes
        (:data:`CORE_FILE_SUFFIXES` — ``.igz``, ``.dae``, ``.skp``, ``.dxf``,
        ``.dwg``, ``.obj``, ``.stl``, ``.glb``) or one an earlier extension
        already claimed: :meth:`views.main_window.MainWindow.open_path`
        consults ``file_openers`` before anything else, so a claim that
        went through would silently steal that suffix from its rightful
        reader instead of just failing to be read itself."""
        suffix = suffix.lower()
        if not suffix.startswith("."):
            suffix = "." + suffix
        if suffix in CORE_FILE_SUFFIXES:
            log.warning("extension %r may not claim %r: a core format",
                        self.key, suffix)
            return
        openers = self._window.file_openers
        if suffix in openers:
            log.warning("extension %r's claim on %r ignored: already "
                        "taken", self.key, suffix)
            return
        openers[suffix] = fn

    def enter_workspace(self, workspace) -> bool:
        """Show the extension's own document instead of the model, which is
        parked untouched — its scene, undo history, camera, file and saved
        state — until :meth:`leave_workspace`. Meanwhile New / Open / Save /
        Save As, the title, the unsaved-changes prompts and quitting go to
        ``workspace``, the model's autosave pauses, and only the tools in
        ``workspace.allowed_tools`` (None = all) can be picked.

        ``workspace`` provides ``scene``, ``history``, ``title()``,
        ``is_dirty()``, ``save()``, ``save_as()`` and ``confirm_leave()``;
        optionally ``new()``, ``open()``, ``allowed_tools``, ``camera`` and
        ``left()``. False when a workspace is shown already."""
        return self._window.enter_workspace(workspace)

    def leave_workspace(self) -> bool:
        """Back to the parked model; False when the workspace would not go
        (its user cancelled the unsaved-changes prompt)."""
        return self._window.leave_workspace()

    def workspace(self):
        """The workspace shown instead of the model, or None."""
        return self._window.workspace()
