# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The legend's rows edited on the sheet, QGIS-style, and a background for
the scale bar, the north arrow and the legend (Marco, 19-11: «debería poder
editar cada capa en lámina cambiando el nombre, color del layer… como
agregar otras capas o líneas en leyenda»; «barra de escala gráfica como
brújula cuando la pongo sobre un mapa como que se pierde»)."""
from __future__ import annotations

import json
import pathlib

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: F401 — legacy copy
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen  # noqa: F401
from PySide6.QtWidgets import QApplication, QWidget

from core.composition import (BarraEscala, Composicion, EditItemCommand,
                              FlechaNorte, FormaItem, Leyenda,
                              free_legend_entry, legend_entries,
                              refreshed_legend_entries)
from core.i18n import tr  # noqa: F401 — legacy copy
from views.composer import (ComposerWindow, LeyendaItem, ScaleBarItem,
                            _draw_text_mm, paint_leyenda_mm,  # noqa: F401
                            paint_norte_mm, paint_scalebar_mm)

_app = QApplication.instance() or QApplication([])


# ---- the legend exactly as it drew before rows could be edited -------------
# A frozen copy of the old painter: an old legend must draw pixel for pixel
# the same through the new one.
def _legacy_paint_leyenda_mm(painter, le) -> None:
    r = QRectF(0, 0, le.w_mm, le.h_mm)
    painter.fillRect(r, QColor(255, 255, 255))
    pen = QPen(QColor(30, 36, 44))
    pen.setWidthF(0.3)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(r)
    _draw_text_mm(painter, QRectF(2, 1.4, le.w_mm - 4, 5), le.title,
                  3.2, bold=True)
    y = 7.5
    rows = le.rows or [tr("(no layers)")]
    from core.layers import LINETYPES
    swatches = getattr(le, "swatches", None) or {}
    for name in rows:
        sw = swatches.get(name) or {}
        rgb = sw.get("color")
        fill = (QColor.fromRgbF(*[float(c) for c in rgb[:3]])
                if isinstance(rgb, (list, tuple)) and len(rgb) >= 3
                else QColor(226, 232, 238))
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(QColor(30, 36, 44), 0.2))
        painter.drawRect(QRectF(2.2, y + 0.8, 4.0, 3.2))
        hatch = sw.get("hatch")
        if hatch:
            # The layer's cut hatch over its colour, as on the cut.
            from PySide6.QtGui import QPainterPath
            from views.hatch_paint import paint_hatch
            box = QPainterPath()
            box.addRect(QRectF(2.2, y + 0.8, 4.0, 3.2))
            under = sw.get("hatch_ground")
            own = sw.get("hatch_color")
            paint_hatch(painter, box, hatch,
                        QColor.fromRgbF(*[float(c) for c in own[:3]])
                        if isinstance(own, (list, tuple)) and len(own) >= 3
                        else QColor(30, 36, 44), 0.12, 0.6,
                        angle=float(sw.get("hatch_angle", 0.0) or 0.0),
                        families=sw.get("hatch_families"),
                        ground=(QColor.fromRgbF(*[float(c)
                                                  for c in under[:3]])
                                if isinstance(under, (list, tuple))
                                and len(under) >= 3
                                else QColor(255, 255, 255)
                                if hatch != "solid" else None))
            painter.setPen(QPen(QColor(30, 36, 44), 0.2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(2.2, y + 0.8, 4.0, 3.2))
        pattern = (sw.get("pattern")
                   or LINETYPES.get(sw.get("linetype"), ()))
        if pattern:
            # The layer's line type, drawn across the swatch.
            line = QPen(QColor(30, 36, 44), 0.25)
            line.setCapStyle(Qt.FlatCap)
            line.setDashPattern([max(0.05, d) / 0.25 * 0.4 for d in pattern])
            painter.setPen(line)
            painter.drawLine(QPointF(2.2, y + 2.4), QPointF(6.2, y + 2.4))
        _draw_text_mm(painter, QRectF(8, y + 0.7, le.w_mm - 10, 5),
                      name, 2.8)
        y += 5.5


def _render(paint, model, w_mm=60.0, h_mm=60.0, scale=10, ox=5.0, oy=5.0):
    img = QImage(int(w_mm * scale), int(h_mm * scale), QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(scale, scale)
    p.translate(ox, oy)
    paint(p, model)
    p.end()
    return img


_OLD_SWATCHES = {
    "Muros": {"color": [0.8, 0.2, 0.1], "linetype": "continuous"},
    "Ejes": {"color": [0.1, 0.3, 0.9], "linetype": "center"},
    "Propio": {"color": [0.2, 0.6, 0.2], "linetype": "lin:mio",
               "pattern": [2.0, 1.0, 0.5, 1.0]},
    "Corte": {"color": [1.0, 1.0, 1.0], "linetype": "continuous",
              "hatch": "crosshatch", "hatch_color": [0.4, 0.0, 0.0]},
}


def _old_record():
    """A legend as an older IngeTrazo saved it: no entries, no background."""
    le = Leyenda(x_mm=10.0, y_mm=12.0, w_mm=48.0, title="LEYENDA",
                 rows=["Muros", "Ejes", "Propio", "Corte", "Sin muestra"],
                 swatches=dict(_OLD_SWATCHES))
    from dataclasses import asdict
    d = asdict(le)
    for k in ("entries", "bg_color", "bg_opacity", "bg_margin_mm"):
        d.pop(k)
    return d


def test_an_old_legend_opens_and_draws_exactly_as_before():
    comp = Composicion.from_dict({"name": "L", "leyendas": [_old_record()]})
    le = comp.leyendas[0]
    assert le.entries is None and le.bg_color == "#ffffff"
    assert le.bg_margin_mm == 0.0 and le.bg_opacity == 1.0
    assert _render(paint_leyenda_mm, le) == _render(
        _legacy_paint_leyenda_mm, le)
    empty = Leyenda(rows=[])
    assert _render(paint_leyenda_mm, empty) == _render(
        _legacy_paint_leyenda_mm, empty)


def test_the_rows_made_entries_draw_the_same_too():
    """The first edit turns rows + swatches into entries; untouched, they
    draw as before."""
    comp = Composicion.from_dict({"name": "L", "leyendas": [_old_record()]})
    le = comp.leyendas[0]
    before = _render(paint_leyenda_mm, le)
    le.entries = legend_entries(le)
    assert [e["label"] for e in le.entries] == le.rows
    assert _render(paint_leyenda_mm, le) == before


def test_entries_are_copies_of_the_snapshot():
    le = Leyenda(rows=["Muros"], swatches={"Muros": {"color": [1, 0, 0]}})
    legend_entries(le)[0]["color"][0] = 0.0
    assert le.swatches["Muros"]["color"] == [1, 0, 0]


def test_old_scale_bar_and_north_arrow_have_no_background():
    from dataclasses import asdict
    for kind, key, paint in ((BarraEscala, "scalebars", paint_scalebar_mm),
                             (FlechaNorte, "nortes", paint_norte_mm)):
        d = asdict(kind())
        for k in ("bg_color", "bg_opacity", "bg_margin_mm"):
            d.pop(k)
        m = getattr(Composicion.from_dict({"name": "L", key: [d]}), key)[0]
        assert m.bg_color == ""
        img = _render(paint, m, w_mm=130.0, h_mm=30.0)
        # 1 mm left of the drawing, where a margin would be: still clear
        assert QColor.fromRgba(img.pixel(int(4.0 * 10), int(5.5 * 10))
                               ).alpha() == 0


# ---- the background in the painter (canvas and exports share it) ----------

def _bg_pixel(paint, m):
    """The pixel 0.5 mm left of the drawing, inside a 1 mm margin."""
    img = _render(paint, m, w_mm=140.0, h_mm=40.0)
    if isinstance(m, BarraEscala):
        from views.composer import scalebar_ink_rect
        x = scalebar_ink_rect(m).left() - 0.5
    else:
        x = -0.5
    return QColor.fromRgba(img.pixel(int((5.0 + x) * 10), int(5.5 * 10)))


@pytest.mark.parametrize("kind,paint", [(BarraEscala, paint_scalebar_mm),
                                        (FlechaNorte, paint_norte_mm),
                                        (Leyenda, paint_leyenda_mm)])
def test_the_background_is_painted_behind(kind, paint):
    m = kind(bg_color="#ffffff", bg_margin_mm=1.0)
    c = _bg_pixel(paint, m)
    assert (c.red(), c.green(), c.blue(), c.alpha()) == (255, 255, 255, 255)
    m.bg_color = ""
    assert _bg_pixel(paint, m).alpha() == 0
    m.bg_color, m.bg_opacity = "#ff0000", 0.5
    c = _bg_pixel(paint, m)
    assert c.red() > 200 and c.green() < 30 and 100 < c.alpha() < 160


def test_the_scale_bar_background_covers_its_labels():
    from views.composer import scalebar_ink_rect
    sb = BarraEscala(scale_n=100.0, segments=4)
    r = scalebar_ink_rect(sb)
    assert r.left() < 0 and r.right() > sb.w_mm and r.bottom() > 8.5


# ---- the composer: panel, undo, refresh, save, exports ---------------------

class _FakeViewport:
    def __init__(self):
        from core.camera import OrbitCamera
        from core.scene import Scene
        self.scene = Scene()
        self.camera = OrbitCamera()

    def update(self):
        pass


@pytest.fixture
def composer(monkeypatch):
    from core.layers import Layer
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    host = QWidget()
    host.viewport = _FakeViewport()
    scene = host.viewport.scene
    scene.layers = [Layer("Layer0"), Layer("Muros", color=(0.8, 0.2, 0.1)),
                    Layer("Ejes", color=(0.1, 0.3, 0.9), linetype="center"),
                    Layer("Oculta", visible=False)]
    win = ComposerWindow(host)
    win._host_keep = host
    yield win
    win._dirty = False
    win.close()


def _settle():
    for _ in range(3):
        _app.processEvents()


def _add_legend(win):
    from core.composition import AddItemCommand
    from core.layers import legend_rows
    rows, sw = legend_rows(win._scene())
    le = Leyenda(x_mm=30.0, y_mm=30.0, rows=rows, swatches=sw)
    win.history.execute(AddItemCommand(win.comp, le))
    _settle()
    _select(win, le)
    return le


def _select(win, model):
    win.canvas.clearSelection()
    for it in win.canvas.items():
        if getattr(it, "model", None) is model:
            it.force_select()
    _settle()
    return win._selected_item()


def _undo(win, model):
    assert win.history.undo()
    _settle()
    _select(win, model)


def _labels(le):
    return [e["label"] for e in legend_entries(le)]


def test_the_panel_lists_the_rows(composer):
    le = _add_legend(composer)
    assert isinstance(composer._selected_item(), LeyendaItem)
    assert composer.props.currentIndex() == 7
    shown = [composer.ley_rows.item(i).text()
             for i in range(composer.ley_rows.count())]
    assert shown == ["Layer0", "Muros", "Ejes"] == _labels(le)


def test_edit_a_row_text_colour_symbol_and_line_type_with_undo(
        composer, monkeypatch):
    le = _add_legend(composer)
    layer = composer._scene().layers[1]
    composer.ley_rows.setCurrentRow(1)
    composer.ley_label.setText("Muros de ladrillo")
    composer.ley_label.editingFinished.emit()
    assert _labels(le)[1] == "Muros de ladrillo"
    assert layer.name == "Muros"                     # the model is untouched
    assert le.entries[1]["layer"] == "Muros" and le.entries[1]["edited"]
    _undo(composer, le)
    assert le.entries is None and _labels(le)[1] == "Muros"

    composer.ley_rows.setCurrentRow(1)
    import views.composer as vc
    monkeypatch.setattr(vc, "get_color", lambda *a, **k: QColor(0, 255, 0))
    composer._on_ley_color()
    assert le.entries[1]["color"] == [0.0, 1.0, 0.0]
    assert layer.color != (0.0, 1.0, 0.0)
    composer.ley_symbol.setCurrentIndex(composer.ley_symbol.findData("line"))
    assert le.entries[1]["symbol"] == "line"
    composer.ley_linetype.setCurrentIndex(
        composer.ley_linetype.findData("dashed"))
    assert le.entries[1]["linetype"] == "dashed"
    assert layer.linetype == "continuous"
    _undo(composer, le)
    assert le.entries[1]["linetype"] == "continuous"
    _undo(composer, le)
    assert le.entries[1].get("symbol", "") == ""
    _undo(composer, le)
    assert le.entries is None


def test_an_edited_row_draws_what_the_user_picked(composer):
    le = _add_legend(composer)
    before = _render(paint_leyenda_mm, le)
    composer.ley_rows.setCurrentRow(0)
    composer.ley_symbol.setCurrentIndex(composer.ley_symbol.findData("line"))
    assert _render(paint_leyenda_mm, le) != before


def test_add_a_model_layer_and_a_free_row_with_undo(composer):
    le = _add_legend(composer)
    missing = [ly.name for ly in composer._ley_missing_layers()]
    assert missing == ["Oculta"]                    # hidden ones offered too
    composer.ley_rows.setCurrentRow(0)
    composer.add_legend_layer("Oculta")
    assert _labels(le) == ["Layer0", "Oculta", "Muros", "Ejes"]
    assert composer._ley_missing_layers() == []
    composer.add_legend_free_row()
    e = le.entries[2]
    assert e["layer"] == "" and e["symbol"] == "line"
    assert composer.ley_rows.currentRow() == 2
    composer.ley_label.setText("Límite de propiedad")
    composer.ley_label.editingFinished.emit()
    assert _labels(le)[2] == "Límite de propiedad"
    assert le.h_mm == pytest.approx(7.5 + 5.5 * 5)
    _undo(composer, le)
    assert _labels(le)[2] == "New entry"
    _undo(composer, le)
    assert _labels(le) == ["Layer0", "Oculta", "Muros", "Ejes"]
    _undo(composer, le)
    assert le.entries is None and _labels(le) == ["Layer0", "Muros", "Ejes"]


def test_remove_and_reorder_rows_with_undo(composer):
    le = _add_legend(composer)
    composer.ley_rows.setCurrentRow(2)
    composer.ley_up_btn.click()
    assert _labels(le) == ["Layer0", "Ejes", "Muros"]
    assert composer.ley_rows.currentRow() == 1
    composer.ley_up_btn.click()
    assert _labels(le) == ["Ejes", "Layer0", "Muros"]
    composer.ley_down_btn.click()
    assert _labels(le) == ["Layer0", "Ejes", "Muros"]
    composer.ley_rows.setCurrentRow(0)
    composer.ley_del_btn.click()
    assert _labels(le) == ["Ejes", "Muros"]
    assert le.h_mm == pytest.approx(7.5 + 5.5 * 2)
    _undo(composer, le)
    assert _labels(le) == ["Layer0", "Ejes", "Muros"]
    _undo(composer, le)
    assert _labels(le) == ["Ejes", "Layer0", "Muros"]
    _undo(composer, le)
    _undo(composer, le)
    assert le.entries is None


def test_refresh_keeps_what_the_user_edited(composer):
    from core.layers import Layer
    le = _add_legend(composer)
    scene = composer._scene()
    composer.ley_rows.setCurrentRow(1)
    composer.ley_label.setText("Muros (editado)")
    composer.ley_label.editingFinished.emit()
    composer.add_legend_free_row()
    # the model changes: Ejes recoloured, Layer0 hidden, a new layer
    scene.layers[2].color = (0.0, 0.0, 0.0)
    scene.layers[0].visible = False
    scene.layers.append(Layer("Nueva"))
    composer._on_leyenda_refresh()
    assert _labels(le) == ["Muros (editado)", "New entry", "Ejes", "Nueva"]
    assert le.entries[2]["color"] == [0.0, 0.0, 0.0]
    _undo(composer, le)
    assert _labels(le) == ["Layer0", "Muros (editado)", "New entry", "Ejes"]


def test_refresh_of_an_unedited_legend_is_as_before(composer):
    le = _add_legend(composer)
    composer._scene().layers[1].visible = False
    composer._on_leyenda_refresh()
    assert le.entries is None and le.rows == ["Layer0", "Ejes"]


def test_refreshed_entries_rules():
    entries = [{"label": "A", "layer": "A"},
               {"label": "Mío", "layer": "B", "edited": True},
               {"label": "Libre", "layer": ""},
               {"label": "Gone", "layer": "G"}]
    out = refreshed_legend_entries(entries, ["A", "C"],
                                   {"A": {"color": [1, 0, 0]}})
    assert [e["label"] for e in out] == ["A", "Mío", "Libre", "C"]
    assert out[0]["color"] == [1, 0, 0]
    assert free_legend_entry("x")["edited"] is True


def test_background_rows_with_undo(composer):
    from core.composition import AddItemCommand
    sb = BarraEscala(x_mm=40.0, y_mm=150.0)
    composer.history.execute(AddItemCommand(composer.comp, sb))
    _settle()
    _select(composer, sb)
    assert composer.props.currentIndex() == 5
    assert not composer.sb_bg_check.isChecked()
    composer.sb_bg_check.setChecked(True)
    assert sb.bg_color == "#ffffff"                  # white comes first
    composer.sb_bg_margin.setValue(3.0)
    assert sb.bg_margin_mm == 3.0
    composer.sb_bg_opacity.setValue(50.0)
    assert sb.bg_opacity == 0.5
    while composer.history.undo():
        pass
    _settle()
    n = FlechaNorte(x_mm=40.0, y_mm=40.0)
    composer.history.execute(AddItemCommand(composer.comp, n))
    _settle()
    _select(composer, n)
    composer.norte_bg_check.setChecked(True)
    assert n.bg_color == "#ffffff"
    _undo(composer, n)
    assert n.bg_color == ""


def _black_under(win, model):
    from core.composition import AddItemCommand
    win.history.execute(AddItemCommand(win.comp, FormaItem(
        kind="rect", x_mm=0.0, y_mm=0.0, w_mm=250.0, h_mm=200.0, fill=True,
        color="#000000", fill_color="#000000", z=1.0)))   # over the frame
    model.z = 5.0
    win.history.execute(AddItemCommand(win.comp, model))
    _settle()


def _sheet_pixel(img, x_mm, y_mm, scale):
    return QColor(img.pixel(int(x_mm * scale), int(y_mm * scale)))


def test_the_background_on_the_canvas_and_in_the_exports(composer, tmp_path):
    from views.composer import scalebar_ink_rect
    sb = BarraEscala(x_mm=40.0, y_mm=100.0, bg_color="#ffffff",
                     bg_margin_mm=2.0)
    _black_under(composer, sb)
    x = sb.x_mm + scalebar_ink_rect(sb).left() - 1.0     # in the margin
    y = sb.y_mm + 1.0
    # the exported image
    path = tmp_path / "s.png"
    composer.export_image(str(path), dpi=100)
    img = QImage(str(path))
    assert _sheet_pixel(img, x, y, 100 / 25.4).name() == "#ffffff"
    # the canvas
    pw, ph = composer.comp.page_size_mm()
    can = QImage(int(pw * 4), int(ph * 4), QImage.Format_ARGB32)
    can.fill(0)
    composer.canvas.clearSelection()
    p = QPainter(can)
    composer.canvas.render(p, QRectF(0, 0, can.width(), can.height()),
                           QRectF(0, 0, pw, ph))
    p.end()
    assert _sheet_pixel(can, x, y, 4).name() == "#ffffff"
    # a north arrow's margin reaches past the item's own box: the canvas
    # item's bounds must take it in, or the view clips it
    from core.composition import AddItemCommand
    n = FlechaNorte(x_mm=150.0, y_mm=60.0, bg_color="#ffffff",
                    bg_margin_mm=3.0, z=5.0)
    composer.history.execute(AddItemCommand(composer.comp, n))
    _settle()
    composer.canvas.clearSelection()
    for it in composer.canvas.items():
        if getattr(it, "model", None) is n:
            assert it.boundingRect().left() <= -3.0
    can.fill(0)
    p = QPainter(can)
    composer.canvas.render(p, QRectF(0, 0, can.width(), can.height()),
                           QRectF(0, 0, pw, ph))
    p.end()
    assert _sheet_pixel(can, n.x_mm - 2.0, n.y_mm + 5.0, 4).name() == "#ffffff"
    # the PDF runs the same painter: written, and without a background the
    # map shows through in the image
    composer.export_pdf(str(tmp_path / "s.pdf"))
    assert (tmp_path / "s.pdf").stat().st_size > 1000
    sb.bg_color = ""
    composer.export_image(str(path), dpi=100)
    img = QImage(str(path))
    assert _sheet_pixel(img, x, y, 100 / 25.4).name() == "#000000"


def test_the_legend_export_draws_the_edited_rows(composer, tmp_path):
    le = _add_legend(composer)
    path = tmp_path / "a.png"
    composer.export_image(str(path), dpi=100)
    before = QImage(str(path))
    composer.ley_rows.setCurrentRow(0)
    composer.ley_del_btn.click()
    composer.export_image(str(path), dpi=100)
    assert QImage(str(path)) != before


def test_edited_legend_and_backgrounds_survive_the_igz(tmp_path):
    from core.scene import Scene
    from formats.igz import load_into, save_scene
    comp = Composicion()
    comp.leyendas = [Leyenda(rows=["A"], entries=[
        {"label": "Muros", "layer": "A", "color": [1.0, 0.0, 0.0],
         "symbol": "line_fill", "linetype": "dashed", "edited": True},
        free_legend_entry("Límite")], bg_color="", bg_margin_mm=1.5)]
    comp.scalebars = [BarraEscala(bg_color="#ffffff", bg_opacity=0.8,
                                  bg_margin_mm=2.0)]
    comp.nortes = [FlechaNorte(bg_color="#fafafa")]
    scene = Scene()
    scene.compositions.append(comp)
    path = tmp_path / "d.igz"
    save_scene(scene, path)
    fresh = Scene()
    load_into(fresh, path)
    again = fresh.compositions[0]
    assert again.to_dict() == comp.to_dict()
    assert again.leyendas[0].entries[1]["label"] == "Límite"
    assert again.scalebars[0].bg_opacity == 0.8
    assert again.nortes[0].bg_color == "#fafafa"


def test_a_legend_edit_is_one_field_edit():
    le = Leyenda(rows=["A"])
    cmd = EditItemCommand(le, {"entries": [{"label": "B", "layer": ""}]})
    cmd.do()
    assert _labels(le) == ["B"]
    cmd.undo()
    assert le.entries is None


_NEW_MESSAGES = (
    "Rows", "Add a row", "Remove row", "Move row up", "Move row down",
    "Only the legend changes: the model's layer stays as it is.",
    "As the layer", "Line and fill", "Background margin",
    "Re-read the visible layers of the model. Rows you edited and your "
    "own rows stay as they are; new layers are added at the end.",
    "Layer: {name}", "Own row (no layer)", "Every layer is in the legend",
    "Free entry", "New entry")


def test_the_new_messages_are_in_every_language():
    root = pathlib.Path(__file__).resolve().parent.parent / "i18n"
    for path in root.glob("*.json"):
        if path.stem == "en":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for k in _NEW_MESSAGES:
            assert data.get(k), (path.stem, k)
        assert "{name}" in data["Layer: {name}"], path.stem
