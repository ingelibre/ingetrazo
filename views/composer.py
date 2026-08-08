# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheet composer window — QGIS-composer-shaped (docs/composer-plan.md).

C2: several model-view frames per sheet, text / image / title-block items,
drag with snapping (page edges, margins, centre, other items), corner
resize, a composition manager (N sheets per document, persisted in the
.igz), and composer-scoped undo. The canvas is a ``QGraphicsScene`` whose
units are paper MILLIMETRES; every item paints itself in mm-space through
the same code the PDF export uses, so screen and paper always agree.
"""
from __future__ import annotations

import datetime
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QKeySequence,
                           QPageLayout, QPageSize, QPainter, QPdfWriter,
                           QPen, QShortcut)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGraphicsItem,
                               QGraphicsScene, QGraphicsView, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from core.composition import (COMMON_SCALES, PAPER_SIZES_MM, RENDER_DPI,
                              AddItemCommand, BarraEscala, Cajetin,
                              ComposerHistory, Composicion, EditItemCommand,
                              ImagenItem, MarcoVista, RemoveItemCommand,
                              TextoItem, apply_frame_camera, snap_mm)
from core.i18n import tr

PT_TO_MM = 25.4 / 72.0
_HANDLE_MM = 3.0          # corner resize handle, in paper mm
_SNAP_MM = 2.0

#: Standard views offered as frame sources (label key → camera.set_view key).
_STD_VIEWS = (
    ("Top (plan)", "top"),
    ("Front", "front"),
    ("Back", "back"),
    ("Left", "left"),
    ("Right", "right"),
    ("Isometric", "iso"),
)


# ── mm-space painters (shared by canvas and PDF) ────────────────────────────

def _draw_text_mm(painter: QPainter, rect: QRectF, text: str, size_mm: float,
                  bold: bool = False, align=Qt.AlignLeft | Qt.AlignTop,
                  color: QColor = QColor(30, 36, 44)) -> None:
    """Draw *text* inside *rect* (mm units) at ``size_mm`` tall. Fonts don't
    take fractional-mm sizes, so set a large pixel size and scale the
    painter down — crisp at any output DPI."""
    if not text:
        return
    painter.save()
    font = QFont("Sans Serif")
    font.setPixelSize(100)
    font.setBold(bold)
    painter.setFont(font)
    painter.setPen(color)
    s = size_mm / 100.0 * 0.75   # pixelSize≈cap height/0.75 — visual match
    painter.scale(s, s)
    painter.drawText(QRectF(rect.x() / s, rect.y() / s,
                            rect.width() / s, rect.height() / s),
                     int(align | Qt.TextWordWrap), text)
    painter.restore()


def frame_title_text(frame: MarcoVista) -> str:
    """The automatic title: view name — scale («Planta — 1:100»)."""
    key = frame.view_key
    if key.startswith("scene:"):
        name = key[6:]
    elif key.startswith("std:"):
        name = {k: tr(lbl) for lbl, k in _STD_VIEWS}.get(key[4:], key[4:])
    else:
        name = tr("View")
    return f"{name} — 1:{frame.scale_n:g}"


def paint_frame_mm(painter: QPainter, frame: MarcoVista,
                   image: Optional[QImage]) -> None:
    r = QRectF(0, 0, frame.w_mm, frame.h_mm)
    if image is not None and not image.isNull():
        painter.drawImage(r, image)
    else:
        painter.fillRect(r, QColor(245, 246, 248))
        _draw_text_mm(painter, r.adjusted(2, 2, -2, -2),
                      tr("Update the view to render"), 3.5,
                      color=QColor(140, 150, 160))
    pen = QPen(QColor(40, 46, 54))
    pen.setWidthF(0.3)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(r)
    if frame.show_title:
        _draw_text_mm(painter,
                      QRectF(0, frame.h_mm + 1.2, frame.w_mm, 8.0),
                      frame_title_text(frame), 4.2, bold=True,
                      align=Qt.AlignHCenter | Qt.AlignTop)


def paint_scalebar_mm(painter: QPainter, sb: BarraEscala) -> None:
    """Alternating black/white boxes + metre labels + the 1:N caption."""
    seg_mm = sb.segment_mm()
    seg_m = sb.segment_m()
    bar_h = 2.4
    pen = QPen(QColor(30, 36, 44))
    pen.setWidthF(0.25)
    painter.setPen(pen)
    for i in range(sb.segments):
        r = QRectF(i * seg_mm, 0, seg_mm, bar_h)
        painter.setBrush(QBrush(QColor(30, 36, 44)) if i % 2 == 0
                         else QBrush(QColor(255, 255, 255)))
        painter.drawRect(r)
    for i in range(sb.segments + 1):
        v = i * seg_m
        label = f"{v:g}"
        _draw_text_mm(painter,
                      QRectF(i * seg_mm - 12, bar_h + 0.8, 24, 4),
                      label, 2.6, align=Qt.AlignHCenter | Qt.AlignTop)
    _draw_text_mm(painter,
                  QRectF(0, bar_h + 4.6, sb.w_mm, 4),
                  tr("metres — scale 1:{n}", n=f"{sb.scale_n:g}"), 2.6,
                  align=Qt.AlignHCenter | Qt.AlignTop)


def paint_text_mm(painter: QPainter, item: TextoItem) -> None:
    size_mm = item.size_pt * PT_TO_MM
    rect = QRectF(0, 0, item.w_mm, size_mm * 1.35 * (item.text.count("\n") + 3))
    _draw_text_mm(painter, rect, item.text, size_mm, item.bold)


def paint_image_mm(painter: QPainter, item: ImagenItem,
                   image: Optional[QImage]) -> None:
    r = QRectF(0, 0, item.w_mm, item.h_mm)
    if image is not None and not image.isNull():
        painter.drawImage(r, image)
    else:
        painter.fillRect(r, QColor(240, 240, 242))
        pen = QPen(QColor(170, 176, 184))
        pen.setWidthF(0.25)
        painter.setPen(pen)
        painter.drawRect(r)
        painter.drawLine(r.topLeft(), r.bottomRight())
        painter.drawLine(r.topRight(), r.bottomLeft())


def paint_cajetin_mm(painter: QPainter, c: Cajetin) -> None:
    r = QRectF(0, 0, c.w_mm, c.h_mm)
    painter.fillRect(r, QColor(255, 255, 255))
    heavy = QPen(QColor(30, 36, 44))
    heavy.setWidthF(0.5)
    light = QPen(QColor(30, 36, 44))
    light.setWidthF(0.2)
    rows = len(Cajetin.FIELDS)
    row_h = c.h_mm / rows
    label_w = min(28.0, c.w_mm * 0.3)
    painter.setPen(light)
    for i in range(1, rows):
        y = i * row_h
        painter.drawLine(QPointF(0, y), QPointF(c.w_mm, y))
    painter.drawLine(QPointF(label_w, 0), QPointF(label_w, c.h_mm))
    for i, (label, attr) in enumerate(Cajetin.FIELDS):
        y = i * row_h
        _draw_text_mm(painter,
                      QRectF(1.2, y + row_h * 0.18, label_w - 2, row_h),
                      label, row_h * 0.38, bold=True,
                      color=QColor(90, 98, 108))
        _draw_text_mm(painter,
                      QRectF(label_w + 1.5, y + row_h * 0.12,
                             c.w_mm - label_w - 3, row_h),
                      getattr(c, attr), row_h * 0.52)
    painter.setPen(heavy)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(r)


# ── Canvas items ────────────────────────────────────────────────────────────

class _SheetItem(QGraphicsItem):
    """A sheet item on the canvas: movable, snappable, corner-resizable.
    Wraps one dataclass (``model`` with x_mm/y_mm and usually w_mm/h_mm)."""

    RESIZABLE = True

    def __init__(self, composer: "ComposerWindow", model) -> None:
        super().__init__()
        self.composer = composer
        self.model = model
        self.setPos(model.x_mm, model.y_mm)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self._press_state: Optional[dict] = None
        self._resizing = False

    # -- geometry ------------------------------------------------------------
    def size_mm(self) -> tuple[float, float]:
        return self.model.w_mm, getattr(self.model, "h_mm", 12.0)

    def boundingRect(self) -> QRectF:
        w, h = self.size_mm()
        pad = _HANDLE_MM
        return QRectF(-0.5, -0.5, w + pad + 0.5, h + pad + 0.5)

    def _paint_selection(self, painter: QPainter) -> None:
        if not self.isSelected():
            return
        w, h = self.size_mm()
        pen = QPen(QColor(58, 110, 165), 0.35, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(0, 0, w, h))
        if self.RESIZABLE:
            painter.setBrush(QBrush(QColor(58, 110, 165)))
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(w - _HANDLE_MM / 2, h - _HANDLE_MM / 2,
                                    _HANDLE_MM, _HANDLE_MM))

    # -- interaction ---------------------------------------------------------
    def _on_resize_handle(self, pos: QPointF) -> bool:
        w, h = self.size_mm()
        return (self.RESIZABLE
                and abs(pos.x() - w) <= _HANDLE_MM
                and abs(pos.y() - h) <= _HANDLE_MM)

    def mousePressEvent(self, event) -> None:
        self._press_state = {
            k: getattr(self.model, k)
            for k in ("x_mm", "y_mm", "w_mm", "h_mm")
            if hasattr(self.model, k)}
        self._resizing = self._on_resize_handle(event.pos())
        if self._resizing:
            event.accept()
            self.setSelected(True)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resizing:
            w = max(10.0, event.pos().x())
            h = max(6.0, event.pos().y())
            targets_x = self.composer.snap_targets_x(exclude=self)
            targets_y = self.composer.snap_targets_y(exclude=self)
            w = snap_mm(self.pos().x() + w, targets_x, _SNAP_MM) - self.pos().x()
            h = snap_mm(self.pos().y() + h, targets_y, _SNAP_MM) - self.pos().y()
            self.prepareGeometryChange()
            self.model.w_mm = w
            if hasattr(self.model, "h_mm"):
                self.model.h_mm = h
            self.composer.on_item_geometry(self)
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_resizing = self._resizing
        self._resizing = False
        super().mouseReleaseEvent(event)
        if self._press_state is None:
            return
        current = {k: getattr(self.model, k) for k in self._press_state}
        if current != self._press_state:
            self.composer.push_geometry_edit(self.model, current,
                                             self._press_state)
        self._press_state = None
        if was_resizing:
            self.composer.on_item_geometry(self, final=True)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            w, h = self.size_mm()
            x = snap_mm(value.x(), self.composer.snap_targets_x(exclude=self),
                        _SNAP_MM)
            x = snap_mm(x + w, self.composer.snap_targets_x(exclude=self),
                        _SNAP_MM) - w
            y = snap_mm(value.y(), self.composer.snap_targets_y(exclude=self),
                        _SNAP_MM)
            y = snap_mm(y + h, self.composer.snap_targets_y(exclude=self),
                        _SNAP_MM) - h
            return QPointF(x, y)
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.model.x_mm = self.pos().x()
            self.model.y_mm = self.pos().y()
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.composer.on_selection_changed()
        return super().itemChange(change, value)


class FrameItem(_SheetItem):
    def boundingRect(self) -> QRectF:
        r = super().boundingRect()
        if self.model.show_title:
            r.setHeight(r.height() + 9.0)
        return r

    def paint(self, painter, option, widget=None) -> None:
        paint_frame_mm(painter, self.model,
                       self.composer.render_cache.get(id(self.model)))
        self._paint_selection(painter)


class ScaleBarItem(_SheetItem):
    RESIZABLE = False

    def boundingRect(self) -> QRectF:
        return QRectF(-12.5, -0.5, self.model.w_mm + 25.0, 12.0)

    def paint(self, painter, option, widget=None) -> None:
        paint_scalebar_mm(painter, self.model)
        self._paint_selection(painter)


class TextItem(_SheetItem):
    RESIZABLE = True

    def size_mm(self):
        size_mm = self.model.size_pt * PT_TO_MM
        lines = self.model.text.count("\n") + 1
        return self.model.w_mm, max(6.0, size_mm * 1.4 * lines)

    def paint(self, painter, option, widget=None) -> None:
        paint_text_mm(painter, self.model)
        self._paint_selection(painter)


class ImageItem(_SheetItem):
    def paint(self, painter, option, widget=None) -> None:
        paint_image_mm(painter, self.model,
                       self.composer.image_cache(self.model.path))
        self._paint_selection(painter)


class CajetinItem(_SheetItem):
    def paint(self, painter, option, widget=None) -> None:
        paint_cajetin_mm(painter, self.model)
        self._paint_selection(painter)


# ── The window ──────────────────────────────────────────────────────────────

class ComposerWindow(QMainWindow):
    """Page canvas on the left, composition manager + properties on the
    right. Compositions live in ``scene.compositions`` and persist in the
    .igz; every mutation goes through the composer's own undo history."""

    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self.setWindowFlag(Qt.Window, True)
        self._window = main_window
        self.render_cache: dict[int, QImage] = {}
        self._images: dict[str, QImage] = {}
        self._updating = False
        self.history = ComposerHistory(on_change=self._on_history_change)

        scene = main_window.viewport.scene
        if not scene.compositions:
            comp = Composicion()
            comp.frames.append(comp.default_frame())
            scene.compositions.append(comp)
        self.comp: Composicion = scene.compositions[0]

        self.setWindowTitle(tr("Sheet composer"))
        self.resize(1180, 800)
        self.canvas = QGraphicsScene(self)
        view = QGraphicsView(self.canvas)
        view.setRenderHints(QPainter.Antialiasing
                            | QPainter.SmoothPixmapTransform)
        view.setBackgroundBrush(QColor(70, 76, 84))
        self._view = view

        panel = self._build_panel()
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(view, 1)
        lay.addWidget(panel, 0)
        self.setCentralWidget(central)

        QShortcut(QKeySequence.Undo, self, activated=self._on_undo)
        QShortcut(QKeySequence.Redo, self, activated=self._on_redo)
        QShortcut(QKeySequence.Delete, self, activated=self._on_delete_item)

        self._rebuild_canvas()

    # ---- panel ---------------------------------------------------------------
    def _build_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(280)
        outer = QVBoxLayout(panel)

        # Composition manager
        mgr = QHBoxLayout()
        self.comp_combo = QComboBox()
        self.comp_combo.setEditable(True)
        self.comp_combo.setInsertPolicy(QComboBox.NoInsert)
        self.comp_combo.setToolTip(tr("Type to rename the sheet"))
        self._reload_comp_combo()
        self.comp_combo.currentIndexChanged.connect(self._on_comp_switched)
        self.comp_combo.lineEdit().editingFinished.connect(self._on_comp_rename)
        mgr.addWidget(self.comp_combo, 1)
        for text, tip, slot in ((tr("+"), tr("New sheet"), self._on_comp_add),
                                (tr("⧉"), tr("Duplicate sheet"),
                                 self._on_comp_dup),
                                (tr("−"), tr("Delete sheet"),
                                 self._on_comp_del)):
            b = QPushButton(text)
            b.setFixedWidth(28)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            mgr.addWidget(b)
        outer.addLayout(mgr)

        # Page
        form = QFormLayout()
        self.paper_combo = QComboBox()
        self.paper_combo.addItems(list(PAPER_SIZES_MM))
        self.paper_combo.currentTextChanged.connect(self._on_page_changed)
        form.addRow(tr("Paper"), self.paper_combo)
        self.landscape_check = QCheckBox(tr("Landscape"))
        self.landscape_check.toggled.connect(self._on_page_changed)
        form.addRow("", self.landscape_check)
        outer.addLayout(form)

        # Add-item buttons
        add_row = QHBoxLayout()
        for text, tip, slot in (
                (tr("+ View"), tr("Add a model-view frame"),
                 self._on_add_frame),
                (tr("+ Text"), tr("Add a text block"), self._on_add_text),
                (tr("+ Image"), tr("Add an image"), self._on_add_image),
                (tr("+ Title block"), tr("Add the title block"),
                 self._on_add_cajetin),
                (tr("+ Scale bar"), tr("Add a graphic scale bar"),
                 self._on_add_scalebar)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            add_row.addWidget(b)
        outer.addLayout(add_row)

        # Per-type properties
        self.props = QStackedWidget()
        self.props.addWidget(self._page_none())      # 0: nothing selected
        self.props.addWidget(self._page_frame())     # 1
        self.props.addWidget(self._page_text())      # 2
        self.props.addWidget(self._page_image())     # 3
        self.props.addWidget(self._page_cajetin())   # 4
        self.props.addWidget(self._page_scalebar())  # 5
        outer.addWidget(self.props)

        outer.addStretch(1)

        refresh_btn = QPushButton(tr("Update all views"))
        refresh_btn.clicked.connect(self.refresh_all_frames)
        outer.addWidget(refresh_btn)
        export_btn = QPushButton(tr("Export PDF…"))
        export_btn.clicked.connect(self._on_export_pdf)
        outer.addWidget(export_btn)
        return panel

    def _page_none(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        hint = QLabel(tr("Select an item to edit it. Drag to move; the "
                         "corner handle resizes. Items snap to margins "
                         "and to each other."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        lay.addWidget(hint)
        return w

    def _page_frame(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.view_combo = QComboBox()
        self.view_combo.currentIndexChanged.connect(self._on_frame_props)
        form.addRow(tr("View"), self.view_combo)
        self.scale_combo = QComboBox()
        self.scale_combo.setEditable(True)
        self.scale_combo.addItems([f"1:{n}" for n in COMMON_SCALES])
        self.scale_combo.currentTextChanged.connect(self._on_frame_props)
        form.addRow(tr("Scale"), self.scale_combo)
        self.fw_spin = QDoubleSpinBox()
        self.fw_spin.setRange(10.0, 2000.0)
        self.fw_spin.setSuffix(" mm")
        self.fw_spin.valueChanged.connect(self._on_frame_props)
        form.addRow(tr("Frame width"), self.fw_spin)
        self.fh_spin = QDoubleSpinBox()
        self.fh_spin.setRange(10.0, 2000.0)
        self.fh_spin.setSuffix(" mm")
        self.fh_spin.valueChanged.connect(self._on_frame_props)
        form.addRow(tr("Frame height"), self.fh_spin)
        self.style_combo = QComboBox()
        for label, key in ((tr("Shaded"), "sombreado"),
                           (tr("Technical (white + edges)"), "tecnico"),
                           (tr("Lines only"), "lineas")):
            self.style_combo.addItem(label, key)
        self.style_combo.currentIndexChanged.connect(self._on_frame_props)
        form.addRow(tr("Style"), self.style_combo)
        self.title_check = QCheckBox(tr("Title under the frame"))
        self.title_check.toggled.connect(self._on_frame_props)
        form.addRow("", self.title_check)
        btn = QPushButton(tr("Update view"))
        btn.clicked.connect(self._on_refresh_selected_frame)
        form.addRow(btn)
        return w

    def _page_text(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFixedHeight(70)
        self.text_edit.textChanged.connect(self._on_text_props)
        form.addRow(tr("Text"), self.text_edit)
        self.text_size = QDoubleSpinBox()
        self.text_size.setRange(4.0, 96.0)
        self.text_size.setSuffix(" pt")
        self.text_size.valueChanged.connect(self._on_text_props)
        form.addRow(tr("Size"), self.text_size)
        self.text_bold = QCheckBox(tr("Bold"))
        self.text_bold.toggled.connect(self._on_text_props)
        form.addRow("", self.text_bold)
        return w

    def _page_image(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.img_label = QLabel("—")
        self.img_label.setWordWrap(True)
        form.addRow(tr("File"), self.img_label)
        btn = QPushButton(tr("Choose image…"))
        btn.clicked.connect(self._on_pick_image)
        form.addRow(btn)
        return w

    def _page_cajetin(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.caj_edits: dict[str, QLineEdit] = {}
        for label, attr in Cajetin.FIELDS:
            edit = QLineEdit()
            edit.editingFinished.connect(self._on_cajetin_props)
            self.caj_edits[attr] = edit
            form.addRow(label.capitalize(), edit)
        return w

    def _page_scalebar(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.sb_scale = QComboBox()
        self.sb_scale.setEditable(True)
        self.sb_scale.addItems([f"1:{n}" for n in COMMON_SCALES])
        self.sb_scale.currentTextChanged.connect(self._on_scalebar_props)
        form.addRow(tr("Scale"), self.sb_scale)
        self.sb_segments = QDoubleSpinBox()
        self.sb_segments.setRange(2, 10)
        self.sb_segments.setDecimals(0)
        self.sb_segments.valueChanged.connect(self._on_scalebar_props)
        form.addRow(tr("Segments"), self.sb_segments)
        return w

    # ---- composition manager -------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def _reload_comp_combo(self) -> None:
        self._updating = True
        self.comp_combo.clear()
        for c in self._scene().compositions:
            self.comp_combo.addItem(c.name)
        self.comp_combo.setCurrentIndex(
            self._scene().compositions.index(self.comp)
            if self.comp in self._scene().compositions else 0)
        self._updating = False

    def _on_comp_switched(self, idx: int) -> None:
        if self._updating or idx < 0:
            return
        comps = self._scene().compositions
        if 0 <= idx < len(comps):
            self.comp = comps[idx]
            self.history = ComposerHistory(on_change=self._on_history_change)
            self._rebuild_canvas()

    def _on_comp_rename(self) -> None:
        if self._updating:
            return
        name = self.comp_combo.currentText().strip()
        if name and name != self.comp.name:
            self.comp.name = name
            self._mark_dirty()
            self._reload_comp_combo()

    def _on_comp_add(self) -> None:
        comps = self._scene().compositions
        comp = Composicion(name=tr("Sheet {n}", n=len(comps) + 1))
        comp.frames.append(comp.default_frame())
        comps.append(comp)
        self.comp = comp
        self._mark_dirty()
        self._reload_comp_combo()
        self._rebuild_canvas()

    def _on_comp_dup(self) -> None:
        comps = self._scene().compositions
        dup = Composicion.from_dict(self.comp.to_dict())
        dup.name = self.comp.name + tr(" (copy)")
        comps.append(dup)
        self.comp = dup
        self._mark_dirty()
        self._reload_comp_combo()
        self._rebuild_canvas()

    def _on_comp_del(self) -> None:
        comps = self._scene().compositions
        if len(comps) <= 1:
            return
        if QMessageBox.question(
                self, tr("Delete sheet"),
                tr("Delete '{name}'?", name=self.comp.name)) \
                != QMessageBox.Yes:
            return
        comps.remove(self.comp)
        self.comp = comps[0]
        self._mark_dirty()
        self._reload_comp_combo()
        self._rebuild_canvas()

    # ---- canvas --------------------------------------------------------------
    def _rebuild_canvas(self) -> None:
        self._updating = True
        self.canvas.clear()
        pw, ph = self.comp.page_size_mm()
        self.canvas.setSceneRect(-20, -20, pw + 40, ph + 40)
        shadow = self.canvas.addRect(2.0, 2.0, pw, ph, QPen(Qt.NoPen),
                                     QBrush(QColor(0, 0, 0, 70)))
        shadow.setZValue(-3)
        page = self.canvas.addRect(0, 0, pw, ph,
                                   QPen(QColor(120, 128, 136), 0.3),
                                   QBrush(QColor(255, 255, 255)))
        page.setZValue(-2)
        m = self.comp.margin_mm
        margin = self.canvas.addRect(m, m, pw - 2 * m, ph - 2 * m,
                                     QPen(QColor(190, 196, 202), 0.2,
                                          Qt.DashLine))
        margin.setZValue(-1)

        for f in self.comp.frames:
            self.canvas.addItem(FrameItem(self, f))
        for t in self.comp.texts:
            self.canvas.addItem(TextItem(self, t))
        for i in self.comp.images:
            self.canvas.addItem(ImageItem(self, i))
        for sb in self.comp.scalebars:
            self.canvas.addItem(ScaleBarItem(self, sb))
        if self.comp.cajetin is not None:
            self.canvas.addItem(CajetinItem(self, self.comp.cajetin))

        self.paper_combo.setCurrentText(self.comp.paper)
        self.landscape_check.setChecked(self.comp.landscape)
        self._updating = False
        self._view.fitInView(self.canvas.sceneRect(), Qt.KeepAspectRatio)
        self.on_selection_changed()

    def _selected_item(self) -> Optional[_SheetItem]:
        for it in self.canvas.selectedItems():
            if isinstance(it, _SheetItem):
                return it
        return None

    def on_selection_changed(self) -> None:
        if self._updating:
            return
        item = self._selected_item()
        self._updating = True
        try:
            if isinstance(item, FrameItem):
                self._reload_view_sources()
                f: MarcoVista = item.model
                idx = self.view_combo.findData(f.view_key)
                self.view_combo.setCurrentIndex(max(idx, 0))
                self.scale_combo.setCurrentText(f"1:{f.scale_n:g}")
                self.fw_spin.setValue(f.w_mm)
                self.fh_spin.setValue(f.h_mm)
                sidx = self.style_combo.findData(f.style)
                self.style_combo.setCurrentIndex(max(sidx, 0))
                self.title_check.setChecked(f.show_title)
                self.props.setCurrentIndex(1)
            elif isinstance(item, TextItem):
                t: TextoItem = item.model
                if self.text_edit.toPlainText() != t.text:
                    self.text_edit.setPlainText(t.text)
                self.text_size.setValue(t.size_pt)
                self.text_bold.setChecked(t.bold)
                self.props.setCurrentIndex(2)
            elif isinstance(item, ImageItem):
                self.img_label.setText(item.model.path or "—")
                self.props.setCurrentIndex(3)
            elif isinstance(item, CajetinItem):
                for attr, edit in self.caj_edits.items():
                    edit.setText(getattr(item.model, attr))
                self.props.setCurrentIndex(4)
            elif isinstance(item, ScaleBarItem):
                self.sb_scale.setCurrentText(f"1:{item.model.scale_n:g}")
                self.sb_segments.setValue(item.model.segments)
                self.props.setCurrentIndex(5)
            else:
                self.props.setCurrentIndex(0)
        finally:
            self._updating = False

    # ---- snapping ------------------------------------------------------------
    def snap_targets_x(self, exclude=None) -> list[float]:
        pw, _ = self.comp.page_size_mm()
        m = self.comp.margin_mm
        out = [0.0, m, pw / 2, pw - m, pw]
        for it in self.canvas.items():
            if isinstance(it, _SheetItem) and it is not exclude:
                w, _h = it.size_mm()
                out += [it.pos().x(), it.pos().x() + w]
        return out

    def snap_targets_y(self, exclude=None) -> list[float]:
        _, ph = self.comp.page_size_mm()
        m = self.comp.margin_mm
        out = [0.0, m, ph / 2, ph - m, ph]
        for it in self.canvas.items():
            if isinstance(it, _SheetItem) and it is not exclude:
                _w, h = it.size_mm()
                out += [it.pos().y(), it.pos().y() + h]
        return out

    # ---- item mutations (all through the composer history) -------------------
    def push_geometry_edit(self, model, after: dict, before: dict) -> None:
        self.history.execute(EditItemCommand(model, after, before))

    def on_item_geometry(self, item: _SheetItem, final: bool = False) -> None:
        if isinstance(item, FrameItem) and final:
            self.render_cache.pop(id(item.model), None)
            item.update()
        if isinstance(item, FrameItem) and not self._updating \
                and item is self._selected_item():
            self._updating = True
            self.fw_spin.setValue(item.model.w_mm)
            self.fh_spin.setValue(item.model.h_mm)
            self._updating = False

    def _on_history_change(self) -> None:
        self._mark_dirty()
        # Commands mutate the models; a rebuild keeps canvas and panel
        # honest. DEFERRED: the change may arrive mid mouse-release, and a
        # synchronous clear would destroy the item still handling the event.
        selected = self._selected_item()
        self._pending_sel = selected.model if selected else None
        QTimer.singleShot(0, self._rebuild_after_change)

    def _rebuild_after_change(self) -> None:
        self._rebuild_canvas()
        if getattr(self, "_pending_sel", None) is not None:
            for it in self.canvas.items():
                if isinstance(it, _SheetItem) and it.model is self._pending_sel:
                    it.setSelected(True)
                    break
        self._pending_sel = None

    def _mark_dirty(self) -> None:
        scene = self._scene()
        scene.version += 1
        if hasattr(self._window, "set_dirty"):
            self._window.set_dirty()

    def _on_undo(self) -> None:
        self.history.undo()

    def _on_redo(self) -> None:
        self.history.redo()

    def _on_delete_item(self) -> None:
        from PySide6.QtWidgets import (QApplication, QAbstractSpinBox,
                                       QLineEdit, QPlainTextEdit)
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QPlainTextEdit, QAbstractSpinBox)) \
                or isinstance(focus, QComboBox):
            return                      # Delete belongs to the text field
        item = self._selected_item()
        if item is None:
            return
        self.history.execute(RemoveItemCommand(self.comp, item.model))

    # ---- add items -----------------------------------------------------------
    def _on_add_frame(self) -> None:
        pw, ph = self.comp.page_size_mm()
        f = MarcoVista(x_mm=self.comp.margin_mm + 5 * len(self.comp.frames),
                       y_mm=self.comp.margin_mm + 5 * len(self.comp.frames),
                       w_mm=min(120.0, pw / 2), h_mm=min(90.0, ph / 2))
        self.history.execute(AddItemCommand(self.comp, f))

    def _on_add_text(self) -> None:
        t = TextoItem(x_mm=self.comp.margin_mm + 4,
                      y_mm=self.comp.margin_mm + 4,
                      text=tr("Text"))
        self.history.execute(AddItemCommand(self.comp, t))

    def _on_add_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Choose image…"), "",
            tr("Images (*.png *.jpg *.jpeg)"))
        if not path:
            return
        img = QImage(path)
        w_mm = 60.0
        h_mm = w_mm * (img.height() / img.width()) if img.width() else 40.0
        self.history.execute(AddItemCommand(self.comp, ImagenItem(
            x_mm=self.comp.margin_mm + 4, y_mm=self.comp.margin_mm + 4,
            w_mm=w_mm, h_mm=h_mm, path=path)))

    def _on_add_scalebar(self) -> None:
        n = self.comp.frames[0].scale_n if self.comp.frames else 100.0
        _pw, ph = self.comp.page_size_mm()
        self.history.execute(AddItemCommand(self.comp, BarraEscala(
            x_mm=self.comp.margin_mm + 4,
            y_mm=ph - self.comp.margin_mm - 12, scale_n=n)))

    def _on_add_cajetin(self) -> None:
        if self.comp.cajetin is not None:
            return
        c = self.comp.default_cajetin()
        c.fecha = datetime.date.today().strftime("%d/%m/%Y")
        if self.comp.frames:
            f = self.comp.frames[0]
            c.escala = f"1:{f.scale_n:g}"
        self.history.execute(AddItemCommand(self.comp, c))

    # ---- property edits ------------------------------------------------------
    def _current_scale_n(self) -> float:
        text = self.scale_combo.currentText().strip()
        if ":" in text:
            text = text.split(":", 1)[1]
        try:
            n = float(text.replace(",", "."))
        except ValueError:
            n = 100.0
        return n if n > 0 else 100.0

    def _on_page_changed(self, *_a) -> None:
        if self._updating:
            return
        self.comp.paper = self.paper_combo.currentText()
        self.comp.landscape = self.landscape_check.isChecked()
        self._mark_dirty()
        self._rebuild_canvas()

    def _panel_edit(self, item: "_SheetItem", changes: dict) -> None:
        """A live property edit from the panel: one coalesced undo step,
        repainting just the touched item (no canvas rebuild mid-typing)."""
        model = item.model
        if all(getattr(model, k) == v for k, v in changes.items()):
            return
        item.prepareGeometryChange()
        self.history.execute(EditItemCommand(model, changes),
                             notify=False, coalesce=True)
        self._mark_dirty()
        item.update()

    def _on_frame_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, FrameItem):
            return
        self._panel_edit(item, {
            "view_key": self.view_combo.currentData() or "__current__",
            "scale_n": self._current_scale_n(),
            "w_mm": self.fw_spin.value(),
            "h_mm": self.fh_spin.value(),
            "style": self.style_combo.currentData() or "sombreado",
            "show_title": self.title_check.isChecked()})
        self.render_cache.pop(id(item.model), None)

    def _on_text_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, TextItem):
            return
        self._panel_edit(item, {
            "text": self.text_edit.toPlainText(),
            "size_pt": self.text_size.value(),
            "bold": self.text_bold.isChecked()})

    def _on_pick_image(self) -> None:
        item = self._selected_item()
        if not isinstance(item, ImageItem):
            return
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Choose image…"), "",
            tr("Images (*.png *.jpg *.jpeg)"))
        if not path:
            return
        self.history.execute(EditItemCommand(item.model, {"path": path}))

    def _on_cajetin_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, CajetinItem):
            return
        self._panel_edit(item, {attr: edit.text()
                                for attr, edit in self.caj_edits.items()})

    def _on_scalebar_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, ScaleBarItem):
            return
        text = self.sb_scale.currentText().strip()
        if ":" in text:
            text = text.split(":", 1)[1]
        try:
            n = float(text.replace(",", "."))
        except ValueError:
            n = item.model.scale_n
        item.prepareGeometryChange()
        self._panel_edit(item, {"scale_n": n if n > 0 else item.model.scale_n,
                                "segments": int(self.sb_segments.value())})

    # ---- rendering -----------------------------------------------------------
    def image_cache(self, path: str) -> Optional[QImage]:
        if not path:
            return None
        if path not in self._images:
            self._images[path] = QImage(path)
        return self._images[path]

    def _reload_view_sources(self) -> None:
        self.view_combo.blockSignals(True)
        current = self.view_combo.currentData()
        self.view_combo.clear()
        self.view_combo.addItem(tr("Current view"), "__current__")
        for label, key in _STD_VIEWS:
            self.view_combo.addItem(tr(label), f"std:{key}")
        for sv in self._scene().saved_views:
            self.view_combo.addItem(tr("Scene: {name}", name=sv.name),
                                    f"scene:{sv.name}")
        idx = self.view_combo.findData(current)
        if idx >= 0:
            self.view_combo.setCurrentIndex(idx)
        self.view_combo.blockSignals(False)

    def _on_refresh_selected_frame(self) -> None:
        item = self._selected_item()
        if isinstance(item, FrameItem):
            self._on_frame_props()
            self.render_frame(item.model)
            item.update()

    def refresh_all_frames(self) -> None:
        for f in self.comp.frames:
            self.render_frame(f)
        for it in self.canvas.items():
            if isinstance(it, FrameItem):
                it.update()

    def render_frame(self, frame: MarcoVista) -> Optional[QImage]:
        """Render *frame* at exact scale through the viewport pipeline,
        leaving the live view state untouched (snapshot → render →
        restore); cache by model identity."""
        vp = self._window.viewport
        cam = vp.camera
        scene = vp.scene
        saved_view = None
        if frame.view_key.startswith("scene:"):
            name = frame.view_key[6:]
            saved_view = next((sv for sv in scene.saved_views
                               if sv.name == name), None)
        keep = (cam.target, cam.distance, cam.yaw, cam.pitch, cam.fov_deg,
                cam.perspective, cam.aspect,
                [(ly, ly.visible) for ly in scene.layers])
        try:
            apply_frame_camera(cam, frame, saved_view, scene)
            if frame.style in ("tecnico", "lineas"):
                vp.plano_style = frame.style
            w_px, h_px = frame.render_px(RENDER_DPI)
            image = vp.render_image(w_px, h_px, overlays=False)
        finally:
            vp.plano_style = None
            (cam.target, cam.distance, cam.yaw, cam.pitch, cam.fov_deg,
             cam.perspective, cam.aspect) = keep[:7]
            for ly, visible in keep[7]:
                ly.visible = visible
            vp.update()
        if image is not None:
            self.render_cache[id(frame)] = image
        return image

    # ---- export --------------------------------------------------------------
    def _on_export_pdf(self) -> None:
        self.refresh_all_frames()
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Export PDF…"), "lamina.pdf", "PDF (*.pdf)")
        if not path:
            return
        self.export_pdf(path)
        self.statusBar().showMessage(tr("Exported {name}", name=path), 4000)

    def export_pdf(self, path: str) -> None:
        """Write the sheet to ``path`` with exact physical page metrics.
        Every item paints through the same mm-space painters the canvas
        uses; the painter is scaled device-px-per-mm once."""
        writer = QPdfWriter(path)
        writer.setPageSize(QPageSize(getattr(QPageSize, self.comp.paper)))
        if self.comp.landscape:
            writer.setPageOrientation(QPageLayout.Landscape)
        writer.setResolution(RENDER_DPI)
        painter = QPainter(writer)
        try:
            k = RENDER_DPI / 25.4
            painter.scale(k, k)
            for f in self.comp.frames:
                painter.save()
                painter.translate(f.x_mm, f.y_mm)
                paint_frame_mm(painter, f, self.render_cache.get(id(f)))
                painter.restore()
            for i in self.comp.images:
                painter.save()
                painter.translate(i.x_mm, i.y_mm)
                paint_image_mm(painter, i, self.image_cache(i.path))
                painter.restore()
            for t in self.comp.texts:
                painter.save()
                painter.translate(t.x_mm, t.y_mm)
                paint_text_mm(painter, t)
                painter.restore()
            for sb in self.comp.scalebars:
                painter.save()
                painter.translate(sb.x_mm, sb.y_mm)
                paint_scalebar_mm(painter, sb)
                painter.restore()
            if self.comp.cajetin is not None:
                c = self.comp.cajetin
                painter.save()
                painter.translate(c.x_mm, c.y_mm)
                paint_cajetin_mm(painter, c)
                painter.restore()
        finally:
            painter.end()

    # ---- lifecycle -----------------------------------------------------------
    def showEvent(self, event) -> None:
        # The document may have been swapped under us (New / Open) while
        # the window was closed — re-adopt the scene's compositions.
        scene = self._scene()
        if not scene.compositions:
            comp = Composicion()
            comp.frames.append(comp.default_frame())
            scene.compositions.append(comp)
        if self.comp not in scene.compositions:
            self.comp = scene.compositions[0]
            self.history = ComposerHistory(on_change=self._on_history_change)
        self._reload_comp_combo()
        self._rebuild_canvas()
        super().showEvent(event)
