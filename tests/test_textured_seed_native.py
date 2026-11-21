# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Rust engine bakes the textured MESH faces a paint walks again
(``Viewport._seed_textured_native``, Bloque 6c): a push that moves the
cap of a textured pillar changes every wall each frame. What it keeps
must be what ``_append_textured_face`` and ``_tris_of`` make in Python,
float for float and in the same runs: convex, concave, holed, thin and
degenerate faces, fitted and planar maps, turned and scaled tiles, walls
swept out and in. Without the engine the seed does nothing."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math  # noqa: E402
import random  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402
from core.mesh import Mesh  # noqa: E402

_app = QApplication.instance() or QApplication([])

ENGINE = (_native.native is not None and _native.qt_hypot() is not None
          and hasattr(_native.native, "textured_faces_bake"))

MAPS = [
    {"path": "/x/a.png", "sw": 1.0, "sh": 1.0},
    {"path": "/x/b.png", "sw": 0.37, "sh": 2.5, "rot": 30.0},
    {"path": "/x/a.png", "sw": 2, "sh": 0.5, "rot": -117.5},
    {"path": "/x/c.png", "uvw": [0.3, -0.2, 0.1, 0.25, 0.05, 0.4, -0.3, 1.5]},
]


@pytest.fixture(scope="module")
def vp():
    from views.main_window import MainWindow
    from views.viewport import Viewport
    win = MainWindow()
    if ENGINE:
        # The seed waits for the engine's preview check (which bakes a
        # sample of these faces both ways too).
        Viewport._preview_native_state = None
        assert win.viewport._check_preview_native()
    yield win.viewport
    win._saved_version = win.viewport.scene.version
    win.close()


def _forget(vp):
    vp.__dict__["_tex_face_memo"] = {}
    vp._tri_memo = None
    vp._newell_memo = None


def _face(points, holes=()):
    return Mesh().add_face(points, [list(h) for h in holes] or None)


def _random_faces(rng, count=60):
    out = []
    for _ in range(count):
        kind = rng.choice(["quad", "star", "holed", "thin", "tiny", "far"])
        o = V(rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5))
        if kind == "far":
            o = o + V(4000.0, -2500.0, 30.0)
        ax = V(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
        if rng.random() < 0.3:
            ax = rng.choice([V(0, 0, 1), V(0, 0, -1), V(1, 0, 0), V(0, 1, 0)])
        u = V.crossProduct(ax, V(0.3, 0.1, 1)).normalized()
        if u.length() < 0.5:
            u = V(1, 0, 0)
        w = V.crossProduct(ax, u).normalized()
        if kind in ("quad", "far"):
            a, b = rng.uniform(0.1, 3), rng.uniform(0.1, 3)
            f = _face([o, o + u * a, o + u * a + w * b, o + w * b])
        elif kind in ("star", "holed"):
            n = rng.randint(5, 40)
            pts = [o + u * (math.cos(2 * math.pi * k / n)
                            * (1.0 if k % 2 or kind == "holed" else 0.45))
                   + w * (math.sin(2 * math.pi * k / n)
                          * (1.0 if k % 2 or kind == "holed" else 0.45))
                   for k in range(n)]
            holes = ([[o + u * (0.3 * math.cos(-2 * math.pi * k / 6))
                       + w * (0.3 * math.sin(-2 * math.pi * k / 6))
                       for k in range(6)]] if kind == "holed" else [])
            f = _face(pts, holes)
        elif kind == "thin":
            f = _face([o, o + u * 3, o + u * 3 + w * 1e-4, o + w * 1e-4])
        else:
            f = _face([o, o + u * 2e-3, o + w * 2e-3])
        f.attrs = {"texture": dict(rng.choice(MAPS))}
        out.append(f)
    return out


def _pillar_walls(n, off):
    """The walls (and the cap) of an ``n``-sided pillar whose cap a push
    moved by ``off``: what a prism preview leaves in the mesh."""
    m = Mesh()
    low = [V(math.cos(2 * math.pi * k / n), math.sin(2 * math.pi * k / n), 0)
           for k in range(n)]
    high = [p + V(0, 0, 3.0 + off) for p in low]
    faces = [m.add_face(list(reversed(low))), m.add_face(high)]
    for i in range(n):
        j = (i + 1) % n
        faces.append(m.add_face([low[i], low[j], high[j], high[i]]))
    for k, f in enumerate(faces):
        f.attrs = {"texture": dict(MAPS[k % len(MAPS)])}
    return faces


def _bake(vp, faces, seed):
    _forget(vp)
    if seed:
        vp._seed_textured_native(faces)
    seeded = len(vp.__dict__["_tex_face_memo"])
    by_tex = {}
    tris = []
    for f in faces:
        vp._append_textured_face(by_tex, f, f.attrs["texture"])
        tris.append([tuple(p.toTuple() for p in t) for t in vp._tris_of(f)])
    return ({k: v.tobytes() for k, v in by_tex.items()}, list(by_tex), tris,
            seeded)


def _same(vp, faces):
    want = _bake(vp, faces, seed=False)
    got = _bake(vp, faces, seed=True)
    if ENGINE:
        assert got[3] == len(faces), "the engine left faces to Python"
    else:
        assert got[3] == 0, "the seed ran without the engine"
    assert got[1] == want[1], "the runs come in another order"
    for key in want[0]:
        assert got[0][key] == want[0][key], key
    assert got[2] == want[2], "other triangles"


@pytest.mark.parametrize("seed", range(10))
def test_random_textured_faces_seed_what_python_bakes(vp, seed):
    _same(vp, _random_faces(random.Random(seed)))


@pytest.mark.parametrize("off", [0.0, 0.37, 2.5, -1.2, -2.999])
@pytest.mark.parametrize("n", [4, 7, 100])
def test_a_pushed_pillars_walls_seed_what_python_bakes(vp, n, off):
    _same(vp, _pillar_walls(n, off))


def test_a_non_finite_corner_is_left_to_python(vp):
    faces = _random_faces(random.Random(99), count=8)
    bad = _face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
    bad.loop[2].position = V(1, float("nan"), 0)
    bad.attrs = {"texture": dict(MAPS[0])}
    faces.insert(3, bad)
    _forget(vp)
    vp._seed_textured_native(faces)
    memo = vp.__dict__["_tex_face_memo"]
    assert all(s[0] != id(bad) for s in memo)
    if ENGINE:
        assert len(memo) == len(faces) - 1


def test_nothing_is_seeded_before_the_check(vp, monkeypatch):
    from views.viewport import Viewport
    monkeypatch.setattr(Viewport, "_preview_native_state", None)
    faces = _pillar_walls(12, 0.5)
    _forget(vp)
    vp._seed_textured_native(faces)
    assert vp.__dict__["_tex_face_memo"] == {}
    if ENGINE:
        assert vp._textured_seed_matches(faces)


def test_few_faces_stay_in_python(vp):
    faces = _random_faces(random.Random(5), count=vp.NATIVE_TEX_MIN_FACES - 1)
    _forget(vp)
    vp._seed_textured_native(faces)
    assert vp.__dict__["_tex_face_memo"] == {}


def test_a_seeded_face_is_walked_again_once_it_moves(vp):
    faces = _pillar_walls(12, 0.5)
    _forget(vp)
    vp._seed_textured_native(faces)
    wall = faces[5]
    v = wall.loop[2]
    v.position = v.position + V(0, 0, 0.25)
    vp._tri_memo = None
    by_tex = {}
    vp._append_textured_face(by_tex, wall, wall.attrs["texture"])
    want = _bake(vp, [wall], seed=False)[0]
    assert {k: b.tobytes() for k, b in by_tex.items()} == want


# ---- The whole loose bake --------------------------------------------------

def _capture(vp, monkeypatch, seed):
    """What one ``_sync_edges`` uploads, slot by slot."""
    got = {}

    def upload(vbo, slot, parts, empty=24):
        raw = b"".join(parts)
        got[slot] = raw
        return len(raw)

    monkeypatch.setattr(vp, "_upload_vbo", upload)
    for name in ("_dback_vbo", "_edges_vbo", "_faces_vbo", "_selected_vbo",
                 "_sel_faces_vbo", "_tex_faces_vbo"):
        if not hasattr(vp, name):
            monkeypatch.setattr(vp, name, None, raising=False)
    if not seed:
        monkeypatch.setattr(vp, "_seed_textured_native",
                            lambda *a, **k: {})
    _forget(vp)
    vp._edges_version = None
    vp.scene.version += 1
    vp._sync_edges()
    monkeypatch.undo()
    runs = (list(vp._tex_runs), list(getattr(vp, "_ttex_runs", [])),
            list(getattr(vp, "_back_tex_runs", [])))
    return got, runs


@pytest.mark.parametrize("off", [0.8, -1.4])
def test_the_loose_bake_uploads_what_python_uploads(vp, monkeypatch, off):
    sc = vp.scene
    mesh = sc.loose_mesh
    for f in _pillar_walls(24, off):
        nf = mesh.add_face(list(f.vertices))
        nf.attrs = dict(f.attrs)
    # A colour face, a glass one, a two-sided one and a holed textured one.
    plain = mesh.add_face([V(5, 0, 0), V(7, 0, 0), V(7, 2, 0), V(5, 2, 0)])
    plain.attrs = {"color": (0.2, 0.5, 0.7)}
    glass = mesh.add_face([V(5, 3, 0), V(7, 3, 0), V(7, 5, 1), V(5, 5, 1)])
    glass.attrs = {"texture": dict(MAPS[1]), "opacity": 0.5}
    two = mesh.add_face([V(5, 6, 0), V(7, 6, 0), V(7, 8, 2), V(5, 8, 2)])
    two.attrs = {"texture": dict(MAPS[0]), "back": {"color": (0.9, 0.1, 0.1)}}
    holed = mesh.add_face(
        [V(-9, -9, 0), V(-3, -9, 0), V(-3, -3, 0), V(-9, -3, 0)],
        [[V(-7, -7, 0), V(-7, -5, 0), V(-5, -5, 0), V(-5, -7, 0)]])
    holed.attrs = {"texture": dict(MAPS[3])}
    hidden = mesh.faces[3]
    vp.set_suppressed_faces({hidden})
    try:
        want = _capture(vp, monkeypatch, seed=False)
        got = _capture(vp, monkeypatch, seed=True)
        if ENGINE:
            assert len(vp.__dict__["_tex_face_memo"]) >= 24
        assert got[1] == want[1]
        assert sorted(got[0]) == sorted(want[0])
        for slot in want[0]:
            assert got[0][slot] == want[0][slot], slot
    finally:
        vp.set_suppressed_faces(set())
