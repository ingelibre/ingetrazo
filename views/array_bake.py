# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The drawing of a lazy mesh, baked from its arrays (the experimental
engine): the very chunk ``Viewport._group_chunk`` bakes from the built
mesh, field for field, with no vertex, edge or face object made — so a
model that is only looked at stays deferred (core.mesh.DeferredMesh).

The face geometry (Newell normal, area, centroid, triangles) comes from
the Rust kernel, which reproduces views.viewport._face_geometry bit for
bit; the topology from core.lazy_mesh.plan. Textured and two-side
painted faces go through the viewport's own helpers on a stand-alone copy
of the face, as they are a few. tests/test_array_bake.py holds the result
to the object bake."""
from __future__ import annotations

import sys
from array import array

import numpy as np
from PySide6.QtGui import QVector3D

import core._native as _native
from core import lazy_mesh
from core.mesh import DeferredMesh, Face, Vertex


def can_bake(mesh) -> bool:
    """Whether ``mesh`` is deferred and this engine can bake it as is."""
    return (type(mesh) is DeferredMesh and _native.native is not None
            and _native.qt_hypot() is not None)


class DeferredFaces:
    """The ``faces`` of a chunk baked from arrays: the drawn faces, built
    (with their whole mesh) only when one is asked for — a click on it."""

    __slots__ = ("mesh", "index")

    def __init__(self, mesh, index):
        self.mesh = mesh
        self.index = index          # drawn face → face of the mesh

    def __len__(self):
        return len(self.index)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self.mesh.faces[k] for k in self.index[i].tolist()]
        return self.mesh.faces[int(self.index[i])]

    def __iter__(self):
        faces = self.mesh.faces
        return (faces[k] for k in self.index.tolist())


def _geometry(mesh, plan):
    d = mesh.__dict__
    hit = d.get("_deferred_geom")
    if hit is None:
        hit = d["_deferred_geom"] = _native.native.face_geometry(
            plan.pos.astype(np.float32), plan.corners, plan.ring_sizes,
            plan.ring_counts, _native.qt_hypot(),
            sys.version_info >= (3, 12))
    return hit


def prefetch(meshes) -> None:
    """Plan and face geometry of every lazy mesh in ``meshes``, side by
    side: the weld and the kernel let go of the GIL, so the meshes of a
    big model are worked out in parallel before the bake reads them."""
    todo = [m for m in {id(m): m for m in meshes}.values() if can_bake(m)
            and "_deferred_geom" not in m.__dict__]
    if len(todo) < 2:
        return
    import os
    from concurrent.futures import ThreadPoolExecutor

    def work(m):
        try:
            _geometry(m, lazy_mesh.plan_of(m))
        except Exception:          # noqa: BLE001 — the bake will retry
            pass
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as ex:
        list(ex.map(work, todo))


def _attrs_table(src):
    """Each face's own attrs dict (a fresh one per face, as Face keeps)
    is one of a few: the document's table, parsed once."""
    from formats.igz import _face_attrs_from_json
    table = src["meta"].get("face_attrs") or []
    return [(_face_attrs_from_json(t) or {}) for t in table]


def _loose_face(plan, f):
    """A stand-alone copy of face ``f`` (its own vertices at the same
    positions): what the viewport's per-face helpers read."""
    rs = plan.extra.get("ring_start")
    if rs is None:
        rs = plan.extra["ring_start"] = np.concatenate(
            [[0], np.cumsum(plan.ring_sizes)])
        plan.extra["face_ring"] = np.concatenate(
            [[0], np.cumsum(plan.ring_counts)])
    fr = plan.extra["face_ring"]
    rings = []
    for k in range(int(fr[f]), int(fr[f + 1])):
        idx = plan.corners[int(rs[k]):int(rs[k + 1])].tolist()
        rings.append([Vertex(QVector3D(*plan.pos[i])) for i in idx])
    return Face(rings[0], rings[1:] or None)


def fingerprint(mesh, plan, table, face_attr):
    """``Viewport._mesh_fingerprint`` of the built mesh."""
    p = plan.pos
    terms = p[:, 0] + p[:, 1] * 1.000003 + p[:, 2] * 1.000007
    s = float(np.cumsum(terms)[-1]) if len(terms) else 0.0
    a = 0
    for i, k in enumerate(face_attr.tolist()):
        at = table[k] if k >= 0 else None
        if at:
            c = at.get("color")
            t = at.get("texture")
            back = at.get("back")
            a ^= hash((i,
                       None if c is None else tuple(c),
                       None if not t else (t.get("path"), t.get("sw"),
                                           t.get("sh"), t.get("rot", 0),
                                           tuple(t.get("uvw") or ())),
                       at.get("layer"),
                       at.get("opacity"),
                       repr(back) if back else None,
                       bool(at.get("hidden"))))
    soft = int(plan.soft.sum())
    hid = 0
    for i in np.flatnonzero(plan.hidden).tolist():
        hid ^= ((i + 1) * 2654435761) & 0xFFFFFFFF
    return (len(plan.pos), len(plan.edges), plan.nfaces, round(s, 4), a,
            soft, hid)


def shade_factors(vp, vecs):
    """``vp._shade_factor`` of each row of ``vecs`` (N,3) float32 — Qt's
    normalized() from the kernel, the float32 dot with the light, then the
    same float rounding (``np.rint`` ties to even, as ``round``)."""
    n = len(vecs)
    if not n:
        return np.zeros(0)
    ln, unit, _u, _v = _native.native.qt_vector_probe(
        np.ascontiguousarray(vecs, dtype=np.float32), _native.qt_hypot())
    lx, ly, lz = (np.float32(c) for c in vp._LIGHT.toTuple())
    d = np.abs((unit[:, 0] * lx + unit[:, 1] * ly) + unit[:, 2] * lz)
    f = np.rint((0.62 + 0.38 * d.astype(np.float64)) * 32.0) / 32.0
    return np.where(ln.astype(np.float64) < 1e-9, 0.84375, f)


def shaded_colors(base, shade):
    """``vp._shaded_color`` rows: ``base`` (N,3) by ``shade`` (N,)."""
    return np.rint(np.minimum(1.0, base * shade[:, None]) * 64.0) / 64.0


def _ordered(codes_by_face):
    """The distinct codes of a per-face array (-1 = none) in the order
    their first face comes — the order a dict filled face by face keeps."""
    c = codes_by_face[codes_by_face >= 0]
    if not len(c):
        return []
    u, first = np.unique(c, return_index=True)
    return u[np.argsort(first, kind="stable")].tolist()


def _rows(stream, tri_code, code):
    """``stream`` rows (one per triangle) of triangles coded ``code``, as
    the bytes the face-by-face ``array("f")`` fill makes."""
    return stream[tri_code == code].tobytes()


def _corner_stream(tpos, extra):
    """Per triangle, per corner: position then ``extra`` (T, 3, k)."""
    t = len(tpos)
    out = np.empty((t, 3, 3 + extra.shape[2]), dtype=np.float32)
    out[:, :, :3] = tpos
    out[:, :, 3:] = extra
    return out


class LazyFingerprint:
    """A chunk's ``fp`` that is only worked out when compared — a per-face
    walk, and a lazy mesh's chunk is only checked against its fingerprint
    once the mesh is built. Compares, slices and extends as the tuple."""

    __slots__ = ("_args", "_suffix", "_value")

    def __init__(self, args, suffix=()):
        self._args = args
        self._suffix = suffix
        self._value = None

    def value(self) -> tuple:
        if self._value is None:
            self._value = fingerprint(*self._args) + self._suffix
            self._args = None
        return self._value

    def __add__(self, other):
        if self._value is not None:
            return self._value + tuple(other)
        return LazyFingerprint(self._args, self._suffix + tuple(other))

    def __eq__(self, other):
        if isinstance(other, LazyFingerprint):
            other = other.value()
        return self.value() == other

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(self.value())

    def __getitem__(self, i):
        return self.value()[i]

    def __len__(self):
        return len(self.value())

    def __iter__(self):
        return iter(self.value())

    def __repr__(self):
        return f"LazyFingerprint({self.value()!r})"


def bake(vp, mesh, paint, msig, vkey, uid):
    """The chunk entry of deferred ``mesh`` inside a container of paint
    ``paint`` — ``Viewport._group_chunk``'s rebuild, from arrays."""
    from core.materials import back_is_default, effective_attrs
    from core.texture import face_uv_axes

    plan = lazy_mesh.plan_of(mesh)
    src = mesh.__dict__["_deferred_source"]
    (normal, ln, cen, tris_v, tri_face, unit, tris_u,
     tri_face_u) = _geometry(mesh, plan)
    table = _attrs_table(src)
    face_attr = np.asarray(src["face_attr"], dtype=np.int64)
    nf = plan.nfaces
    pos32 = plan.pos.astype(np.float32)

    # Everything but the normal is decided by a face's attrs, i.e. by its
    # table entry (k; -1: no attrs): one row per entry.
    keys = [-1] + [k for k in np.unique(face_attr).tolist() if k >= 0]
    ent = []
    for k in keys:
        own = table[k] if k >= 0 else {}
        fattrs = effective_attrs(own, paint)
        tex = fattrs.get("texture")
        back = fattrs.get("back")
        e = {"hidden": bool(own.get("hidden")), "fattrs": fattrs,
             "textured": tex is not None and bool(tex.get("path")),
             "op": float(fattrs.get("opacity", 1.0)),
             "dback": back_is_default(fattrs), "back": None}
        col = fattrs.get("color")
        e["base"] = tuple(col) if col is not None else vp.DEFAULT_FACE_COLOR
        if isinstance(back, dict):
            bop = float(back.get("opacity", 1.0))
            btex = back.get("texture")
            if btex is not None and btex.get("path"):
                e["back"] = ("ttex" if bop < 0.999 else "tex", btex,
                             round(bop, 3))
            elif back.get("color") is not None:
                e["back"] = ("tcol" if bop < 0.999 else "vcol",
                             tuple(back["color"]), round(bop, 3))
        ckind = e["back"][0] if e["back"] else None
        e["fcull"] = 1 if ckind in ("tcol", "ttex") else 0
        ent.append(e)
    fk = np.searchsorted(np.asarray(keys, dtype=np.int64), face_attr)

    def per_key(name, dtype=bool):
        return np.array([e[name] for e in ent], dtype=dtype)[fk] \
            if nf else np.zeros(0, dtype=dtype)
    hidden = per_key("hidden")
    drawn = np.flatnonzero(~hidden)
    is_drawn = ~hidden
    faces = DeferredFaces(mesh, drawn)
    draw_index = np.full(nf, -1, dtype=np.int64)
    draw_index[drawn] = np.arange(len(drawn))

    # The two triangle streams: by the plain normal (colour faces, pick)
    # and by the unit normal (textures, back sides).
    tfa = tri_face.astype(np.int64)
    tva = tris_v.astype(np.int64)
    tpa = pos32[tva]
    tfb = tri_face_u.astype(np.int64)
    tpb = pos32[tris_u.astype(np.int64)]
    has_tris = np.bincount(tfa, minlength=nf) > 0 if nf else \
        np.zeros(0, dtype=bool)

    # The shade of every face, by both normals, vectorized.
    shade_a = shade_factors(vp, normal)
    shade_bv = shade_factors(vp, unit)
    shade_b_vals, shade_ix = np.unique(shade_bv, return_inverse=True)
    shade_b = shade_b_vals.tolist()
    shade_ix = shade_ix.reshape(-1)

    # ---- back sides (two-side paint) -----------------------------------
    back_vcol_parts: list = []
    back_tex: dict = {}
    back_tcol: dict = {}
    back_ttex: dict = {}
    bcode = np.full(nf, -1, dtype=np.int64)       # face → back bucket
    b_rgb = np.zeros((nf, 3), dtype=np.float64)
    bnames: dict = {}                             # code → bucket key
    nbits_a = normal.view(np.uint32).reshape(nf, 3) if nf else \
        np.zeros((0, 3), np.uint32)

    def uv_maps(faces_ix, tex_of_key):
        """Per face of ``faces_ix``, its world→UV map (texture of its key,
        the plain normal): once per distinct pair. ``(gu, cu, gv, cv)``
        arrays, one row per face."""
        pairs = np.concatenate([fk[faces_ix][:, None].astype(np.uint32),
                                nbits_a[faces_ix]], axis=1)
        u, inv = np.unique(pairs, axis=0, return_inverse=True)
        gu = np.empty((len(u), 3), np.float32)
        gv = np.empty((len(u), 3), np.float32)
        cu = np.empty(len(u))
        cv = np.empty(len(u))
        for j, r in enumerate(u):
            n = QVector3D(*r[1:].astype(np.uint32).view(np.float32).tolist())
            m = face_uv_axes(tex_of_key[int(r[0])], n)
            gu[j], cu[j], gv[j], cv[j] = m[0].toTuple(), m[1], \
                m[2].toTuple(), m[3]
        inv = inv.reshape(-1)
        out = np.full(nf, -1, dtype=np.int64)
        out[faces_ix] = inv
        return out, (gu, cu, gv, cv)

    def uv_stream(face_map, maps):
        """Unit-normal triangles with ``u, v`` per corner (rows of faces
        without a map: zeros)."""
        uv = np.zeros((len(tpb), 3, 2), dtype=np.float32)
        tm = face_map[tfb] if len(tfb) else np.zeros(0, np.int64)
        rows = np.flatnonzero(tm >= 0)
        if len(rows):
            gu, cu, gv, cv = maps
            mi = tm[rows]
            P = tpb[rows]
            g = gu[mi][:, None, :]
            du = (P[:, :, 0] * g[:, :, 0] + P[:, :, 1] * g[:, :, 1]) \
                + P[:, :, 2] * g[:, :, 2]
            g = gv[mi][:, None, :]
            dv = (P[:, :, 0] * g[:, :, 0] + P[:, :, 1] * g[:, :, 1]) \
                + P[:, :, 2] * g[:, :, 2]
            uv[rows, :, 0] = (du.astype(np.float64)
                              + cu[mi][:, None]).astype(np.float32)
            uv[rows, :, 1] = (dv.astype(np.float64)
                              + cv[mi][:, None]).astype(np.float32)
        return _corner_stream(tpb, uv)

    kinds_b = np.array([e["back"][0] if e["back"] else "" for e in ent])
    fkind_b = kinds_b[fk] if nf else np.zeros(0, dtype=kinds_b.dtype)
    # Colour backs: the bucket is the key's; the shade the unit normal's.
    cb = np.flatnonzero(is_drawn & np.isin(fkind_b, ["vcol", "tcol"]))
    if len(cb):
        bases_b = np.array([e["back"][1] if e["back"] and e["back"][0] in
                            ("vcol", "tcol") else (0.0, 0.0, 0.0)
                            for e in ent], dtype=np.float64)
        b_rgb[cb] = shaded_colors(bases_b[fk[cb]], shade_bv[cb])
        key_code = {}
        for i, e in enumerate(ent):
            if e["back"] and e["back"][0] in ("vcol", "tcol"):
                name = ("bvcol",) if e["back"][0] == "vcol" else \
                    ("btcol", e["back"][2])
                key_code[i] = bnames.setdefault(name, len(bnames))
        kc = np.full(len(ent), -1, dtype=np.int64)
        for i, c in key_code.items():
            kc[i] = c
        bcode[cb] = kc[fk[cb]]
    # Textured backs: the bucket is (texture, shade of the unit normal).
    tb = np.flatnonzero(is_drawn & np.isin(fkind_b, ["tex", "ttex"]))
    b_map = np.full(nf, -1, dtype=np.int64)
    b_maps = None
    if len(tb):
        pairs = np.stack([fk[tb], shade_ix[tb]], axis=1)
        u, inv = np.unique(pairs, axis=0, return_inverse=True)
        codes = []
        for k, si in u.tolist():
            kind, btex, bop = ent[k]["back"]
            tkey = (btex["path"], shade_b[si])
            name = ("btex", tkey) if kind == "tex" else ("bttex", (tkey, bop))
            codes.append(bnames.setdefault(name, len(bnames)))
        bcode[tb] = np.asarray(codes, dtype=np.int64)[inv.reshape(-1)]
        tex_b = [e["back"][1] if e["back"] else None for e in ent]
        b_map, b_maps = uv_maps(tb, tex_b)
    # The buckets in the order their first face fills them.
    names_of = {c: n for n, c in bnames.items()}
    bt_code = bcode[tfb] if len(tfb) else np.zeros(0, dtype=np.int64)
    if len(cb):
        col_b = _corner_stream(tpb, np.repeat(b_rgb[tfb][:, None, :], 3,
                                              axis=1))
    if len(tb):
        uvs_b = uv_stream(b_map, b_maps)
    for code in _ordered(bcode):
        name = names_of[code]
        if name[0] == "bvcol":
            back_vcol_parts.append(_rows(col_b, bt_code, code))
        elif name[0] == "btcol":
            back_tcol.setdefault(name[1], []).append(
                _rows(col_b, bt_code, code))
        elif name[0] == "btex":
            back_tex.setdefault(name[1], []).append(
                _rows(uvs_b, bt_code, code))
        else:
            back_ttex.setdefault(name[1], []).append(
                _rows(uvs_b, bt_code, code))

    # ---- fronts ---------------------------------------------------------
    textured = per_key("textured") & is_drawn
    plain = ~per_key("textured") & is_drawn
    op = per_key("op", np.float64)
    fcull = per_key("fcull", np.int64)
    by_texture: dict = {}
    by_ttexture: dict = {}
    tcode = np.full(nf, -1, dtype=np.int64)
    tnames: dict = {}
    tf_ix = np.flatnonzero(textured)
    if len(tf_ix):
        pairs = np.stack([fk[tf_ix], shade_ix[tf_ix]], axis=1)
        u, inv = np.unique(pairs, axis=0, return_inverse=True)
        codes = []
        for k, si in u.tolist():
            e = ent[k]
            tkey = (e["fattrs"]["texture"]["path"], shade_b[si])
            name = (tkey,) if e["op"] >= 0.999 else \
                ((round(e["op"], 3), int(e["fcull"])), tkey)
            codes.append(tnames.setdefault(name, len(tnames)))
        tcode[tf_ix] = np.asarray(codes, dtype=np.int64)[inv.reshape(-1)]
        tex_f = [e["fattrs"].get("texture") for e in ent]
        f_map, f_maps = uv_maps(tf_ix, tex_f)
        uvs_f = uv_stream(f_map, f_maps)
        tt_code = tcode[tfb]
    tnames_of = {c: n for n, c in tnames.items()}
    for code in _ordered(tcode):
        name = tnames_of[code]
        rows = _rows(uvs_f, tt_code, code)
        if len(name) == 1:
            by_texture[name[0]] = rows
        else:
            by_ttexture.setdefault(name[0], {})[name[1]] = rows

    # Colour faces: their shade by the plain normal.
    f_rgb = np.zeros((nf, 3), dtype=np.float64)
    pf = np.flatnonzero(plain)
    if len(pf):
        bases = np.array([e["base"] for e in ent], dtype=np.float64)
        f_rgb[pf] = shaded_colors(bases[fk[pf]], shade_a[pf])
    ccode = np.full(nf, -1, dtype=np.int64)     # 0 vcol, 1 fvcol, 2+ tcol
    cnames = {}
    translucent = plain & (op < 0.999)
    ccode[plain & ~translucent & (fcull == 1)] = 1
    ccode[plain & ~translucent & (fcull == 0)] = 0
    for f in np.flatnonzero(translucent).tolist():
        key = (round(float(op[f]), 3), int(fcull[f]))
        ccode[f] = cnames.setdefault(key, 2 + len(cnames))
    cnames_of = {c: n for n, c in cnames.items()}
    ct_code = ccode[tfa] if len(tfa) else np.zeros(0, dtype=np.int64)
    col_a = _corner_stream(tpa, np.repeat(f_rgb[tfa][:, None, :], 3, axis=1))
    vcol = _rows(col_a, ct_code, 0)
    fcull_vcol = _rows(col_a, ct_code, 1)
    tcol = {}
    for code in _ordered(np.where(ccode >= 2, ccode, -1)):
        tcol[cnames_of[code]] = _rows(col_a, ct_code, code)

    # Pick triangles, areas, the default-back tint.
    areas = (0.5 * ln.astype(np.float64))[drawn]
    tkeep = is_drawn[tfa] if len(tfa) else np.zeros(0, dtype=bool)
    tf = tfa[tkeep]
    dback = is_drawn & has_tris & per_key("dback")
    if len(tf):
        t = tpa[tkeep].astype(np.float64)
        v0, e1, e2 = t[:, 0], t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
        tri_ent_a = draw_index[tf]
        dback_raw = (t[dback[tf]].astype(np.float32).tobytes()
                     if dback.any() else b"")
    else:
        v0 = e1 = e2 = tri_ent_a = None
        dback_raw = b""
    by_texture_b = by_texture
    by_ttexture_b = by_ttexture

    # Edges: hard ones drawn, soft ones kept for the silhouettes with the
    # normal and centroid of their (one or two) faces.
    vis = ~plan.hidden
    ef_n = np.diff(plan.ef_start)
    hard = np.flatnonzero(vis & ~plan.soft)
    edges_data = pos32[plan.edges[hard]].reshape(-1).tobytes() \
        if len(hard) else b""
    softs = np.flatnonzero(vis & plan.soft & ((ef_n == 1) | (ef_n == 2)))
    fn = normal.astype(np.float64)
    fc = cen.astype(np.float64)
    short = np.isnan(fc[:, 0]) if nf else np.zeros(0, dtype=bool)
    if short.any():                       # under 3 corners: Face.centroid
        rs = np.concatenate([[0], np.cumsum(plan.ring_sizes)])
        fr = np.concatenate([[0], np.cumsum(plan.ring_counts)])
        for f in np.flatnonzero(short).tolist():
            idx = plan.corners[int(rs[fr[f]]):int(rs[fr[f] + 1])].tolist()
            if idx:
                p = pos32[idx].astype(np.float64)
                cnt = len(idx)
                c = [sum(p[:, k].tolist()) / cnt for k in range(3)]
            else:
                c = [0.0, 0.0, 0.0]
            fc[f] = np.float32(c)
    if len(softs):
        f0 = plan.ef_face[plan.ef_start[softs]]
        two = ef_n[softs] == 2
        f1 = np.where(two, plan.ef_face[np.minimum(plan.ef_start[softs] + 1,
                                                   len(plan.ef_face) - 1)],
                      f0)
        soft_pts = pos32[plan.edges[softs]].reshape(-1, 6)
        soft_n0, soft_c0 = fn[f0], fc[f0]
        soft_n1, soft_c1 = fn[f1], fc[f1]
        soft_single = ~two
    else:
        soft_pts = None
        soft_n0 = soft_c0 = soft_n1 = soft_c1 = np.zeros((0,))
        soft_single = np.zeros(0, dtype=bool)

    blo = bhi = None
    if v0 is not None:
        allv = np.concatenate((v0, v0 + e1, v0 + e2))
        blo, bhi = allv.min(axis=0), allv.max(axis=0)
    if len(edges_data):
        ea = np.frombuffer(edges_data, dtype=np.float32).reshape(-1, 3)
        elo, ehi = ea.min(axis=0), ea.max(axis=0)
        blo = elo if blo is None else np.minimum(blo, elo)
        bhi = ehi if bhi is None else np.maximum(bhi, ehi)
    bbox = (((float(blo[0]), float(blo[1]), float(blo[2])),
             (float(bhi[0]), float(bhi[1]), float(bhi[2])))
            if blo is not None else None)
    fp = LazyFingerprint((mesh, plan, table, face_attr))
    nv = len(plan.pos)
    idxs = sorted({k * max(nv - 1, 0) // 31 for k in range(32)}) if nv else []
    samples = [(i, tuple(plan.pos[i].tolist())) for i in idxs]
    return {"fp": fp, "vkey": vkey, "rev": 0, "uid": uid,
            "msig": msig, "serial": None,
            "nv": nv, "ne": len(plan.edges), "nf": nf,
            "samples": samples, "coordsum": _coordsum(plan), "bbox": bbox,
            "obb": None,
            "edges": edges_data,
            "vcol": vcol,
            "by_texture": by_texture_b,
            "tcol": tcol,
            "ttex": {(pth, a, fc_): v
                     for (a, fc_), d in by_ttexture_b.items()
                     for pth, v in d.items()},
            "back_vcol": b"".join(back_vcol_parts),
            "back_tex": {k: b"".join(v) for k, v in back_tex.items()},
            "back_tcol": {k: b"".join(v) for k, v in back_tcol.items()},
            "back_ttex": {k: b"".join(v) for k, v in back_ttex.items()},
            "fvcol": fcull_vcol,
            "dback": dback_raw,
            "faces": faces,
            "areas": areas,
            "v0": v0, "e1": e1, "e2": e2, "tri_ent": tri_ent_a,
            "soft_pts": soft_pts,
            "soft_n0": soft_n0, "soft_c0": soft_c0,
            "soft_n1": soft_n1, "soft_c1": soft_c1,
            "soft_single": soft_single,
            "mesh": mesh}


def _coordsum(plan) -> float:
    p = plan.pos
    if not len(p):
        return 0.0
    return float(np.cumsum(p[:, 0] + p[:, 1] * 1.000003
                           + p[:, 2] * 1.000007)[-1])


class LazyPairs:
    """``[(face, owner) for face in faces]`` of a :class:`DeferredFaces`,
    made one by one when asked for."""

    __slots__ = ("faces", "owner")

    def __init__(self, faces, owner):
        self.faces = faces
        self.owner = owner

    def __len__(self):
        return len(self.faces)

    def __getitem__(self, i):
        return (self.faces[i], self.owner)

    def __iter__(self):
        owner = self.owner
        return ((f, owner) for f in self.faces)


class PickEntities:
    """The pick index's ``entities`` — one list of ``(face, owner)`` — kept
    as the pieces it is made of, so a lazy mesh's faces are only built
    when a pick lands on one. Only used once a lazy piece is in."""

    __slots__ = ("_parts", "_starts", "_len")

    def __init__(self, first=()):
        self._parts: list = []
        self._starts: list = []
        self._len = 0
        self.extend(first)

    def extend(self, seq):
        if isinstance(seq, PickEntities):
            for part in seq._parts:
                self.extend(part)
            return
        n = len(seq)
        if n:
            self._parts.append(seq)
            self._starts.append(self._len)
            self._len += n

    def __len__(self):
        return self._len

    def __bool__(self):
        return self._len > 0

    def __getitem__(self, i):
        import bisect
        i = int(i)
        if i < 0:
            i += self._len
        if not 0 <= i < self._len:
            raise IndexError(i)
        k = bisect.bisect_right(self._starts, i) - 1
        return self._parts[k][i - self._starts[k]]

    def __iter__(self):
        for part in self._parts:
            yield from part
