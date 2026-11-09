# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The bevel's panel: every setting of Fillet 3D at hand while the tool
is active — edges or vertices, how the size is read, the size, the
segments, the profile (with an editor to draw it, see
:mod:`views.bevel_profile_editor`) and how box corners close — floating in the lower-left corner of the
view. Each change redraws the live preview; Apply (or a click on the
model, or Enter) rounds. The keys keep working beside it (a Ctrl tap,
«Ns», «0.3p»), and the panel follows them.

It is a child of the viewport, so it never covers the rest of the
window; it eats its own clicks and keys so none of them reach the model
behind it, and gives the keyboard back to the view once a field is
done, so typing a measure in the value box works as before."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDoubleSpinBox,
                               QFormLayout, QFrame, QHBoxLayout, QLineEdit,
                               QPushButton, QSpinBox, QWidget)

from core import bevel_profiles
from core.fillet import CIRCULAR

from core.i18n import tr
from core.units import fmt_len_fine

#: Gap between the panel and the view's lower-left corner (px).
MARGIN = 12
#: The profile each named shape stands for; «custom» keeps the number.
#: The drawn outlines (steps, mouldings) are added from the tool.
SHAPES = (("round", "Round", CIRCULAR), ("flat", "Flat (chamfer)", 0.25),
          ("custom", "Curve (value 0–1)", None))


class BevelPanel(QFrame):
    def __init__(self, viewport, tool) -> None:
        super().__init__(viewport)
        self._viewport = viewport
        self.tool = tool
        self.setObjectName("bevelPanel")
        self.setFrameShape(QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        self.setCursor(Qt.ArrowCursor)
        form = QFormLayout(self)
        form.setContentsMargins(8, 6, 8, 6)
        form.setSpacing(4)

        self.affect = QComboBox()
        self.affect.addItem(tr("Edges"), "edges")
        self.affect.addItem(tr("Vertices"), "vertices")
        self.affect.setFocusPolicy(Qt.NoFocus)
        self.affect.activated.connect(self._affect_picked)
        form.addRow(tr("Affect"), self.affect)

        self.measure = QComboBox()
        for key, label in tool._MEASURES:
            self.measure.addItem(tr(label), key)
        self.measure.setFocusPolicy(Qt.NoFocus)
        self.measure.activated.connect(self._measure_picked)
        form.addRow(tr("Size as"), self.measure)

        self.amount = QLineEdit()
        self.amount.editingFinished.connect(self._amount_typed)
        form.addRow(tr("Amount"), self.amount)

        self.segments = QSpinBox()
        self.segments.setRange(1, 64)
        self.segments.valueChanged.connect(self._segments_changed)
        self.segments.editingFinished.connect(self._done)
        form.addRow(tr("Segments"), self.segments)

        self.shape = QComboBox()
        for key, label, _value in SHAPES:
            self.shape.addItem(tr(label), key)
        self.shape.insertSeparator(self.shape.count())
        for key, label in tool._SHAPES:
            self.shape.addItem(tr(label), key)
        self.shape.addItem(tr("Custom (draw)"), "drawn")
        self.shape.setFocusPolicy(Qt.NoFocus)
        self.shape.activated.connect(self._shape_picked)
        form.addRow(tr("Profile"), self.shape)

        # The number behind the shape; typed only for a custom one.
        self.profile = QDoubleSpinBox()
        self.profile.setRange(0.01, 0.99)
        self.profile.setDecimals(2)
        self.profile.setSingleStep(0.05)
        self.profile.valueChanged.connect(self._profile_changed)
        self.profile.editingFinished.connect(self._done)
        form.addRow(tr("Profile value"), self.profile)
        self._custom = False

        # Any drawn outline — a preset or the user's — shows here, editable;
        # touching a preset makes it the user's own.
        from views.bevel_profile_editor import ProfileEditor
        self.editor = ProfileEditor(self)
        self.editor.edited.connect(self._outline_edited)
        form.addRow(self.editor)
        # The kind of point a double-click adds.
        self.point_kind = QWidget(self)
        row = QHBoxLayout(self.point_kind)
        row.setContentsMargins(0, 0, 0, 0)
        self.smooth_point = QPushButton("● " + tr("Smooth point"))
        self.corner_point = QPushButton("■ " + tr("Corner point"))
        kinds = QButtonGroup(self.point_kind)
        for b in (self.smooth_point, self.corner_point):
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            kinds.addButton(b)
            row.addWidget(b)
        self.smooth_point.setChecked(True)
        self.smooth_point.toggled.connect(self._point_kind_picked)
        form.addRow(self.point_kind)

        self.corners = QComboBox()
        self.corners.addItem(tr("Fill (triangle / cap)"), "round")
        self.corners.addItem(tr("No fill (notch)"), "cut")
        self.corners.setFocusPolicy(Qt.NoFocus)
        self.corners.activated.connect(self._corners_picked)
        form.addRow(tr("Corners"), self.corners)

        self.apply = QPushButton(tr("Apply"))
        self.apply.setFocusPolicy(Qt.NoFocus)
        self.apply.clicked.connect(self._apply_clicked)
        form.addRow(self.apply)

        self._syncing = False
        self._follow = _FollowResize(self)
        viewport.installEventFilter(self._follow)
        self.sync()

    # ---- Showing ------------------------------------------------------------
    def place(self) -> None:
        """Lower-left corner of the view."""
        self.adjustSize()
        h = self._viewport.height()
        self.move(MARGIN, max(MARGIN, h - self.height() - MARGIN))

    def show_for(self, tool) -> None:
        self.tool = tool
        self.sync()
        self.place()
        self.show()
        self.raise_()

    def sync(self) -> None:
        """Show the tool's current settings (they change from the keys and
        the cursor too)."""
        cls = type(self.tool)
        self._syncing = True
        try:
            i = self.affect.findData(cls.affect)
            if i >= 0:
                self.affect.setCurrentIndex(i)
            edges = cls.affect != "vertices"
            # Bevelling corners the size is a distance along the edges and
            # there is no box corner to close: those two do not apply.
            self.measure.setEnabled(edges)
            self.corners.setEnabled(edges)
            i = self.measure.findData(cls.measure)
            if i >= 0:
                self.measure.setCurrentIndex(i)
            if not self.amount.hasFocus():
                self.amount.setText(fmt_len_fine(cls.radius))
            self.segments.setValue(int(cls.segments))
            self.profile.setValue(float(cls.profile))
            if isinstance(cls.shape, tuple):
                shape = "drawn"
            elif cls.shape is not None:
                shape = cls.shape
            else:
                shape = "custom" if self._custom else self._shape_of(cls.profile)
            self.shape.setCurrentIndex(self.shape.findData(shape))
            self.profile.setEnabled(shape == "custom")
            self.corners.setEnabled(edges)
            drawn = cls.shape is not None and edges
            self.editor.setVisible(drawn)
            self.point_kind.setVisible(drawn)
            if drawn and self.editor._drag is None:
                self.editor.set_points(
                    bevel_profiles.controls(cls.shape, cls.segments), cls.segments)
            i = self.corners.findData(cls.corners)
            if i >= 0:
                self.corners.setCurrentIndex(i)
        finally:
            self._syncing = False

    # ---- Edits ----------------------------------------------------------------
    @staticmethod
    def _shape_of(profile: float) -> str:
        for key, _label, value in SHAPES:
            if value is not None and abs(profile - value) < 1e-9:
                return key
        return "custom"

    def _shape_picked(self, _index: int) -> None:
        key = self.shape.currentData()
        if key == "drawn":
            cls = type(self.tool)
            self._custom = False
            self.tool.set_shape(self._viewport, tuple(
                bevel_profiles.controls(cls.shape, cls.segments)))
            self.sync()
            self.place()
            return
        if key in dict(self.tool._SHAPES):
            self._custom = False
            self.tool.set_shape(self._viewport, key)
            self.sync()
            self.place()
            return
        value = dict((k, v) for k, _l, v in SHAPES).get(key)
        self._custom = key == "custom"
        if value is not None:
            self.tool.on_profile_value(self._viewport, value)
        else:
            self.tool.set_shape(self._viewport, None)
        self.sync()
        self.place()

    def _point_kind_picked(self, smooth: bool) -> None:
        self.editor.new_smooth = smooth

    def _outline_edited(self, points) -> None:
        self.tool.set_shape(self._viewport, tuple(points))
        self.sync()

    def _affect_picked(self, _index: int) -> None:
        self.tool.set_affect(self._viewport, self.affect.currentData())

    def _measure_picked(self, _index: int) -> None:
        self.tool.set_measure(self._viewport, self.measure.currentData())

    def _amount_typed(self) -> None:
        if self._syncing:
            return
        from views.viewport import Viewport
        value = Viewport._parse_value_buffer(self.amount.text())
        if isinstance(value, (int, float)) and value > 0:
            self.tool.set_size(self._viewport, float(value))
        self.sync()
        self._done()

    def _segments_changed(self, n: int) -> None:
        if not self._syncing:
            self.tool.on_segments_value(self._viewport, n)

    def _profile_changed(self, p: float) -> None:
        if not self._syncing:
            self.tool.on_profile_value(self._viewport, p)

    def _corners_picked(self, _index: int) -> None:
        self.tool.set_corners(self._viewport, self.corners.currentData())

    def _apply_clicked(self) -> None:
        self.tool.apply_from_panel(self._viewport)

    def _done(self) -> None:
        """A field is finished: the keyboard goes back to the view."""
        self._viewport.setFocus(Qt.OtherFocusReason)

    # ---- Nothing gets through to the model --------------------------------------
    def mousePressEvent(self, ev) -> None:
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:
        ev.accept()

    def mouseDoubleClickEvent(self, ev) -> None:
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        ev.accept()

    def wheelEvent(self, ev) -> None:
        ev.accept()

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape:
            self.sync()
            self._done()
        ev.accept()


class _FollowResize(QObject):
    """Keeps the panel in its corner when the view changes size."""

    def __init__(self, panel: BevelPanel) -> None:
        super().__init__(panel)
        self._panel = panel

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.Resize and not self._panel.isHidden():
            self._panel.place()
        return False
