# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Owned raw geometry is released at its last use without changing imports."""
import copy
from types import SimpleNamespace as NS

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.scene import Scene
from formats import igz, skp, skp_openskp as adapter
from formats.skp_consumption import PrototypeGeometry
from tests.test_skp_backend import _tri_def, _fake_definition


def _instance(did, material=None, **kwargs):
    return NS(ref_idx=did, material_id=material,
              matrix=[1, 0, 0, 0, 1, 0, 0, 0, 1, did * 10, 0, 0, 1], **kwargs)


def _model():
    a = _tri_def(1, "first", [_instance(3)])
    b = _tri_def(2, "second", [_instance(3)])
    c = _tri_def(3, "nested")
    a.edges[10].soft = True
    root = _fake_definition(id=0, name="ROOT_MODEL", verts={}, edges={}, faces={},
                            instances=[_instance(1, 1), _instance(1, 2),
                                       _instance(2, 1), _instance(2, 1)])
    mats = {i: NS(name=str(i), color=color, transparency=1, id=i, texture=None)
            for i, color in ((1, (255, 0, 0)), (2, (0, 255, 0)))}
    return NS(root=root, definitions={1: a, 2: b, 3: c}, materials_by_id=mats)


def _canonical(x):
    if isinstance(x, QVector3D):
        return list(x.toTuple())
    if isinstance(x, QMatrix4x4):
        return list(x.data())
    if isinstance(x, dict):
        return {k: _canonical(v) for k, v in x.items()}
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return [_canonical(v) for v in x]


def _uids(groups, prefix=""):
    for i, g in enumerate(groups):
        g.uid = f"{prefix}/{i}"
        _uids(g.children or (), g.uid)


@pytest.mark.parametrize("variant", ["shared", "flattened", "tagged", "faceme", "cycle"])
def test_consumed_and_reusable_models_have_identical_payload_and_bytes(
        variant, monkeypatch, tmp_path):
    from formats import dae
    monkeypatch.setattr(dae, "_INST_MIN_POLYS", 1 if variant != "flattened" else 100)
    monkeypatch.setattr(dae, "_INST_MIN_SAVED", 1 if variant != "flattened" else 100)
    model = _model()
    if variant == "tagged":
        model.definitions[1].instances[0].layer = "nested tag"
    elif variant == "faceme":
        model.definitions[1].always_faces_camera = True
    elif variant == "cycle":
        model.definitions[3].instances.append(_instance(1))
    owned = copy.deepcopy(model)
    before = adapter._adapt(model, "test")
    after = adapter._adapt(owned, "test", consume=True)
    assert _canonical(before) == _canonical(after)
    assert all(d.faces for d in model.definitions.values())
    assert all(not d.faces and not d.edges and not d.vertices
               for d in owned.definitions.values())
    # Cycle payloads are compared above; applying a recursive placement is
    # outside this adapter ownership test.
    if variant == "cycle":
        return
    for label, payload in (("before", before), ("after", after)):
        scene = Scene()
        skp.apply_payload(scene, payload)
        _uids(scene.groups)
        igz.save_scene(scene, tmp_path / f"{label}.igz")
    assert (tmp_path / "before.igz").read_bytes() == (tmp_path / "after.igz").read_bytes()


def test_release_precedes_next_unrelated_prototype(monkeypatch):
    model = _model()
    # Each of two one-off top-level components is a separate prototype.
    model.root.instances = [_instance(1), _instance(2)]
    model.definitions[1].instances = []
    model.definitions[2].instances = []
    old = adapter._collect
    observed = []

    def collect(d, *args, **kwargs):
        if d.id == 2:
            first = model.definitions[1]
            observed.append((bool(first.faces), hasattr(first, "_geom")))
        return old(d, *args, **kwargs)

    monkeypatch.setattr(adapter, "_collect", collect)
    adapter._adapt(model, "test", consume=True)
    assert observed == [(False, False)]


def test_flattened_dependency_survives_all_material_variants_and_aliases():
    model = _model()
    defs = model.definitions
    # Child 3 is flattened into both parents, and parent 1 has two paints.
    consumer = PrototypeGeometry(defs, {1, 2}, [(1, 1), (1, 2), (2, 1)], [], 32)
    consumer.release((1, 1))
    assert defs[1].faces and defs[3].faces
    consumer.release((1, 2))
    assert not defs[1].faces and defs[3].faces
    consumer.release((2, 1))
    assert not defs[2].faces and not defs[3].faces
    assert not consumer.remaining


def test_depth_guard_and_aliased_tables():
    a, b = _tri_def(1, "a"), _tri_def(2, "b")
    b.faces = a.faces
    original = a.faces
    consumer = PrototypeGeometry({1: a, 2: b}, {1, 2}, [(1, None), (2, None)], [], 0)
    consumer.release((1, None))
    assert not a.faces and b.faces is original and original
    consumer.release((2, None))
    assert not b.faces and original


def test_parse_transfers_only_its_private_model_and_keeps_progress(monkeypatch):
    import openskp
    from formats import openskp_compat
    model = _model()
    monkeypatch.setattr(openskp.SkpFile, "open", lambda path: NS(parse=lambda: model))
    monkeypatch.setattr(openskp_compat, "apply", lambda: None)
    monkeypatch.setattr(openskp_compat, "resolve_face_layers", lambda m: None)
    calls = []
    assert adapter.parse("test.skp", lambda f, text: calls.append(f))
    assert calls == [0.1, 0.6]
    assert all(not d.faces for d in model.definitions.values())


@pytest.mark.parametrize("transformed", [False, True])
def test_packed_soft_segments_preserve_endpoint_bits_repr_and_pickle(transformed):
    import pickle
    import struct
    import numpy as np
    from formats.skp_consumption import SoftSegments
    d = _tri_def(1, "soft")
    for edge in d.edges.values():
        edge.soft = True
    d.vertices[1].x = -0.0
    transform = QMatrix4x4()
    if transformed:
        transform.rotate(37, 1, 2, 3)
        transform.translate(-2.3, 7.1, -0.0)
    expected, actual = [], SoftSegments()
    adapter._soft_edge_segments(d, transform, expected)
    adapter._soft_edge_segments(d, transform, actual)
    # Both the flat double-precision byte representation and dedup repr agree.
    def bits(segments):
        return b"".join(struct.pack("ddd", *p) for pair in segments for p in pair)
    assert bits(actual) == bits(expected)
    assert repr(actual) == repr(expected)
    assert actual[-1] == expected[-1]
    assert actual[::-1] == expected[::-1]
    assert bits(pickle.loads(pickle.dumps(actual))) == bits(expected)
    assert sum(c.nbytes for c in actual.chunks) == len(expected) * 24
    assert all(c.dtype == np.float32 and not c.flags.writeable for c in actual.chunks)


def test_one_use_flattened_geometry_is_released_before_next_group(monkeypatch):
    model = _model()
    # Tagged subtrees are deliberately flattened instead of promoted.
    model.root.instances = [_instance(1), _instance(2)]
    model.definitions[1].instances[0].layer = "a"
    model.definitions[2].instances[0].layer = "b"
    old = adapter._collect
    observed = []

    def collect(d, *args, **kwargs):
        if d.id == 2:
            observed.append(bool(model.definitions[1].faces))
            # The twice-used child must remain available for both tags.
            assert model.definitions[3].faces
        return old(d, *args, **kwargs)

    monkeypatch.setattr(adapter, "_collect", collect)
    adapter._adapt(model, "test", consume=True)
    assert observed == [False]


@pytest.mark.parametrize("veto", ["cycle", "depth"])
def test_early_release_defers_ambiguous_or_global_reads(veto):
    from formats.skp_consumption import FlatGeometry
    root = _tri_def(0, "root", [_instance(1)])
    child = _tri_def(1, "child")
    defs = {0: root, 1: child}
    if veto == "cycle":
        child.instances = [_instance(0)]
    tracker = FlatGeometry(defs, set(), {1: 1}, [root], 0 if veto == "depth" else 32)
    tracker.release(child)
    assert child.faces and child.vertices and child.edges



def test_repeated_flat_geometry_survives_until_its_last_visit():
    from formats.skp_consumption import FlatGeometry
    root = _tri_def(0, "root", [_instance(1), _instance(1)])
    child = _tri_def(1, "child")
    tracker = FlatGeometry({0: root, 1: child}, set(), {1: 2}, [root], 32)
    tracker.release(child)
    assert child.faces and child.edges and child.vertices
    tracker.release(child)
    assert not child.faces and not child.edges and not child.vertices


@pytest.mark.parametrize("test_name", [
    "test_openskp_adapter_image_entities_become_billboards",
    "test_a_cutout_image_stuck_on_a_face_stays_put",
])
@pytest.mark.parametrize("nested", [False, True])
def test_image_attachment_parity_when_support_geometry_is_consumed(
        test_name, nested, tmp_path, monkeypatch):
    from tests import test_skp_backend
    original = adapter._adapt
    checked = []

    def compare(model, *args, **kwargs):
        # A tagged child makes the support panel a flattened group, which can
        # be released before the image groups are built. Keep its face intact.
        panel = model.definitions.get(7)
        if panel is not None:
            model.definitions[999] = _tri_def(999, "tagged child")
            panel.instances.append(_instance(999, layer="nested tag"))
        if nested:
            root = model.definitions[0]
            model.definitions[1000] = _fake_definition(
                id=1000, name="container", verts={}, edges={}, faces={},
                instances=root.instances)
            root.instances = [_instance(1000, 51, layer="outer tag")]
            root.instances[0].matrix = [0, 1, 0, -1, 0, 0, 0, 0, 1, 20, 30, 0, 1]
        expected = original(copy.deepcopy(model), *args, **kwargs)
        actual = original(model, *args, **kwargs, consume=True)
        assert _canonical(actual) == _canonical(expected)
        if panel is not None:
            assert not panel.faces
        checked.append(True)
        return actual

    monkeypatch.setattr(adapter, "_adapt", compare)
    getattr(test_skp_backend, test_name)(tmp_path)
    assert checked
