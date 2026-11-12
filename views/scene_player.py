# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The scene player: glides the viewport's camera to a scene, or runs
through every scene in turn (core/scene_animation.py has the maths).

- ``glide_to``: showing a scene. The camera slides there; on arrival the
  scene's layers, style, section… come in (the Scenes panel's
  ``finish_view``).
- ``play``: the run. From the scene after the one shown, one after another
  in the order of the tabs, waiting on each, round and round until
  stopped.

Anything the user does to the view stops it where it is: a click or the
wheel in the viewport, Esc, a camera moved by anything else (a standard
view, Zoom Extents, a tool), another project brought to the front. A
glide stopped short still brings its scene's layers and style: that
scene is the one marked; the camera stays where the user took it.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal

from core.scene_animation import Pose, Run, glide

#: Milliseconds between two frames (~60 per second).
FRAME_MS = 16


class ScenePlayer(QObject):
    """Moves ``window.viewport.camera``; the window owns one."""

    #: Started or stopped (the menu's Play follows it).
    activeChanged = Signal(bool)

    def __init__(self, window, clock=None) -> None:
        super().__init__(window)
        self._window = window
        self._clock = clock or time.monotonic
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self.tick)
        self._viewport = None
        self._t0 = 0.0
        #: The pose the player last gave the camera: any other there means
        #: something else moved it, and the player lets go.
        self._last = None
        # A glide: from, to, seconds, what to do on arrival.
        self._glide = None
        # A run: the Run, its views (in its order), the last one reached.
        self._run = None
        self._views: list = []
        self._reached = -1
        self._arrive = None

    # ---- State ------------------------------------------------------------
    def is_active(self) -> bool:
        return self._glide is not None or self._run is not None

    def is_playing(self) -> bool:
        """A run through the scenes (not a single glide)."""
        return self._run is not None

    # ---- Start --------------------------------------------------------------
    def glide_to(self, view, seconds: float, arrive) -> bool:
        """Glide the camera to ``view`` over ``seconds``, then
        ``arrive(view)``. Returns False (and does nothing) when there is
        nothing to glide — no time, or already there: the caller jumps."""
        self.cancel()
        viewport = self._window.viewport
        a, b = Pose.of_camera(viewport.camera), Pose.of_view(view)
        if seconds <= 0.0 or a.close_to(b):
            return False
        self._glide = (a, b, float(seconds), view)
        self._arrive = arrive
        self._begin(viewport, a)
        return True

    def play(self, views, start: int, transition: float, pause: float,
             arrive) -> bool:
        """Run through ``views`` from ``start`` on, round and round, with
        ``arrive(view)`` as each scene is reached."""
        self.cancel()
        views = list(views)
        if not views:
            return False
        start %= len(views)
        order = views[start:] + views[:start]
        viewport = self._window.viewport
        here = Pose.of_camera(viewport.camera)
        self._run = Run(here, [Pose.of_view(v) for v in order],
                        transition, pause)
        self._views = order
        self._reached = -1
        self._arrive = arrive
        self._begin(viewport, here)
        self.tick()                  # a run without glide arrives at once
        return True

    def _begin(self, viewport, pose) -> None:
        self._viewport = viewport
        self._last = pose
        self._t0 = self._clock()
        viewport.installEventFilter(self)
        self._timer.start()
        self.activeChanged.emit(True)

    # ---- Stop ---------------------------------------------------------------
    def stop(self) -> None:
        """Stop where it is. A glide cut short still brings its scene's
        state (see the module's note); a run leaves the last one shown."""
        if not self.is_active():
            return
        glide_ = self._glide
        arrive = self._arrive
        self._end()
        if glide_ is not None and arrive is not None:
            arrive(glide_[3])

    def cancel(self) -> None:
        """Stop with nothing brought in: another scene takes over."""
        if self.is_active():
            self._end()

    def _end(self) -> None:
        self._timer.stop()
        if self._viewport is not None:
            try:
                self._viewport.removeEventFilter(self)
            except RuntimeError:             # the viewport went with its doc
                pass
        self._viewport = None
        self._glide = self._run = None
        self._views = []
        self._arrive = None
        self._last = None
        self.activeChanged.emit(False)

    # ---- Frames -------------------------------------------------------------
    def tick(self) -> None:
        """One frame: the pose of the moment onto the camera."""
        if not self.is_active():
            return
        viewport = self._viewport
        if viewport is not self._window.viewport:     # another project
            self.stop()
            return
        camera = viewport.camera
        if self._last is not None and not Pose.of_camera(camera).close_to(
                self._last, 1e-5):
            self.stop()                               # moved by someone else
            return
        t = self._clock() - self._t0
        if self._glide is not None:
            a, b, seconds, view = self._glide
            pose = glide(a, b, seconds, t)
            pose.put_on(camera)
            self._last = pose
            viewport.update()
            if t >= seconds:
                arrive = self._arrive
                self._end()
                if arrive is not None:
                    arrive(view)
            return
        pose, reached = self._run.at(t)
        pose.put_on(camera)
        self._last = pose
        viewport.update()
        if reached >= 0 and reached != self._reached:
            self._reached = reached
            view = self._views[reached]
            scene = viewport.scene
            if not any(view is v for v in getattr(scene, "saved_views", [])):
                self._end()                           # the scene was deleted
                return
            if self._arrive is not None:
                self._arrive(view)
            # Arriving may change the camera's projection (a parallel
            # scene): what it holds now is the player's own doing.
            if self.is_active():
                self._last = Pose.of_camera(camera)

    # ---- The user takes the view back ---------------------------------------
    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 — Qt override
        t = ev.type()
        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick,
                 QEvent.Wheel):
            self.stop()
        elif t == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self.stop()
            return True          # Esc stopped the run; the tool keeps its own
        return False


def ask_animation_settings(parent, current):
    """The transition settings in a small dialog: a new
    :class:`~core.scene_animation.SceneAnimation`, or None if cancelled."""
    from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                                   QDoubleSpinBox, QFormLayout)

    from core.i18n import tr
    from core.scene_animation import MAX_SECONDS, SceneAnimation
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Animation Settings"))
    form = QFormLayout(dlg)
    enabled = QCheckBox(tr("Glide from scene to scene"), dlg)
    enabled.setChecked(current.enabled)
    enabled.setToolTip(tr(
        "Off: showing a scene jumps straight to it, as it always did."))
    form.addRow(enabled)

    def seconds(value):
        box = QDoubleSpinBox(dlg)
        box.setRange(0.0, MAX_SECONDS)
        box.setDecimals(1)
        box.setSingleStep(0.5)
        box.setSuffix(" s")
        box.setValue(value)
        return box

    transition = seconds(current.transition)
    transition.setObjectName("animation_transition")
    form.addRow(tr("Scene transition:"), transition)
    enabled.toggled.connect(transition.setEnabled)
    transition.setEnabled(current.enabled)
    pause = seconds(current.pause)
    pause.setObjectName("animation_pause")
    pause.setToolTip(tr("How long Play stays on each scene."))
    form.addRow(tr("Scene delay:"), pause)
    buttons = QDialogButtonBox(
        QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    form.addRow(buttons)
    if dlg.exec() != QDialog.Accepted:
        return None
    return SceneAnimation(enabled=enabled.isChecked(),
                          transition=transition.value(), pause=pause.value())
