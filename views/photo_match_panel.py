# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Camera from Photo panel: everything the tool does, as buttons.

A tab of its own among the side tray's panels, there only while the lines
of a photo are being laid (Camera ▸ Camera from Photo): it comes in front
when that starts and goes when it ends — Done, Cancel, another tool, or an
orbit away from the photo — and the tab that was in front comes back
(``MainWindow.show_photo_dock``). Nothing here is only here: the keys and
the right-click menu over the photo do the same, so neither has to be
remembered.

- Lines: where they start for the kind of photo, Reset, Swap red and green,
  the length the blue handle stands for, the photo's own focal length.
- Display: the model shown or hidden, the photo in front of it and how
  opaque.
- Grid: lines on the axis planes every so many metres, to judge the fit.

What it shows comes from the tool, and every change goes through the
tool's own methods (``tools.photo_match.PhotoMatchTool``): the panel keeps
no state of its own.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from core import photo_match as PM
from core.i18n import tr


class PhotoMatchPanel(QWidget):
    def __init__(self, window) -> None:
        super().__init__(window)
        from tools.photo_match import GRID_PLANES, STARTS
        self._window = window
        self.tool = None
        self.viewport = None
        self._syncing = False

        root = QVBoxLayout(self)
        self.scene_label = QLabel()
        self.scene_label.setStyleSheet("font-weight: bold;")
        root.addWidget(self.scene_label)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        root.addWidget(self.info)

        # ---- Lines ----
        lines = QGroupBox(tr("Lines"))
        form = QFormLayout(lines)
        row = QHBoxLayout()
        self.start = QComboBox()
        for key, label in STARTS:
            self.start.addItem(tr(label), key)
        self.start.setToolTip(tr(
            "The kind of photo: the lines start where its edges usually "
            "are."))
        row.addWidget(self.start, 1)
        self.reset = QPushButton(tr("Reset lines"))
        self.reset.setToolTip(tr(
            "Put the lines back where they start for this kind of photo."))
        self.reset.clicked.connect(self._on_reset)
        row.addWidget(self.reset)
        form.addRow(tr("Start from:"), row)
        self.swap = QPushButton(tr("Swap red and green"))
        self.swap.setToolTip(tr(
            "For lines laid the wrong way round: the red ones become green "
            "and the green ones red."))
        self.swap.clicked.connect(self._on_swap)
        form.addRow("", self.swap)
        self.length = QLineEdit()
        self.length.setToolTip(tr(
            "The real length from the origin to the blue handle — a "
            "storey, a door. It sets the scale; it can also be typed "
            "straight away, over the photo."))
        self.length.editingFinished.connect(self._on_length)
        form.addRow(tr("Blue length:"), self.length)
        self.exif = QCheckBox(tr("Use the photo's focal length"))
        self.exif.setToolTip(tr(
            "Keep the focal length the camera wrote in the photo (F) "
            "instead of reading it from the lines."))
        self.exif.toggled.connect(self._on_exif)
        form.addRow("", self.exif)
        root.addWidget(lines)

        # ---- Display ----
        show = QGroupBox(tr("Display"))
        form = QFormLayout(show)
        self.model = QCheckBox(tr("Show model"))
        self.model.toggled.connect(self._on_model)
        form.addRow("", self.model)
        self.front = QCheckBox(tr("Photo in front of the model"))
        self.front.toggled.connect(self._on_front)
        form.addRow("", self.front)
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setToolTip(tr("How opaque the photo in front is."))
        self.opacity.valueChanged.connect(self._on_opacity)
        form.addRow(tr("Opacity:"), self.opacity)
        root.addWidget(show)

        # ---- Grid ----
        grid = QGroupBox(tr("Grid"))
        form = QFormLayout(grid)
        self.planes = {}
        for key, label in GRID_PLANES:
            box = QCheckBox(tr(label))
            box.toggled.connect(lambda on, k=key: self._on_plane(k, on))
            self.planes[key] = box
            form.addRow("", box)
        self.spacing = QLineEdit()
        self.spacing.editingFinished.connect(self._on_spacing)
        form.addRow(tr("Spacing:"), self.spacing)
        root.addWidget(grid)

        hint = QLabel(tr(
            "Keys: Enter = done, Esc = cancel, F = photo's focal length. "
            "Right-click over the photo for this menu. Orbiting leaves the "
            "photo; its scene tab brings it back."))
        hint.setWordWrap(True)
        # Smaller, in the text's own colour: a dimmed one did not read on
        # the dark themes.
        small = hint.font()
        small.setPointSizeF(max(small.pointSizeF() * 0.9, 7.0))
        hint.setFont(small)
        root.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel = QPushButton(tr("Cancel"))
        self.cancel.clicked.connect(self._on_cancel)
        buttons.addWidget(self.cancel)
        self.done = QPushButton(tr("Done"))
        self.done.setDefault(False)
        self.done.setAutoDefault(False)
        self.done.clicked.connect(self._on_done)
        buttons.addWidget(self.done)
        root.addLayout(buttons)
        root.addStretch(1)

    # ---- Binding ----------------------------------------------------------------
    def bind(self, tool, viewport) -> None:
        """Show the panel's tab for ``tool`` (the lines being laid)."""
        self.tool = tool
        self.viewport = viewport
        tool.on_change = self.refresh
        tool.on_finish = self.unbind
        self.refresh()
        show = getattr(self._window, "show_photo_dock", None)
        if callable(show):
            show()
        viewport.setFocus(Qt.OtherFocusReason)

    def unbind(self) -> None:
        """The tool ended: the panel's tab goes with it."""
        tool = self.tool
        if tool is not None:
            tool.on_change = tool.on_finish = None
        self.tool = None
        hide = getattr(self._window, "hide_photo_dock", None)
        if callable(hide):
            hide()

    # ---- Showing ---------------------------------------------------------------------
    def refresh(self) -> None:
        tool = self.tool
        if tool is None:
            return
        from core.units import fmt_len
        pm = tool.view.photo
        self._syncing = True
        try:
            self.scene_label.setText(tool.view.name)
            sol = tool.result if isinstance(tool.result, PM.Solution) \
                else None
            rows = []
            for text, warn in tool.info_lines(sol):
                safe = (text.replace("&", "&amp;").replace("<", "&lt;")
                        .replace(">", "&gt;"))
                rows.append(f'<span style="color:#d0503c">{safe}</span>'
                            if warn else safe)
            if pm.exif_model:
                rows.append(tr("Camera: {model}", model=pm.exif_model))
            self.info.setText("<br>".join(rows))
            if not self.length.hasFocus():
                self.length.setText(fmt_len(pm.scale_length))
            self.exif.setEnabled(bool(pm.exif_focal_35))
            self.exif.setChecked(bool(pm.use_exif_focal
                                      and pm.exif_focal_35))
            self.model.setChecked(bool(pm.show_model))
            self.front.setChecked(bool(pm.photo_front))
            self.front.setEnabled(bool(pm.show_model))
            self.opacity.setValue(int(round(pm.photo_opacity * 100)))
            self.opacity.setEnabled(bool(pm.show_model and pm.photo_front))
            planes = type(tool).grid_planes
            for key, box in self.planes.items():
                box.setChecked(key in planes)
            if not self.spacing.hasFocus():
                self.spacing.setText(fmt_len(type(tool).grid_spacing))
            self.spacing.setEnabled(bool(planes))
        finally:
            self._syncing = False

    # ---- Changes -----------------------------------------------------------------------
    def _act(self, name, *args, keys_back: bool = True):
        """Run the tool's ``name``. The keyboard then goes back to the
        model (Enter, Esc, F, a typed length), except from a field."""
        if self._syncing or self.tool is None:
            return None
        vp = self.viewport
        result = getattr(self.tool, name)(vp, *args)
        if keys_back and vp is not None:
            vp.setFocus(Qt.OtherFocusReason)
        return result

    def _on_reset(self) -> None:
        self._act("reset_lines", self.start.currentData())

    def _on_swap(self) -> None:
        self._act("swap_axes")

    def _on_length(self) -> None:
        from core.units import parse_length_field
        value = parse_length_field(self.length.text())
        if value is None or not self._act("set_length", value,
                                          keys_back=False):
            self.length.clearFocus()
            self.refresh()

    def _on_exif(self, on: bool) -> None:
        if self._act("set_exif_focal", on) is False:
            self.refresh()

    def _on_model(self, on: bool) -> None:
        self._act("set_show_model", on)

    def _on_front(self, on: bool) -> None:
        self._act("set_photo_front", on)

    def _on_opacity(self, value: int) -> None:
        self._act("set_photo_opacity", value / 100.0, keys_back=False)

    def _on_plane(self, key: str, on: bool) -> None:
        self._act("set_grid_plane", key, on)

    def _on_spacing(self) -> None:
        from core.units import parse_length_field
        value = parse_length_field(self.spacing.text())
        if value is None or not self._act("set_grid_spacing", value,
                                          keys_back=False):
            self.refresh()

    def _on_done(self) -> None:
        self._act("done_ok")

    def _on_cancel(self) -> None:
        self._act("cancel")
