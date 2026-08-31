# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""DXF import (D1): CAD linework arrives as tagged layer groups, curves as
single contours, units honoured, survey coordinates recentred — SketchUp's
documented 2D import behaviour, on our machinery."""
from __future__ import annotations

import pytest

ezdxf = pytest.importorskip("ezdxf")

from core.scene import Scene                              # noqa: E402
from formats.dxf_in import (                              # noqa: E402
    RECENTER_BEYOND_M, load_dxf, read_unit_scale)


def _doc(units: int | None = 6):
    doc = ezdxf.new("R2018")
    # ezdxf's template ships a default $INSUNITS; write 0 explicitly to make
    # a genuinely unitless header (what old exports actually look like).
    doc.header["$INSUNITS"] = units if units is not None else 0
    return doc


def _save(doc, tmp_path, name="t.dxf"):
    out = tmp_path / name
    doc.saveas(str(out))
    return out


def _load(tmp_path, doc, scale=1.0):
    scene = Scene()
    stats = load_dxf(scene, _save(doc, tmp_path), scale=scale)
    return scene, stats


# ---- Entities ---------------------------------------------------------------
def test_lines_and_polylines_become_edges(tmp_path):
    doc = _doc()
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0))
    msp.add_lwpolyline([(0, 0), (0, 5), (10, 5), (10, 0)])
    scene, stats = _load(tmp_path, doc)
    assert stats["groups"] == 1
    g = scene.groups[0]
    assert len(g.mesh.edges) == 4            # 1 line + 3 polyline segments
    assert stats["skipped"] == {}


def test_a_circle_is_one_selectable_contour(tmp_path):
    doc = _doc()
    msp = doc.modelspace()
    msp.add_circle((0, 0), 2.0)
    msp.add_line((5, 0), (6, 0))
    scene, _ = _load(tmp_path, doc)
    g = scene.groups[0]
    curve_ids = {e.curve for e in g.mesh.edges if e.curve is not None}
    assert len(curve_ids) == 1               # the whole circle shares one id
    plain = [e for e in g.mesh.edges if e.curve is None]
    assert len(plain) == 1                   # the line stays a plain edge
    # and the circle closed on itself: every circle vertex touches 2 edges
    curved = [e for e in g.mesh.edges if e.curve is not None]
    assert len(curved) >= 8


def test_a_bulged_polyline_counts_as_a_curve(tmp_path):
    doc = _doc()
    msp = doc.modelspace()
    # format: (x, y, start_width, end_width, bulge)
    msp.add_lwpolyline([(0, 0, 0, 0, 1.0), (4, 0, 0, 0, 0)])
    msp.add_lwpolyline([(0, 5), (4, 5), (4, 9)])          # all straight
    scene, _ = _load(tmp_path, doc)
    g = scene.groups[0]
    curved = [e for e in g.mesh.edges if e.curve is not None]
    straight = [e for e in g.mesh.edges if e.curve is None]
    assert len(curved) >= 4                  # the arc flattened, one contour
    assert len({e.curve for e in curved}) == 1
    assert len(straight) == 2


def test_text_and_dimensions_are_skipped_and_counted(tmp_path):
    doc = _doc()
    msp = doc.modelspace()
    msp.add_line((0, 0), (1, 0))
    msp.add_text("COTA 3.50")
    msp.add_text("N.P.T.")
    scene, stats = _load(tmp_path, doc)
    assert stats["skipped"] == {"TEXT": 2}
    assert stats["edges"] == 1


def test_a_drawing_with_no_linework_refuses_loudly(tmp_path):
    doc = _doc()
    doc.modelspace().add_text("solo texto")
    with pytest.raises(ValueError):
        _load(tmp_path, doc)


# ---- Blocks -----------------------------------------------------------------
def test_inserts_become_component_instances_sharing_one_proto(tmp_path):
    """D2: 500 trees are one prototype and 500 matrices, not 500 meshes."""
    doc = _doc()
    blk = doc.blocks.new("ARBOL")
    blk.add_line((0, 0), (0, 2))
    blk.add_circle((0, 2.5), 0.5)
    msp = doc.modelspace()
    msp.add_blockref("ARBOL", (10, 10))
    msp.add_blockref("ARBOL", (20, 10))
    scene, stats = _load(tmp_path, doc)
    instances = [g for g in scene.groups if g.xform is not None]
    assert len(instances) == 2
    a, b = instances
    assert a.mesh is b.mesh                  # SHARED prototype
    assert stats["components"] == {"ARBOL": 2}
    # the xform places the proto: local (0,0) lands at each insert point
    pa = a.xform.map(__import__("PySide6.QtGui", fromlist=["QVector3D"])
                     .QVector3D(0, 0, 0))
    pb = b.xform.map(__import__("PySide6.QtGui", fromlist=["QVector3D"])
                     .QVector3D(0, 0, 0))
    assert sorted((round(pa.x()), round(pb.x()))) == [10, 20]
    # and the circle inside the proto is still one contour
    curves = {e.curve for e in a.mesh.edges if e.curve is not None}
    assert len(curves) == 1


def test_a_rotated_scaled_insert_lands_where_autocad_put_it(tmp_path):
    doc = _doc()
    blk = doc.blocks.new("B")
    blk.add_line((0, 0), (1, 0))
    doc.modelspace().add_blockref(
        "B", (10, 20), dxfattribs={"rotation": 90.0,
                                   "xscale": 2.0, "yscale": 2.0})
    scene, _ = _load(tmp_path, doc)
    inst = next(g for g in scene.groups if g.xform is not None)
    from PySide6.QtGui import QVector3D
    tip = inst.xform.map(QVector3D(1, 0, 0))
    assert (round(tip.x(), 6), round(tip.y(), 6)) == (10.0, 22.0)


def test_an_annotation_only_block_places_nothing_quietly(tmp_path):
    doc = _doc()
    blk = doc.blocks.new("ROTULO")
    blk.add_text("N.P.T. +0.15")
    msp = doc.modelspace()
    msp.add_blockref("ROTULO", (5, 5))
    msp.add_line((0, 0), (1, 0))             # so the file is not empty
    scene, stats = _load(tmp_path, doc)
    assert stats["components"] == {}
    assert all(g.xform is None for g in scene.groups)


def test_block_children_on_layer_zero_inherit_the_inserts_layer(tmp_path):
    doc = _doc()
    doc.layers.add("MOBILIARIO")
    blk = doc.blocks.new("BANCA")
    blk.add_line((0, 0), (1, 0))             # drawn on layer "0"
    doc.modelspace().add_blockref(
        "BANCA", (0, 0), dxfattribs={"layer": "MOBILIARIO"})
    scene, _ = _load(tmp_path, doc)
    assert scene.groups[0].layer == "MOBILIARIO"


# ---- Layers → tagged groups -------------------------------------------------
def test_each_cad_layer_becomes_a_tagged_group(tmp_path):
    doc = _doc()
    doc.layers.add("MUROS")
    doc.layers.add("EJES")
    msp = doc.modelspace()
    msp.add_line((0, 0), (1, 0), dxfattribs={"layer": "MUROS"})
    msp.add_line((0, 1), (1, 1), dxfattribs={"layer": "EJES"})
    msp.add_line((0, 2), (1, 2))             # layer "0"
    scene, stats = _load(tmp_path, doc)
    assert stats["groups"] == 3
    by_layer = {g.layer: g for g in scene.groups}
    assert set(by_layer) == {"MUROS", "EJES", None}
    assert by_layer[None].name == "t"        # layer 0 → named by the file
    tags = {ly.name for ly in scene.layers}
    assert {"MUROS", "EJES"} <= tags
    assert "0" not in tags                   # the default layer gets no tag


def test_unused_cad_layers_leave_no_empty_tags(tmp_path):
    doc = _doc()
    doc.layers.add("VACIA")                  # declared, never drawn on
    doc.modelspace().add_line((0, 0), (1, 0))
    scene, _ = _load(tmp_path, doc)
    assert all(ly.name != "VACIA" for ly in scene.layers)


# ---- Units ------------------------------------------------------------------
def test_units_are_read_from_the_header(tmp_path):
    for code, metres in ((4, 0.001), (5, 0.01), (6, 1.0), (1, 0.0254)):
        scale, got = read_unit_scale(_save(_doc(code), tmp_path,
                                           f"u{code}.dxf"))
        assert (scale, got) == (metres, code)


def test_a_unitless_header_says_so_instead_of_guessing(tmp_path):
    scale, code = read_unit_scale(_save(_doc(None), tmp_path))
    assert scale is None and code == 0


def test_millimetre_drawings_arrive_in_metres(tmp_path):
    doc = _doc(4)                            # millimetres
    doc.modelspace().add_line((0, 0), (3500, 0))
    scene, _ = _load(tmp_path, doc, scale=0.001)
    xs = [v.position.x() for v in scene.groups[0].mesh.vertices]
    assert max(xs) == 3.5                    # a 3.5 m wall, not 3500 m


# ---- Survey coordinates -----------------------------------------------------
def test_utm_coordinates_are_recentred_and_reported(tmp_path):
    doc = _doc()
    east, north = 276_000.0, 8_214_000.0     # southern-Peru UTM
    doc.modelspace().add_line((east, north), (east + 12, north + 8))
    scene, stats = _load(tmp_path, doc)
    assert stats["offset"] is not None
    ox, oy, _oz = stats["offset"]
    assert abs(ox - east) < 1.0 and abs(oy - north) < 1.0
    xs = [abs(v.position.x()) for v in scene.groups[0].mesh.vertices]
    assert max(xs) < RECENTER_BEYOND_M       # geometry now near the origin


def test_local_coordinates_are_left_alone(tmp_path):
    doc = _doc()
    doc.modelspace().add_line((100, 200), (300, 400))
    _scene, stats = _load(tmp_path, doc)
    assert stats["offset"] is None


# ---- Undo -------------------------------------------------------------------
def test_the_whole_import_is_one_undoable_step(tmp_path):
    from core.history import History, SnapshotImport

    doc = _doc()
    doc.layers.add("MUROS")
    doc.modelspace().add_line((0, 0), (1, 0), dxfattribs={"layer": "MUROS"})
    path = _save(doc, tmp_path)
    scene = Scene()
    hist = History(scene)
    hist.execute(SnapshotImport(lambda sc: load_dxf(sc, path)))
    assert len(scene.groups) == 1
    assert any(ly.name == "MUROS" for ly in scene.layers)
    hist.undo()
    assert scene.groups == []
    assert all(ly.name != "MUROS" for ly in scene.layers)
    hist.redo()
    assert len(scene.groups) == 1


# ---- Faces (D2) -------------------------------------------------------------
def test_3dfaces_become_faces(tmp_path):
    doc = _doc()
    doc.modelspace().add_3dface([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)])
    scene, stats = _load(tmp_path, doc)
    g = scene.groups[0]
    assert len(g.mesh.faces) == 1
    assert stats["faces"] == 1


def test_solid_corners_unswap_their_z_order(tmp_path):
    # SOLID stores its quad zigzagged (0,1,3,2 walks the perimeter); imported
    # naively it makes a bow-tie. The area tells: a 2x2 square is 4, the
    # bow-tie folds to ~0.
    doc = _doc()
    doc.modelspace().add_solid([(0, 0), (2, 0), (0, 2), (2, 2)])
    scene, _ = _load(tmp_path, doc)
    f = scene.groups[0].mesh.faces[0]
    assert abs(f.area() - 4.0) < 1e-6


def test_a_triangulated_plane_merges_back_to_one_face(tmp_path):
    """SketchUp's "Merge coplanar faces" option, always on: a CAD export
    that triangulated a slab comes back as the slab."""
    doc = _doc()
    msp = doc.modelspace()
    msp.add_3dface([(0, 0, 0), (4, 0, 0), (4, 3, 0)])
    msp.add_3dface([(0, 0, 0), (4, 3, 0), (0, 3, 0)])
    scene, _ = _load(tmp_path, doc)
    g = scene.groups[0]
    assert len(g.mesh.faces) == 1            # the diagonal dissolved
    assert abs(g.mesh.faces[0].area() - 12.0) < 1e-6


# ---- The lying header (D2) --------------------------------------------------
def test_a_lying_millimetre_header_is_vetoed_by_the_drawing(tmp_path):
    """Detalles Plaza Yanque's disease: $INSUNITS says mm, the drawing is
    1 unit = 1 metre. Median entity size rules mm out; metres suggested."""
    from formats.dxf_in import open_document, suggest_unit_scale

    doc = _doc(4)                            # header claims millimetres
    msp = doc.modelspace()
    for i in range(30):                      # walls 3-6 "units" long
        msp.add_line((i, 0), (i, 3.0 + (i % 4)))
    path = _save(doc, tmp_path)
    scale, code = suggest_unit_scale(open_document(path))
    assert code == 4                         # the header still says mm...
    assert scale == 1.0                      # ...and the drawing says metres


def test_an_honest_header_is_believed(tmp_path):
    from formats.dxf_in import open_document, suggest_unit_scale

    doc = _doc(4)                            # mm, honestly: walls 3500 units
    msp = doc.modelspace()
    for i in range(30):
        msp.add_line((i * 1000, 0), (i * 1000, 3500))
    path = _save(doc, tmp_path)
    scale, code = suggest_unit_scale(open_document(path))
    assert (scale, code) == (0.001, 4)


def test_the_display_name_survives_a_file_with_blocks(tmp_path):
    """Regression: the block loop shadowed the ``name`` parameter, so the
    layer-0 group of a real DWG came out named after the LAST BLOCK in the
    file ('asrco') instead of the drawing."""
    doc = _doc()
    blk = doc.blocks.new("asrco")
    blk.add_line((0, 0), (1, 0))
    msp = doc.modelspace()
    msp.add_blockref("asrco", (5, 5))
    msp.add_line((0, 0), (2, 0))             # layer-0 loose content
    scene = Scene()
    load_dxf(scene, _save(doc, tmp_path), scale=1.0,
             name="Detalles Plaza Yanque")
    loose = next(g for g in scene.groups
                 if g.layer is None and g.xform is None)
    assert loose.name == "Detalles Plaza Yanque"
