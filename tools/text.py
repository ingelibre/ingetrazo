# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Text tool (X): place a leader-text annotation.

Two clicks: (1) the anchor on the model (snapped), (2) where the label
floats — then type the text. The default text describes what was clicked:
an edge offers its length, a face its area, anything else
the point's coordinates.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import AddTextLabelCommand
from core.i18n import tr
from core.textlabel import TextLabel
from tools.base import AxisMagnet, Tool, ToolContext
from core.units import fmt_area, fmt_len


class TextTool(AxisMagnet, Tool):
    name = "Text"
    shortcut = "X"
    description = (
        "Place a text with a leader pointing at the model; it "
        "suggests the length, area or coordinates of what you click.")

    def __init__(self) -> None:
        self.anchor: QVector3D | None = None
        self.hover_point: QVector3D | None = None
        self._default_text: str = ""
        self.start_point: QVector3D | None = None
        self.work_plane: tuple[QVector3D, QVector3D] | None = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    def _reset(self) -> None:
        self.anchor = None
        self.start_point = None
        self.work_plane = None
        self._default_text = ""

    # ---- Spatial input ------------------------------------------------------
    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world

    def on_click(self, ctx: ToolContext) -> None:
        if self.anchor is None:
            self.anchor = QVector3D(ctx.world)
            self.start_point = self.anchor
            self._default_text = self._describe(ctx)
            return
        # Second click: label position → ask for the text.
        offset = ctx.world - self.anchor
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getMultiLineText(
            ctx.viewport.window(), tr("Text"), tr("Label text:"),
            self._default_text)
        if ok and text.strip():
            ctx.viewport.history.execute(AddTextLabelCommand(
                TextLabel(QVector3D(self.anchor), offset, text.strip())))
        self._reset()
        ctx.viewport.update()

    def _describe(self, ctx: ToolContext) -> str:
        """The default label: what did the anchor click land on?"""
        viewport = ctx.viewport
        sx, sy = ctx.screen.x(), ctx.screen.y()
        try:
            edge = viewport.pick_edge(sx, sy)
        except Exception:
            edge = None
        if edge is not None:
            return fmt_len((QVector3D(edge.b) - QVector3D(edge.a)).length())
        try:
            face = viewport.pick_face_any(sx, sy)
        except Exception:
            face = None
        if face is not None:
            f = face[0] if isinstance(face, tuple) else face
            area = getattr(f, "area", None)
            if callable(area):
                return fmt_area(f.area())
        p = ctx.world
        return f"({p.x():.2f}, {p.y():.2f}, {p.z():.2f})"

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- Live preview -------------------------------------------------------
    def rubber_band_lines(self):
        if self.anchor is not None and self.hover_point is not None:
            return [(self.anchor, self.hover_point)]     # the leader forming
        return []

    def value_label(self):
        if self.anchor is not None and self.hover_point is not None:
            return (self._default_text or "…", self.hover_point)
        return None
