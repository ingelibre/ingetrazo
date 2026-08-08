# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheet composer window — QGIS-composer-shaped (docs/composer-plan.md).

C1 scope: one page, one movable model-view frame at exact 1:N scale,
PDF export. The canvas is a ``QGraphicsScene`` whose units are paper
MILLIMETRES; the frame is filled by rendering the model through the
viewport's own pipeline with a parallel camera, then restoring the live
view state untouched (camera, aspect, layer visibility).
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QPageLayout, QPageSize,
                           QPainter, QPdfWriter, QPen)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGraphicsItem,
                               QGraphicsRectItem, QGraphicsScene,
                               QGraphicsView, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from core.composition import (COMMON_SCALES, PAPER_SIZES_MM, RENDER_DPI,
                              Composicion, MarcoVista, apply_frame_camera,
                              mm_to_px)
from core.i18n import tr


#: Standard views offered as frame sources (label key → camera.set_view key).
_STD_VIEWS = (
    ("Top (plan)", "top"),
    ("Front", "front"),
    ("Back", "back"),
    ("Left", "left"),
    ("Right", "right"),
    ("Isometric", "iso"),
)


class _FrameItem(QGraphicsRectItem):
    """The model-view frame on the page: movable, shows the rendered fill."""

    def __init__(self, frame: MarcoVista) -> None:
        super().__init__(0, 0, frame.w_mm, frame.h_mm)
        self.frame = frame
        self.image: Optional[QImage] = None
        self.setPos(frame.x_mm, frame.y_mm)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setPen(QPen(QColor("#3a6ea5"), 0.4))
        self.setBrush(QBrush(QColor(255, 255, 255)))

    def set_image(self, image: Optional[QImage]) -> None:
        self.image = image
        self.update()

    def sync_size(self) -> None:
        self.setRect(0, 0, self.frame.w_mm, self.frame.h_mm)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.frame.x_mm = self.pos().x()
            self.frame.y_mm = self.pos().y()
        return super().itemChange(change, value)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        r = self.rect()
        if self.image is not None and not self.image.isNull():
            painter.drawImage(r, self.image)
        else:
            painter.fillRect(r, QColor(245, 246, 248))
            painter.setPen(QPen(QColor(140, 150, 160), 0.4))
            painter.drawText(r, Qt.AlignCenter,
                             tr("Update the view to render"))
        painter.setPen(self.pen())
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r)


class ComposerWindow(QMainWindow):
    """The composer: page canvas on the left, frame properties on the right."""

    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self.setWindowFlag(Qt.Window, True)
        self._window = main_window
        self.comp = Composicion()
        self.comp.frames.append(self.comp.default_frame())
        self.setWindowTitle(tr("Sheet composer"))
        self.resize(1100, 760)

        self.canvas = QGraphicsScene(self)
        view = QGraphicsView(self.canvas)
        view.setRenderHints(QPainter.Antialiasing
                            | QPainter.SmoothPixmapTransform)
        view.setBackgroundBrush(QColor(70, 76, 84))
        view.scale(3.0, 3.0)          # ~3 px/mm: an A4 fills the window
        self._view = view

        panel = self._build_panel()
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(view, 1)
        lay.addWidget(panel, 0)
        self.setCentralWidget(central)

        self._page_item: Optional[QGraphicsRectItem] = None
        self._frame_item: Optional[_FrameItem] = None
        self._rebuild_page()

    # ---- UI ------------------------------------------------------------------
    def _build_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(260)
        outer = QVBoxLayout(panel)

        form = QFormLayout()
        self.paper_combo = QComboBox()
        self.paper_combo.addItems(list(PAPER_SIZES_MM))
        self.paper_combo.setCurrentText(self.comp.paper)
        self.paper_combo.currentTextChanged.connect(self._on_page_changed)
        form.addRow(tr("Paper"), self.paper_combo)

        self.landscape_check = QCheckBox(tr("Landscape"))
        self.landscape_check.setChecked(self.comp.landscape)
        self.landscape_check.toggled.connect(self._on_page_changed)
        form.addRow("", self.landscape_check)

        self.view_combo = QComboBox()
        self._reload_view_sources()
        self.view_combo.currentIndexChanged.connect(self._on_frame_changed)
        form.addRow(tr("View"), self.view_combo)

        self.scale_combo = QComboBox()
        self.scale_combo.setEditable(True)
        self.scale_combo.addItems([f"1:{n}" for n in COMMON_SCALES])
        self.scale_combo.setCurrentText("1:100")
        self.scale_combo.currentTextChanged.connect(self._on_frame_changed)
        form.addRow(tr("Scale"), self.scale_combo)

        self.w_spin = QDoubleSpinBox()
        self.w_spin.setRange(20.0, 2000.0)
        self.w_spin.setSuffix(" mm")
        self.h_spin = QDoubleSpinBox()
        self.h_spin.setRange(20.0, 2000.0)
        self.h_spin.setSuffix(" mm")
        frame = self.comp.frames[0]
        self.w_spin.setValue(frame.w_mm)
        self.h_spin.setValue(frame.h_mm)
        self.w_spin.valueChanged.connect(self._on_frame_changed)
        self.h_spin.valueChanged.connect(self._on_frame_changed)
        form.addRow(tr("Frame width"), self.w_spin)
        form.addRow(tr("Frame height"), self.h_spin)
        outer.addLayout(form)

        hint = QLabel(tr("Drag the frame to place it on the page."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        outer.addWidget(hint)

        refresh_btn = QPushButton(tr("Update view"))
        refresh_btn.clicked.connect(self.refresh_frame)
        outer.addWidget(refresh_btn)

        outer.addStretch(1)

        export_btn = QPushButton(tr("Export PDF…"))
        export_btn.clicked.connect(self._on_export_pdf)
        outer.addWidget(export_btn)
        return panel

    def _reload_view_sources(self) -> None:
        self.view_combo.blockSignals(True)
        self.view_combo.clear()
        self.view_combo.addItem(tr("Current view"), "__current__")
        for label, key in _STD_VIEWS:
            self.view_combo.addItem(tr(label), f"std:{key}")
        for sv in self._window.viewport.scene.saved_views:
            self.view_combo.addItem(tr("Scene: {name}", name=sv.name),
                                    f"scene:{sv.name}")
        self.view_combo.blockSignals(False)

    # ---- Page / frame model sync --------------------------------------------
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
        self.comp.paper = self.paper_combo.currentText()
        self.comp.landscape = self.landscape_check.isChecked()
        self._rebuild_page()

    def _on_frame_changed(self, *_a) -> None:
        frame = self.comp.frames[0]
        frame.view_key = self.view_combo.currentData() or "__current__"
        frame.scale_n = self._current_scale_n()
        frame.w_mm = self.w_spin.value()
        frame.h_mm = self.h_spin.value()
        if self._frame_item is not None:
            self._frame_item.sync_size()
            self._frame_item.set_image(None)   # stale at the new scale/size

    def _rebuild_page(self) -> None:
        self.canvas.clear()
        self._frame_item = None
        pw, ph = self.comp.page_size_mm()
        self.canvas.setSceneRect(-20, -20, pw + 40, ph + 40)
        shadow = self.canvas.addRect(2.0, 2.0, pw, ph, QPen(Qt.NoPen),
                                     QBrush(QColor(0, 0, 0, 70)))
        shadow.setZValue(-2)
        self._page_item = self.canvas.addRect(
            0, 0, pw, ph, QPen(QColor(120, 128, 136), 0.3),
            QBrush(QColor(255, 255, 255)))
        self._page_item.setZValue(-1)
        m = self.comp.margin_mm
        margin = self.canvas.addRect(m, m, pw - 2 * m, ph - 2 * m,
                                     QPen(QColor(190, 196, 202), 0.2,
                                          Qt.DashLine))
        margin.setZValue(-1)

        frame = self.comp.frames[0]
        # Keep the frame inside the new page bounds.
        frame.w_mm = min(frame.w_mm, pw - 2 * m)
        frame.h_mm = min(frame.h_mm, ph - 2 * m)
        frame.x_mm = min(frame.x_mm, pw - m - frame.w_mm)
        frame.y_mm = min(frame.y_mm, ph - m - frame.h_mm)
        self.w_spin.blockSignals(True)
        self.h_spin.blockSignals(True)
        self.w_spin.setValue(frame.w_mm)
        self.h_spin.setValue(frame.h_mm)
        self.w_spin.blockSignals(False)
        self.h_spin.blockSignals(False)
        self._frame_item = _FrameItem(frame)
        self.canvas.addItem(self._frame_item)

    # ---- Rendering -----------------------------------------------------------
    def refresh_frame(self) -> None:
        """Fill the frame by rendering the model at exact scale, leaving the
        live viewport state untouched (snapshot → render → restore)."""
        self._on_frame_changed()
        frame = self.comp.frames[0]
        image = self._render_frame(frame)
        if self._frame_item is not None:
            self._frame_item.set_image(image)

    def _render_frame(self, frame: MarcoVista) -> Optional[QImage]:
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
            w_px, h_px = frame.render_px(RENDER_DPI)
            return vp.render_image(w_px, h_px, overlays=False)
        finally:
            (cam.target, cam.distance, cam.yaw, cam.pitch, cam.fov_deg,
             cam.perspective, cam.aspect) = keep[:7]
            for ly, visible in keep[7]:
                ly.visible = visible
            vp.update()

    # ---- Export --------------------------------------------------------------
    def _on_export_pdf(self) -> None:
        self.refresh_frame()
        frame = self.comp.frames[0]
        if self._frame_item is None or self._frame_item.image is None:
            QMessageBox.warning(self, tr("Sheet composer"),
                                tr("Nothing rendered to export."))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Export PDF…"), "lamina.pdf", "PDF (*.pdf)")
        if not path:
            return
        self.export_pdf(path)
        self.statusBar().showMessage(
            tr("Exported {name}", name=path), 4000)

    def export_pdf(self, path: str) -> None:
        """Write the sheet to ``path`` with exact physical page metrics."""
        pw, ph = self.comp.page_size_mm()
        writer = QPdfWriter(path)
        writer.setPageSize(QPageSize(getattr(QPageSize, self.comp.paper)))
        if self.comp.landscape:
            writer.setPageOrientation(QPageLayout.Landscape)
        writer.setResolution(RENDER_DPI)
        painter = QPainter(writer)
        try:
            k = RENDER_DPI / 25.4          # device pixels per paper mm
            frame = self.comp.frames[0]
            target = QRectF(frame.x_mm * k, frame.y_mm * k,
                            frame.w_mm * k, frame.h_mm * k)
            painter.drawImage(target, self._frame_item.image)
            pen = QPen(QColor(40, 46, 54))
            pen.setWidthF(0.3 * k)         # 0.3 mm frame line
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(target)
        finally:
            painter.end()

    # ---- Lifecycle -----------------------------------------------------------
    def showEvent(self, event) -> None:
        # Scenes may have changed while the composer was closed.
        current = self.view_combo.currentData()
        self._reload_view_sources()
        idx = self.view_combo.findData(current)
        if idx >= 0:
            self.view_combo.setCurrentIndex(idx)
        super().showEvent(event)
        # First impression: the whole page in view, whatever the paper size.
        self._view.fitInView(self.canvas.sceneRect(), Qt.KeepAspectRatio)
