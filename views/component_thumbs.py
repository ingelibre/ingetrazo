# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Thumbnails for the tray's «In model» list: a small picture of each
component definition, drawn by hand.

Not a render — the GL renderer is never touched, which is what keeps the
tray cheap. The faces are projected from one fixed corner (front-right,
from above), painted back to front with a plain light on their own colour,
and fitted to the icon. Enough to tell a chair from a table at a glance.
A definition is drawn once and kept; a change to its geometry, its paint
or its subgroups draws it again.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

#: Icon side, in pixels.
SIZE = 40
#: Faces drawn at most: a big definition is thinned evenly, which still
#: reads at this size and keeps a refresh well under a frame.
MAX_FACES = 3000
#: Vertices read for the change check, at most.
_PROBE = 2000

#: Where the picture is seen from (towards the viewer), and the light.
_EYE = (0.62, -0.74, 0.55)
_LIGHT = (0.35, -0.55, 0.85)
#: The default material's front, as the viewport shows it.
_DEFAULT = (0.96, 0.95, 0.925)

_cache: dict = {}


def _unit(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / n for c in v)


_E = _unit(_EYE)
_R = _unit((-_E[1], _E[0], 0.0))
_U = _unit((_E[1] * _R[2] - _E[2] * _R[1],
            _E[2] * _R[0] - _E[0] * _R[2],
            _E[0] * _R[1] - _E[1] * _R[0]))
_L = _unit(_LIGHT)


def _placements(definition, m=None, depth=0):
    """``(mesh, matrix_or_None, paint)`` for the definition's own mesh and
    every subgroup below it, in the definition's coordinates — its own
    placement in the model is left out, so every copy draws the same."""
    paint = getattr(definition, "material", None)
    yield definition.mesh, m, paint
    if depth > 16:
        return
    for child in getattr(definition, "children", None) or ():
        xf = getattr(child, "xform", None)
        cm = xf if m is None else (m if xf is None else m * xf)
        yield from _placements(child, cm, depth + 1)


def _signature(definition) -> tuple:
    """What the picture depends on: counts, a sampled coordinate sum and
    the paint of each piece. Cheap, and it changes when the geometry does."""
    sig = []
    for mesh, m, paint in _placements(definition):
        verts = mesh.vertices
        step = max(1, len(verts) // _PROBE)
        s = 0.0
        for v in verts[::step]:
            p = v.position
            s += p.x() + p.y() * 1.000003 + p.z() * 1.000007
        faces = mesh.faces
        fstep = max(1, len(faces) // _PROBE)
        colors = tuple(_paint_key(f.attrs) for f in faces[::fstep])
        sig.append((id(mesh), len(verts), len(faces), round(s, 6),
                    hash(colors), _paint_key(paint),
                    tuple(m.data()) if m is not None else None))
    return tuple(sig)


def _paint_key(attrs):
    if not attrs:
        return None
    c = attrs.get("color")
    t = attrs.get("texture")
    return (tuple(round(float(x), 3) for x in c) if c else None,
            t.get("path") if isinstance(t, dict) else None)


def _rgb(attrs, inherited):
    """The colour a face shows: its own paint, else the definition's, else
    the default material. A texture without a colour reads as a mid tone."""
    for paint in (attrs, inherited):
        if not paint:
            continue
        c = paint.get("color")
        if c:
            return tuple(float(x) for x in c[:3])
        if paint.get("texture"):
            return (0.72, 0.66, 0.58)
    return _DEFAULT


def thumbnail(definition, size: int = SIZE) -> QPixmap:
    """The icon for ``definition`` (a component instance or a kept
    template), from the cache when nothing it shows has changed."""
    sig, pm = cached_thumbnail(definition, size)
    if pm is not None:
        return pm
    return draw_thumbnail(definition, sig, size)


def cached_thumbnail(definition, size: int = SIZE):
    """``(signature, icon)``: the icon from the cache, or ``None`` when it
    has to be drawn (:func:`draw_thumbnail`, with the same signature) —
    so a caller can spread the drawing over several turns of the loop."""
    sig = _signature(definition)
    hit = _cache.get((sig[0][0], size))
    if hit is not None and hit[0] == sig:
        return sig, hit[1]
    return sig, None


def draw_thumbnail(definition, sig, size: int = SIZE) -> QPixmap:
    """Draw ``definition``'s icon and keep it under ``sig``."""
    key = (sig[0][0], size)
    pm = _draw(definition, size)
    # Past this, definitions long gone. (256 was below the 1 815 of a big
    # plant, and scrolling its list drew every picture again, #158.)
    if len(_cache) > 4096:
        _cache.clear()
    _cache[key] = (sig, pm)
    return pm


def _draw(definition, size: int) -> QPixmap:
    """The picture, painted far to near.

    The per-face arithmetic runs in numpy over every face at once, in the
    same order the one-face-at-a-time loop of 0.6.2 did it (``_draw_ref``
    in the tests): the same doubles, so the same pixels. That loop was
    ~50 ms a picture on the pergolas of a large plaza, and the twelve rows
    a selection scrolls into view landed inside the next Ctrl+Z (20-11)."""
    total = sum(len(mesh.faces) for mesh, _m, _p in _placements(definition))
    stride = max(1, math.ceil(total / MAX_FACES))
    coords = []                     # x, y, z of every corner, face after face
    lens = []
    rgbs = []
    k = 0
    for mesh, m, paint in _placements(definition):
        rgb_of = {}
        for f in mesh.faces:
            k += 1
            if k % stride:
                continue
            loop = f.loop
            if len(loop) < 3:
                continue
            if m is None:
                for v in loop:
                    coords.extend(v.position.toTuple())
            else:
                for v in loop:
                    coords.extend(m.map(v.position).toTuple())
            lens.append(len(loop))
            attrs = f.attrs
            rgb = rgb_of.get(id(attrs))
            if rgb is None:
                rgb = rgb_of[id(attrs)] = _rgb(attrs, paint)
            rgbs.append(rgb)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    if not lens:
        return pm
    P = np.array(coords, dtype=np.float64).reshape(-1, 3)
    lens = np.array(lens, dtype=np.int64)
    starts = np.zeros(len(lens), dtype=np.int64)
    np.cumsum(lens[:-1], out=starts[1:])
    nf = len(lens)
    nx = np.zeros(nf)
    ny = np.zeros(nf)
    nz = np.zeros(nf)
    depth = np.zeros(nf)
    px, py, pz = P[:, 0], P[:, 1], P[:, 2]
    # Faces of one corner count at a time: their sums run column by
    # column, corner 0 first, as the loop added them.
    for n in np.unique(lens).tolist():
        rows = np.nonzero(lens == n)[0]
        base = starts[rows]
        # Newell, from 0.0, corner after corner.
        sx = np.zeros(len(rows))
        sy = np.zeros(len(rows))
        sz = np.zeros(len(rows))
        # The depth: ``sum()`` of the corners' depths — 0 + the first,
        # then Neumaier's compensated sum, as CPython's sum() of floats.
        acc = comp = None
        for i in range(n):
            ia = base + i
            ib = base + (i + 1) % n
            ax, ay, az = px[ia], py[ia], pz[ia]
            bx, by, bz = px[ib], py[ib], pz[ib]
            sx = sx + (ay - by) * (az + bz)
            sy = sy + (az - bz) * (ax + bx)
            sz = sz + (ax - bx) * (ay + by)
            d = ax * _E[0] + ay * _E[1] + az * _E[2]
            if acc is None:
                acc = 0.0 + d
                comp = np.zeros(len(rows))
            else:
                t = acc + d
                comp = comp + np.where(np.abs(acc) >= np.abs(d),
                                       (acc - t) + d, (d - t) + acc)
                acc = t
        fix = (comp != 0.0) & np.isfinite(comp)
        acc = np.where(fix, acc + comp, acc)
        nx[rows], ny[rows], nz[rows] = sx, sy, sz
        depth[rows] = acc / float(n)
    nn = np.sqrt(nx * nx + ny * ny + nz * nz)
    keep = ~(nn < 1e-12)
    if not keep.any():
        return pm
    with np.errstate(invalid="ignore", divide="ignore"):
        ux, uy, uz = nx / nn, ny / nn, nz / nn
    lam = np.abs(ux * _L[0] + uy * _L[1] + uz * _L[2])
    X = px * _R[0] + py * _R[1] + pz * _R[2]
    Y = -(px * _U[0] + py * _U[1] + pz * _U[2])
    # Only the corners of the faces drawn set the frame.
    corner_kept = np.repeat(keep, lens)
    xs, ys = X[corner_kept], Y[corner_kept]
    x0, x1 = float(xs.min()), float(xs.max())
    y0, y1 = float(ys.min()), float(ys.max())
    span = max(x1 - x0, y1 - y0) or 1.0
    margin = 2.0
    scale = (size - 2 * margin) / span
    ox = margin + (size - 2 * margin - (x1 - x0) * scale) / 2
    oy = margin + (size - 2 * margin - (y1 - y0) * scale) / 2
    SX = (ox + (X - x0) * scale).tolist()
    SY = (oy + (Y - y0) * scale).tolist()
    kk = 0.5 + 0.5 * lam
    rgb = np.array(rgbs, dtype=np.float64)
    shade = np.minimum(1.0, rgb * kk[:, None]).tolist()
    drawn = np.nonzero(keep)[0]
    # Far first: nearer ones cover; equal depths keep the faces' order.
    order = drawn[np.argsort(depth[drawn], kind="stable")].tolist()
    starts = starts.tolist()
    lens = lens.tolist()
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    for j in order:
        col = QColor.fromRgbF(*shade[j])
        p.setBrush(col)
        p.setPen(QPen(col.darker(150), 0.6))
        a = starts[j]
        p.drawPolygon([QPointF(SX[i], SY[i]) for i in range(a, a + lens[j])])
    p.end()
    return pm
