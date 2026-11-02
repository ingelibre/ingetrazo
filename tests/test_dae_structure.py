"""COLLADA export keeps the model's structure (groups, components, tags) and
IngeTrazo reads its own .dae back as it was."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from PySide6.QtGui import QImage, QMatrix4x4, QVector3D

from core.group import Group
from core.layers import Layer
from core.materials import Material, register
from core.mesh import Mesh
from core.scene import Scene
from formats import dae as dae_format

_NS = "{http://www.collada.org/2005/11/COLLADASchema}"


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _box(size=1.0, color=(0.8, 0.2, 0.2)) -> Mesh:
    m = Mesh()
    s = size
    c = [V(0, 0), V(s, 0), V(s, s), V(0, s),
         V(0, 0, s), V(s, 0, s), V(s, s, s), V(0, s, s)]
    for q in ([3, 2, 1, 0], [4, 5, 6, 7], [0, 1, 5, 4],
              [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]):
        f = m.add_face([c[i] for i in q])
        f.attrs["color"] = color
    return m


def _placed(mesh, x, name) -> Group:
    g = Group(mesh, name=name)
    m = QMatrix4x4()
    m.translate(x, 0, 0)
    g.xform = m
    return g


def _scene() -> Scene:
    scene = Scene()
    scene.materials = {}
    register(scene.materials, Material("Concreto visto", (0.6, 0.6, 0.6)))
    # Loose geometry: an L-shaped (concave) face, a face with a hole and a
    # free edge.
    ell = scene.mesh.add_face([V(0, 0), V(4, 0), V(4, 1), V(1, 1), V(1, 3), V(0, 3)])
    ell.attrs.update({"color": (0.6, 0.6, 0.6), "mat": "Concreto visto"})
    scene.mesh.add_face([V(10, 0), V(14, 0), V(14, 4), V(10, 4)],
                        [[V(11, 1), V(11, 3), V(13, 3), V(13, 1)]])
    scene.mesh.add_edge(V(0, 10), V(5, 10))
    # A tagged classic group with a space in its name.
    scene.layers.append(Layer("Muros exteriores"))
    wall = Group(_box(2.0), name="Muro 1")
    wall.layer = "Muros exteriores"
    scene.groups.append(wall)
    # Two copies of one component.
    chair = _box(0.5, (0.1, 0.4, 0.8))
    scene.groups.append(_placed(chair, 20, "Silla"))
    scene.groups.append(_placed(chair, 22, "Silla"))
    # A group that nests a component.
    table = _placed(_box(1.0, (0.5, 0.3, 0.1)), 30, "Mesa con silla")
    table.adopt([_placed(chair, 2, "Silla")])
    table.component = False
    scene.groups.append(table)
    return scene


def _roundtrip(tmp_path, scene):
    path = tmp_path / "m.dae"
    dae_format.save_dae(scene, path)
    back = Scene()
    dae_format.load_dae(back, path)
    return path, back


def test_components_are_one_definition_with_placed_instances(tmp_path):
    path = tmp_path / "m.dae"
    dae_format.save_dae(_scene(), path)
    root = ET.parse(path).getroot()
    lib = root.find(f"{_NS}library_nodes")
    assert lib is not None and len(lib.findall(f"{_NS}node")) == 1
    insts = list(root.iter(f"{_NS}instance_node"))
    assert len(insts) == 3                       # two chairs + the nested one
    assert {i.get("url") for i in insts} == {"#" + lib[0].get("id")}
    # Each copy carries its own placement.
    placed = [n for n in root.iter(f"{_NS}node")
              if n.find(f"{_NS}instance_node") is not None]
    assert all(n.find(f"{_NS}matrix") is not None for n in placed)


def test_names_and_tags_are_schema_safe_and_kept_exactly(tmp_path):
    path = tmp_path / "m.dae"
    dae_format.save_dae(_scene(), path)
    root = ET.parse(path).getroot()
    wall = next(n for n in root.iter(f"{_NS}node") if n.get("name") == "Muro_1")
    assert wall.get("layer") == "Muros_exteriores"
    for el in root.iter():
        name = el.get("name")
        if name is not None and el.tag != f"{_NS}param":
            assert " " not in name, el.tag
    back = Scene()
    dae_format.load_dae(back, path)
    wall2 = next(g for g in back.groups if g.name == "Muro 1")
    assert wall2.layer == "Muros exteriores"
    assert any(ly.name == "Muros exteriores" for ly in back.layers)


def test_faces_are_polygons_and_concave_or_holed_faces_come_back_whole(tmp_path):
    path, back = _roundtrip(tmp_path, _scene())
    root = ET.parse(path).getroot()
    assert list(root.iter(f"{_NS}polylist"))
    assert list(root.iter(f"{_NS}triangles"))    # the L and the holed face
    sizes = sorted(len(f.loop) for f in back.mesh.faces)
    assert sizes == [4, 6]
    holed = next(f for f in back.mesh.faces if len(f.loop) == 4)
    assert len(holed.hole_loops) == 1
    ell = next(f for f in back.mesh.faces if len(f.loop) == 6)
    assert ell.attrs.get("mat") == "Concreto visto"
    assert "Concreto visto" in back.materials


def test_free_edges_and_soft_edges_survive(tmp_path):
    scene = _scene()
    box = next(g for g in scene.groups if g.name == "Muro 1").mesh
    shared = next(e for e in box.edges if len(e.faces) == 2)
    shared.soft = True
    _path, back = _roundtrip(tmp_path, scene)
    assert sum(1 for e in back.mesh.edges if not e.faces) == 1
    wall = next(g for g in back.groups if g.name == "Muro 1")
    assert sum(1 for e in wall.mesh.edges if e.soft) == 1


def test_structure_comes_back_as_it_was(tmp_path):
    _path, back = _roundtrip(tmp_path, _scene())
    by_name = {}
    for g in back.groups:
        by_name.setdefault(g.name, []).append(g)
    chairs = by_name["Silla"]
    assert len(chairs) == 2 and all(g.is_component() for g in chairs)
    table = by_name["Mesa con silla"][0]
    assert not table.is_component() and len(table.children) == 1
    nested = table.children[0]
    assert nested.is_component()
    # One prototype mesh shared by every chair, nested one included.
    assert chairs[0].mesh is chairs[1].mesh is nested.mesh
    assert abs(chairs[1].xform.map(V(0, 0)).x() - 22.0) < 1e-6


def test_textured_face_exports_image_and_reimports_texture(tmp_path):
    img = QImage(8, 8, QImage.Format_RGB888)
    img.fill(0x884422)
    png = tmp_path / "madera.png"
    img.save(str(png))
    scene = Scene()
    f = scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 1), V(0, 1)])
    f.attrs["texture"] = {"path": str(png), "sw": 1.0, "sh": 1.0}
    out = tmp_path / "out" / "t.dae"
    out.parent.mkdir()
    dae_format.save_dae(scene, out)
    assert (out.parent / "madera.png").exists()
    back = Scene()
    dae_format.load_dae(back, out)
    tex = back.mesh.faces[0].attrs.get("texture")
    assert tex and tex["path"].endswith("madera.png")
