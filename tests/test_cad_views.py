# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""2D CAD views — plans, elevations and sections on discipline layers.

Pins the three things the export is built on: the hidden-line pass says
which object each line came from (and never merges two objects' lines),
the view range (an explicit cut and a far plane) leaves the document
alone, and the DXF carries one layer per discipline and line class with
its pen. Ends with a real sample model exported as a plan.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from core import cad_layers, cad_views
from core.group import Group
from core.hlr import (KIND_CUT, KIND_HIDDEN, Owner, collect_geometry,
                      hlr_drawing)
from core.mesh import Mesh
from core.scene import Scene
from core.section import SectionPlane
from formats.dxf_cad import chain_segments

_app = QApplication.instance() or QApplication([])
V = QVector3D
ROOT = Path(__file__).resolve().parents[1]


def _box_mesh(x0, y0, z0, x1, y1, z1) -> Mesh:
    m = Mesh()
    m.add_face([V(x0, y0, z0), V(x0, y1, z0), V(x1, y1, z0), V(x1, y0, z0)])
    m.add_face([V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)])
    m.add_face([V(x0, y0, z0), V(x1, y0, z0), V(x1, y0, z1), V(x0, y0, z1)])
    m.add_face([V(x1, y1, z0), V(x0, y1, z0), V(x0, y1, z1), V(x1, y1, z1)])
    m.add_face([V(x0, y1, z0), V(x0, y0, z0), V(x0, y0, z1), V(x0, y1, z1)])
    m.add_face([V(x1, y0, z0), V(x1, y1, z0), V(x1, y1, z1), V(x1, y0, z1)])
    return m


def _group(scene, name, box, ifc=None, layer=None) -> Group:
    g = Group(_box_mesh(*box), name)
    if ifc:
        g.ifc = {"class": ifc, "name": name}
    g.layer = layer
    scene.groups.append(g)
    return g


def _small_building() -> Scene:
    """A slab, a wall on it and a column beside the wall; a low box
    under the slab that a plan's view depth should leave out."""
    s = Scene()
    _group(s, "Slab", (0, 0, -0.2, 6, 4, 0.0), ifc="IfcSlab")
    _group(s, "Wall", (0, 0, 0, 4, 0.2, 3), ifc="IfcWall")
    _group(s, "Column", (5, 1, 0, 5.3, 1.3, 3), ifc="IfcColumn")
    _group(s, "MEP · Cold water (PPR)", (1, 2, 0.5, 3, 2.05, 0.55))
    _group(s, "Footing deep below", (1, 1, -3, 2, 2, -2.5), ifc="IfcFooting")
    return s


def _plan(scene, **kw):
    spec = cad_views.ViewSpec(kind=cad_views.PLAN, **kw)
    return cad_views.build_view(scene, spec)


def _layers(scene, **kw):
    drawing, table = _plan(scene, **kw)
    return cad_layers.split_drawing(drawing, table)


# ---- owners through the hidden-line pass -------------------------------------

def test_every_segment_knows_its_owner():
    drawing, table = _plan(_small_building())
    assert drawing.owners is not None
    assert len(drawing.owners) == len(drawing.segs) > 0
    names = {table[int(o)].name for o in drawing.owners}
    assert {"Slab", "Wall", "Column"} <= names


def test_cut_lines_belong_to_what_the_plane_slices():
    drawing, table = _plan(_small_building())
    cut = {table[int(o)].name
           for o, k in zip(drawing.owners, drawing.kinds) if k == KIND_CUT}
    # the cut at 1.20 m slices the wall and the column, nothing else
    assert cut == {"Wall", "Column"}
    fills = {table[o].name for o in drawing.loop_owners}
    assert fills == {"Wall", "Column"}


def test_lines_of_two_owners_are_never_merged():
    """Two boxes side by side share a straight top edge line on a plan;
    with owners each keeps its own segment, without them they join."""
    s = Scene()
    _group(s, "A", (0, 0, 0, 1, 1, 1), ifc="IfcWall")
    _group(s, "B", (1, 0, 0, 2, 1, 1), ifc="IfcColumn")
    cam, _sec, _far = cad_views.view_setup(
        s, cad_views.ViewSpec(kind=cad_views.PLAN, cut_height=5.0,
                              view_depth=0.0))
    tris, hard, soft, (to, ho, so, _t) = collect_geometry(s, owners=True)
    owned = hlr_drawing(s, cam, geometry=(tris, hard, soft), section=None,
                        owners=(to, ho, so))
    plain = hlr_drawing(s, cam, geometry=(tris, hard, soft), section=None)

    def spans_y0(d):
        return {round(abs(x1 - x0), 6) for x0, y0, x1, y1 in d.segs
                if abs(y0) < 1e-9 and abs(y1) < 1e-9}

    assert spans_y0(owned) == {1.0}         # each box its own line
    assert spans_y0(plain) == {2.0}         # one line across both


def test_drawing_without_owners_is_unchanged():
    s = _small_building()
    cam, sec, far = cad_views.view_setup(s, cad_views.ViewSpec())
    d = hlr_drawing(s, cam, section=sec)
    assert d.owners is None and d.loop_owners is None
    assert (d.kinds == KIND_CUT).any()


def test_nested_placement_keeps_its_own_tag():
    s = Scene()
    wall = Group(_box_mesh(0, 0, 0, 4, 0.2, 3), "Wall")
    wall.ifc = {"class": "IfcWall"}
    win = Group(_box_mesh(1, -0.05, 1, 2, 0.25, 2), "Window")
    win.ifc = {"class": "IfcWindow"}
    trim = Group(_box_mesh(1, 0.25, 1, 2, 0.3, 1.1), "Sill")   # untagged
    win.children = [trim]
    wall.children = [win]
    s.groups.append(wall)
    *_g, (_to, _ho, _so, table) = collect_geometry(s, owners=True)
    by_name = {o.name: o for o in table}
    assert by_name["Wall"].ifc == "IfcWall"
    assert by_name["Window"].ifc == "IfcWindow"
    assert by_name["Sill"].ifc == "IfcWindow"        # inherited


# ---- the view range -------------------------------------------------------------

def test_view_depth_leaves_out_what_lies_beyond():
    s = _small_building()

    def kinds_of(name, **kw):
        d, t = _plan(s, hidden=True, **kw)
        return {int(k) for o, k in zip(d.owners, d.kinds)
                if t[int(o)].name == name}

    # within reach but under the slab: drawn hidden; beyond reach: gone
    assert kinds_of("Footing deep below", view_depth=10.0) == {KIND_HIDDEN}
    assert kinds_of("Footing deep below", view_depth=1.5) == set()
    # the far plane is not a cut: no chords where the depth ends
    d, t = _plan(s, view_depth=1.0)
    cut = {t[int(o)].name for o, k in zip(d.owners, d.kinds) if k == KIND_CUT}
    assert "Slab" not in cut


def test_explicit_section_does_not_touch_the_document():
    s = _small_building()
    assert s.active_section() is None
    _plan(s)
    assert s.active_section() is None and not s.section_planes


def test_explicit_none_ignores_the_active_plane():
    s = _small_building()
    sp = SectionPlane(V(0, 0, 1.2), V(0, 0, 1))
    s.section_planes.append(sp)
    s.set_active_section(sp)
    cam, _sec, _far = cad_views.view_setup(s, cad_views.ViewSpec())
    assert (hlr_drawing(s, cam).kinds == KIND_CUT).any()             # default
    assert not (hlr_drawing(s, cam, section=None).kinds == KIND_CUT).any()


def test_plan_and_elevations_come_out_in_world_coordinates():
    s = Scene()
    _group(s, "Box", (2, 5, 0, 3, 6, 1))
    plan, _ = cad_views.build_view(s, cad_views.ViewSpec(
        kind=cad_views.PLAN, cut_height=5.0, view_depth=0.0))
    xs, ys = plan.segs[:, [0, 2]], plan.segs[:, [1, 3]]
    assert np.allclose([xs.min(), xs.max(), ys.min(), ys.max()], [2, 3, 5, 6])
    south, _ = cad_views.build_view(s, cad_views.ViewSpec(
        kind=cad_views.ELEVATION, direction="S", view_depth=0.0))
    xs, ys = south.segs[:, [0, 2]], south.segs[:, [1, 3]]
    assert np.allclose([xs.min(), xs.max(), ys.min(), ys.max()], [2, 3, 0, 1])
    north, _ = cad_views.build_view(s, cad_views.ViewSpec(
        kind=cad_views.ELEVATION, direction="N", view_depth=0.0))
    xs = north.segs[:, [0, 2]]
    assert np.allclose([xs.min(), xs.max()], [-3, -2])       # seen from behind


def test_section_view_uses_the_named_plane_and_rejects_a_missing_one():
    s = _small_building()
    sp = SectionPlane(V(0, 0.1, 0), V(0, -1, 0), name="A")
    s.section_planes.append(sp)
    d, t = cad_views.build_view(s, cad_views.ViewSpec(
        kind=cad_views.SECTION, section_uid=sp.uid, view_depth=0.0))
    cut = {t[int(o)].name for o, k in zip(d.owners, d.kinds) if k == KIND_CUT}
    assert {"Wall", "Slab"} <= cut and "Column" not in cut
    with pytest.raises(ValueError):
        cad_views.build_view(s, cad_views.ViewSpec(
            kind=cad_views.SECTION, section_uid=-42))


def test_hidden_lines_go_to_the_hidn_layers():
    # deep enough to reach the footing under the slab
    layers = _layers(_small_building(), hidden=True, view_depth=10.0)
    assert "S-FNDN-HIDN" in layers
    hidn = [n for n in layers if n.endswith("-HIDN")]
    assert all(layers[n].pen.linetype == "DASHED" for n in hidn)


# ---- layers and pens --------------------------------------------------------------

@pytest.mark.parametrize("owner, layer", [
    (Owner(None, "x", None, "IfcWall"), "A-WALL"),
    (Owner(None, "x", None, "IfcColumn"), "S-COLS"),
    (Owner(None, "x", "M-HVAC", None), "M-HVAC"),
    (Owner(None, "x", "E-Power", None), "E-POWER"),
    (Owner(None, "x", "P-Drainage", None), "P-DRAINAGE"),
    (Owner(None, "MEP · Cold water (PPR)", None, None), "P-DOMW"),
    (Owner(None, "MEP · Supply duct", None, None), "M-DUCT"),
    (Owner(None, "STR · Beam · 2F", None, None), "S-BEAM"),
    (Owner(None, "FUR · Chair · 2F", None, None), "I-FURN"),
    (Owner(None, "North wall", None, None), "A-WALL"),
    (Owner(None, "Group 12", "Layer 0", None), "A-GENM"),
    (None, "A-GENM"),
])
def test_base_layer(owner, layer):
    assert cad_layers.base_layer(owner) == layer


def test_pens():
    assert cad_layers.pen_for("A-WALL-CUT").lineweight == cad_layers.LW_CUT_HEAVY
    assert cad_layers.pen_for("A-DOOR-CUT").lineweight == cad_layers.LW_CUT
    assert cad_layers.pen_for("A-DOOR-PROJ").lineweight == cad_layers.LW_PROJ
    hid = cad_layers.pen_for("M-DUCT-HIDN")
    assert (hid.lineweight, hid.linetype, hid.color) == (
        cad_layers.LW_HIDDEN, "DASHED", cad_layers.DISCIPLINE_COLORS["M"])


def test_discipline_filter():
    drawing, table = _plan(_small_building())
    only_s = cad_layers.split_drawing(
        drawing, table, cad_layers.DISCIPLINE_FILTERS["structural"])
    assert only_s and all(n.startswith("S-") for n in only_s)
    mep = cad_layers.split_drawing(drawing, table,
                                   cad_layers.DISCIPLINE_FILTERS["mep"])
    assert set(mep) == {"P-DOMW-PROJ"}


def test_layers_of_a_plan():
    layers = _layers(_small_building())
    assert {"A-WALL-CUT", "S-COLS-CUT", "S-SLAB-PROJ"} <= set(layers)
    assert layers["A-WALL-CUT"].fills and layers["S-COLS-CUT"].fills
    assert not layers["S-SLAB-PROJ"].fills


# ---- DXF --------------------------------------------------------------------------

def test_chain_segments_closes_rings_and_stops_at_junctions():
    square = [(0, 0, 1, 0), (1, 1, 1, 0), (1, 1, 0, 1), (0, 0, 0, 1)]
    (ring,) = chain_segments(square)
    assert len(ring) == 5 and ring[0] == ring[-1]
    tee = [(0, 0, 1, 0), (1, 0, 2, 0), (1, 0, 1, 1)]
    assert len(chain_segments(tee)) == 3


def test_dxf_has_a_layer_per_discipline_and_class(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    path = tmp_path / "plan.dxf"
    res = cad_views.export_dxf(_small_building(), cad_views.ViewSpec(),
                               path, scale_n=50)
    assert res["lines"] > 0
    doc = ezdxf.readfile(str(path))
    assert doc.header["$INSUNITS"] == 6
    wall = doc.layers.get("A-WALL-CUT")
    assert wall.dxf.lineweight == cad_layers.LW_CUT_HEAVY
    assert wall.dxf.color == cad_layers.DISCIPLINE_COLORS["A"]
    assert doc.layers.get("S-SLAB-PROJ").dxf.lineweight == cad_layers.LW_PROJ
    msp = doc.modelspace()
    hatches = msp.query("HATCH")
    assert {h.dxf.layer for h in hatches} == {"A-WALL-CUT", "S-COLS-CUT"}
    on = {e.dxf.layer for e in msp.query("LINE LWPOLYLINE")}
    assert set(res["layers"]) == on
    # the wall's cut is one closed ring: 4 m × 0.2 m
    rings = [e for e in msp.query("LWPOLYLINE")
             if e.dxf.layer == "A-WALL-CUT" and e.closed]
    assert len(rings) == 1
    pts = np.array([p[:2] for p in rings[0].get_points()])
    assert np.allclose(pts.min(axis=0), [0, 0]) and np.allclose(
        pts.max(axis=0), [4, 0.2])


def test_sample_model_exports_a_layered_plan(tmp_path):
    """A real document from examples/: loads, cuts, writes, reads back."""
    ezdxf = pytest.importorskip("ezdxf")
    from formats import igz
    sample = ROOT / "examples" / "banca-pergola-yanque.igz"
    if not sample.is_file():
        pytest.skip("sample model not in this checkout")
    scene = Scene()
    igz.load_into(scene, sample)
    *_g, (_to, _ho, _so, table) = collect_geometry(scene, owners=True)
    lo = min(p[2] for t in collect_geometry(scene)[0] for p in t)
    path = tmp_path / "banca.dxf"
    res = cad_views.export_dxf(
        scene, cad_views.ViewSpec(level=lo, cut_height=0.5, view_depth=1.0),
        path)
    assert res["lines"] > 0 and res["layers"]
    doc = ezdxf.readfile(str(path))
    assert len(doc.modelspace()) > 0
    assert all(any(n.endswith(s) for s in ("-CUT", "-PROJ", "-HIDN"))
               for n in res["layers"])


# ---- the plugin ---------------------------------------------------------------------

def test_plugin_dialog_lists_views_and_builds_specs():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_cad_views_plugin", ROOT / "plugins" / "cad_views.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _App:
        scene = _small_building()
        window = None

    sp = SectionPlane(V(0, 0.1, 0), V(0, -1, 0), name="A-A")
    _App.scene.section_planes.append(sp)
    dlg = mod.CadViewDialog(_App())
    labels = [dlg.view.itemText(i) for i in range(dlg.view.count())]
    assert len(labels) == 1 + 4 + 1 and "A-A" in labels[-1]
    dlg.view.setCurrentIndex(len(labels) - 1)
    got = dlg.spec()
    assert got.kind == cad_views.SECTION and got.section_uid == sp.uid
    assert not dlg.cut.isEnabled()
    dlg.view.setCurrentIndex(0)
    assert dlg.spec().kind == cad_views.PLAN and dlg.cut.isEnabled()
