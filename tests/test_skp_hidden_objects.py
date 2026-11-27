# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""#1329: what a .skp hides comes in hidden.

Two kinds of hiding, both lost before: a group or component the user hid
(the Hide stored on a placement, ``Instance.hidden``), and the objects each scene hides
(``Page.hidden_entity_ids``, entity ids). A placement either one touches
must stay an object of its own instead of melting into its parent's mesh.

The models are built like OpenSKP's ``scene_hidden_entities_*.skp``
fixtures: Part A, Part B and a Crate holding Part C, all three parts copies
of one small definition."""
from __future__ import annotations

from types import SimpleNamespace as NS

from core.purge import iter_groups
from core.scene import Scene
from formats import skp as skp_format
from formats import skp_openskp


def _box(did, name, instances=()):
    """A definition with one triangle (inches), placing ``instances``."""
    return NS(
        id=did, name=name,
        vertices={1: NS(id=1, x=0, y=0, z=0), 2: NS(id=2, x=10, y=0, z=0),
                  3: NS(id=3, x=10, y=10, z=0)},
        edges={10: NS(id=10, v1_id=1, v2_id=2), 11: NS(id=11, v1_id=2, v2_id=3),
               12: NS(id=12, v1_id=3, v2_id=1)},
        faces={20: NS(id=20, loops=[[(10, 1), (11, 1), (12, 1)]],
                      normal=(0, 0, 1), material_id=None)},
        instances=list(instances))


def _place(ref, eid, name, x=0.0, hidden=False):
    return NS(ref_idx=ref, id=eid, name=name, hidden=hidden, layer="",
              material_id=None,
              matrix=[1, 0, 0, 0, 1, 0, 0, 0, 1, x, 0, 0, 1])


def _page(name, hidden=(), saves=None):
    """``saves``: ``Page.use_hidden_objects`` (openskp#660); None as an
    older OpenSKP, which has no such property, leaves it."""
    return NS(name=name, eye=(0.0, -100.0, 50.0), target=(0.0, 0.0, 0.0),
              up=(0.0, 0.0, 1.0), fov=35.0, parallel=False, ortho_height=0.0,
              hidden_layers=[], hidden_entity_ids=list(hidden),
              use_hidden_objects=saves)


def _crate_model(*, c_hidden=False, pages=()):
    part = _box(5, "Part")
    crate = _box(6, "Group", [_place(5, 100, "Part C", hidden=c_hidden)])
    root = NS(id=0, name="ROOT_MODEL", vertices={}, edges={}, faces={},
              instances=[_place(5, 70, "Part A"),
                         _place(5, 71, "Part B", x=50),
                         _place(6, 73, "Crate", x=100)])
    return NS(definitions={0: root, 5: part, 6: crate}, pages=list(pages))


def _imported(model):
    scene = Scene()
    skp_format.apply_payload(scene, skp_openskp._adapt(model, "m"))
    groups = {g.name: g for g in iter_groups(scene.groups)}
    return scene, groups


def _view(scene, name):
    return next(v for v in scene.saved_views if v.name == name)


def _names(groups, uids):
    by_uid = {g.uid: name for name, g in groups.items()}
    return sorted(by_uid[u] for u in uids)


def test_a_hidden_group_arrives_hidden():
    _scene, groups = _imported(_crate_model(c_hidden=True))
    # Part C kept as an object of its own inside the Crate (before, a copy
    # of a small definition melted into the Crate's mesh) and hidden.
    assert groups["Part C"].hidden
    assert groups["Part C"] in groups["Crate"].children
    assert not groups["Part A"].hidden
    assert not groups["Crate"].hidden


def test_each_scene_hides_its_own_objects():
    scene, groups = _imported(_crate_model(pages=[
        _page("All"), _page("No B, no crate", [71, 73]),
        _page("No C", [100]), _page("Edge", [17])]))
    assert _names(groups, _view(scene, "No B, no crate").hidden_objects) \
        == ["Crate", "Part B"]
    assert _names(groups, _view(scene, "No C").hidden_objects) == ["Part C"]
    # An empty list cannot tell "hides nothing" from "does not save hidden
    # objects" (OpenSKP does not say yet): the view leaves objects alone.
    assert _view(scene, "All").hidden_objects is None
    # Entity 17 is an edge (hidden geometry), no group: nothing to hide.
    assert _view(scene, "Edge").hidden_objects is None


def test_picking_a_scene_hides_and_shows_what_it_says():
    scene, groups = _imported(_crate_model(pages=[
        _page("No B, no crate", [71, 73]), _page("No C", [100]),
        _page("All")]))
    _view(scene, "No B, no crate").apply_state(scene)
    assert groups["Part B"].hidden and groups["Crate"].hidden
    assert not groups["Part A"].hidden
    _view(scene, "No C").apply_state(scene)
    assert groups["Part C"].hidden
    assert not groups["Part B"].hidden and not groups["Crate"].hidden
    _view(scene, "All").apply_state(scene)      # leaves objects alone
    assert groups["Part C"].hidden


def test_a_scene_that_saves_hidden_objects_and_hides_none_shows_them():
    # OpenSKP's fixtures: «All» saves hidden objects (0x191) and hides none,
    # «Not saved» does not save them (0x001). Both list nothing; the flag
    # tells them apart, and «All» shows again what another scene hid.
    scene, groups = _imported(_crate_model(pages=[
        _page("All", saves=True), _page("No C", [100], saves=True),
        _page("Edge", [17], saves=True), _page("Not saved", saves=False)]))
    assert _view(scene, "All").hidden_objects == []
    assert _view(scene, "Edge").hidden_objects == []   # an edge, no object
    assert _view(scene, "Not saved").hidden_objects is None
    _view(scene, "No C").apply_state(scene)
    assert groups["Part C"].hidden
    _view(scene, "Not saved").apply_state(scene)        # leaves it alone
    assert groups["Part C"].hidden
    _view(scene, "All").apply_state(scene)              # shows it again
    assert not any(g.hidden for g in groups.values())


def test_a_scene_hides_what_was_pulled_out_of_a_flattened_group():
    # A component placed twice at the top level, too small to share, is
    # flattened into one group per copy. A hidden bolt inside it is pulled
    # out next to that group, not inside it, so hiding the copy in a scene
    # must reach the bolt by the copy's id.
    bolt = _box(7, "Bolt")
    part = _box(5, "Part", [_place(7, 200, "Bolt", hidden=True)])
    root = NS(id=0, name="ROOT_MODEL", vertices={}, edges={}, faces={},
              instances=[_place(5, 70, "Left"), _place(5, 71, "Right", x=50)])
    model = NS(definitions={0: root, 5: part, 7: bolt},
               pages=[_page("No left", [70])])
    payload = skp_openskp._adapt(model, "m")
    bolts = [gp for gp in payload["groups"] if gp["name"] == "Bolt"]
    assert sorted(gp["skp_ids"] for gp in bolts) == [[200, 70], [200, 71]]
    assert all(gp["hidden"] for gp in bolts)
    scene = Scene()
    skp_format.apply_payload(scene, payload)
    view = _view(scene, "No left")
    left = [g for g in scene.groups if g.name == "Left"]
    assert view.hidden_objects
    hidden = set(view.hidden_objects)
    assert left and left[0].uid in hidden
    assert sum(g.uid in hidden for g in scene.groups if g.name == "Bolt") == 1


def test_a_file_without_hidden_entities_imports_as_before():
    # An older OpenSKP has no ``hidden_entity_ids`` or ``Instance.id``.
    model = _crate_model()
    for d in model.definitions.values():
        for ins in d.instances:
            del ins.id, ins.hidden
    model.pages = [NS(name="Front", eye=(0.0, -100.0, 50.0),
                      target=(0.0, 0.0, 0.0), up=(0.0, 0.0, 1.0))]
    scene, groups = _imported(model)
    assert "Part C" not in groups        # melts into the Crate, as before
    assert not any(g.hidden for g in groups.values())
    assert _view(scene, "Front").hidden_objects is None
