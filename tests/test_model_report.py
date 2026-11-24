# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The model report (core.model_report): areas, volumes and counts of the
whole model by layer, material and component, and its CSV.

Every scene is generated here: unit cubes and squares whose areas and
volumes are known by heart, so each number is checked exactly."""
from __future__ import annotations

import csv
import io
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core import model_report                                     # noqa: E402
from core.group import Group                                      # noqa: E402
from core.layers import DEFAULT_LAYER, Layer                      # noqa: E402
from core.mesh import Mesh                                        # noqa: E402
from core.scene import Scene                                      # noqa: E402

V = QVector3D
APPROX = dict(abs=1e-6)


def _cube(mesh=None, o=(0.0, 0.0, 0.0), s=1.0):
    """A closed cube of side ``s`` (outward faces) — 6 s² and s³."""
    mesh = mesh or Mesh()
    x, y, z = o
    p = [V(x, y, z), V(x + s, y, z), V(x + s, y + s, z), V(x, y + s, z),
         V(x, y, z + s), V(x + s, y, z + s), V(x + s, y + s, z + s),
         V(x, y + s, z + s)]
    for loop in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([p[i] for i in loop])
    return mesh


def _square(mesh, z=0.0, s=1.0):
    return mesh.add_face([V(0, 0, z), V(s, 0, z), V(s, s, z), V(0, s, z)])


def _instance(mesh, name, matrix):
    g = Group(mesh, name=name)
    g.xform = matrix
    g.component = True
    return g


def _rows(report, grouping):
    return {r["name"]: r for r in report[grouping]}


# ---- By layer ------------------------------------------------------------

def test_layers_sum_areas_and_volumes_and_count_objects():
    scene = Scene()
    scene.layers.append(Layer("Muros"))
    _square(scene.mesh, s=2.0)                     # loose, default layer: 4 m²
    wall = Group(_cube(), name="Muro")
    wall.layer = "Muros"
    scene.groups.append(wall)

    rep = model_report.collect_report(scene)
    rows = _rows(rep, model_report.LAYER)
    assert rows[DEFAULT_LAYER]["area"] == pytest.approx(4.0, **APPROX)
    assert rows[DEFAULT_LAYER]["count"] == 0       # loose geometry: no object
    assert rows[DEFAULT_LAYER]["volume"] is None   # nothing closed there
    assert rows["Muros"]["count"] == 1
    assert rows["Muros"]["faces"] == 6
    assert rows["Muros"]["area"] == pytest.approx(6.0, **APPROX)
    assert rows["Muros"]["volume"] == pytest.approx(1.0, **APPROX)


def test_a_face_on_its_own_layer_counts_there():
    scene = Scene()
    scene.layers.append(Layer("Muros"))
    scene.layers.append(Layer("Pintura"))
    mesh = _cube()
    mesh.faces[0].attrs["layer"] = "Pintura"
    g = Group(mesh, name="Muro")
    g.layer = "Muros"
    scene.groups.append(g)

    rows = _rows(model_report.collect_report(scene), model_report.LAYER)
    assert rows["Pintura"]["faces"] == 1
    assert rows["Pintura"]["area"] == pytest.approx(1.0, **APPROX)
    assert rows["Muros"]["faces"] == 5
    assert rows["Muros"]["volume"] == pytest.approx(1.0, **APPROX)


def test_nested_groups_inherit_the_layer_above():
    scene = Scene()
    scene.layers.append(Layer("Mobiliario"))
    parent = Group(Mesh(), name="Juego")
    parent.layer = "Mobiliario"
    parent.adopt([Group(_cube(), name="Pata")])
    scene.groups.append(parent)

    rows = _rows(model_report.collect_report(scene), model_report.LAYER)
    assert rows["Mobiliario"]["count"] == 2        # the set and its leg
    assert rows["Mobiliario"]["volume"] == pytest.approx(1.0, **APPROX)
    assert rows[DEFAULT_LAYER]["count"] == 0


def test_hidden_layers_and_objects_still_count():
    """The report must not change with what is switched on."""
    scene = Scene()
    ly = Layer("Oculta")
    ly.visible = False
    scene.layers.append(ly)
    g = Group(_cube(), name="Caja")
    g.layer = "Oculta"
    g.hidden = True
    scene.groups.append(g)

    rows = _rows(model_report.collect_report(scene), model_report.LAYER)
    assert rows["Oculta"]["visible"] is False
    assert rows["Oculta"]["volume"] == pytest.approx(1.0, **APPROX)


def test_an_open_shell_has_no_volume():
    scene = Scene()
    mesh = _cube()
    mesh.remove_face(mesh.faces[0])
    scene.groups.append(Group(mesh, name="Caja abierta"))

    rows = _rows(model_report.collect_report(scene), model_report.LAYER)
    assert rows[DEFAULT_LAYER]["area"] == pytest.approx(5.0, **APPROX)
    assert rows[DEFAULT_LAYER]["volume"] is None


# ---- By material -----------------------------------------------------------

def test_materials_by_name_with_volume_of_uniform_solids():
    scene = Scene()
    concrete = _cube()
    for f in concrete.faces:
        f.attrs["color"] = (0.6, 0.6, 0.6)
        f.attrs["mat"] = "Concreto"
    scene.groups.append(Group(concrete, name="Columna"))
    mixed = _cube(o=(5, 0, 0))
    for f in mixed.faces:
        f.attrs["color"] = (0.6, 0.6, 0.6)
        f.attrs["mat"] = "Concreto"
    mixed.faces[0].attrs.update(color=(1.0, 0.0, 0.0), mat="Pintura roja")
    scene.groups.append(Group(mixed, name="Caja pintada"))

    rows = _rows(model_report.collect_report(scene), model_report.MATERIAL)
    assert rows["Concreto"]["faces"] == 11
    assert rows["Concreto"]["area"] == pytest.approx(11.0, **APPROX)
    assert rows["Concreto"]["count"] == 2
    # Only the all-concrete column gives its volume to Concreto.
    assert rows["Concreto"]["volume"] == pytest.approx(1.0, **APPROX)
    assert rows["Pintura roja"]["volume"] is None


def test_unpainted_faces_take_the_group_paint():
    scene = Scene()
    g = Group(_cube(), name="Caja")
    g.material = {"color": (0.2, 0.4, 0.6), "mat": "Azul"}
    scene.groups.append(g)
    _square(scene.mesh, z=-1.0)                    # loose, unpainted

    rep = model_report.collect_report(scene)
    rows = _rows(rep, model_report.MATERIAL)
    assert rows["Azul"]["faces"] == 6
    assert rows["Azul"]["volume"] == pytest.approx(1.0, **APPROX)
    # The unpainted loose face is its own last row, with an empty name.
    assert rep[model_report.MATERIAL][-1]["name"] == ""
    assert rep[model_report.MATERIAL][-1]["faces"] == 1


def test_anonymous_colours_and_textures_get_a_label():
    scene = Scene()
    a = _square(scene.mesh)
    a.attrs["color"] = (1.0, 0.0, 0.0)
    b = _square(scene.mesh, z=1.0)
    b.attrs["texture"] = {"path": "/tex/ladrillo.png", "sw": 1.0}

    names = set(_rows(model_report.collect_report(scene),
                      model_report.MATERIAL))
    assert {"rgb(255,0,0)", "ladrillo"} <= names


# ---- By component and world size ---------------------------------------------

def test_component_instances_share_one_row_in_world_size():
    """Two copies of one definition, the second scaled ×2: one row, two
    instances, 6 + 24 m² and 1 + 8 m³ — the local cube measured through
    each matrix, not twice the definition."""
    scene = Scene()
    proto = _cube()
    m1 = QMatrix4x4()
    m2 = QMatrix4x4()
    m2.translate(10, 0, 0)
    m2.scale(2.0)
    scene.groups += [_instance(proto, "Silla", m1),
                     _instance(proto, "Silla", m2)]

    rep = model_report.collect_report(scene)
    rows = _rows(rep, model_report.COMPONENT)
    assert list(rows) == ["Silla"]
    chair = rows["Silla"]
    assert chair["count"] == 2
    assert chair["faces"] == 6                     # one definition's faces
    assert chair["area"] == pytest.approx(30.0, **APPROX)
    assert chair["volume"] == pytest.approx(9.0, **APPROX)
    layer = _rows(rep, model_report.LAYER)[DEFAULT_LAYER]
    assert layer["area"] == pytest.approx(30.0, **APPROX)


def test_non_uniform_and_mirrored_scale():
    scene = Scene()
    m = QMatrix4x4()
    m.scale(-2.0, 1.0, 3.0)                        # mirrored in X
    scene.groups.append(_instance(_cube(), "Bloque", m))

    row = _rows(model_report.collect_report(scene),
                model_report.COMPONENT)["Bloque"]
    # Box 2 × 1 × 3: area 2(2+6+3) = 22, volume 6, both positive.
    assert row["area"] == pytest.approx(22.0, **APPROX)
    assert row["volume"] == pytest.approx(6.0, **APPROX)


def test_a_component_counts_its_nested_parts():
    scene = Scene()
    leg = _instance(_cube(), "Pata", QMatrix4x4())
    table = _instance(Mesh(), "Mesa", QMatrix4x4())
    table.adopt([leg])
    scene.groups.append(table)

    rows = _rows(model_report.collect_report(scene), model_report.COMPONENT)
    assert rows["Mesa"]["volume"] == pytest.approx(1.0, **APPROX)
    assert rows["Pata"]["count"] == 1
    assert rows["Pata"]["volume"] == pytest.approx(1.0, **APPROX)


def test_plain_groups_are_not_components():
    scene = Scene()
    scene.groups.append(Group(_cube(), name="Grupo suelto"))
    assert model_report.collect_report(scene)[model_report.COMPONENT] == []


def test_report_is_stable_while_a_group_is_open():
    scene = Scene()
    _square(scene.mesh)
    g = Group(_cube(o=(3, 0, 0)), name="Caseta")
    scene.groups.append(g)

    closed = model_report.collect_report(scene)
    scene.begin_group_edit(g)
    opened = model_report.collect_report(scene)
    scene.end_group_edit()
    assert opened == closed


# ---- CSV -------------------------------------------------------------------

def test_csv_is_one_long_table_with_raw_numbers():
    scene = Scene()
    scene.layers.append(Layer("Muros, exteriores"))
    g = _instance(_cube(), "Silla", QMatrix4x4())
    g.layer = "Muros, exteriores"
    scene.groups.append(g)
    _square(scene.mesh, z=-2.0)

    text = model_report.report_csv(model_report.collect_report(scene),
                                   no_material_label="(sin material)")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["grouping", "name", "count", "faces", "area_m2",
                       "volume_m3", "value"]
    assert all(len(r) == 7 for r in rows)
    by = {(r[0], r[1]): r for r in rows[1:]}
    assert by[("layer", "Muros, exteriores")][4:6] == ["6.0000", "1.0000"]
    assert by[("layer", DEFAULT_LAYER)][5] == ""   # empty, not zero
    assert ("material", "(sin material)") in by
    assert by[("component", "Silla")][2] == "1"
    assert {r[0] for r in rows[1:]} == set(model_report.GROUPINGS)


def test_csv_of_one_grouping_only():
    """«Export shown»: just the table on screen."""
    scene = Scene()
    scene.groups.append(_instance(_cube(), "Silla", QMatrix4x4()))
    text = model_report.report_csv(model_report.collect_report(scene),
                                   groupings=(model_report.COMPONENT,))
    rows = list(csv.reader(io.StringIO(text)))
    assert [r[0] for r in rows[1:]] == ["component"]


def test_empty_scene():
    rep = model_report.collect_report(Scene())
    assert rep[model_report.MATERIAL] == []
    assert rep[model_report.COMPONENT] == []
    text = model_report.report_csv(rep)
    assert text.splitlines()[0].startswith("grouping,")


# ---- The Report tab in Model Info ---------------------------------------------

def test_model_info_report_tab_shows_and_exports(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from plugins.model_info import ModelInfoDialog
    from views.filedialogs import file_dialogs

    scene = Scene()
    proto = _cube()
    scene.groups += [_instance(proto, "Silla", QMatrix4x4()),
                     _instance(proto, "Silla", QMatrix4x4())]
    viewport = QWidget()
    viewport.scene = scene
    dlg = ModelInfoDialog(viewport)

    dlg._report_by.setCurrentIndex(
        dlg._report_by.findData(model_report.COMPONENT))
    table = dlg._report_table
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "Silla"
    assert table.item(0, 1).text() == "2"
    assert dlg._export_all_btn.isEnabled() and dlg._export_shown_btn.isEnabled()

    out = tmp_path / "informe.csv"
    monkeypatch.setattr(file_dialogs, "getSaveFileName",
                        lambda *a, **k: (str(out), ""))

    def read():
        return list(csv.reader(io.StringIO(out.read_text(encoding="utf-8"))))

    # Export all: the three groupings plus the rest of Model Info.
    dlg._export_all_btn.click()
    rows = read()
    silla = [r for r in rows if r[:2] == ["component", "Silla"]]
    assert silla and silla[0][2] == "2" and silla[0][5] == "2.0000"
    kinds = {r[0] for r in rows[1:]}
    assert {"layer", "material", "component", "summary"} <= kinds
    summary = {r[1]: r for r in rows if r[0] == "summary"}
    assert summary["faces"][2] == "12"             # 2 instances × 6 faces
    assert summary["component_instances"][2] == "2"
    assert summary["width_m"][6] == "1.0000"

    # Export shown: only the component table on screen.
    dlg._export_shown_btn.click()
    assert {r[0] for r in read()[1:]} == {"component"}
    dlg.close()


def test_export_all_carries_bim_objects_and_location():
    from core import bim
    from georef.datum import SceneDatum
    from plugins.model_info import _collect_stats, info_csv_rows

    scene = Scene()
    _cube(scene.mesh)
    bim.tag_faces(list(scene.mesh.faces), "IfcColumn", "C-1", obj_id=1)
    scene.georef = SceneDatum(-12.05, -77.04)

    rows = info_csv_rows(_collect_stats(scene))
    assert all(len(r) == len(model_report.CSV_HEADER) for r in rows)
    col = [r for r in rows if r[0] == "bim"]
    assert col == [["bim", "C-1", 1, "", "6.0000", "1.0000", "IfcColumn"]]
    loc = {r[1]: r[6] for r in rows if r[0] == "location"}
    assert loc["latitude"].startswith("-12.05")
    assert loc["utm_zone"] == "18S"
