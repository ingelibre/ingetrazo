"""Nested placements: a component keeps the internal sharing SketchUp gave it.

The hedge in ``piscina`` is 9600 stored faces placed 48 times inside its own
definition. Flattening that on import produced 230400 real faces — 89% of the
model, 24x over — which is why our .skp came out at 80 MB against the
original's 14. These tests pin the contract that fixes it: the geometry is
stored ONCE and placed by matrix, while the user still sees (and clicks) ONE
object.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QMatrix4x4, QVector3D  # noqa: E402

from core.group import (Group, copy_group, iter_placements,  # noqa: E402
                        world_mesh)
from core.mesh import Mesh  # noqa: E402
from core.scene import Scene  # noqa: E402
from views.viewport import Viewport  # noqa: E402


def _unit_quad(mesh, z=0.0):
    return mesh.add_face([QVector3D(0, 0, z), QVector3D(1, 0, z),
                          QVector3D(1, 1, z), QVector3D(0, 1, z)])


def _at(*t):
    m = QMatrix4x4()
    m.translate(QVector3D(*t))
    return m


def _tree():
    """One prototype quad, placed twice inside a child that is itself placed
    inside the top-level group — two levels of nesting over ONE mesh."""
    proto = Mesh()
    _unit_quad(proto)
    leaf_a = Group(proto, name="leaf A")
    leaf_a.xform = _at(0, 0, 0)
    leaf_b = Group(proto, name="leaf B")
    leaf_b.xform = _at(10, 0, 0)
    mid = Group(proto, name="mid")
    mid.xform = _at(0, 100, 0)
    mid.children = [leaf_a, leaf_b]
    top = Group(proto, name="top")
    top.xform = _at(0, 0, 1000)
    top.children = [mid]
    return top, proto


def test_iter_placements_composes_the_chain():
    top, proto = _tree()
    seen = [(g.name, (m(0, 3), m(1, 3), m(2, 3))) for g, m in
            iter_placements(top)]
    assert seen == [("top", (0.0, 0.0, 1000.0)),
                    ("mid", (0.0, 100.0, 1000.0)),
                    ("leaf A", (0.0, 100.0, 1000.0)),
                    ("leaf B", (10.0, 100.0, 1000.0))]
    assert all(g.mesh is proto for g, _ in iter_placements(top))  # ONE mesh


def test_world_mesh_folds_children_without_touching_the_prototype():
    top, proto = _tree()
    world = world_mesh(top)
    assert len(proto.faces) == 1                  # stored once...
    assert len(world.faces) == 4                  # ...drawn four times
    xs = sorted({round(v.position.x()) for v in world.vertices})
    zs = sorted({round(v.position.z()) for v in world.vertices})
    assert xs == [0, 1, 10, 11] and zs == [1000]


def test_copy_group_keeps_the_nesting_and_the_shared_prototype():
    top, proto = _tree()
    dup = copy_group(top, QVector3D(0, 0, 7))
    assert len(dup.children) == 1 and len(dup.children[0].children) == 2
    assert all(g.mesh is proto for g, _ in iter_placements(dup))
    zs = {round(v.position.z()) for v in world_mesh(dup).vertices}
    assert zs == {1007}
    assert len(world_mesh(top).faces) == 4        # source untouched


def test_materialize_bakes_children_in_and_drops_them():
    top, _ = _tree()
    top.materialize()
    assert top.xform is None and top.children == []
    assert len(top.mesh.faces) == 4               # nothing drawn twice


class _VP:
    """Minimal stand-in for the viewport's placement expansion."""

    def __init__(self, scene):
        self.scene = scene
        for name in ("_placements", "_expand_placements", "_owner_of",
                     "_draws_in_edit_context"):
            setattr(self, name, getattr(Viewport, name).__get__(self))


def test_placements_expand_for_draw_and_map_back_to_the_owner():
    scene = Scene()
    top, _ = _tree()
    scene.groups.append(top)
    vp = _VP(scene)
    out = vp._placements()
    assert len(out) == 4                          # every placement draws
    assert out[0] is top
    assert all(vp._owner_of(g) is top for g in out)   # ONE object to click
    # The proxies carry composed world matrices, so each draws its prototype
    # in the right place with no copy of the geometry.
    assert [(m(0, 3), m(1, 3), m(2, 3)) for m in
            (g.xform for g in out[1:])] == [(0.0, 100.0, 1000.0),
                                            (0.0, 100.0, 1000.0),
                                            (10.0, 100.0, 1000.0)]


def test_placement_proxies_are_stable_across_frames():
    """The chunk caches key on ``id(group)``: a fresh proxy per frame would
    re-transform every instance's arrays every frame."""
    scene = Scene()
    top, _ = _tree()
    scene.groups.append(top)
    vp = _VP(scene)
    first = vp._placements()
    assert [id(g) for g in vp._placements()] == [id(g) for g in first]
    top.xform = _at(0, 0, 2000)                   # a Move drag
    again = vp._placements()
    assert [id(g) for g in again] == [id(g) for g in first]   # same objects
    assert again[1].xform(2, 3) == 2000.0                     # new matrices


def test_flat_scenes_take_the_untouched_fast_path():
    scene = Scene()
    plain = Group(Mesh(), name="plain")
    _unit_quad(plain.mesh)
    scene.groups.append(plain)
    assert _VP(scene)._placements() is scene.groups


def test_hidden_owner_hides_its_nested_placements():
    scene = Scene()
    top, _ = _tree()
    top.layer = "oculta"
    top.children[0].layer = "visible"             # a differently tagged child
    from core.layers import Layer
    scene.layers.append(Layer("oculta", visible=False))
    scene.layers.append(Layer("visible"))
    scene.groups.append(top)
    out = _VP(scene)._placements()
    assert not any(scene.entity_visible(g) for g in out)


def test_editing_into_a_nested_group_bakes_it():
    """Inside a group you edit real geometry, so the internal sharing has to
    become real faces first — SketchUp does the same."""
    scene = Scene()
    top, _ = _tree()
    scene.groups.append(top)
    scene.begin_group_edit(top)
    assert scene.mesh is top.mesh
    assert len(top.mesh.faces) == 4 and top.children == []


def test_igz_round_trip_keeps_the_tree_and_writes_the_prototype_once(tmp_path):
    """The whole point: what a document stores is one copy of the geometry
    plus a matrix per placement."""
    from formats.igz import _read_document, load_into, save_scene

    scene = Scene()
    top, proto = _tree()
    top.layer = "vegetacion"
    scene.groups.append(top)
    path = tmp_path / "arbolito.igz"
    save_scene(scene, path)

    raw = _read_document(path)[0]["scene"]
    assert len(raw["protos"]) == 1        # ONE mesh on disk...
    assert len(raw["protos"][0]["faces"]) == 1
    assert len(raw["groups"]) == 1        # ...one top-level object...
    kids = raw["groups"][0]["children"]
    assert len(kids) == 1 and len(kids[0]["children"]) == 2   # ...tree intact

    back = Scene()
    load_into(back, path)
    assert len(back.groups) == 1
    g = back.groups[0]
    assert g.layer == "vegetacion"
    assert len(world_mesh(g).faces) == 4
    assert len({id(pg.mesh) for pg, _ in iter_placements(g)}) == 1


def test_scene_queries_see_the_nested_geometry():
    """Bounds, world faces and the render views all used to walk
    ``scene.groups`` and read ``g.mesh`` — which is blind to what a component
    places inside itself."""
    from formats.meshexport import world_faces

    scene = Scene()
    top, _ = _tree()
    scene.groups.append(top)
    assert len(list(scene.placements())) == 4
    assert len(list(scene.render_faces())) == 4
    assert len(list(world_faces(scene))) == 4
    lo, hi = scene.bounds()
    assert (round(lo.x()), round(hi.x())) == (0, 11)     # leaf B at x=10
    assert (round(lo.y()), round(hi.y())) == (0, 101)    # mid at y=100
    assert (round(lo.z()), round(hi.z())) == (1000, 1000)


def test_a_group_that_owns_placements_is_always_an_instance():
    """Move/Rotate/Scale compose into ``xform`` for an instance and walk the
    vertices otherwise — and walking the vertices would leave the children
    behind."""
    plain = Group(Mesh(), name="classic")
    _unit_quad(plain.mesh)
    kid = Group(plain.mesh, name="kid")
    kid.xform = _at(3, 0, 0)
    assert plain.xform is None
    plain.adopt([kid])
    assert plain.xform is not None
    assert len(world_mesh(plain).faces) == 2


def test_skp_export_writes_the_prototype_once_and_places_it(tmp_path):
    from formats.skp_out import _split_containers, save_skp

    scene = Scene()
    proto = Mesh()
    _unit_quad(proto)
    inner = [Group(proto, name=f"hoja {i}") for i in range(6)]
    for i, g in enumerate(inner):
        g.xform = _at(i * 2.0, 0, 0)
    bush = Group(Mesh(), name="arbusto")
    bush.xform = _at(0, 0, 0)
    bush.adopt(inner)
    scene.groups.append(bush)
    scene.groups.append(copy_group(bush, QVector3D(0, 50, 0)))

    loose, classic, defs, roots = _split_containers(scene)
    # ONE definition for the leaf, ONE for the bush that places it six times,
    # and the two bushes are placements of that same definition.
    assert not loose and not classic
    assert len(defs) == 2
    leaf, container = defs[0], defs[1]
    assert len(leaf["mesh"].faces) == 1 and not leaf["children"]
    assert not container["mesh"].faces and len(container["children"]) == 6
    assert all(ci == 0 for ci, _c in container["children"])
    assert [di for di, _g in roots] == [1, 1]

    out = tmp_path / "arbustos.skp"
    save_skp(scene, out)
    assert out.exists() and out.stat().st_size > 0


def test_the_drag_preview_carries_the_whole_subtree():
    """The scratch copy a drag draws is built from the groups handed to
    ``begin_groups_preview``. Handing it only the top-level group uploaded an
    EMPTY copy — the component stood still through the drag and teleported on
    release (Marco: "cuando roto o muevo tiene laj bastante")."""
    scene = Scene()
    top, _ = _tree()
    scene.groups.append(top)
    vp = _VP(scene)
    movers = vp._expand_placements(top)
    assert len(movers) == 4                        # every placement moves
    assert movers[0] is top
    assert sum(len(g.mesh.faces) for g in movers) == 4
    # and the same objects the draw list uses, so skipping them by id works
    assert [id(g) for g in movers] == [id(g) for g in vp._placements()]


def test_box_selection_reaches_nested_geometry():
    from tools.select import _box_group_fast

    scene = Scene()
    top, _ = _tree()
    scene.groups.append(top)
    vp = _VP(scene)
    # No projector on the stub: the fast path must bail cleanly rather than
    # claim the group is outside the box because its own mesh looks empty.
    assert _box_group_fast(vp, top, (0, 0, 10, 10), True) is None


def test_explode_brings_the_nested_geometry_out():
    from core.history import ExplodeGroupCommand, History

    scene = Scene()
    top, _ = _tree()
    scene.groups.append(top)
    h = History(scene)
    h.execute(ExplodeGroupCommand(top))
    assert not scene.groups
    assert len(scene.mesh.faces) == 4              # nothing left behind
    xs = sorted({round(v.position.x()) for v in scene.mesh.vertices})
    assert xs == [0, 1, 10, 11]                    # the far leaf came out too
    h.undo()
    assert len(scene.groups) == 1 and not scene.mesh.faces


def test_the_selection_box_follows_a_moved_group():
    """The box is world geometry cached ON the chunk, and the translation
    fast path moved every array except that one — so a moved component left
    a ghost rectangle where it used to be. Predates nesting; fixed for every
    group."""
    from core.group import oriented_box_corners

    scene = Scene()
    top, _ = _tree()
    scene.groups.append(top)
    vp = _VP(scene)
    for name in ("_group_chunk", "_instance_chunk", "_shift_instance_entry",
                 "_group_obb", "_group_fp", "_shift_chunk",
                 "_append_textured_face", "_shaded_color", "_shade_factor",
                 "_newell_of", "_area_of", "_tris_of", "_normal_of"):
        setattr(vp, name, getattr(Viewport, name).__get__(vp))
    for name in ("_shift_obb", "_samples_match", "_translation_probe",
                 "_mesh_fingerprint"):          # staticmethods
        setattr(vp, name, getattr(Viewport, name))
    vp.DEFAULT_FACE_COLOR = Viewport.DEFAULT_FACE_COLOR
    vp._LIGHT = Viewport._LIGHT

    def centre():
        cs = oriented_box_corners(*vp._group_obb(top))
        return QVector3D(sum(c.x() for c in cs) / len(cs),
                         sum(c.y() for c in cs) / len(cs),
                         sum(c.z() for c in cs) / len(cs))

    before = centre()
    top.xform = _at(7, 0, 0) * top.xform          # a Move drag
    scene.version += 1
    after = centre()
    assert round(after.x() - before.x(), 6) == 7.0
    assert round(after.y() - before.y(), 6) == 0.0
    assert round(after.z() - before.z(), 6) == 0.0
