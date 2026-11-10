# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Camera ▸ Camera Settings: the view's camera by the numbers.

Orbiting and walking put the camera somewhere by eye; this window says
where it is and takes it to an exact place: the eye and the point it looks
at as coordinates, the lens as a focal length (35 mm format) or an angle,
the roll, the frame shift that keeps a tall facade's verticals parallel,
the clipping distances that look through a wall, and the frame of the
picture (16:9, 4:3…).

Two levels: the BASIC settings are what most pictures need — projection,
lens, vertical shift and frame; «Advanced options» opens the rest — the
eye and target by coordinates, the angle in degrees, roll, horizontal
shift and clipping. The window remembers which one was left open.

It stays open beside the model (a tool window): what you type changes the
view at once, and what the mouse does to the view shows in the fields —
a field being typed in is left alone. It works on the active view, so
with four views it follows the one you are working in.

Opened from a scene's right-click menu it shows that scene and edits it:
what is changed here is kept in the scene, until the view is moved by
other means (an orbit, another scene), which ends the editing.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                               QFormLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QStyle, QVBoxLayout,
                               QWidget)

from core.camera import (MAX_SHIFT, fov_from_focal, focal_from_fov)
from core.i18n import tr
from views.length_field import LengthSpinBox

#: Lenses offered by name, in millimetres of the 35 mm format.
LENS_PRESETS = (14, 18, 24, 28, 35, 50, 85, 105, 135)

#: Picture frames offered, as (width / height, label). ``None`` = no frame.
FRAMES = (
    (None, "No frame"),
    (16 / 9, "16:9"),
    (4 / 3, "4:3"),
    (3 / 2, "3:2"),
    (1.0, "1:1"),
    (math.sqrt(2.0), "A (√2:1)"),
    (2.39, "2.39:1"),
    (9 / 16, "9:16"),
)

#: How far a typed coordinate may go — the camera's own ceiling.
_COORD_LIMIT = 1.0e6

#: Where the window remembers whether the advanced options were open.
_ADVANCED_KEY = "camera_settings/advanced"


def _settings():
    """The app's settings — none while the app has no name (the tests), so
    a test run never writes into the user's own."""
    from PySide6.QtCore import QCoreApplication, QSettings
    return QSettings() if QCoreApplication.organizationName() else None


def _load_advanced() -> bool:
    st = _settings()
    return st is not None and str(st.value(_ADVANCED_KEY, "false")) == "true"


def _spin(lo: float, hi: float, decimals: int, suffix: str = "") -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(lo, hi)
    box.setDecimals(decimals)
    box.setSuffix(suffix)
    box.setKeyboardTracking(False)      # a value per Enter, not per key
    box.setAccelerated(True)
    return box


def _length(lo: float = -_COORD_LIMIT, hi: float = _COORD_LIMIT) -> LengthSpinBox:
    box = LengthSpinBox(minimum=lo, maximum=hi)
    box.setKeyboardTracking(False)
    return box


def _row(*widgets) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        lay.addWidget(x)
    return w


class CameraSettingsDialog(QDialog):
    """The camera of ``window.viewport`` (whichever view is active)."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self._syncing = False
        self._shown = None
        #: The scene being edited (opened from its right-click menu) and the
        #: camera as this window last left it there.
        self._scene_view = None
        self._bound_state = None
        self.setWindowTitle(tr("Camera Settings"))
        self.setWindowFlag(Qt.Tool, True)
        self.setModal(False)

        root = QVBoxLayout(self)
        self.scene_label = QLabel()
        self.scene_label.setWordWrap(True)
        self.scene_label.setStyleSheet("font-weight: bold;")
        self.scene_label.hide()
        root.addWidget(self.scene_label)

        # The settings scroll when the screen is too low for them all; the
        # buttons under them stay in sight.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._body = QWidget()
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, 1)

        # The parts fold like the side panels' sections (title in bold with
        # its arrow, open or folded as left last time); the advanced ones
        # show only with «Advanced options» ticked.
        self.sections = []

        def section(title: str, key: str):
            from views.fold_section import FoldSection
            sec = FoldSection(title, f"camera_settings/open/{key}")
            sec.header.toggled.connect(self._refit_soon)
            self.sections.append(sec)
            return sec, QFormLayout(sec.body)

        # ---- Basic: what most pictures need ---------------------------------
        basic, form = section(tr("Lens and frame"), "basic")
        self.projection = QComboBox()
        for mode, label in (("perspective", tr("Perspective")),
                            ("two_point", tr("Two-Point Perspective")),
                            ("parallel", tr("Parallel Projection"))):
            self.projection.addItem(label, mode)
        form.addRow(tr("Projection:"), self.projection)
        lo, hi = getattr(window, "FOV_RANGE", (10.0, 120.0))
        self.preset = QComboBox()
        self.preset.addItem(tr("Custom"), None)
        for mm in LENS_PRESETS:
            if lo <= fov_from_focal(mm) <= hi:
                self.preset.addItem(tr("{mm} mm", mm=mm), float(mm))
        self.focal = _spin(focal_from_fov(hi), focal_from_fov(lo), 1, " mm")
        form.addRow(tr("Lens:"), self.preset)
        form.addRow(tr("Focal length (35 mm):"), self.focal)
        pct = MAX_SHIFT * 100.0
        self.shift_y = _spin(-pct, pct, 1, " %")
        self.shift_y.setToolTip(tr(
            "Slides the picture up or down without tilting the camera: a "
            "tall facade fits and its verticals stay parallel."))
        form.addRow(tr("Vertical shift:"), self.shift_y)
        self.frame = QComboBox()
        for aspect, label in FRAMES:
            self.frame.addItem(tr(label) if aspect is None else label, aspect)
        self.frame.setToolTip(tr(
            "The shape of the picture, drawn over the view: what lies "
            "outside it is shaded."))
        form.addRow(tr("Frame:"), self.frame)
        body.addWidget(basic)

        # ---- Advanced: every setting ----------------------------------------
        self.advanced = QWidget()
        adv = QVBoxLayout(self.advanced)
        adv.setContentsMargins(0, 0, 0, 0)
        pos, form = section(tr("Position"), "position")
        self.eye = [_length() for _ in range(3)]
        self.target = [_length() for _ in range(3)]
        form.addRow(tr("Eye (X, Y, Z):"), _row(*self.eye))
        form.addRow(tr("Looks at (X, Y, Z):"), _row(*self.target))
        adv.addWidget(pos)
        lens, form = section(tr("Angle, roll and shift"), "angle")
        self.fov = _spin(lo, hi, 1, "°")
        form.addRow(tr("Field of view (vertical):"), self.fov)
        self.roll = _spin(-180.0, 180.0, 1, "°")
        form.addRow(tr("Roll:"), self.roll)
        self.shift_x = _spin(-pct, pct, 1, " %")
        self.shift_x.setToolTip(tr(
            "Slides the picture sideways without turning the camera."))
        form.addRow(tr("Horizontal shift:"), self.shift_x)
        adv.addWidget(lens)
        clip, form = section(tr("Clipping"), "clipping")
        self.near_on = QCheckBox(tr("Manual"))
        self.near = _length(0.001, _COORD_LIMIT)
        self.far_on = QCheckBox(tr("Manual"))
        self.far = _length(0.01, _COORD_LIMIT)
        self.near_on.setToolTip(tr(
            "Hide everything closer to the eye than this distance — "
            "to look through a wall."))
        self.far_on.setToolTip(tr(
            "Hide everything farther from the eye than this distance."))
        form.addRow(tr("Near clipping:"), _row(self.near_on, self.near))
        form.addRow(tr("Far clipping:"), _row(self.far_on, self.far))
        adv.addWidget(clip)
        body.addWidget(self.advanced)
        body.addStretch(1)          # any spare height goes below, not in a box

        buttons = QHBoxLayout()
        # A tick, where it stays put while the window grows and shrinks.
        self.more = QCheckBox(tr("Advanced options"))
        self.more.setToolTip(tr(
            "Show every setting: the eye and target by coordinates, the "
            "angle in degrees, roll, horizontal shift and clipping."))
        buttons.addWidget(self.more)
        buttons.addStretch(1)
        self.reset = QPushButton(tr("Reset Lens"))
        self.reset.setToolTip(tr(
            "Shift, roll, clipping and frame back to an ordinary lens; the "
            "position and the field of view stay."))
        close = QPushButton(tr("Close"))
        buttons.addWidget(self.reset)
        buttons.addWidget(close)
        root.addLayout(buttons)

        # ---- Wiring ----------------------------------------------------------
        self.more.toggled.connect(self.set_advanced)
        self.projection.currentIndexChanged.connect(self._on_projection)
        for box in self.eye + self.target:
            box.valueChanged.connect(self._on_position)
        self.preset.currentIndexChanged.connect(self._on_preset)
        self.focal.valueChanged.connect(self._on_focal)
        self.fov.valueChanged.connect(self._on_fov)
        for box in (self.roll, self.shift_x, self.shift_y, self.near,
                    self.far):
            box.valueChanged.connect(self._on_lens)
        for box in (self.near_on, self.far_on):
            box.toggled.connect(self._on_lens)
        self.frame.currentIndexChanged.connect(self._on_lens)
        self.reset.clicked.connect(self._on_reset)
        close.clicked.connect(self.close)

        self._show_advanced(_load_advanced())

        # What the mouse does to the view shows here while the window is
        # open: a light poll (no signal covers every way the camera moves —
        # orbit, walk, scenes, the composer — and the check is a few
        # numbers compared).
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    # ---- Basic / advanced ---------------------------------------------------
    def set_advanced(self, on: bool) -> None:
        """Show or hide the advanced options, and remember it."""
        self._show_advanced(on)
        st = _settings()
        if st is not None:
            st.setValue(_ADVANCED_KEY, "true" if on else "false")

    def _show_advanced(self, on: bool) -> None:
        on = bool(on)
        self.more.blockSignals(True)
        self.more.setChecked(on)
        self.more.blockSignals(False)
        self.advanced.setVisible(on)
        # Grows or shrinks about its own centre, and stays on the screen.
        self.fit_on_screen(keep_centre=self.isVisible())

    def _refit_soon(self, _on=None) -> None:
        """A section folded or opened: fit the window once it has."""
        if self.isVisible():
            QTimer.singleShot(0, self.fit_on_screen)

    # ---- Size and place -----------------------------------------------------
    def _screen_area(self):
        from PySide6.QtGui import QGuiApplication
        screen = None
        if self.isVisible():
            screen = self.screen()
        if screen is None and hasattr(self._window, "screen"):
            screen = self._window.screen()
        screen = screen or QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    def _decoration(self):
        """The title bar and borders around the window, in pixels."""
        if self.isVisible():
            fg, g = self.frameGeometry(), self.geometry()
            return fg.width() - g.width(), fg.height() - g.height()
        title = self.style().pixelMetric(QStyle.PM_TitleBarHeight)
        return 2, max(title, 24) + 2

    def fit_on_screen(self, keep_centre: bool = True) -> None:
        """Size the window to show every setting it holds, but never
        larger than the screen (the settings scroll then), and place it
        whole on the screen: about the centre it had (``keep_centre``) or
        in the middle of the screen."""
        area = self._screen_area()
        lay = self.layout()
        lay.activate()
        body = self._body.sizeHint()
        bar = self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        m = lay.contentsMargins()
        extra_h = lay.sizeHint().height() - self._scroll.sizeHint().height()
        want_w = max(lay.sizeHint().width(),
                     body.width() + bar + m.left() + m.right())
        want_h = extra_h + body.height()
        if area is None:
            self.resize(want_w, want_h)
            return
        dw, dh = self._decoration()
        w = min(want_w, area.width() - dw)
        h = min(want_h, area.height() - dh)
        if keep_centre and self.isVisible():
            fg = self.frameGeometry()
            cx = fg.x() + fg.width() / 2.0
            cy = fg.y() + fg.height() / 2.0
            # The exact centre it was given, unless it was dragged since:
            # rounding to whole pixels must not walk it a pixel a click.
            anchor = getattr(self, "_anchor", None)
            if anchor is not None and abs(anchor[0] - cx) <= 1.0 \
                    and abs(anchor[1] - cy) <= 1.0:
                cx, cy = anchor
        else:
            cx = area.x() + area.width() / 2.0
            cy = area.y() + area.height() / 2.0
        self._anchor = (cx, cy)
        self.resize(w, h)
        fw, fh = w + dw, h + dh
        x = int(round(cx - fw / 2.0))
        y = int(round(cy - fh / 2.0))
        x = max(area.left(), min(x, area.right() + 1 - fw))
        y = max(area.top(), min(y, area.bottom() + 1 - fh))
        self.move(x, y)

    def present(self) -> None:
        """Show the window — opened anew, whole and in the middle of the
        screen; already open, it is only raised."""
        opening = not self.isVisible()
        if opening:
            self.fit_on_screen(keep_centre=False)
        self.show()
        if opening:
            # Its title bar is known only once shown: centre it again.
            self.fit_on_screen(keep_centre=False)
        self.raise_()
        self.activateWindow()

    def is_advanced(self) -> bool:
        return self.more.isChecked()

    # ---- Editing a scene ----------------------------------------------------
    def edit_scene(self, view) -> None:
        """Edit the scene ``view``, already shown in the view: every change
        made here is kept in it."""
        cam = self._camera()
        self._scene_view = view
        self._bound_state = self._state(cam) if cam is not None else None
        self._show_scene_label()

    def editing_scene(self):
        """The scene this window is editing, or ``None``."""
        return self._scene_view

    def stop_editing_scene(self) -> None:
        self._scene_view = None
        self._bound_state = None
        self._show_scene_label()

    def _show_scene_label(self) -> None:
        view = self._scene_view
        if view is None:
            self.scene_label.hide()
            self.setWindowTitle(tr("Camera Settings"))
            return
        self.scene_label.setText(tr(
            "Scene «{name}»: the changes made here are kept in the scene.",
            name=view.name))
        self.scene_label.show()
        if self.isVisible():
            self.fit_on_screen()
        self.setWindowTitle(f"{tr('Camera Settings')} — {view.name}")

    def _keep_in_scene(self) -> None:
        """Write the camera into the scene being edited."""
        view, cam = self._scene_view, self._camera()
        if view is None or cam is None:
            return
        scene = getattr(self._viewport(), "scene", None)
        if scene is None or view not in scene.saved_views:
            self.stop_editing_scene()        # deleted meanwhile
            return
        view.take_camera(cam)
        scene.version += 1                   # the document has changed
        self._bound_state = self._state(cam)

    # ---- The camera ---------------------------------------------------------
    def _viewport(self):
        return getattr(self._window, "viewport", None)

    def _camera(self):
        vp = self._viewport()
        return getattr(vp, "camera", None)

    def _repaint(self) -> None:
        """After an edit made here: show it, keep it in the scene being
        edited, and read the result back."""
        vp = self._viewport()
        if vp is not None:
            vp.update()
        self._keep_in_scene()
        self._shown = None
        self.refresh()

    @staticmethod
    def _state(cam) -> tuple:
        e, t = cam.eye(), cam.target
        return (round(e.x(), 6), round(e.y(), 6), round(e.z(), 6),
                round(t.x(), 6), round(t.y(), 6), round(t.z(), 6),
                cam.projection_mode(), round(cam.fov_deg, 4),
                tuple(sorted(cam.lens_dict().items())))

    def showEvent(self, event) -> None:  # noqa: N802 (Qt)
        super().showEvent(event)
        self._shown = None
        self.refresh()
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt)
        self._timer.stop()
        self.stop_editing_scene()
        super().hideEvent(event)

    def refresh(self) -> None:
        """Show the camera as it is now; a field being typed in keeps what
        is in it. A view moved by other means than this window ends the
        editing of a scene."""
        cam = self._camera()
        if cam is None:
            return
        state = self._state(cam)
        if (self._scene_view is not None and self._bound_state is not None
                and state != self._bound_state):
            self.stop_editing_scene()
        if state == self._shown:
            return
        self._shown = state
        self._syncing = True
        try:
            def put(box, value):
                if not box.hasFocus():
                    box.setValue(value)
            e, t = cam.eye(), cam.target
            for box, v in zip(self.eye, (e.x(), e.y(), e.z())):
                put(box, v)
            for box, v in zip(self.target, (t.x(), t.y(), t.z())):
                put(box, v)
            i = self.projection.findData(cam.projection_mode())
            self.projection.setCurrentIndex(max(0, i))
            persp = cam.perspective
            for w in (self.focal, self.fov, self.preset):
                w.setEnabled(persp)
            put(self.fov, cam.fov_deg)
            put(self.focal, cam.focal_mm)
            i = self.preset.findData(float(round(cam.focal_mm)))
            if i < 0 or abs(cam.focal_mm - round(cam.focal_mm)) > 0.05:
                i = 0
            self.preset.setCurrentIndex(i)
            # Two-point keeps its verticals: no roll there.
            self.roll.setEnabled(cam.projection_mode() != "two_point")
            put(self.roll, cam.roll_deg)
            put(self.shift_x, cam.shift_x * 100.0)
            put(self.shift_y, cam.shift_y * 100.0)
            self.near_on.setChecked(cam.clip_near is not None)
            self.far_on.setChecked(cam.clip_far is not None)
            self.near.setEnabled(cam.clip_near is not None)
            self.far.setEnabled(cam.clip_far is not None)
            put(self.near, cam.near_plane())
            put(self.far, cam.far_plane())
            i = 0
            for k in range(self.frame.count()):
                a = self.frame.itemData(k)
                if a is not None and cam.frame_aspect is not None \
                        and abs(a - cam.frame_aspect) < 1e-6:
                    i = k
            self.frame.setCurrentIndex(i)
        finally:
            self._syncing = False

    # ---- Edits ----------------------------------------------------------------
    def _on_projection(self, _i=None) -> None:
        if self._syncing:
            return
        vp = self._viewport()
        mode = self.projection.currentData()
        if vp is None or mode is None:
            return
        vp.set_projection(mode)
        self._repaint()

    def _on_position(self, _v=None) -> None:
        if self._syncing:
            return
        cam = self._camera()
        if cam is None:
            return
        eye = QVector3D(*(b.value() for b in self.eye))
        target = QVector3D(*(b.value() for b in self.target))
        cam.place(eye, target)
        self._repaint()

    def _set_fov(self, degrees: float) -> None:
        cam = self._camera()
        if cam is None or not cam.perspective:
            return
        lo, hi = getattr(self._window, "FOV_RANGE", (10.0, 120.0))
        cam.fov_deg = float(min(hi, max(lo, degrees)))
        self._repaint()

    def _on_preset(self, _i=None) -> None:
        if self._syncing:
            return
        mm = self.preset.currentData()
        if mm is not None:
            self._set_fov(fov_from_focal(mm))

    def _on_focal(self, _v=None) -> None:
        if not self._syncing:
            self._set_fov(fov_from_focal(self.focal.value()))

    def _on_fov(self, _v=None) -> None:
        if not self._syncing:
            self._set_fov(self.fov.value())

    def _on_lens(self, _v=None) -> None:
        if self._syncing:
            return
        cam = self._camera()
        if cam is None:
            return
        raw = {"shift_x": self.shift_x.value() / 100.0,
               "shift_y": self.shift_y.value() / 100.0,
               "roll_deg": self.roll.value(),
               "frame_aspect": self.frame.currentData()}
        if self.near_on.isChecked():
            raw["clip_near"] = self.near.value()
        if self.far_on.isChecked():
            raw["clip_far"] = self.far.value()
        cam.apply_lens(raw)
        self._repaint()

    def _on_reset(self) -> None:
        cam = self._camera()
        if cam is None:
            return
        cam.reset_lens()
        self._repaint()
