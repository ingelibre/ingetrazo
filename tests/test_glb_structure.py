# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A GLB for other programs keeps the model's structure (#304) and its
scale figures (#353).

Until now the file was ONE mesh named «IngeTrazo»: groups and components
gone, and the face-me figures left out — unless they sat inside a group,
where they came out baked with their picture anchored to the world:
sliding, repeated, mirrored halves. Every check reads the file back
through our importer, which applies the node matrices, so a wrong matrix
shows as triangles in the wrong place.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QImage, QColor, QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.group import Group  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats.glb import read_triangles  # noqa: E402
from formats.gltf import save_glb  # noqa: E402
from tests.test_gltf_dae_export import _read_glb  # noqa: E402


def _square(x0=0.0, color=(0.8, 0.2, 0.2)):
    m = Mesh()
    f = m.add_face([V(x0, 0, 0), V(x0 + 1, 0, 0), V(x0 + 1, 1, 0),
                    V(x0, 1, 0)])
    f.attrs["color"] = list(color)
    return m


def _at(dx, dy=0.0):
    xf = QMatrix4x4()
    xf.translate(dx, dy, 0)
    return xf


def _world_tris(path):
    batches, _js = read_triangles(path)
    return np.concatenate([b[0] for b in batches])


def test_groups_and_components_are_nodes_and_copies_share_one_mesh(tmp_path):
    s = Scene()
    proto = _square()
    for dx in (3.0, 6.0):
        chair = Group(proto, "silla")
        chair.xform = _at(dx)
        s.groups.append(chair)
    table = Group(_square(20.0), "mesa")
    s.groups.append(table)
    out = tmp_path / "m.glb"
    save_glb(s, out)
    gltf, _ = _read_glb(out)
    names = [n["name"] for n in gltf["nodes"]]
    assert names.count("silla") == 2 and "mesa" in names
    chairs = [n for n in gltf["nodes"] if n["name"] == "silla"]
    assert chairs[0]["mesh"] == chairs[1]["mesh"], "copies must share a mesh"
    assert len(gltf["meshes"]) == 2
    xs = sorted({round(float(x), 3) for x in _world_tris(out)[:, :, 0].ravel()})
    assert xs == [3.0, 4.0, 6.0, 7.0, 20.0, 21.0]      # each copy in place


def test_a_nested_component_keeps_its_parent(tmp_path):
    s = Scene()
    leg = Group(_square(), "pata")
    leg.xform = _at(2.0)
    bench = Group(Mesh(), "banca")
    bench.adopt([leg])
    bench.xform = _at(10.0)
    s.groups.append(bench)
    out = tmp_path / "n.glb"
    save_glb(s, out)
    gltf, _ = _read_glb(out)
    root = gltf["nodes"][gltf["scenes"][0]["nodes"][0]]
    assert root["name"] == "banca"
    kid = gltf["nodes"][root["children"][0]]
    assert kid["name"] == "pata"
    xs = _world_tris(out)[:, :, 0]
    assert np.isclose(xs.min(), 12.0) and np.isclose(xs.max(), 13.0)


def _figure(tmp_path, x=0.0):
    img = QImage(8, 16, QImage.Format.Format_ARGB32)
    img.fill(QColor(30, 90, 200))
    png = tmp_path / "persona.png"
    img.save(str(png))
    m = Mesh()
    f = m.add_face([V(x, 0, 0), V(x + 0.5, 0, 0), V(x + 0.5, 0, 1.7),
                    V(x, 0, 1.7)])
    f.attrs["texture"] = {"path": str(png), "sw": 0.5, "sh": 1.7}
    g = Group(m, "Ingeniero")
    g.billboard = True
    return g


def _figure_uvs_are_one_unmirrored_picture(gltf, buf):
    """The figure's quad shows the picture once, left to right as seen
    from the Front view (its U grows with x)."""
    import struct
    node = next(n for n in gltf["nodes"]
                if "ingetrazo_faceme" in n.get("extras", {}))
    prim = gltf["meshes"][node["mesh"]]["primitives"][0]

    def acc(i, n):
        a = gltf["accessors"][i]
        v = gltf["bufferViews"][a["bufferView"]]
        raw = buf[v["byteOffset"]:v["byteOffset"] + v["byteLength"]]
        return np.array(struct.unpack(f"<{a['count'] * n}f", raw)).reshape(-1, n)

    pos = acc(prim["attributes"]["POSITION"], 3)
    uv = acc(prim["attributes"]["TEXCOORD_0"], 2)
    assert uv[:, 0].min() > -1e-6 and uv[:, 0].max() < 1 + 1e-6
    left = uv[np.argmin(pos[:, 0]), 0]
    right = uv[np.argmax(pos[:, 0]), 0]
    assert left < right, "the picture is mirrored"
    return node


def test_a_loose_figure_is_exported_standing_toward_the_front(tmp_path):
    s = Scene()
    s.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
    s.groups.append(_figure(tmp_path, 3.0))
    out = tmp_path / "f.glb"
    save_glb(s, out)
    gltf, buf = _read_glb(out)
    node = _figure_uvs_are_one_unmirrored_picture(gltf, buf)
    feet = node["extras"]["ingetrazo_faceme"]
    assert np.allclose(feet[:3], [3.25, 0.0, 0.0])


def test_a_figure_inside_a_group_is_not_baked_mirrored(tmp_path):
    s = Scene()
    holder = Group(Mesh(), "grupo")
    fig = _figure(tmp_path)
    fig.xform = _at(5.0)
    holder.adopt([fig])
    s.groups.append(holder)
    out = tmp_path / "g.glb"
    save_glb(s, out)
    gltf, buf = _read_glb(out)
    node = _figure_uvs_are_one_unmirrored_picture(gltf, buf)
    assert np.isclose(node["extras"]["ingetrazo_faceme"][0], 5.25)


def test_a_colour_with_alpha_does_not_stop_the_export(tmp_path):
    s = Scene()
    f = s.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
    f.attrs["color"] = [0.1, 0.5, 0.9, 1.0]
    out = tmp_path / "c.glb"
    save_glb(s, out)
    gltf, _ = _read_glb(out)
    assert gltf["materials"][0]["pbrMetallicRoughness"][
        "baseColorFactor"][:3] == [0.1, 0.5, 0.9]


def test_only_the_selection(tmp_path):
    s = Scene()
    keep = s.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
    s.mesh.add_face([V(5, 0, 0), V(6, 0, 0), V(6, 1, 0)])
    chosen = Group(_square(10.0), "elegido")
    other = Group(_square(20.0), "otro")
    s.groups += [chosen, other]
    out = tmp_path / "s.glb"
    save_glb(s, out, only={keep, chosen})
    xs = _world_tris(out)[:, :, 0]
    assert xs.max() < 12.0 and xs.min() >= 0.0
    assert not np.any((xs > 4.5) & (xs < 6.5))          # the other loose face


def test_our_own_wide_model_comes_back_in_metres(tmp_path):
    """Two 1 m squares 60 m apart: wider than the 40 m the importer's guess
    allows, so a file of ours came back shrunk to inches (app bench, 10-10).
    glTF is metres, and ours says who wrote it."""
    from formats.glb import load_glb
    scene = Scene()
    scene.mesh = _square(0.0)
    far = Group(_square(0.0), "far")
    far.xform = _at(60.0)
    scene.groups.append(far)
    path = tmp_path / "wide.glb"
    save_glb(scene, path)
    back = Scene()
    load_glb(back, path)
    lo, hi = back.bounds()
    assert hi.x() - lo.x() == pytest.approx(61.0, abs=1e-3)
