# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Groups import as groups and components as components (#1029, @antrrax).

A 2021+ .skp marks each definition's kind (``8315``: 0 component, 1 group,
2 image); the reader kept only «image», so a group placed once came in as a
component, and six small copies of one component came in as six loose
groups — the file's groups and components read the other way round. The
kind is now noted during the parse, and a component copied side by side at
the top level is shared whatever its size."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

pytest.importorskip("openskp")

from formats import openskp_compat, skp_openskp  # noqa: E402

_ID = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]


def _at(x):
    return _ID[:9] + [x, 0, 0, 1]


def _box_def(did, name, instances=()):
    """A 1-face definition (well under the sharing thresholds)."""
    return NS(
        id=did, name=name,
        vertices={1: NS(id=1, x=0, y=0, z=0), 2: NS(id=2, x=10, y=0, z=0),
                  3: NS(id=3, x=10, y=10, z=0), 4: NS(id=4, x=0, y=10, z=0)},
        edges={10: NS(id=10, v1_id=1, v2_id=2), 11: NS(id=11, v1_id=2, v2_id=3),
               12: NS(id=12, v1_id=3, v2_id=4), 13: NS(id=13, v1_id=4, v2_id=1)},
        faces={20: NS(id=20, loops=[[(10, 1), (11, 1), (12, 1), (13, 1)]],
                      normal=(0, 0, 1), material_id=None)},
        instances=list(instances))


def _empty(did, name, instances=()):
    return NS(id=did, name=name, vertices={}, edges={}, faces={},
              instances=list(instances))


@pytest.fixture
def kinds():
    """The state a parse leaves: which definitions were groups."""
    def note(groups):
        openskp_compat.reset_group_definitions()
        openskp_compat._parse_tables.kinds = True
        openskp_compat._parse_tables.groups = set(groups)
    yield note
    openskp_compat.reset_group_definitions()


def _model():
    shelf = _box_def(5, "panela_prateleira")
    side = _box_def(6, "panela_lateral")
    group = _box_def(7, "Agrupar#1")
    inner = _box_def(8, "dobradica")
    cabinet = _empty(9, "armario", [NS(ref_idx=8, matrix=_ID)])
    root = _empty(0, "ROOT_MODEL", [
        NS(ref_idx=5, matrix=_at(0)), NS(ref_idx=5, matrix=_at(20)),
        NS(ref_idx=5, matrix=_at(40)),
        NS(ref_idx=6, matrix=_at(60)),
        NS(ref_idx=7, matrix=_at(80)),
        NS(ref_idx=8, matrix=_at(100)), NS(ref_idx=9, matrix=_at(120)),
    ])
    return NS(definitions={d.id: d for d in (root, shelf, side, group,
                                             inner, cabinet)})


def _protos_by_name(payload):
    return {p["name"]: p for p in payload["protos"]}


def test_a_small_component_copied_at_the_top_level_is_shared(kinds):
    kinds({7})
    protos = _protos_by_name(skp_openskp._adapt(_model(), "m"))
    shelf = protos["panela_prateleira"]
    assert len(shelf["instances"]) == 3 and shelf["component"] is True
    # Placed once: a component, as before.
    assert protos["panela_lateral"]["component"] is True
    # A group placed once is a group.
    assert protos["Agrupar#1"]["component"] is False
    # Copied once at the top and once inside another definition: left as
    # it was, or the nested copy would leave its parent.
    assert "dobradica" not in protos


def test_without_the_kinds_nothing_changes(kinds):
    openskp_compat.reset_group_definitions()        # kinds unknown
    protos = _protos_by_name(skp_openskp._adapt(_model(), "m"))
    assert "panela_prateleira" not in protos
    assert protos["Agrupar#1"]["component"] is True


def test_the_definition_kind_is_noted_during_the_parse():
    from openskp import _core
    openskp_compat.apply()
    openskp_compat.reset_group_definitions()
    try:
        def rec(tag, payload):
            return {"tag": tag, "payload": payload, "children": []}

        builder = _core._GeometryBuilder()
        _core._extract_geometry_from_nodes(
            [rec("DE05", b"\x2a"), rec("8315", b"\x01\x00\x00\x00")], builder)
        _core._extract_geometry_from_nodes(
            [rec("DE05", b"\x2b"), rec("8315", b"\x00\x00\x00\x00")], builder)
        assert openskp_compat.group_definitions() == {0x2a}
        assert openskp_compat.kinds_known(False)
    finally:
        openskp_compat.reset_group_definitions()


def test_lines_on_a_hidden_tag_stay_out():
    """The loose lines #922 brings in follow the file's tags: the plaza's
    survey contours sit on two hidden tags and covered the whole model; a
    line inside a group does not hide with its tag here, so the ones the
    file hides are left out (lines on a visible tag still come)."""
    def v(i, x):
        return NS(id=i, x=x, y=0, z=0)
    lines = NS(id=5, name="top.dwg", faces={}, instances=[],
               vertices={1: v(1, 0), 2: v(2, 10), 3: v(3, 20), 4: v(4, 30),
                         5: v(5, 40), 6: v(6, 50)},
               edges={10: NS(id=10, v1_id=1, v2_id=2, layer="CVL_CURV"),
                      11: NS(id=11, v1_id=3, v2_id=4, layer="limite"),
                      12: NS(id=12, v1_id=5, v2_id=6, layer=None)})
    root = _empty(0, "ROOT_MODEL", [NS(ref_idx=5, matrix=_ID)])
    model = NS(definitions={0: root, 5: lines},
               layers=[NS(name="CVL_CURV", hidden=True),
                       NS(name="limite", hidden=False)])
    payload = skp_openskp._adapt(model, "plaza")
    got = [seg for part in payload["groups"] + payload["protos"]
           for seg in part.get("loose_edges") or []]
    assert sorted(round(a[0] / 0.0254) for a, _b in got) == [20, 40]
