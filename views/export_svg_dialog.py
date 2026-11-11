# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The options of the SVG view export, with a preview of the sheet.

How the faces go under the lines — with their materials and textures,
their materials alone, all in the default colour, as a picture of the view
exactly as on screen, or not at all —, whether lit by their orientation,
whether with the sun's shadows, and the paper the drawing is fitted on.
Each choice shows what it gives — a small cube drawn that way and a line
of explanation —, the preview shows the sheet as it will come out, and the
dialog remembers the last choices."""
from __future__ import annotations

import re
import time
from contextlib import contextmanager

from PySide6.QtCore import (QByteArray, QLineF, QPoint, QPointF, QRectF,
                            QSettings, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox,
                               QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QGridLayout,
                               QHBoxLayout, QLabel, QProgressDialog,
                               QPushButton, QRadioButton, QToolButton, QVBoxLayout,
                               QWidget)

from core.i18n import tr
from views.svg_export import NO_FRAME

#: The face choices, in the dialog's order: key and the options of
#: core.vista_caras.view_faces (``None``: no faces; ``image``: the picture
#: of the view).
FACE_CHOICES = (
    ("view", {"image": True}),
    ("full", {"materials": True, "textures": True}),
    ("colours", {"materials": True, "textures": False}),
    ("default", {"materials": False, "textures": False}),
    ("none", None),
)

#: What the dialog begins with, the first time: the view as on screen —
#: what the window shows, at the screen's size.
DEFAULT_FACES = "view"
DEFAULT_AREA = "view"
DEFAULT_SIZE = "screen"

#: The main size choice, in the list's order: what the screen shows at
#: its size, your own measures, the drawing at its scale.
MODES = ("screen", "custom", "scale")

#: The paper sheets «Custom» offers: name and portrait (w, h) in mm.
SHEETS = (("A4", (210.0, 297.0)), ("A3", (297.0, 420.0)),
          ("A2", (420.0, 594.0)), ("A1", (594.0, 841.0)),
          ("A0", (841.0, 1189.0)))

#: The proportions «Custom» keeps without a paper sheet: key and width
#: over height lying down (``None``: free; ``"screen"``: the screen's).
RATIOS = (("free", None), ("screen", "screen"), ("1:1", 1.0),
          ("16:9", 16.0 / 9.0), ("4:3", 4.0 / 3.0), ("3:2", 1.5),
          ("2:1", 2.0))

#: The composition guides the preview can show, as a camera's viewfinder
#: does — only to frame by; they never go into the file.
GUIDES = ("none", "thirds", "golden", "grid", "diagonals", "centre")
#: The guides the preview begins with.
DEFAULT_GUIDES = "thirds"

#: The golden section of a side: where the golden ratio's lines fall.
GOLDEN = (5.0 ** 0.5 - 1.0) / 2.0         # 0.618…

#: The basic dialog's choices of what to export (all but lines only), and
#: the one it begins with.
BASIC_FACES = ("view", "full", "colours", "default")
DEFAULT_BASIC_FACES = "view"
#: The basic dialog begins with the screen's size, its millimetres shown.
DEFAULT_BASIC_SIZE = "screen"

#: Where the last choices are kept.
_KEY = "export_svg/v5/"

#: The preview's size on screen, in pixels.
PREVIEW_W, PREVIEW_H = 420, 340

#: The choices' little cubes, in pixels: the basic dialog's, and the
#: advanced one's, a little smaller to keep it low.
ICON_PX = 40
ADVANCED_ICON_PX = 30


def _face_texts() -> dict:
    """Each face choice's label and explanation, translated."""
    return {
        "full": (tr("Materials and textures"), tr(
            "Each visible face as one filled shape under the lines, in its "
            "colour or with its texture as the view lays it.")),
        "colours": (tr("Materials, no textures"), tr(
            "The faces in their materials' colours; a textured one in the "
            "mean colour of its image.")),
        "default": (tr("Default colour only"), tr(
            "Every face in IngeTrazo's default colour and every line in "
            "black, whatever their material or layer colour — a clean model "
            "to colour in the illustration program.")),
        "view": (tr("Picture of the view"), tr(
            "The view exactly as on screen — sun shadows, ambient occlusion, "
            "textures — as one picture under the vector lines. Its faces "
            "are not shapes to edit.")),
        "none": (tr("No faces (lines only)"), tr(
            "The lines alone, as the DXF export.")),
    }


def cube_preview(key: str, size: int = 56, ink: QColor | None = None
                 ) -> QPixmap:
    """A small cube drawn the way choice ``key`` exports it: textured,
    in flat colours, in the default white, as a picture with its shadow,
    or as lines alone — those in ``ink`` (the theme's text colour, so they
    show on a dark dialog)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 56.0
    # The whole cube inside the picture: its top corner at 5, its foot at
    # 49 (out of 56) — the picture used to cut the top corner off.
    c = QPointF(28 * s, 38 * s)
    dx, dy, h = 20 * s, 11 * s, 22 * s
    top = QPolygonF([c + QPointF(0, -2 * dy) + QPointF(0, -h / 2),
                     c + QPointF(dx, -dy) + QPointF(0, -h / 2),
                     c + QPointF(0, 0) + QPointF(0, -h / 2),
                     c + QPointF(-dx, -dy) + QPointF(0, -h / 2)])
    left = QPolygonF([top[3], top[2], top[2] + QPointF(0, h),
                      top[3] + QPointF(0, h)])
    right = QPolygonF([top[2], top[1], top[1] + QPointF(0, h),
                       top[2] + QPointF(0, h)])
    if key == "view":
        # Its shadow on the ground, and the frame of a picture round it.
        foot = [left[3], left[2], right[2]]
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawPolygon(QPolygonF(foot + [right[2] + QPointF(-14 * s, 5 * s),
                                        left[3] + QPointF(-14 * s, 5 * s)]))
    light = {"top": 1.0, "left": 0.78, "right": 0.66}
    if key in ("full", "colours", "view"):
        base = (QColor(176, 82, 58), QColor(150, 60, 45))
    else:
        base = (QColor(245, 242, 236), QColor(245, 242, 236))
    if key != "none":
        for name, poly in (("left", left), ("right", right), ("top", top)):
            col = base[1] if name == "top" and key != "default" else base[0]
            f = light[name] * (0.75 if key == "view" and name == "left"
                               else 1.0)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(int(col.red() * f), int(col.green() * f),
                              int(col.blue() * f)))
            p.drawPolygon(poly)
            if key in ("full", "view") and name != "top":
                # Courses of brick along the face, the joints staggered.
                p.setPen(QPen(QColor(225, 210, 195), max(1.0, 0.7 * s)))
                a, b, d = poly[0], poly[1], poly[3] - poly[0]
                rows = 4
                for k in range(1, rows):
                    p.drawLine(a + d * (k / rows), b + d * (k / rows))
                for k in range(rows):
                    for j in ((1, 3) if k % 2 else (2,)):
                        x = a + (b - a) * (j / 4.0)
                        p.drawLine(x + d * (k / rows),
                                   x + d * ((k + 1) / rows))
    if key != "none" or ink is None:
        edge = QColor(30, 30, 30)
    else:
        edge = ink
    p.setPen(QPen(edge, max(1.0, 1.1 * s)))
    p.setBrush(Qt.NoBrush)
    for poly in (top, left, right):
        p.drawPolygon(poly)
    if key == "view":
        p.setPen(QPen(ink if ink is not None else QColor(90, 90, 90),
                      max(1.0, 1.0 * s)))
        p.drawRoundedRect(QRectF(2 * s, 4 * s, 52 * s, 50 * s), 3 * s, 3 * s)
    p.end()
    return pm


class ExportSvgDialog(QDialog):
    """``build(options, sheet, preview=True)`` → ``(svg text, n)`` draws
    the preview (``None``: no preview). ``base_label`` names the size that
    keeps the drawing at its scale — the composer's frame has one; without
    it there is no such size; ``screen_label`` the one that is the
    screen's (or the frame's) own size, and ``view_label`` the part that is
    what it shows. ``shadows_available`` / ``axes_available``: the document
    has the sun shadows on / the view shows the axes. ``screen_mm``: the
    screen's (or frame's) size in millimetres.

    The preview on the left; on the right what to export, its options and
    the sheet — which part goes out and at what size, its measures always
    in sight with a lock for the proportion and two buttons for the turn."""

    def __init__(self, parent, build=None, base_label: str | None = None,
                 shadows_available: bool = False,
                 screen_label: str | None = None,
                 axes_available: bool = False,
                 screen_mm=None, view_label: str | None = None,
                 selection_available: bool = False,
                 can_frame: bool = False,
                 settings: QSettings | None = None,
                 advanced: bool | None = None,
                 scenes=None, on_scene=None, hold=None) -> None:
        super().__init__(parent)
        #: The view, kept from painting while the preview works out faces
        #: (see :func:`faces_progress`).
        self._hold = hold
        #: The model's scenes by name, and what shows one (an index, or
        #: ``None`` for the view as it was) and hands back its builder.
        self._scenes = list(scenes or [])
        self._on_scene = on_scene
        self._settings = settings if settings is not None else QSettings()
        self._build = build
        self._shadows_available = shadows_available
        self._axes_available = axes_available
        self._selection_available = selection_available
        self._can_frame = can_frame
        #: The export's own framing of what the screen shows: pan (in
        #: window widths and heights, right and up) and zoom — set by
        #: dragging and turning the wheel on the preview.
        self._frame = NO_FRAME
        self._screen_mm = (tuple(float(v) for v in screen_mm)
                           if screen_mm else (297.0, 210.0))
        self._syncing = False
        self.setWindowTitle(tr("Export SVG"))
        intro = QLabel(tr(
            "A vector drawing of the view to finish in an illustration "
            "program: one layer per model layer, the faces under the "
            "lines."))
        intro.setWordWrap(True)
        ink = self.palette().color(self.foregroundRole())

        # ---- what to export -----------------------------------------------
        # IngeTrazo's own look: sections under a bold title, as the side
        # panels have them (no framed boxes), fields as form rows.
        what = QWidget()
        grid = QGridLayout(what)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        self.face_group = QButtonGroup(self)
        self.face_buttons = {}
        self._tips = {}
        texts = _face_texts()
        for i, (key, _opts) in enumerate(FACE_CHOICES):
            label, tip = texts[key]
            self._tips[key] = tip
            pic = QLabel()
            pic.setPixmap(cube_preview(key, ADVANCED_ICON_PX, ink=ink))
            pic.setFixedSize(ADVANCED_ICON_PX, ADVANCED_ICON_PX)
            btn = QRadioButton(label)
            btn.setToolTip(tip)
            pic.setToolTip(tip)
            pic.mousePressEvent = (lambda _e, b=btn: b.setChecked(True))
            self.face_group.addButton(btn, i)
            self.face_buttons[key] = btn
            grid.addWidget(pic, i, 0)
            grid.addWidget(btn, i, 1)
        grid.setColumnStretch(1, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setEnabled(False)         # the theme's quiet text colour
        self.note.setMinimumHeight(self.fontMetrics().lineSpacing() * 2)
        self.note.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        grid.addWidget(self.note, len(FACE_CHOICES), 0, 1, 2)

        # ---- options ------------------------------------------------------
        self.as_view_box = QCheckBox(tr("Light by orientation"))
        self.as_view_box.setToolTip(tr(
            "Each face lighter or darker by the way it faces, as the view "
            "shades it — white, light grey or grey. It is not the sun's "
            "shadows."))
        self.shadows_box = QCheckBox(tr("Sun shadows"))
        self.shadows_box.setToolTip(tr(
            "The sun's shadows of the view as shapes of their own over the "
            "faces, on a «-SOMBRAS» layer per model layer and the ground's "
            "on «SOMBRAS-SUELO». Turn the shadows on in the view to export "
            "them."))
        self.axes_box = QCheckBox(tr("Hide the axes"))
        self.axes_box.setToolTip(tr(
            "The picture of the view without the red, green and blue axes, "
            "when the view shows them."))
        # Two to a row, to keep the dialog low.
        self.options_part = QWidget()
        opts = QGridLayout(self.options_part)
        opts.setContentsMargins(0, 0, 0, 0)
        opts.setHorizontalSpacing(16)
        opts.setVerticalSpacing(4)
        for i, box in enumerate((self.as_view_box, self.shadows_box,
                                 self.axes_box)):
            opts.addWidget(box, i // 2, i % 2)
        opts.setColumnStretch(1, 1)

        # ---- the sheet ----------------------------------------------------
        # One main choice — on screen, your own measures, at scale — and,
        # only with your own measures, the controls that shape them: a
        # paper sheet, else a proportion, the millimetres and the turn.
        # Off «Custom» they are all switched off: nothing to misread.
        self.size_combo = UpwardComboBox()
        names = {"screen": screen_label or tr("On screen"),
                 "custom": tr("Custom"), "scale": base_label}
        for key in MODES:
            if names[key]:              # at scale only with a scale to keep
                self.size_combo.addItem(names[key], key)
        self.size_combo.setToolTip(tr(
            "On screen: the size the window has. Custom: a paper sheet, a "
            "proportion or your own millimetres. At scale: the drawing at "
            "its scale, the sheet as big as it needs.") if base_label
            else tr("On screen: the size the window has. Custom: a paper "
                    "sheet, a proportion or your own millimetres."))
        self.sheet_combo = UpwardComboBox()
        self.sheet_combo.addItem(tr("None (your own measures)"), "none")
        for key, _wh in SHEETS:
            self.sheet_combo.addItem(key, key)
        self.sheet_combo.setToolTip(tr(
            "A paper sheet sets the measures; change them and it is your "
            "own measures again."))
        self.ratio_combo = UpwardComboBox()
        ratio_names = {"free": tr("Free"), "screen": tr("Like the screen"),
                       "1:1": tr("Square (1:1)")}
        for key, _r in RATIOS:
            self.ratio_combo.addItem(ratio_names.get(key, key), key)
        self.ratio_combo.setToolTip(tr(
            "Keep the width and the height in this proportion: type one and "
            "the other follows. Only without a paper sheet, which has its "
            "own."))
        self.w_box, self.h_box = QDoubleSpinBox(), QDoubleSpinBox()
        for box in (self.w_box, self.h_box):
            box.setRange(10.0, 10000.0)
            box.setDecimals(0)
            box.setSuffix(" mm")
        self.turn_group = QButtonGroup(self)
        self.turn_buttons = {}
        for i, (key, tip) in enumerate((("landscape", tr("Landscape")),
                                        ("portrait", tr("Portrait")))):
            b = QToolButton()
            b.setCheckable(True)
            b.setAutoRaise(True)
            # Its own dimmed look when off: the style's greying leaves a
            # light icon on a dark theme looking switched on.
            icon = QIcon(_sheet_icon(key, ink))
            faint = QColor(ink)
            faint.setAlphaF(0.3)
            icon.addPixmap(_sheet_icon(key, faint), QIcon.Disabled)
            b.setIcon(icon)
            b.setToolTip(tip)
            self.turn_group.addButton(b, i)
            self.turn_buttons[key] = b
        self.turn_buttons["landscape"].setChecked(True)
        measures = QHBoxLayout()
        measures.setSpacing(4)
        measures.addWidget(self.w_box, 1)
        measures.addWidget(QLabel("×"))
        measures.addWidget(self.h_box, 1)
        for key in ("landscape", "portrait"):
            measures.addWidget(self.turn_buttons[key])
        self.area_combo = UpwardComboBox()
        # What the window shows, or the selection alone (the whole model
        # is a Zoom Extents away: what the screen shows is what you get).
        self.area_combo.addItem(view_label or tr("What you see"), "view")
        self.area_combo.addItem(tr("Selection"), "selection")
        self.area_combo.setItemData(0, tr(
            "What the window shows, as it is framed."), Qt.ToolTipRole)
        self.area_combo.setItemData(1, tr(
            "Only what is selected, as if the rest were hidden."),
            Qt.ToolTipRole)
        self.area_combo.setToolTip(tr(
            "What the window shows, as it is framed."))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setVerticalSpacing(6)
        form.addRow(_title(tr("What to export")))
        form.addRow(what)
        form.addRow(_title(tr("Options")))
        form.addRow(self.options_part)
        form.addRow(_title(tr("Sheet")))
        form.addRow(tr("Size:"), self.size_combo)
        form.addRow(tr("Paper sheet:"), self.sheet_combo)
        form.addRow(tr("Proportion:"), self.ratio_combo)
        form.addRow(tr("Measures:"), measures)
        form.addRow(tr("Part:"), self.area_combo)
        # The model's scenes: export one of them, not only the view as it
        # is. Only when the model has scenes and the window can show them.
        self.scene_combo = UpwardComboBox()
        self.scene_combo.addItem(tr("Current view"), -1)
        for i, name in enumerate(self._scenes):
            self.scene_combo.addItem(name, i)
        self.scene_combo.setToolTip(tr(
            "Export one of the model's scenes: the view shows it while the "
            "dialog is open and comes back as it was afterwards."))
        form.addRow(tr("Scene:"), self.scene_combo)
        form.setRowVisible(self.scene_combo,
                           bool(self._scenes) and on_scene is not None)

        # ---- the preview ----------------------------------------------------
        self.preview = FramePreview()
        self.preview.panned.connect(self._on_pan)
        self.preview.zoomed.connect(self._on_zoom)
        self.preview.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview_note = QLabel()
        self.preview_note.setEnabled(False)
        self.preview_note.setAlignment(Qt.AlignCenter)
        #: A preview being worked out: the bar lets the events through, the
        #: timer among them, and one preview must not start inside another.
        self._previewing = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._refresh_preview)
        self.preview_box = QCheckBox(tr("Show the preview"))
        self.preview_box.setToolTip(tr(
            "Work out the preview as the choices change. Off, nothing is "
            "worked out until Export — quicker on a big model."))
        preview_col = QWidget()
        preview_lay = QVBoxLayout(preview_col)
        preview_lay.setContentsMargins(0, 0, 0, 0)
        preview_lay.addWidget(_title(tr("Preview")))
        preview_lay.addWidget(self.preview)
        preview_lay.addWidget(self.preview_note)
        self.frame_hint = QLabel(tr("Drag to move the framing, turn the "
                                    "wheel to zoom."))
        self.frame_hint.setEnabled(False)
        self.frame_hint.setAlignment(Qt.AlignCenter)
        self.frame_reset = QPushButton(tr("Reset framing"))
        self.frame_reset.setToolTip(tr(
            "Back to what the screen shows, as it is framed."))
        self.frame_reset.clicked.connect(self._reset_frame)
        frame_row = QHBoxLayout()
        frame_row.addWidget(self.frame_hint, 1)
        frame_row.addWidget(self.frame_reset)
        preview_lay.addLayout(frame_row)
        self.guides_combo = UpwardComboBox()
        guide_names = {"none": tr("No guides"), "thirds": tr("Rule of thirds"),
                       "golden": tr("Golden ratio"), "grid": tr("Grid"),
                       "diagonals": tr("Diagonals"), "centre": tr("Centre")}
        for key in GUIDES:
            self.guides_combo.addItem(guide_names[key], key)
        self.guides_combo.setToolTip(tr(
            "Lines over the preview to frame the drawing by, as a camera's "
            "viewfinder shows them. They are not exported."))
        self.guides_combo.currentIndexChanged.connect(
            lambda *_a: self.preview.set_guides(
                self.guides_combo.currentData()))
        guides_row = QHBoxLayout()
        guides_row.addWidget(QLabel(tr("Guides:")))
        guides_row.addWidget(self.guides_combo, 1)
        preview_lay.addLayout(guides_row)
        preview_lay.addWidget(self.preview_box)
        preview_lay.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        ok = buttons.button(QDialogButtonBox.Ok)
        ok.setText(tr("Export"))
        ok.setDefault(True)
        # The primary action in the accent colour, Cancel as it is.
        ok.setStyleSheet(
            "QPushButton { background: palette(highlight); "
            "color: palette(highlighted-text); border: none; "
            "border-radius: 4px; padding: 5px 18px; }"
            "QPushButton:hover { background: palette(highlight); }")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        right = QVBoxLayout()
        right.addLayout(form)
        right.addStretch(1)
        body = QHBoxLayout()
        body.setSpacing(18)
        body.addWidget(preview_col)
        body.addLayout(right, 1)
        intro.setEnabled(False)            # a quiet line, as panel hints
        self.advanced_page = QWidget()
        adv = QVBoxLayout(self.advanced_page)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.addWidget(intro)
        adv.addSpacing(4)
        adv.addLayout(body)
        if build is None:
            preview_col.hide()
        self.advanced_page.setMinimumWidth(
            PREVIEW_W + 420 if build is not None else 420)
        self.basic_page = self._basic_page(ink, view_label is not None)
        self.basic_page.setMinimumWidth(380)
        # The way to the advanced dialog: a plain check box, low on the
        # left — secondary to the export itself, on the right.
        self.advanced_box = QCheckBox(tr("Advanced options"))
        self.advanced_box.setToolTip(tr(
            "The full dialog: a preview to frame by, paper sheets and "
            "proportions, the part to export, shadows and guides."))
        foot = QHBoxLayout()
        foot.addWidget(self.advanced_box)
        foot.addStretch(1)
        foot.addWidget(buttons)
        lay = QVBoxLayout(self)
        lay.addWidget(self.basic_page)
        lay.addWidget(self.advanced_page)
        lay.addSpacing(8)                  # the foot apart from the options
        lay.addLayout(foot)

        self._restore()
        self._basic_restore()
        self._last_mode = self._size_mode()
        self.basic_size.currentIndexChanged.connect(self._on_basic_size)
        self.basic_lock.toggled.connect(self._on_basic_lock)
        self.basic_w.valueChanged.connect(lambda *_a: self._basic_keep("w"))
        self.basic_h.valueChanged.connect(lambda *_a: self._basic_keep("h"))
        self.size_combo.currentIndexChanged.connect(self._on_mode)
        self.sheet_combo.currentIndexChanged.connect(self._on_sheet)
        self.ratio_combo.currentIndexChanged.connect(self._on_ratio)
        self.turn_group.idClicked.connect(self._on_turn)
        self.w_box.valueChanged.connect(lambda *_a: self._keep("w"))
        self.h_box.valueChanged.connect(lambda *_a: self._keep("h"))
        self.face_group.idToggled.connect(lambda *_a: self._changed())
        self.area_combo.currentIndexChanged.connect(
            lambda *_a: self._changed())
        self.scene_combo.currentIndexChanged.connect(self._on_scene_chosen)
        for box in (self.as_view_box, self.shadows_box, self.axes_box,
                    self.preview_box):
            box.toggled.connect(lambda *_a: self._changed())
        for combo in (self.size_combo, self.sheet_combo, self.ratio_combo):
            combo.currentIndexChanged.connect(lambda *_a: self._changed())
        self.turn_group.idClicked.connect(lambda *_a: self._changed())
        for box in (self.w_box, self.h_box):
            box.valueChanged.connect(lambda *_a: self._changed())
        if advanced is None:
            v = str(self._settings.value(_KEY + "advanced", False)).lower()
            advanced = v not in ("false", "0")
        self._advanced = bool(advanced)
        self.advanced_box.setChecked(self._advanced)
        self.advanced_box.toggled.connect(self._set_advanced)
        self._sync_sheet_controls()
        self._show_mode()

    # ---- the sheet ----------------------------------------------------------
    def _size_mode(self) -> str:
        """``"screen"``, ``"custom"`` or ``"scale"``."""
        return self.size_combo.currentData() or DEFAULT_SIZE

    def _sheet_wh(self):
        """The paper sheet chosen, portrait ``(w, h)`` mm, or ``None``."""
        return dict(SHEETS).get(self.sheet_combo.currentData())

    def _turn(self) -> str:
        return next((k for k, b in self.turn_buttons.items()
                     if b.isChecked()), "landscape")

    def _landscape(self) -> bool:
        return self._turn() == "landscape"

    def ratio(self):
        """Width over height the custom measures keep — the proportion
        chosen, turned — or ``None`` (free, or a paper sheet's own)."""
        if self._sheet_wh() is not None:
            return None
        value = dict(RATIOS).get(self.ratio_combo.currentData())
        if value is None:
            return None
        if value == "screen":
            w, h = self._screen_mm
            value = max(w, h) / max(min(w, h), 1e-9)
        if value == 1.0:
            return 1.0
        return value if self._landscape() else 1.0 / value

    def _set_measures(self, w: float, h: float) -> None:
        self._syncing = True
        try:
            self.w_box.setValue(round(w))
            self.h_box.setValue(round(h))
        finally:
            self._syncing = False

    def _on_mode(self, *_a) -> None:
        """Into «Custom» from another size: the screen's measures and
        shape to begin with, no paper sheet."""
        mode = self._size_mode()
        if mode == "custom" and self._last_mode != "custom":
            self._syncing = True
            self.sheet_combo.setCurrentIndex(0)
            self.ratio_combo.setCurrentIndex(
                self.ratio_combo.findData("screen"))
            w, h = self._screen_mm
            self.turn_buttons["landscape" if w >= h else "portrait"
                              ].setChecked(True)
            self._syncing = False
            self._set_measures(w, h)
        elif mode == "screen":
            self._set_measures(*self._screen_mm)
        self._last_mode = mode

    def _on_sheet(self, *_a) -> None:
        """A paper sheet: its measures, turned as the buttons say."""
        wh = self._sheet_wh()
        if wh is None or self._syncing:
            return
        w, h = wh
        if self._landscape():
            w, h = h, w
        self._set_measures(w, h)

    def _on_ratio(self, *_a) -> None:
        """A proportion: the height follows the width."""
        r = self.ratio()
        if r is not None and not self._syncing:
            self._set_measures(self.w_box.value(), self.w_box.value() / r)

    def _on_turn(self, *_a) -> None:
        if self._sheet_wh() is not None:
            self._on_sheet()
        elif self.ratio() is not None:
            self._on_ratio()
        else:
            # Free measures: the turn swaps them.
            w, h = self.w_box.value(), self.h_box.value()
            if w != h and (w > h) != self._landscape():
                self._set_measures(h, w)

    def _keep(self, moved: str) -> None:
        """Width or height typed: a paper sheet's measures changed are
        your own again; with a proportion, the other side follows."""
        if self._syncing or self._size_mode() != "custom":
            return
        wh = self._sheet_wh()
        if wh is not None:
            w, h = self.w_box.value(), self.h_box.value()
            if sorted((w, h)) != sorted(wh):
                self._syncing = True
                self.sheet_combo.setCurrentIndex(0)
                self.ratio_combo.setCurrentIndex(
                    self.ratio_combo.findData("free"))
                self._syncing = False
            return
        r = self.ratio()
        if r is None:
            return
        if moved == "w":
            self._set_measures(self.w_box.value(), self.w_box.value() / r)
        else:
            self._set_measures(self.h_box.value() * r, self.h_box.value())

    def _sync_sheet_controls(self) -> None:
        """The controls that depend on «Custom»: on with it — the paper
        sheet; the proportion when no sheet sets one; the millimetres and
        the turn (not for a square) — and off with anything else."""
        custom = self._size_mode() == "custom"
        no_sheet = self._sheet_wh() is None
        self.sheet_combo.setEnabled(custom)
        self.ratio_combo.setEnabled(custom and no_sheet)
        self.w_box.setEnabled(custom)
        self.h_box.setEnabled(custom)
        square = no_sheet and self.ratio() == 1.0
        for b in self.turn_buttons.values():
            b.setEnabled(custom and not square)
        if custom and no_sheet and self.ratio() is None:
            # Free measures: the turn shows their shape as you type.
            w, h = self.w_box.value(), self.h_box.value()
            if w != h:
                self.turn_buttons["landscape" if w > h else "portrait"
                                  ].setChecked(True)

    # ---- state ------------------------------------------------------------
    def _mode(self) -> str:
        return FACE_CHOICES[self.face_group.checkedId()][0]

    def _changed(self) -> None:
        mode = self._mode()
        self.note.setText(self._tips.get(mode, ""))
        shaded = mode in ("full", "colours", "default")
        self.as_view_box.setEnabled(shaded)
        self.shadows_box.setEnabled(shaded and self._shadows_available)
        self.axes_box.setEnabled(mode == "view" and self._axes_available)
        self._sync_sheet_controls()
        framing = (self._can_frame and self._area() == "view"
                   and self.preview_box.isChecked())
        self.preview.set_framing(framing)
        self.frame_hint.setVisible(framing)
        self.frame_reset.setVisible(self._can_frame)
        self.frame_reset.setEnabled(framing and self._frame != NO_FRAME)
        # «Selection»: with something selected, and not for the picture of
        # the view, which is the screen as it is.
        can_select = self._selection_available
        _set_item_enabled(self.area_combo,
                          self.area_combo.findData("selection"), can_select)
        if not can_select and self.area_combo.currentData() == "selection":
            self.area_combo.setCurrentIndex(0)
        if self._build is None or not getattr(self, "_advanced", True):
            return
        if not self.preview_box.isChecked():
            self._timer.stop()
            self.preview.setPixmap(QPixmap())
            self.preview.setText(tr("Preview off"))
            self.preview_note.setText("")
            return
        self.preview.setText("")
        self.preview_note.setText(tr("Working out the preview…"))
        self._timer.start()

    def _refresh_preview(self) -> None:
        if not self.preview_box.isChecked():
            return
        if self._previewing:
            self._timer.start()          # again once this one is done
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self._previewing = True
        try:
            with faces_progress(self, self._hold):
                text, _n = self._build(self.options(), self.paper(),
                                       preview=True)
        except SvgCancelled:
            self._previewing = False
            self._timer.stop()
            # Too slow to wait for: the preview goes off, as its box says.
            QApplication.restoreOverrideCursor()
            self.preview_box.setChecked(False)
            return
        except Exception as exc:  # noqa: BLE001
            self._previewing = False
            QApplication.restoreOverrideCursor()
            self.preview.setPixmap(QPixmap())
            self.preview_note.setText(str(exc))
            return
        self._previewing = False
        QApplication.restoreOverrideCursor()
        pixmap, page = svg_thumbnail_page(text, PREVIEW_W, PREVIEW_H)
        self.preview.show_sheet(pixmap, page)
        self.preview_note.setText(self._sheet_note(text))

    def _sheet_note(self, text: str) -> str:
        """«297 × 210 mm · scale 1:148» from the SVG; the size boxes show
        the measures the drawing's scale gave the sheet."""
        w = re.search(r'<svg[^>]* width="([\d.]+)mm"', text)
        h = re.search(r'<svg[^>]* height="([\d.]+)mm"', text)
        scale = re.search(r"<desc>([^<]*)</desc>", text)
        if not (w and h):
            return ""
        wv, hv = float(w.group(1)), float(h.group(1))
        if self._size_mode() == "scale":
            self._set_measures(wv, hv)
        return tr("{w} × {h} mm · scale {scale}", w=f"{wv:.0f}",
                  h=f"{hv:.0f}", scale=scale.group(1) if scale else "")

    # ---- the last choices -------------------------------------------------
    def _restore(self) -> None:
        st = self._settings

        def flag(name, default):
            v = st.value(_KEY + name, default)
            return str(v).lower() not in ("false", "0")

        key = st.value(_KEY + "faces", DEFAULT_FACES)
        self.face_buttons.get(str(key),
                              self.face_buttons[DEFAULT_FACES]).setChecked(True)
        self.as_view_box.setChecked(flag("as_view", True))
        self.shadows_box.setChecked(flag("shadows", True))
        self.axes_box.setChecked(flag("hide_axes", True))
        self.preview_box.setChecked(flag("preview", True))
        i = self.guides_combo.findData(str(st.value(_KEY + "guides",
                                                    DEFAULT_GUIDES)))
        self.guides_combo.setCurrentIndex(max(0, i))
        self.preview.set_guides(self.guides_combo.currentData())
        i = self.area_combo.findData(str(st.value(_KEY + "area",
                                                  DEFAULT_AREA)))
        self.area_combo.setCurrentIndex(max(0, i))
        turn = str(st.value(_KEY + "turn", "landscape"))
        self.turn_buttons.get(turn, self.turn_buttons["landscape"]
                              ).setChecked(True)
        self._syncing = True
        for combo, name, default in ((self.sheet_combo, "sheet", "none"),
                                     (self.ratio_combo, "ratio", "screen")):
            i = combo.findData(str(st.value(_KEY + name, default)))
            combo.setCurrentIndex(max(0, i))
        self._syncing = False
        try:
            w = float(st.value(_KEY + "width", self._screen_mm[0]))
            h = float(st.value(_KEY + "height", self._screen_mm[1]))
        except (TypeError, ValueError):
            w, h = self._screen_mm
        self._set_measures(w, h)
        i = self.size_combo.findData(str(st.value(_KEY + "size",
                                                  DEFAULT_SIZE)))
        self.size_combo.setCurrentIndex(
            i if i >= 0 else self.size_combo.findData(DEFAULT_SIZE))
        if self._size_mode() == "screen":
            self._set_measures(*self._screen_mm)

    def accept(self) -> None:
        st = self._settings
        st.setValue(_KEY + "faces", self._mode())
        st.setValue(_KEY + "as_view", self.as_view_box.isChecked())
        st.setValue(_KEY + "shadows", self.shadows_box.isChecked())
        st.setValue(_KEY + "hide_axes", self.axes_box.isChecked())
        st.setValue(_KEY + "preview", self.preview_box.isChecked())
        st.setValue(_KEY + "guides", self.guides_combo.currentData())
        st.setValue(_KEY + "area", self._area())
        st.setValue(_KEY + "size", self.size_combo.currentData())
        st.setValue(_KEY + "turn", self._turn())
        st.setValue(_KEY + "sheet", self.sheet_combo.currentData())
        st.setValue(_KEY + "ratio", self.ratio_combo.currentData())
        st.setValue(_KEY + "width", self.w_box.value())
        st.setValue(_KEY + "height", self.h_box.value())
        st.setValue(_KEY + "advanced", self._advanced)
        st.setValue(_KEY + "basic_faces", next(
            k for k, b in self.basic_buttons.items() if b.isChecked()))
        st.setValue(_KEY + "basic_size", self.basic_size.currentData())
        st.setValue(_KEY + "basic_lock", self.basic_lock.isChecked())
        st.setValue(_KEY + "basic_width", self.basic_w.value())
        st.setValue(_KEY + "basic_height", self.basic_h.value())
        self._timer.stop()
        super().accept()

    def reject(self) -> None:
        self._timer.stop()
        super().reject()

    # ---- what was asked ---------------------------------------------------
    def _area(self) -> str:
        return self.area_combo.currentData() or DEFAULT_AREA

    def options(self) -> dict | None:
        """``None`` for the lines alone, ``{"image": True}`` for the
        picture of the view (``"axes": False`` without the axes), else the
        face options of :func:`core.vista_caras.view_faces`."""
        if not self._advanced:
            face = next(k for k, b in self.basic_buttons.items()
                        if b.isChecked())
            opts = dict(FACE_CHOICES)[face]
        else:
            opts = FACE_CHOICES[self.face_group.checkedId()][1]
        if opts is None:
            return None
        if opts.get("image"):
            if self._axes_available and self.axes_box.isChecked():
                return {**opts, "axes": False}
            return opts
        return {**opts, "as_view": self.as_view_box.isChecked(),
                "shadows": self._shadows_available
                and self.shadows_box.isChecked()}

    # ---- the basic dialog ---------------------------------------------------
    def _basic_page(self, ink, frame_label: bool) -> QWidget:
        """The compact dialog: what to export — the picture of the view or
        its faces with their materials and textures — and the size, the
        screen's or your own millimetres, the lock keeping its proportion.
        One column, no preview: a quick export of the view as it is."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        hint = QLabel(tr("Quick export of the view as it is."))
        hint.setEnabled(False)
        lay.addWidget(hint)
        lay.addWidget(_title(tr("What to export")))
        texts = _face_texts()
        self.basic_group = QButtonGroup(self)
        self.basic_buttons = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        for i, key in enumerate(BASIC_FACES):
            label, tip = texts[key]
            pic = QLabel()
            pic.setPixmap(cube_preview(key, ICON_PX, ink=ink))
            pic.setFixedSize(ICON_PX, ICON_PX)
            pic.setToolTip(tip)
            btn = QRadioButton(label)
            btn.setToolTip(tip)
            pic.mousePressEvent = (lambda _e, b=btn: b.setChecked(True))
            self.basic_group.addButton(btn, i)
            self.basic_buttons[key] = btn
            grid.addWidget(pic, i, 0)
            grid.addWidget(btn, i, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        # The model's scenes, as in the advanced dialog (one choice for
        # both): only when there are scenes to show.
        self.basic_scene = QComboBox()
        for i in range(self.scene_combo.count()):
            self.basic_scene.addItem(self.scene_combo.itemText(i),
                                     self.scene_combo.itemData(i))
        self.basic_scene.setToolTip(self.scene_combo.toolTip())
        scene_title = _title(tr("Scene"))
        lay.addWidget(scene_title)
        lay.addWidget(self.basic_scene)
        has_scenes = bool(self._scenes) and self._on_scene is not None
        scene_title.setVisible(has_scenes)
        self.basic_scene.setVisible(has_scenes)
        self.basic_scene.currentIndexChanged.connect(
            self.scene_combo.setCurrentIndex)
        lay.addWidget(_title(tr("Export size")))
        self.basic_size = QComboBox()
        self.basic_size.addItem(tr("Like the frame") if frame_label
                                else tr("Like the screen"), "screen")
        self.basic_size.addItem(tr("Custom (mm)"), "custom")
        lay.addWidget(self.basic_size)
        self.basic_w, self.basic_h = QDoubleSpinBox(), QDoubleSpinBox()
        for box in (self.basic_w, self.basic_h):
            box.setRange(10.0, 10000.0)
            box.setDecimals(0)
            box.setSuffix(" mm")
        self.basic_lock = QToolButton()
        self.basic_lock.setCheckable(True)
        self.basic_lock.setAutoRaise(True)
        icon = QIcon()
        icon.addPixmap(_sheet_icon("unlock", ink), QIcon.Normal, QIcon.Off)
        icon.addPixmap(_sheet_icon("lock", ink), QIcon.Normal, QIcon.On)
        faint = QColor(ink)
        faint.setAlphaF(0.3)
        icon.addPixmap(_sheet_icon("lock", faint), QIcon.Disabled, QIcon.On)
        icon.addPixmap(_sheet_icon("unlock", faint), QIcon.Disabled,
                       QIcon.Off)
        self.basic_lock.setIcon(icon)
        self.basic_lock.setToolTip(tr(
            "Locked: change the width and the height follows, keeping the "
            "proportion. Open: each measure on its own."))
        sizes = QHBoxLayout()
        sizes.setSpacing(4)
        sizes.addWidget(self.basic_w, 1)
        sizes.addWidget(self.basic_lock)
        sizes.addWidget(self.basic_h, 1)
        lay.addLayout(sizes)
        lay.addStretch(1)
        self._basic_ratio = None
        return page

    def _basic_restore(self) -> None:
        st = self._settings
        key = str(st.value(_KEY + "basic_faces", DEFAULT_BASIC_FACES))
        self.basic_buttons.get(key, self.basic_buttons[DEFAULT_BASIC_FACES]
                               ).setChecked(True)
        i = self.basic_size.findData(str(st.value(_KEY + "basic_size",
                                                  DEFAULT_BASIC_SIZE)))
        self.basic_size.setCurrentIndex(max(0, i))
        lock = str(st.value(_KEY + "basic_lock", True)).lower()
        self.basic_lock.setChecked(lock not in ("false", "0"))
        w, h = self._screen_mm
        if self.basic_size.currentData() == "custom":
            try:
                w = float(st.value(_KEY + "basic_width", w))
                h = float(st.value(_KEY + "basic_height", h))
            except (TypeError, ValueError):
                w, h = self._screen_mm
        self._set_basic(w, h)
        self._basic_ratio = w / max(h, 1e-9)

    def _set_basic(self, w: float, h: float) -> None:
        self._syncing = True
        try:
            self.basic_w.setValue(round(w))
            self.basic_h.setValue(round(h))
        finally:
            self._syncing = False

    def _on_basic_size(self, *_a) -> None:
        """Like the screen: its measures, read only. Custom: the same
        measures, now yours to change."""
        if self.basic_size.currentData() == "screen":
            self._set_basic(*self._screen_mm)
            w, h = self._screen_mm
            self._basic_ratio = w / max(h, 1e-9)
        self._basic_changed()

    def _on_basic_lock(self, on: bool) -> None:
        if on:
            self._basic_ratio = (self.basic_w.value()
                                 / max(self.basic_h.value(), 1.0))

    def _basic_keep(self, moved: str) -> None:
        """With the lock closed, the other measure follows."""
        if (self._syncing or not self.basic_lock.isChecked()
                or not self._basic_ratio):
            return
        r = self._basic_ratio
        if moved == "w":
            self._set_basic(self.basic_w.value(), self.basic_w.value() / r)
        else:
            self._set_basic(self.basic_h.value() * r, self.basic_h.value())

    def _basic_changed(self) -> None:
        custom = self.basic_size.currentData() == "custom"
        for w in (self.basic_w, self.basic_h, self.basic_lock):
            w.setEnabled(custom)

    # ---- basic and advanced -------------------------------------------------
    def is_advanced(self) -> bool:
        return self._advanced

    def _set_advanced(self, on: bool) -> None:
        """Into the advanced dialog with what the basic one says, or back
        with what the advanced one says, as near as the basic can."""
        if on == self._advanced:
            return
        if on:
            key = self.basic_group.checkedButton()
            face = next(k for k, b in self.basic_buttons.items() if b is key)
            self.face_buttons[face].setChecked(True)
            self.area_combo.setCurrentIndex(self.area_combo.findData("view"))
            mode = self.basic_size.currentData()
            self.size_combo.setCurrentIndex(self.size_combo.findData(mode))
            if mode == "custom":
                self._syncing = True
                self.sheet_combo.setCurrentIndex(0)
                self.ratio_combo.setCurrentIndex(
                    self.ratio_combo.findData("free"))
                self._syncing = False
                self._set_measures(self.basic_w.value(),
                                   self.basic_h.value())
        else:
            face = self._mode() if self._mode() in BASIC_FACES else "full"
            self.basic_buttons[face].setChecked(True)
            screen = self._size_mode() == "screen"
            self.basic_size.setCurrentIndex(
                self.basic_size.findData("screen" if screen else "custom"))
            if not screen:
                self._set_basic(self.w_box.value(), self.h_box.value())
                self._basic_ratio = (self.basic_w.value()
                                     / max(self.basic_h.value(), 1.0))
        self._advanced = on
        self._show_mode()

    def _show_mode(self) -> None:
        self.basic_page.setVisible(not self._advanced)
        self.advanced_page.setVisible(self._advanced)
        if self._advanced:
            self._changed()
        else:
            self._timer.stop()
            self._basic_changed()
        self.layout().activate()
        self.adjustSize()
        self._recentre()

    def _recentre(self) -> None:
        """Keep the dialog centred on its window when it grows or shrinks
        between basic and advanced, and wholly on the screen."""
        if not self.isVisible():
            return
        host = self.parentWidget()
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry()
        centre = (host.window().frameGeometry().center() if host is not None
                  else avail.center())
        g = self.frameGeometry()
        g.moveCenter(centre)
        x = max(avail.left(), min(g.left(), avail.right() + 1 - g.width()))
        y = max(avail.top(), min(g.top(), avail.bottom() + 1 - g.height()))
        # move() places the frame's corner; the frame is what must fit.
        self.move(x, y)

    # ---- the framing ------------------------------------------------------
    def _on_pan(self, dx: float, dy: float) -> None:
        """The preview dragged by ``dx``, ``dy`` sheet widths and heights:
        the framing moves the other way — the drawing follows the hand."""
        px, py, zoom = self._frame
        self._frame = (px - dx / zoom, py + dy / zoom, zoom)
        self._changed()

    def _on_zoom(self, factor: float) -> None:
        px, py, zoom = self._frame
        self._frame = (px, py, min(50.0, max(0.05, zoom * factor)))
        self._changed()

    def scene_index(self):
        """The scene chosen (its index), or ``None``: the view as it is."""
        i = self.scene_combo.currentData()
        return None if i is None or i < 0 else int(i)

    def _on_scene_chosen(self, *_a) -> None:
        """Show the scene chosen — or the view as it was — and work out
        the preview from it, framed afresh."""
        if self.basic_scene.currentIndex() != self.scene_combo.currentIndex():
            self.basic_scene.blockSignals(True)
            self.basic_scene.setCurrentIndex(self.scene_combo.currentIndex())
            self.basic_scene.blockSignals(False)
        if self._on_scene is None:
            return
        build = self._on_scene(self.scene_index())
        if build is not None:
            self._build = build
        self._frame = NO_FRAME
        self._changed()

    def _reset_frame(self) -> None:
        self._frame = NO_FRAME
        self._changed()

    def paper(self) -> dict:
        """The sheet: ``{"area": "view" | "selection", "size":
        …}`` with
        ``size`` ``"screen"`` (the screen's own), ``None`` (at the
        drawing's scale) or ``(width_mm, height_mm)``."""
        if not self._advanced:
            # The basic dialog: the view as it is, at the screen's size or
            # your own millimetres.
            if self.basic_size.currentData() == "screen":
                return {"area": "view", "size": "screen"}
            return {"area": "view",
                    "size": (self.basic_w.value(), self.basic_h.value())}
        mode = self._size_mode()
        if mode == "screen":
            size = "screen"
        elif mode == "scale":
            size = None
        else:
            size = (self.w_box.value(), self.h_box.value())
        sheet = {"area": self._area(), "size": size}
        if self._can_frame and self._area() == "view" \
                and self._frame != NO_FRAME:
            sheet["frame"] = self._frame
        return sheet


class FramePreview(QLabel):
    """The preview, which also frames: drag to move what goes out, turn
    the wheel to zoom. The picture follows the hand at once — the sheet's
    drawing moved or scaled — and ``panned`` (in sheet widths and heights,
    right and down) or ``zoomed`` (a factor) tells the dialog, which works
    the real one out afterwards."""

    panned = Signal(float, float)
    zoomed = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.setAlignment(Qt.AlignCenter)
        self._sheet = QPixmap()
        self._page = QRectF()
        self._framing = False
        self._grab = None               # where the drag began
        self._shift = QPointF()         # how far the picture follows it
        self._scale = 1.0               # the wheel's zoom not yet worked out
        self._guides = "none"           # the composition guides on top

    def set_framing(self, on: bool) -> None:
        self._framing = on
        self.setCursor(Qt.OpenHandCursor if on else Qt.ArrowCursor)

    def show_sheet(self, pixmap: QPixmap, page: QRectF) -> None:
        """A newly worked-out sheet: no drag, no zoom pending."""
        self._sheet, self._page = pixmap, QRectF(page)
        self._shift, self._scale = QPointF(), 1.0
        self.setText("")
        self.setPixmap(pixmap)

    def mousePressEvent(self, event) -> None:
        if self._framing and event.button() == Qt.LeftButton \
                and not self._sheet.isNull():
            self._grab = event.position()
            self.setCursor(Qt.ClosedHandCursor)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._grab is not None:
            self._shift = event.position() - self._grab
            self._draw_moved()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._grab is None:
            super().mouseReleaseEvent(event)
            return
        self._grab = None
        self.setCursor(Qt.OpenHandCursor)
        w, h = self._page.width(), self._page.height()
        if w > 0 and h > 0 and (abs(self._shift.x()) > 1
                                or abs(self._shift.y()) > 1):
            self.panned.emit(self._shift.x() / w, self._shift.y() / h)

    def wheelEvent(self, event) -> None:
        if not self._framing or self._sheet.isNull():
            super().wheelEvent(event)
            return
        steps = event.angleDelta().y() / 120.0
        if not steps:
            return
        factor = 1.15 ** steps
        self._scale *= factor
        self._draw_moved()
        self.zoomed.emit(factor)

    def set_guides(self, key: str) -> None:
        self._guides = key if key in GUIDES else "none"
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._guides != "none" and not self._page.isEmpty():
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            draw_guides(p, self._page, self._guides)
            p.end()

    def _draw_moved(self) -> None:
        """The last sheet with its drawing moved and scaled as the hand
        asks, inside the sheet's own edge."""
        out = QPixmap(self._sheet.size())
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.drawPixmap(0, 0, self._sheet)
        p.setClipRect(self._page)
        p.fillRect(self._page, Qt.white)
        c = self._page.center()
        p.translate(c + self._shift)
        p.scale(self._scale, self._scale)
        p.translate(-c)
        p.drawPixmap(0, 0, self._sheet)
        p.end()
        self.setPixmap(out)


def draw_guides(p: QPainter, page: QRectF, key: str) -> None:
    """The composition guides ``key`` over the sheet ``page``: a light
    line over a dark one, so they read on paper and on a picture alike."""
    x0, y0, w, h = page.x(), page.y(), page.width(), page.height()
    lines = []

    def across(fracs):
        for f in fracs:
            lines.append(QLineF(x0 + f * w, y0, x0 + f * w, y0 + h))
            lines.append(QLineF(x0, y0 + f * h, x0 + w, y0 + f * h))

    if key == "thirds":
        across((1.0 / 3.0, 2.0 / 3.0))
    elif key == "golden":
        across((1.0 - GOLDEN, GOLDEN))
    elif key == "grid":
        across((0.25, 0.5, 0.75))
    elif key == "diagonals":
        lines.append(QLineF(page.topLeft(), page.bottomRight()))
        lines.append(QLineF(page.bottomLeft(), page.topRight()))
    elif key == "centre":
        c = page.center()
        arm = min(w, h) * 0.12
        lines.append(QLineF(c.x() - arm, c.y(), c.x() + arm, c.y()))
        lines.append(QLineF(c.x(), c.y() - arm, c.x(), c.y() + arm))
    if not lines:
        return
    ring = min(w, h) * 0.04 if key == "centre" else 0.0
    p.save()
    p.setClipRect(page)
    p.setBrush(Qt.NoBrush)
    for pen in (QPen(QColor(0, 0, 0, 90), 2.2),
                QPen(QColor(255, 255, 255, 200), 1.0)):
        p.setPen(pen)
        p.drawLines(lines)
        if ring:
            p.drawEllipse(page.center(), ring, ring)
    p.restore()


class UpwardComboBox(QComboBox):
    """A drop-down that opens upwards: low in the dialog, a list dropping
    below runs past the dialog's foot and, near the screen's, off it —
    the eye then hunts for the list instead of the next choice. It opens
    below only when there is no room above."""

    def showPopup(self) -> None:
        super().showPopup()
        popup = self.view().window()
        top = self.mapToGlobal(QPoint(0, 0)).y() - popup.height()
        screen = self.screen()
        if screen is None or top >= screen.availableGeometry().top():
            popup.move(popup.x(), top)


def _set_item_enabled(combo: QComboBox, row: int, on: bool) -> None:
    item = combo.model().item(row)
    if item is not None:
        flags = item.flags()
        item.setFlags(flags | Qt.ItemIsEnabled if on
                      else flags & ~Qt.ItemIsEnabled)


def _title(text: str) -> QLabel:
    """A section's title, bold, as the side panels head theirs."""
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    label.setContentsMargins(0, 6, 0, 2)
    return label


def _sheet_icon(key: str, ink: QColor, size: int = 18) -> QPixmap:
    """The small icons: a sheet lying down (landscape) or standing up
    (portrait), a padlock closed (lock) or open (unlock)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(ink, 1.4))
    s = size / 18.0
    if key == "landscape":
        p.drawRect(QRectF(2 * s, 5 * s, 14 * s, 9 * s))
    elif key in ("lock", "unlock"):
        p.drawRoundedRect(QRectF(4 * s, 8 * s, 10 * s, 8 * s), 1.5, 1.5)
        if key == "lock":
            p.drawArc(QRectF(5.5 * s, 2.5 * s, 7 * s, 9 * s), 0, 180 * 16)
        else:
            # The shackle open, swung up to the right.
            p.drawArc(QRectF(8.5 * s, 1.0 * s, 7 * s, 9 * s), 0, 180 * 16)
    else:
        p.drawRect(QRectF(4.5 * s, 2 * s, 9 * s, 14 * s))
    p.end()
    return pm


def svg_thumbnail(text: str, width: int, height: int) -> QPixmap:
    """The SVG ``text`` drawn as a sheet of paper fitted into ``width`` ×
    ``height`` pixels (see :func:`svg_thumbnail_page`)."""
    return svg_thumbnail_page(text, width, height)[0]


def svg_thumbnail_page(text: str, width: int, height: int):
    """The SVG ``text`` drawn as a sheet of paper — white, edged, with a
    soft shadow — fitted into ``width`` × ``height`` pixels: ``(pixmap,
    the sheet's rectangle in it)``."""
    from PySide6.QtSvg import QSvgRenderer
    pm = QPixmap(width, height)
    pm.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(text.encode("utf-8")))
    size = r.defaultSize()
    if not r.isValid() or size.width() <= 0 or size.height() <= 0:
        return pm, QRectF()
    pad = 8.0
    k = min((width - 2 * pad) / size.width(),
            (height - 2 * pad) / size.height())
    w, h = size.width() * k, size.height() * k
    page = QRectF((width - w) / 2.0, (height - h) / 2.0, w, h)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.fillRect(page.translated(3, 3), QColor(0, 0, 0, 60))
    p.fillRect(page, Qt.white)
    # Qt's renderer draws past the viewBox; the file itself is cut there.
    p.save()
    p.setClipRect(page)
    r.render(p, page)
    p.restore()
    p.setPen(QPen(QColor(150, 150, 150), 1))
    p.drawRect(page)
    p.end()
    return pm, page


class SvgCancelled(Exception):
    """The person stopped the visible faces being worked out."""


#: Seconds of work before the bar shows: a small model never sees it.
PROGRESS_AFTER = 0.5


@contextmanager
def faces_progress(parent, hold=None):
    """Within it, working out the visible faces of a view shows a bar
    with Cancel over ``parent`` once it has taken half a second; Cancel
    raises :class:`SvgCancelled` where the work is.

    A plaza of 90 000 faces froze the window for minutes, exporting or
    previewing «Faces in colour», with nothing to say it was working nor
    a way to stop. ``hold``: a widget that does not paint meanwhile — the
    view, whose camera the export moves while it works."""
    from core import vista_caras
    started = time.monotonic()
    box = []

    def progress(done):
        if not box:
            if time.monotonic() - started < PROGRESS_AFTER:
                return
            dlg = QProgressDialog(tr("Working out the visible faces…"),
                                  tr("Cancel"), 0, 1000, parent)
            dlg.setWindowTitle(tr("Export SVG"))
            dlg.setWindowModality(Qt.WindowModal)
            dlg.setMinimumDuration(0)
            dlg.setAutoClose(False)
            dlg.setAutoReset(False)
            # The wait cursor of the work is not over Cancel.
            QApplication.setOverrideCursor(Qt.ArrowCursor)
            box.append(dlg)
            dlg.show()
        dlg = box[0]
        dlg.setValue(int(round(done * 1000)))
        QApplication.processEvents()
        if dlg.wasCanceled():
            raise SvgCancelled()

    held = hold is not None and hold.updatesEnabled()
    if held:
        hold.setUpdatesEnabled(False)
    try:
        with vista_caras.reporting(progress):
            yield
    finally:
        if box:
            QApplication.restoreOverrideCursor()
            box[0].close()
            box[0].deleteLater()
        if held:
            hold.setUpdatesEnabled(True)


def ask_svg_options(parent, build=None, base_label: str | None = None,
                    shadows_available: bool = False,
                    screen_label: str | None = None,
                    axes_available: bool = False, screen_mm=None,
                    view_label: str | None = None,
                    selection_available: bool = False,
                    can_frame: bool = False, scenes=None, on_scene=None,
                    hold=None):
    """Show the dialog: ``(accepted, options, sheet)`` as
    :meth:`ExportSvgDialog.options` and :meth:`ExportSvgDialog.paper`
    give them. ``scenes`` (names) and ``on_scene`` offer the model's scenes
    in the advanced dialog; ``hold``, the view (see :func:`faces_progress`)."""
    dlg = ExportSvgDialog(parent, build, base_label, shadows_available,
                          screen_label, axes_available, screen_mm, view_label,
                          selection_available, can_frame, scenes=scenes,
                          on_scene=on_scene, hold=hold)
    ok = bool(dlg.exec())
    opts, sheet = dlg.options(), dlg.paper()
    dlg.deleteLater()
    return ok, opts, sheet
