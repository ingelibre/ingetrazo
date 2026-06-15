"""Right-side dockable tray (SketchUp-style), built from QDockWidget.

Holds collapsible sections:
- **Materiales** — a palette of colour + texture swatches ("En el modelo" and a
  bundled "Biblioteca"). Clicking a swatch makes it the active Paint material
  and switches to the Paint tool. ``+ Textura…`` adds an image with a tile size.
- **Estilo de cota** — precision, unit, font size and colour of dimensions,
  applied live to ``scene.dimension_style``.
- **Info de entidad** — read-only facts about the current selection (face area,
  edge length, dimension value, material).

A ``QDockWidget`` gives docking/floating/closing for free; the sections are a
vertical stack of lightweight collapsibles inside a scroll area.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.mesh import Edge, Face
from core.group import Group
from core.dimension import Dimension
from tools.paint import PaintTool

_TEX_DIR = Path(__file__).resolve().parent.parent / "resources" / "textures"
_SWATCH = 44  # swatch pixel size

# A small starter colour set for the library row.
_LIBRARY_COLORS = [
    (0.92, 0.89, 0.81), (0.80, 0.45, 0.30), (0.20, 0.45, 0.75),
    (0.45, 0.62, 0.35), (0.85, 0.78, 0.45), (0.55, 0.55, 0.58),
    (0.30, 0.30, 0.33), (0.95, 0.95, 0.95),
]


class _Section(QWidget):
    """A collapsible section: a header button that toggles its content."""

    def __init__(self, title: str, content: QWidget) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._btn = QToolButton()
        self._btn.setText(f"  {title}")
        self._btn.setCheckable(True)
        self._btn.setChecked(True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._btn.setArrowType(Qt.DownArrow)
        self._btn.setStyleSheet(
            "QToolButton { font-weight: bold; padding: 6px; border: none;"
            " background: #2d3340; color: #e8ebf0; text-align: left; }")
        self._btn.toggled.connect(self._on_toggle)
        self._content = content
        lay.addWidget(self._btn)
        lay.addWidget(content)

    def _on_toggle(self, on: bool) -> None:
        self._content.setVisible(on)
        self._btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)


def _color_pixmap(rgb, size=_SWATCH) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor.fromRgbF(*rgb))
    return pm


def _texture_pixmap(path, size=_SWATCH) -> QPixmap | None:
    img = QImage(str(path))
    if img.isNull():
        return None
    return QPixmap.fromImage(img.scaled(size, size, Qt.IgnoreAspectRatio,
                                        Qt.SmoothTransformation))


def _swatch_button(pm: QPixmap, tip: str) -> QToolButton:
    b = QToolButton()
    b.setIcon(QIcon(pm))
    b.setIconSize(QSize(_SWATCH, _SWATCH))
    b.setToolTip(tip)
    b.setAutoRaise(True)
    return b


class MaterialsPanel(QWidget):
    """Swatch palette: pick a colour/texture to paint with."""

    COLS = 5

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._tile_size = 1.0
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)

        # Active material preview.
        row = QHBoxLayout()
        row.addWidget(QLabel("Activo:"))
        self._preview = QLabel()
        self._preview.setFixedSize(_SWATCH, _SWATCH)
        self._preview.setFrameShape(QFrame.Box)
        row.addWidget(self._preview)
        row.addStretch(1)
        root.addLayout(row)

        root.addWidget(self._heading("En el modelo"))
        self._in_model_grid = QGridLayout()
        self._in_model_grid.setSpacing(3)
        root.addLayout(self._in_model_grid)

        root.addWidget(self._heading("Biblioteca"))
        lib_grid = QGridLayout()
        lib_grid.setSpacing(3)
        root.addLayout(lib_grid)
        self._fill_library(lib_grid)

        btns = QHBoxLayout()
        add_color = QPushButton("+ Color…")
        add_color.clicked.connect(self._add_color)
        add_tex = QPushButton("+ Textura…")
        add_tex.clicked.connect(self._add_texture)
        btns.addWidget(add_color)
        btns.addWidget(add_tex)
        root.addLayout(btns)
        root.addStretch(1)

        self._refresh_preview()
        self.refresh_in_model()

    def _heading(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#9aa3b2; margin-top:6px; font-size:11px;")
        return lbl

    # ---- Library + in-model swatches ---------------------------------------
    def _fill_library(self, grid: QGridLayout) -> None:
        i = 0
        for rgb in _LIBRARY_COLORS:
            b = _swatch_button(_color_pixmap(rgb), "Color")
            b.clicked.connect(lambda _=False, c=rgb: self._apply_color(c))
            grid.addWidget(b, i // self.COLS, i % self.COLS)
            i += 1
        for path in sorted(_TEX_DIR.glob("*.png")):
            pm = _texture_pixmap(path)
            if pm is None:
                continue
            b = _swatch_button(pm, path.stem)
            b.clicked.connect(lambda _=False, p=str(path): self._apply_texture(p))
            grid.addWidget(b, i // self.COLS, i % self.COLS)
            i += 1

    def refresh_in_model(self) -> None:
        """Rebuild the 'En el modelo' swatches from the materials in use."""
        while self._in_model_grid.count():
            item = self._in_model_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        colors: dict = {}
        textures: dict = {}
        for face in self._window.viewport.scene.render_faces():
            tex = face.attrs.get("texture")
            if tex and tex.get("path"):
                textures.setdefault(tex["path"], tex)
            else:
                col = face.attrs.get("color")
                if col is not None:
                    colors[tuple(col)] = col
        i = 0
        for col in colors.values():
            b = _swatch_button(_color_pixmap(tuple(col)), "Color")
            b.clicked.connect(lambda _=False, c=tuple(col): self._apply_color(c))
            self._in_model_grid.addWidget(b, i // self.COLS, i % self.COLS)
            i += 1
        for path, tex in textures.items():
            pm = _texture_pixmap(path)
            if pm is None:
                continue
            b = _swatch_button(pm, Path(path).stem)
            b.clicked.connect(
                lambda _=False, t=dict(tex): self._apply_texture(
                    t["path"], t.get("sw", 1.0)))
            self._in_model_grid.addWidget(b, i // self.COLS, i % self.COLS)
            i += 1

    # ---- Apply / add --------------------------------------------------------
    def _apply_color(self, rgb) -> None:
        PaintTool.current_color = tuple(rgb)
        PaintTool.current_texture = None
        self._window._activate_tool("paint")
        self._refresh_preview()

    def _apply_texture(self, path: str, size: float | None = None) -> None:
        sz = self._tile_size if size is None else size
        PaintTool.current_texture = {"path": path, "sw": sz, "sh": sz}
        self._window._activate_tool("paint")
        self._refresh_preview()

    def _add_color(self) -> None:
        r, g, b = PaintTool.current_color
        chosen = QColorDialog.getColor(QColor.fromRgbF(r, g, b), self, "Color")
        if chosen.isValid():
            self._apply_color((chosen.redF(), chosen.greenF(), chosen.blueF()))

    def _add_texture(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Elegir textura", str(_TEX_DIR),
            "Imágenes (*.png *.jpg *.jpeg *.bmp);;Todos (*)")
        if not path_str:
            return
        size, ok = QInputDialog.getDouble(
            self, "Tamaño de textura", "Tamaño real de un tile (metros):",
            self._tile_size, 0.001, 1000.0, 3)
        if not ok:
            return
        self._tile_size = size
        self._apply_texture(path_str, size)

    def _refresh_preview(self) -> None:
        if PaintTool.current_texture is not None:
            pm = _texture_pixmap(PaintTool.current_texture["path"])
            if pm is not None:
                self._preview.setPixmap(pm)
                return
        self._preview.setPixmap(_color_pixmap(PaintTool.current_color))


class DimensionStylePanel(QWidget):
    """Live editor for ``scene.dimension_style``."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 6, 8, 8)
        style = self._style()

        grid.addWidget(QLabel("Decimales:"), 0, 0)
        self._decimals = QSpinBox()
        self._decimals.setRange(0, 4)
        self._decimals.setValue(int(style.get("decimals", 2)))
        self._decimals.valueChanged.connect(self._apply)
        grid.addWidget(self._decimals, 0, 1)

        grid.addWidget(QLabel("Unidad:"), 1, 0)
        self._units = QComboBox()
        self._units.addItems(["m", "cm", "mm"])
        self._units.setCurrentText(style.get("units", "m"))
        self._units.currentTextChanged.connect(self._apply)
        grid.addWidget(self._units, 1, 1)

        grid.addWidget(QLabel("Fuente:"), 2, 0)
        self._font = QSpinBox()
        self._font.setRange(6, 28)
        self._font.setValue(int(style.get("font_size", 9)))
        self._font.valueChanged.connect(self._apply)
        grid.addWidget(self._font, 2, 1)

        grid.addWidget(QLabel("Color:"), 3, 0)
        self._color_btn = QPushButton()
        self._color_btn.clicked.connect(self._pick_color)
        grid.addWidget(self._color_btn, 3, 1)
        self._refresh_color_btn()

    def _style(self) -> dict:
        return self._window.viewport.scene.dimension_style

    def _apply(self) -> None:
        style = self._style()
        style["decimals"] = self._decimals.value()
        style["units"] = self._units.currentText()
        style["font_size"] = self._font.value()
        self._window.viewport.scene.version += 1
        self._window.viewport.update()

    def _pick_color(self) -> None:
        c = self._style().get("color", [45, 55, 75])
        chosen = QColorDialog.getColor(QColor(c[0], c[1], c[2]), self,
                                       "Color de cota")
        if chosen.isValid():
            self._style()["color"] = [chosen.red(), chosen.green(), chosen.blue()]
            self._refresh_color_btn()
            self._apply()

    def _refresh_color_btn(self) -> None:
        c = self._style().get("color", [45, 55, 75])
        self._color_btn.setStyleSheet(
            f"background: rgb({c[0]},{c[1]},{c[2]}); min-height: 18px;")


class EntityInfoPanel(QWidget):
    """Read-only facts about the current selection."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        self._label = QLabel("Nada seleccionado")
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.RichText)
        self._label.setStyleSheet("font-size: 12px;")
        lay.addWidget(self._label)

    def refresh(self) -> None:
        sel = list(self._window.viewport.scene.selection)
        self._label.setText(self._describe(sel))

    def _describe(self, sel: list) -> str:
        if not sel:
            return "Nada seleccionado"
        if len(sel) == 1:
            e = sel[0]
            if isinstance(e, Face):
                mat = self._material_of(e)
                return (f"<b>Cara</b><br>Área: {e.area():.3f} m²<br>"
                        f"Vértices: {len(e.vertices)}<br>Material: {mat}")
            if isinstance(e, Edge):
                return f"<b>Arista</b><br>Largo: {(e.b - e.a).length():.3f} m"
            if isinstance(e, Dimension):
                return f"<b>Cota</b><br>Medida: {e.value():.3f} m"
            if isinstance(e, Group):
                return f"<b>Grupo</b><br>Caras: {len(e.mesh.faces)}"
            return "<b>1 entidad</b>"
        counts = {"caras": 0, "aristas": 0, "cotas": 0, "grupos": 0}
        for e in sel:
            if isinstance(e, Face):
                counts["caras"] += 1
            elif isinstance(e, Edge):
                counts["aristas"] += 1
            elif isinstance(e, Dimension):
                counts["cotas"] += 1
            elif isinstance(e, Group):
                counts["grupos"] += 1
        parts = [f"{n} {k}" for k, n in counts.items() if n]
        return "<b>Selección</b><br>" + ", ".join(parts)

    @staticmethod
    def _material_of(face) -> str:
        tex = face.attrs.get("texture")
        if tex and tex.get("path"):
            return Path(tex["path"]).stem
        col = face.attrs.get("color")
        if col is not None:
            return f"color {tuple(round(c, 2) for c in col)}"
        return "—"


class Tray(QDockWidget):
    """The right-side tray assembling the three panels."""

    def __init__(self, window) -> None:
        super().__init__("Bandeja", window)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetFloatable)

        self.materials = MaterialsPanel(window)
        self.dim_style = DimensionStylePanel(window)
        self.entity_info = EntityInfoPanel(window)

        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(_Section("Materiales", self.materials))
        col.addWidget(_Section("Estilo de cota", self.dim_style))
        col.addWidget(_Section("Info de entidad", self.entity_info))
        col.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setMinimumWidth(240)
        self.setWidget(scroll)

    def on_scene_changed(self) -> None:
        """React to a scene/version change: refresh selection-driven views."""
        self.entity_info.refresh()
        self.materials.refresh_in_model()
