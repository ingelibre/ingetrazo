# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SKP import keeps the file's groups, nested as the file nests them.

``tests/data/test_export.skp`` (a .skp of the 2017 version) holds one group «geometries»
with «closed» (a circle and a rectangle, each a group) and «lines» (two
edges, no face). It arrived as ONE component named after its definition
(«Gruppe#3») with both faces flattened into it and the lines gone. Now each
group is a Group of the name the user gave it, nested as in the file, a
group and not a component, and the lines-only group comes with its lines —
with every corner where it was."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4  # noqa: E402

pytest.importorskip("openskp")

from core.scene import Scene  # noqa: E402
from formats.skp import load_skp  # noqa: E402

_FILE = Path(__file__).parent / "data" / "test_export.skp"


@pytest.fixture(scope="module")
def scene():
    s = Scene()
    load_skp(s, _FILE)
    return s


def _tree(groups):
    return [(g.name, _tree(g.children)) for g in groups]


def _by_name(groups, name):
    for g in groups:
        if g.name == name:
            return g
        found = _by_name(g.children, name)
        if found is not None:
            return found
    return None


def test_the_groups_nest_as_in_the_file(scene):
    assert _tree(scene.groups) == [
        ("geometries", [("closed", [("circle", []), ("rectangle", [])]),
                        ("lines", [])])]


def test_groups_import_as_groups_not_components(scene):
    def walk(gs):
        for g in gs:
            yield g
            yield from walk(g.children)
    assert not any(g.is_component() for g in walk(scene.groups))


def test_each_face_lives_in_its_own_group(scene):
    assert len(_by_name(scene.groups, "circle").mesh.faces) == 1
    assert len(_by_name(scene.groups, "rectangle").mesh.faces) == 1
    assert len(_by_name(scene.groups, "rectangle").mesh.edges) == 4
    for name in ("geometries", "closed", "lines"):
        assert not _by_name(scene.groups, name).mesh.faces


def test_a_group_of_only_lines_keeps_its_lines(scene):
    lines = _by_name(scene.groups, "lines")
    assert len(lines.mesh.edges) == 2


def test_nothing_moved_in_the_world(scene):
    """The nesting changes the structure, not where the geometry is: the
    world corners of every face, each group's matrix applied down the tree."""
    corners = []

    def walk(gs, m):
        for g in gs:
            mm = m * (g.xform if g.xform is not None else QMatrix4x4())
            for f in g.mesh.faces:
                for v in f.vertices:              # positions (QVector3D)
                    p = mm.map(v)
                    corners.append((round(p.x(), 3), round(p.y(), 3),
                                    round(p.z(), 3)))
            walk(g.children, mm)
    walk(scene.groups, QMatrix4x4())
    assert len(corners) == 28                      # 24-gon circle + rectangle
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    assert (min(xs), max(xs)) == pytest.approx((1.236, 4.294), abs=1e-3)
    assert (min(ys), max(ys)) == pytest.approx((1.295, 6.169), abs=1e-3)
    assert all(c[2] == 0.0 for c in corners)
