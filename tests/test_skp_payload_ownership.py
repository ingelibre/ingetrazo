# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Owned imports release geometry without changing placement or undo/redo."""
import copy
import weakref

import pytest
from PySide6.QtGui import QMatrix4x4

from core.history import History, SnapshotImport
from core.scene import Scene
from formats import igz, skp


class _Faces(list):
    pass


def _payload():
    faces = _Faces([([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [],
                     {"color": [0.2, 0.3, 0.4], "back": True})])
    return {
        "backend": "test", "groups": [{"name": "plain", "faces": faces,
                                           "soft_edges": []}],
        "protos": [
            {"name": "parent", "faces": copy.deepcopy(faces), "soft_edges": [],
             "instances": [QMatrix4x4(), QMatrix4x4()],
             "children": [{"proto": 1, "xform": QMatrix4x4(), "layer": "nested"}]},
            {"name": "child", "faces": copy.deepcopy(faces), "soft_edges": [],
             "instances": []},
        ],
    }


def _ids(groups, prefix=""):
    for i, g in enumerate(groups):
        g.uid = f"{prefix}/{i}"
        _ids(g.children or [], g.uid)


def test_consumption_matches_retained_payload_and_redo(tmp_path):
    retained, consumed = _payload(), _payload()
    expected, actual = Scene(), Scene()
    skp.apply_payload(expected, retained, consume=False)
    history = History(actual)
    calls = []

    def apply(scene):
        calls.append(1)
        skp.apply_payload(scene, consumed, consume=True)

    history.execute(SnapshotImport(apply))
    assert consumed["groups"] == consumed["protos"] == []
    assert retained["groups"][0]["faces"]
    assert actual.groups[1].mesh is actual.groups[2].mesh
    assert actual.groups[1].children[0].mesh is actual.groups[2].children[0].mesh
    assert actual.groups[1].children[0].layer == "nested"
    history.undo()
    assert actual.groups == []
    history.redo()
    assert calls == [1]
    _ids(expected.groups)
    _ids(actual.groups)
    before, after = tmp_path / "before.igz", tmp_path / "after.igz"
    igz.save_scene(expected, before)
    igz.save_scene(actual, after)
    assert before.read_bytes() == after.read_bytes()


def test_geometry_is_released_before_the_next_part(monkeypatch):
    import time

    payload = _payload()
    refs = [weakref.ref(p["faces"]) for p in payload["groups"] + payload["protos"]]
    clock = iter(range(1, 101))
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    alive = []
    scene = Scene()

    def progress(frac, text):
        assert all(g.mesh.faces or g.children for g in scene.groups)
        alive.append([r() is not None for r in refs])

    skp.apply_payload(scene, payload, progress, consume=True)
    assert alive[:4] == [[True, True, True], [False, True, True],
                         [False, False, True], [False, False, False]]
    assert all(r() is None for r in refs)


def test_shared_payload_lists_are_not_cleared_in_place():
    payload = _payload()
    faces = payload["groups"][0]["faces"]
    payload["protos"][0]["faces"] = faces
    scene = Scene()
    skp.apply_payload(scene, payload, consume=True)
    assert faces
    assert all(len(g.mesh.faces) == 1 for g in scene.groups)


@pytest.mark.parametrize("marker, consume, released", [
    (False, None, False), (True, None, True), (True, False, False),
])
def test_explicit_retention_overrides_parse_ownership(marker, consume, released):
    payload = _payload()
    payload["_consume_geometry"] = marker
    skp.apply_payload(Scene(), payload, consume=consume)
    assert (not payload["groups"]) is released


def test_parse_marks_geometry_owned_without_applying_it(tmp_path, monkeypatch):
    path = tmp_path / "owned.skp"
    path.write_bytes(b"unused")
    backend = type("Backend", (), {
        "available": lambda self: True, "supports": lambda self, fmt: True,
        "parse": lambda self, path, progress=None: _payload(),
    })()
    monkeypatch.setattr(skp, "_BACKENDS", [backend])
    payload = skp.parse_skp(path)
    assert payload["_consume_geometry"] is True
    assert payload["groups"][0]["faces"]


def test_failed_owned_import_still_rolls_back_the_command(monkeypatch):
    import gc
    import time

    payload = _payload()
    scene = Scene()
    history = History(scene)
    clock = iter(range(1, 101))
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    enabled = gc.isenabled()

    def progress(frac, text):
        if scene.groups:
            raise RuntimeError("interrupted import")

    history.execute(SnapshotImport(
        lambda s: skp.apply_payload(s, payload, progress, consume=True)))
    assert history.last_error == "SnapshotImport: interrupted import"
    assert not scene.groups
    assert gc.isenabled() == enabled
    assert not payload["groups"][0]["faces"]
    assert payload["protos"][0]["faces"]


def test_repeated_part_record_keeps_geometry_until_its_last_use():
    payload = _payload()
    payload["groups"].append(payload["groups"][0])
    payload["protos"][0]["faces"] = payload["groups"][0]["faces"]
    scene = Scene()
    skp.apply_payload(scene, payload, consume=True)
    assert len(scene.groups) == 4
    assert all(len(g.mesh.faces) == 1 for g in scene.groups)
    assert payload["groups"] == payload["protos"] == []
