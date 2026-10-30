# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 José Castro Basso (FADU–UDELAR) — idea and first version.
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Niveles — building levels as an IngeTrazo EXTENSION.

Levels (PB, PA, Azotea…) with their height; in an elevation or a section
seen in parallel projection, a dashed guide across the drawing at each
level, and the cursor snaps to those heights — «Nivel PA» on the tip.

José Castro Basso wrote the first version for teaching architectural
representation at FADU–UDELAR (Montevideo). It is an extension and not part
of IngeTrazo on purpose: the core stays for everyone, and what a course or
an office needs is installed by whoever needs it — and can be maintained
by them. It is also the worked example of the extension API
(docs/plugins.md): document data, a side panel, a viewport overlay and an
inference, all through ``setup(app)``.

Install: copy this file into the plugins folder (Extensions ▸ Open plugins
folder) and restart IngeTrazo. The «Niveles» tab appears in the side tray.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from core.i18n import current_language

#: Guides and snapping only when the view looks sideways: |pitch| below this.
MAX_PITCH_DEG = 15.0
COLOR = (0.95, 0.45, 0.16)                    # IngeTrazo's accent

# An extension brings its own words — the core catalogues stay the core's.
_TEXTS = {
    "es": {"Levels": "Niveles", "Level guides": "Guías de nivel",
           "Add": "Añadir", "Edit": "Editar", "Delete": "Eliminar",
           "Name:": "Nombre:", "Height:": "Altura:", "New level": "Nuevo nivel",
           "Edit level": "Editar nivel", "Level {n}": "Nivel {n}",
           "Show elevation": "Ver alzado",
           "Front view in parallel projection, where the level guides show.":
           "Vista frontal en proyección paralela, donde se ven las guías de "
           "nivel.",
           "Double-click a level to edit it. The guides show in elevations "
           "and sections in parallel projection.":
           "Doble clic en un nivel para editarlo. Las guías se ven en alzados "
           "y cortes en proyección paralela."},
    "pt-BR": {"Levels": "Níveis", "Level guides": "Guias de nível",
              "Add": "Adicionar", "Edit": "Editar", "Delete": "Excluir",
              "Name:": "Nome:", "Height:": "Altura:", "New level": "Novo nível",
              "Edit level": "Editar nível", "Level {n}": "Nível {n}",
              "Show elevation": "Ver elevação",
              "Front view in parallel projection, where the level guides show.":
              "Vista frontal em projeção paralela, onde as guias de nível "
              "aparecem.",
              "Double-click a level to edit it. The guides show in elevations "
              "and sections in parallel projection.":
              "Clique duas vezes num nível para editá-lo. As guias aparecem "
              "em elevações e cortes em projeção paralela."},
}


def _t(text: str, **kw) -> str:
    out = _TEXTS.get(current_language(), {}).get(text, text)
    return out.format(**kw) if kw else out


# ---- The data (the document's, through the API) --------------------------------

def _state(app) -> dict:
    """``{"levels": [{"name", "z"}...], "guides": bool}`` — what the
    document holds, sorted by height."""
    raw = app.document_data({}) or {}
    levels = []
    for lv in raw.get("levels", []) if isinstance(raw, dict) else []:
        try:
            levels.append({"name": str(lv["name"]), "z": float(lv["z"])})
        except (KeyError, TypeError, ValueError):
            continue
    levels.sort(key=lambda lv: lv["z"])
    return {"levels": levels, "guides": bool(raw.get("guides", True))
            if isinstance(raw, dict) else True}


def _sideways(viewport) -> bool:
    """An elevation or section in parallel projection — where heights read."""
    cam = viewport.camera
    if getattr(cam, "perspective", True):
        return False
    return abs(math.degrees(getattr(cam, "pitch", 0.0))) <= MAX_PITCH_DEG


def _units():
    """``core.units`` when the host has document units (0.5.8+), else None:
    an older IngeTrazo keeps the metre labels and field it always had."""
    try:
        from core import units
    except ImportError:
        return None
    return units if hasattr(units, "format_signed_level") else None


def _fmt(z: float) -> str:
    """A level's height as a level mark, in the document's units: «+3.00»,
    «±0.00» in metres (the text printed on every sheet), «+9'10"» in feet."""
    units = _units()
    if units is None:
        return f"{z:+.2f}".replace("+0.00", "±0.00")
    return units.localized(units.format_signed_level(
        z, units.model_unit(), units.model_precision()))


def _fmt_listed(z: float) -> str:
    """:func:`_fmt` with the unit spelled out where the mark has none
    (metres): the list in the panel has no sheet around it to say so."""
    units = _units()
    if units is None or units.model_unit() == "m":
        return _fmt(z) + " m"
    return _fmt(z)


#: Floor-to-floor height offered for the second level, before there is a
#: previous one to repeat.
DEFAULT_STORY = 2.6


def _next_height(levels) -> float:
    """Where a new level goes: the first at ±0, then one floor-to-floor
    above the highest, repeating the spacing of the two highest levels (so
    10' stories keep coming at 10') or :data:`DEFAULT_STORY` before there
    are two."""
    zs = sorted(float(lv["z"]) for lv in levels)
    if not zs:
        return 0.0
    step = zs[-1] - zs[-2] if len(zs) >= 2 else 0.0
    return zs[-1] + (step if step > 1e-6 else DEFAULT_STORY)


# ---- Panel ------------------------------------------------------------------------

class _LevelDialog(QDialog):
    def __init__(self, parent, title: str, name: str, z: float) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        form = QFormLayout(self)
        self.name = QLineEdit(name)
        form.addRow(_t("Name:"), self.name)
        if _units() is not None:
            # The height in the document's units; value() stays in metres.
            from views.length_field import LengthSpinBox
            self.z = LengthSpinBox(minimum=-1000.0, maximum=1000.0)
        else:
            self.z = QDoubleSpinBox()
            self.z.setRange(-1000.0, 1000.0)
            self.z.setDecimals(2)
            self.z.setSingleStep(0.10)
            self.z.setSuffix(" m")
        self.z.setValue(z)
        form.addRow(_t("Height:"), self.z)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class LevelsPanel(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        lay = QVBoxLayout(self)
        self.guides = QCheckBox(_t("Level guides"))
        self.guides.toggled.connect(self._on_guides)
        lay.addWidget(self.guides)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self._edit())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, slot in ((_t("Add"), self._add), (_t("Edit"), self._edit),
                           (_t("Delete"), self._delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)
        # The guides only exist in a parallel elevation — which is exactly
        # where nobody starts. One click gets there (Marco's first try, 25-09:
        # «hice niveles pero no veo nada en el dibujo» — he was in perspective).
        elev = QPushButton(_t("Show elevation"))
        elev.setToolTip(_t("Front view in parallel projection, where the "
                           "level guides show."))
        elev.clicked.connect(self._show_elevation)
        lay.addWidget(elev)
        hint = QLabel(_t("Double-click a level to edit it. The guides show in "
                         "elevations and sections in parallel projection."))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.refresh()

    def _show_elevation(self) -> None:
        vp = self.app.viewport
        vp.camera.set_view("front")
        vp.camera.perspective = False
        vp.update()

    def refresh(self) -> None:
        st = _state(self.app)
        self.guides.blockSignals(True)
        self.guides.setChecked(st["guides"])
        self.guides.blockSignals(False)
        current = self.list.currentRow()
        self.list.clear()
        for lv in reversed(st["levels"]):          # the highest on top
            self.list.addItem(QListWidgetItem(f"{lv['name']}   {_fmt_listed(lv['z'])}"))
        if 0 <= current < self.list.count():
            self.list.setCurrentRow(current)

    def _index(self):
        """The selected level's index in the height-sorted list."""
        row = self.list.currentRow()
        n = len(_state(self.app)["levels"])
        return None if row < 0 or row >= n else n - 1 - row

    def _store(self, st: dict) -> None:
        self.app.set_document_data(st)             # one undo step
        self.refresh()

    def _on_guides(self, on: bool) -> None:
        st = _state(self.app)
        st["guides"] = bool(on)
        self._store(st)

    def _add(self) -> None:
        st = _state(self.app)
        dlg = _LevelDialog(self, _t("New level"),
                           _t("Level {n}", n=len(st["levels"]) + 1),
                           _next_height(st["levels"]))
        if dlg.exec() != QDialog.Accepted or not dlg.name.text().strip():
            return
        st["levels"].append({"name": dlg.name.text().strip(),
                             "z": dlg.z.value()})
        self._store(st)

    def _edit(self) -> None:
        i = self._index()
        if i is None:
            return
        st = _state(self.app)
        lv = st["levels"][i]
        dlg = _LevelDialog(self, _t("Edit level"), lv["name"], lv["z"])
        if dlg.exec() != QDialog.Accepted or not dlg.name.text().strip():
            return
        lv["name"], lv["z"] = dlg.name.text().strip(), dlg.z.value()
        self._store(st)

    def _delete(self) -> None:
        i = self._index()
        if i is None:
            return
        st = _state(self.app)
        del st["levels"][i]
        self._store(st)


# ---- Viewport: guides and snapping ------------------------------------------------

def _guide_ends(viewport, z: float):
    """Two world points of a horizontal line at height ``z`` running across
    the view, through the model — or None when the view is not sideways."""
    cam = viewport.camera
    right = QVector3D(-math.sin(cam.yaw), math.cos(cam.yaw), 0.0)
    c = cam.target
    span = max(cam.distance * 10.0, 100.0)
    return (QVector3D(c.x(), c.y(), z) - right * span,
            QVector3D(c.x(), c.y(), z) + right * span)


def draw_guides(app, viewport, painter) -> None:
    st = _state(app)
    if not st["guides"] or not st["levels"] or not _sideways(viewport):
        return
    color = QColor.fromRgbF(*COLOR, 0.9)
    pen = QPen(color, 1.2, Qt.DashLine)
    font = QFont()
    font.setPointSize(9)
    painter.setFont(font)
    for lv in st["levels"]:
        a, b = _guide_ends(viewport, lv["z"])
        pa, pb = viewport._world_to_pixel(a), viewport._world_to_pixel(b)
        if pa is None or pb is None:
            continue
        seg = viewport._clip_pixel_line(pa, pb, margin=0.0)
        if seg is None:
            continue
        (x0, y0), (x1, y1) = seg
        painter.setPen(pen)
        painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        left = (x0, y0) if x0 <= x1 else (x1, y1)
        painter.setPen(QPen(color))
        painter.drawText(QPointF(left[0] + 8, left[1] - 4),
                         f"{lv['name']}  {_fmt(lv['z'])}")


def snap_to_levels(app, viewport, snap, px: float, py: float):
    st = _state(app)
    if not st["guides"] or not st["levels"] or not _sideways(viewport):
        return None
    p = snap.point
    here = viewport._world_to_pixel(p)
    if here is None:
        return None
    best, best_d = None, viewport.snap_threshold_px * 1.5
    for lv in st["levels"]:
        q = QVector3D(p.x(), p.y(), lv["z"])
        there = viewport._world_to_pixel(q)
        if there is None:
            continue
        d = abs(there[1] - here[1])
        if d <= best_d:
            best, best_d = (q, lv), d
    if best is None:
        return None
    from core.snap import SnapResult
    q, lv = best
    return SnapResult(q, "reference", COLOR, label=lv["name"])


# ---- Entry point --------------------------------------------------------------------

def setup(app) -> None:
    panel = LevelsPanel(app)
    app.add_panel(_t("Levels"), panel)
    app.on_document_changed(panel.refresh)
    app.add_overlay(lambda vp, painter: draw_guides(app, vp, painter))
    app.add_snap_provider(
        lambda vp, snap, px, py: snap_to_levels(app, vp, snap, px, py))
