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
  the extension, never to the .igz reader.
- A **workspace** shows the extension's own document instead of the model,
  which waits untouched ("parked") until the workspace is left.
"""
from __future__ import annotations

API_VERSION = 2


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

    def on_document_changed(self, fn) -> None:
        """Call ``fn()`` whenever the document changes — an edit, an undo,
        New, Open — so a panel can show the current data."""
        self.viewport.sceneVersionChanged.connect(lambda _v: fn())

    # ---- Side panel ----------------------------------------------------------
    def add_panel(self, title: str, widget, name: str | None = None):
        """Put ``widget`` in the side tray as a tab of its own, beside
        Properties / BIM / Terrain. Returns the dock.

        ``name`` tells apart several panels of one extension; the dock's
        object name (``extension_<key>`` or ``extension_<key>_<name>``) is
        what the window layout remembers it by, so keep it stable. The panel
        goes back where the user left it last session, and gets a Window
        menu entry. Asking again for a panel that exists returns it (the new
        ``widget`` is not used), so an extension may call this whenever its
        tool runs."""
        from PySide6.QtWidgets import QDockWidget, QWidget
        win = self._window
        object_name = f"extension_{self.key}" + (f"_{name}" if name else "")
        existing = win.extension_panels().get(object_name)
        if existing is not None:
            return existing
        dock = QDockWidget(title, win)
        dock.setObjectName(object_name)
        dock.setWidget(widget)
        dock.setTitleBarWidget(QWidget(dock))   # the tab already names it
        win._register_extension_dock(dock)
        tray = getattr(win, "tray", None)
        if tray is not None:
            tray.raise_()                   # Properties stays the one in front
        return dock

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

    # ---- Documents of the extension's own -----------------------------------------
    def add_file_opener(self, suffix: str, fn) -> None:
        """Documents ending in ``suffix`` (``".xyz"``) are the extension's:
        opened from Open Recent, the command line or a double-click (once
        the system associates the type with IngeTrazo), they go to
        ``fn(path)``, which returns True when it opened the document."""
        suffix = suffix.lower()
        if not suffix.startswith("."):
            suffix = "." + suffix
        self._window.file_openers[suffix] = fn

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
