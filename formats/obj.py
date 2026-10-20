# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""OBJ export — indexed vertices + triangles, with per-face colour as materials.

Wavefront OBJ with a sidecar ``.mtl``: vertices are de-duplicated by position,
every face is triangulated, and triangles are grouped by their material
(``Face.attrs["color"]``, default cream, under its registry name when it has
one — ``formats.meshexport.material_key``) so each becomes one ``usemtl``
material. Opens in Blender, MeshLab, etc. with the painted colours intact.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath

from PySide6.QtGui import QVector3D

from .meshexport import (SmoothNormals, _corner, export_triangles,
                         material_key, world_faces_painted)

# Cream painted on faces with no material colour (mirrors the viewport default).
_DEFAULT_COLOR = (0.96, 0.95, 0.925)


def save_obj(scene, path) -> None:
    """Write the scene as ``path`` (.obj) + a sibling ``.mtl``. Solid colours
    become ``Kd`` materials; textured faces become ``map_Kd`` materials with the
    image copied next to the .obj and per-vertex ``vt`` from the same planar
    projection the viewport uses — so the model opens with matching textures in
    other modellers (Blender, ...). Every corner carries a ``vn``: smooth
    across soft edges, so curved surfaces open round, and the face's own
    flat normal everywhere else."""
    import shutil
    from core.texture import planar_uv

    path = Path(path)
    verts: list[tuple[float, float, float]] = []
    vindex: dict[tuple, int] = {}
    uvs: list[tuple[float, float]] = []
    uvindex: dict[tuple, int] = {}

    def vidx(p) -> int:
        key = (round(p.x(), 6), round(p.y(), 6), round(p.z(), 6))
        i = vindex.get(key)
        if i is None:
            verts.append((p.x(), p.y(), p.z()))
            i = vindex[key] = len(verts)  # OBJ indices are 1-based
        return i

    def uvidx(uv) -> int:
        key = (round(uv[0], 6), round(uv[1], 6))
        i = uvindex.get(key)
        if i is None:
            uvs.append((uv[0], uv[1]))
            i = uvindex[key] = len(uvs)
        return i

    nrms: list[tuple[float, float, float]] = []
    nindex: dict[tuple, int] = {}

    def nidx(n) -> int:
        key = (round(n.x(), 5), round(n.y(), 5), round(n.z(), 5))
        i = nindex.get(key)
        if i is None:
            nrms.append((n.x(), n.y(), n.z()))
            i = nindex[key] = len(nrms)
        return i

    def corner_n(smooth, flat, p) -> int:
        """``vn`` index of a corner: smooth across soft edges, else flat."""
        return nidx(smooth.get(_corner(p), flat) if smooth else flat)

    # material key -> {"color": rgb, "map": basename|None} and its triangles
    # (each triangle a list of (vi, ti|None, ni)).
    materials: dict[tuple, dict] = {}
    groups: dict[tuple, list] = {}
    # Every face as it SHOWS: the paint of a group or component reaches the
    # faces inside that wear the default material, as in the viewport.
    smoother = SmoothNormals()
    for face, attrs in world_faces_painted(scene):
        tex = attrs.get("texture")
        key = material_key(attrs, with_opacity=False)
        flat = smoother.flat(face)
        smooth = smoother.corners(face)
        if tex is not None and tex.get("path"):
            src = Path(tex["path"])
            materials.setdefault(key, {"color": (1.0, 1.0, 1.0),
                                       "map": src.name, "src": src})
            if attrs.get("mat") and "mat" not in materials[key]:
                materials[key]["mat"] = attrs["mat"]
            n = flat
            sw = tex.get("sw", 1.0) or 1.0
            sh = tex.get("sh", 1.0) or 1.0
            rot = float(tex.get("rot", 0.0))
            uvw = tex.get("uvw")
            for tri in export_triangles(face):
                if uvw:
                    from core.texture import affine_uv
                    uv = affine_uv(uvw, list(tri))   # imported explicit UVs
                else:
                    uv = planar_uv(n, list(tri), sw, sh, rot)
                groups.setdefault(key, []).append(
                    [(vidx(tri[k]), uvidx(uv[k]), corner_n(smooth, flat, tri[k]))
                     for k in range(3)])
        else:
            # RGB only: an AI recipe's (r, g, b, 1.0) broke the .mtl writer.
            col = tuple(attrs.get("color") or _DEFAULT_COLOR)[:3]
            materials.setdefault(key, {"color": col, "map": None})
            if attrs.get("mat") and "mat" not in materials[key]:
                materials[key]["mat"] = attrs["mat"]
            for tri in export_triangles(face):
                groups.setdefault(key, []).append(
                    [(vidx(tri[k]), None, corner_n(smooth, flat, tri[k]))
                     for k in range(3)])

    keys = list(groups.keys())
    # Registry identities (attrs["mat"]) export under their real name —
    # "Concreto_visto", not "mat0"; anonymous paints keep matN.
    from .meshexport import export_names
    matname = export_names({k: materials[k] for k in keys})

    # Copy texture images next to the .obj so map_Kd resolves.
    from core.texture import is_image_file
    for k in keys:
        mat = materials[k]
        if mat.get("map"):
            dst = path.parent / mat["map"]
            try:
                if (mat["src"].resolve() != dst.resolve()
                        and is_image_file(mat["src"])):
                    shutil.copy(mat["src"], dst)
            except Exception:  # noqa: BLE001 — best-effort; export still valid
                pass

    # UTF-8 on every platform: material names and texture files carry
    # accents («Mármol»), and the locale default would write cp1252 on
    # Windows — a file other machines read as mojibake.
    mtl_path = path.with_suffix(".mtl")
    with open(mtl_path, "w", encoding="utf-8") as m:
        for k in keys:
            mat = materials[k]
            r, g, b = mat["color"]
            m.write(f"newmtl {matname[k]}\n")
            m.write(f"Kd {r:.4f} {g:.4f} {b:.4f}\n")
            if mat.get("map"):
                m.write(f"map_Kd {mat['map']}\n")
            m.write("\n")

    with open(path, "w", encoding="utf-8") as o:
        o.write("# IngeTrazo OBJ export\n")
        o.write(f"mtllib {mtl_path.name}\n")
        for x, y, z in verts:
            o.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        for u, v in uvs:
            o.write(f"vt {u:.6f} {v:.6f}\n")
        for x, y, z in nrms:
            o.write(f"vn {x:.6f} {y:.6f} {z:.6f}\n")
        for k in keys:
            o.write(f"usemtl {matname[k]}\n")
            for tri in groups[k]:
                toks = [(f"{vi}/{ti}/{ni}" if ti is not None else f"{vi}//{ni}")
                        for vi, ti, ni in tri]
                o.write("f " + " ".join(toks) + "\n")


# ---- Import --------------------------------------------------------------------

def read_obj_text(path) -> str:
    """The text of an ``.obj`` or ``.mtl`` file, whatever machine wrote it.

    OBJ declares no encoding. Our own export and most modern tools write
    UTF-8, so that comes first, the same on every platform — Python's
    default is the locale's, cp1252 on Windows, which read «Escultura
    pública» back as «pÃºblica». A file that is not valid UTF-8 came from
    an older Windows exporter and is read as cp1252, with ``errors=
    "replace"``: a stray byte costs a character, never the model.
    """
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _is_number(tok: str) -> bool:
    try:
        float(tok)
    except ValueError:
        return False
    return True


def _resolve_map(mtl: Path, line: str):
    """The image file a ``map_Kd`` line points at, or ``None``.

    Third-party OBJs point wherever the model was made. Taking the line's
    last token broke on the spaces every Windows path has — a bed from this
    library carries ``map_Kd C:/Documents and Settings/Jeremy.KIDSXP/Desktop/
    WoodFine0031_10_S.jpg`` and the tail alone, "Settings/…/WoodFine…jpg",
    then blew up ``Path.with_name`` (Invalid name) and took the WHOLE import
    down with it. One dead reference must cost its own texture, nothing more.

    So: the value is everything after the tag, minus the ``-s``/``-o`` option
    groups the format allows; it is looked for beside the ``.mtl`` as written
    and then by bare filename, which is what rescues a foreign absolute path
    whose image did travel with the model; and anything still missing returns
    ``None``, leaving the material to fall back to its ``Kd`` colour.
    """
    rest = line.split(None, 1)
    if len(rest) < 2:
        return None
    toks = rest[1].split()
    while toks and toks[0].startswith("-"):        # -s 1 1 1, -o 0 0 0, -bm 1
        toks = toks[1:]
        while toks and _is_number(toks[0]):
            toks = toks[1:]
    value = " ".join(toks).strip().strip('"')
    if not value:
        return None
    here = mtl.parent
    ref = PurePosixPath(value.replace("\\", "/"))
    for cand in (here / value, here / ref.name):
        try:
            if cand.is_file():
                return cand
        except OSError:                            # a path the OS refuses
            continue
    return None


def _parse_mtl(path: Path) -> dict:
    """Map material name → ``{"color": (r,g,b), "map": Path|None}`` from a
    ``.mtl`` file's ``Kd`` / ``map_Kd`` lines. The image is resolved here,
    once — see :func:`_resolve_map` for what a dead reference costs."""
    mats: dict[str, dict] = {}
    if not path.exists():
        return mats
    current = None
    # These files carry whatever encoding the author's machine had, and a
    # stray byte must not cost the model either (see read_obj_text).
    for line in read_obj_text(path).splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "newmtl":
            current = parts[1]
            mats[current] = {"color": None, "map": None}
        elif current is None:
            continue
        elif parts[0] == "Kd" and len(parts) >= 4:
            mats[current]["color"] = (float(parts[1]), float(parts[2]),
                                      float(parts[3]))
        elif parts[0] == "map_Kd" and len(parts) >= 2:
            mats[current]["map"] = _resolve_map(path, line)
    return mats


#: What a unit is worth in metres. OBJ carries no unit of its own — the
#: format simply does not say — so the importer has to be told, and every
#: library picks its own: Sweet Home 3D's models are centimetres, CAD
#: exports are often millimetres, ours are metres.
OBJ_UNITS = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "ft": 0.3048}

#: The quarter turn about X that stands a Y-up file up in this app's Z-up
#: world, row-major. OBJ never records which axis is the vertical, and the
#: two conventions in the wild disagree: this app (and what it writes) puts Z
#: up, Sweet Home 3D and Blender's exporter put Y up. Handedness is kept, so
#: nothing arrives mirrored.
Y_UP_TO_Z_UP = (1.0, 0.0, 0.0,
                0.0, 0.0, -1.0,
                0.0, 1.0, 0.0)


def suggest_unit(path) -> str:
    """The unit an OBJ was most likely written in, from its own size.

    Only useful where the number cannot be metres: a model 200 units across
    is not a 200 m object, so it is centimetres (or millimetres above 20000).
    Below that it is genuinely ambiguous — a chair 115 units tall reads the
    same as a 115 m tower — and the caller is better off asking. Metres is
    the answer there: it is what this app writes, so a round trip through
    our own exporter never asks the user to correct it.

    One pass over the ``v`` lines; it does not parse the model.
    """
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    try:
        with open(path, "rb") as fh:
            for line in fh:
                if not line.startswith(b"v "):
                    continue
                p = line.split()
                if len(p) < 4:
                    continue
                for k in range(3):
                    v = float(p[k + 1])
                    lo[k] = min(lo[k], v)
                    hi[k] = max(hi[k], v)
    except (OSError, ValueError):
        return "m"
    span = max((hi[k] - lo[k]) for k in range(3)) if hi[0] > lo[0] else 0.0
    if span > 20000.0:
        return "mm"
    if span > 200.0:
        return "cm"
    return "m"


def load_obj(scene, path, progress=None, scale: float = 1.0,
             matrix=None) -> None:
    """See :func:`_load_obj_inner`. Wrapped to run with the generational GC off —
    mass vertex/edge/face construction ahead (see formats.skp.apply_payload);
    collection is merely deferred to the re-enable."""
    import gc
    _gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        _load_obj_inner(scene, path, progress=progress, scale=scale,
                        matrix=matrix)
    finally:
        if _gc_was_enabled:
            gc.enable()


def _load_obj_inner(scene, path, progress=None, scale: float = 1.0,
                    matrix=None) -> None:
    """Add the faces of a Wavefront OBJ at ``path`` to ``scene``'s mesh, then
    weld + merge coplanar so a triangulated file (e.g. our own export, or another
    modeller's OBJ) comes back as clean editable polygons. Material ``Kd`` colours
    become per-face ``attrs["color"]`` (skipped when they match the default
    cream, so plain faces stay unpainted). Adds to the current scene; the caller
    wraps it for undo.

    ``matrix`` is an optional row-major 3x3 applied to every vertex after
    ``scale``: it stands a Y-up file up (:data:`Y_UP_TO_Z_UP`) and can carry
    whatever else the source says about the model — a catalogue's own
    rotation, a fit to a declared size. The file itself never says which
    axis is the vertical, so this is the caller's to know, not a guess."""
    from core.history import run_stitch
    from core.orient import orient_outward
    from core.topology import _key

    def tick(frac, text):
        if progress is not None:
            progress(frac, text)

    tick(0.05, "Reading file…")
    path = Path(path)
    verts: list[QVector3D] = []
    uvs: list[tuple[float, float]] = []
    materials: dict = {}
    current_mat = None
    current_smooth = 0
    # Which piece of the model each face belongs to: the file's own ``o``
    # (object) and ``g`` (group) statements. A furniture OBJ is written as
    # its parts — a stool's seat, its legs, its footrest — and those names
    # are the only record of which facet belongs to which part.
    current_o = ""
    current_g = ""
    pending: list[tuple[list[QVector3D], object, object, int, tuple]] = []

    for line in read_obj_text(path).splitlines():
        parts = line.split()
        if not parts:
            continue
        tag = parts[0]
        if tag == "v":
            x = float(parts[1]) * scale
            y = float(parts[2]) * scale
            z = float(parts[3]) * scale
            if matrix is not None:
                m = matrix
                x, y, z = (m[0] * x + m[1] * y + m[2] * z,
                           m[3] * x + m[4] * y + m[5] * z,
                           m[6] * x + m[7] * y + m[8] * z)
            verts.append(QVector3D(x, y, z))
        elif tag == "vt":
            try:
                uvs.append((float(parts[1]),
                            float(parts[2]) if len(parts) > 2 else 0.0))
            except (IndexError, ValueError):
                uvs.append((0.0, 0.0))
        elif tag == "mtllib":
            materials = _parse_mtl(path.with_name(parts[1]))
        elif tag == "usemtl":
            current_mat = materials.get(parts[1])
        elif tag == "o":
            current_o = " ".join(parts[1:])
            current_g = ""
        elif tag == "g":
            current_g = " ".join(parts[1:])
        elif tag == "s":
            # "s 1", "s off": which faces the file means as one surface.
            v = parts[1].lower() if len(parts) > 1 else "off"
            current_smooth = int(v) if v.isdigit() else 0
        elif tag == "f":
            idxs, tidxs = [], []
            try:
                for tok in parts[1:]:
                    bits = tok.split("/")
                    raw = int(bits[0])
                    idxs.append(raw - 1 if raw > 0 else len(verts) + raw)
                    t = bits[1] if len(bits) > 1 else ""
                    ti = int(t) if t else 0
                    tidxs.append((ti - 1 if ti > 0 else len(uvs) + ti)
                                 if t else -1)
            except ValueError:
                continue                       # a face this file cannot mean
            if len(idxs) >= 3 and all(0 <= i < len(verts) for i in idxs):
                # The file's own texture coordinates, when it gives one per
                # corner — without them a curved surface can only be guessed
                # at, and the guess shatters (see _face_attrs).
                loop_uv = ([uvs[t] for t in tidxs]
                           if all(0 <= t < len(uvs) for t in tidxs) else None)
                pending.append(([verts[i] for i in idxs], current_mat,
                                loop_uv, current_smooth,
                                (current_o, current_g)))

    def _face_attrs(mat, loop=None, loop_uv=None, smooth=0):
        """The attrs of one imported polygon.

        A textured face carries the file's own ``vt`` as a world→UV affine
        (the same map a COLLADA import fits). It matters most where the
        surface curves: a car wheel or a person's clothing is hundreds of
        small facets, and projecting an image flatly onto each one in turn
        breaks the image into confetti. Only when the file gives no texture
        coordinates does the planar projection remain, which is right for
        what it is meant for — a wall, a floor, a flat panel.
        """
        base = {SMOOTH_KEY: smooth} if smooth else {}
        if mat is None:
            return base or None
        if mat.get("map"):
            tex = {"path": str(mat["map"]), "sw": 1.0, "sh": 1.0}
            if loop and loop_uv:
                from core.texture import fit_uv_affine
                uvw = fit_uv_affine(loop, loop_uv)
                if uvw is not None:
                    import math as _math
                    glu = _math.hypot(uvw[0], uvw[1], uvw[2])
                    glv = _math.hypot(uvw[4], uvw[5], uvw[6])
                    tex["uvw"] = uvw
                    # Tile size for display and re-export, read back from the
                    # gradients the fit produced.
                    tex["sw"] = (1.0 / glu) if glu > 1e-9 else 1.0
                    tex["sh"] = (1.0 / glv) if glv > 1e-9 else 1.0
            # A mesh format paints a triangle, not a side: the material
            # shows from both sides (``back = True``).
            return {**base, "texture": tex, "back": True}
        color = mat.get("color")
        if color is not None and tuple(round(c, 4) for c in color) != \
                tuple(round(c, 4) for c in _DEFAULT_COLOR):
            return {**base, "color": list(color), "back": True}
        return base or None

    # Library-scale meshes are *reference* geometry: they land in their own
    # Group (isolated mesh, coplanar triangles fast-fused into clean facade
    # polygons + smooth edges softened — the classic import look) so drawing
    # beside them never scans their triangles — see formats/dae.py.
    from formats.dae import _MAX_FUSE_LOOPS, _add_fused
    from formats.fuse import (SMOOTH_KEY, drop_smoothing_groups,
                              soften_by_smoothing_group)
    pieces: dict = {}
    for item in pending:
        pieces.setdefault(item[4], []).append(item)
    if len(pieces) > 1:
        # A model the file describes as parts arrives as parts: one
        # container (the object you place, move and copy) whose children
        # are the file's pieces, each named as the file names it. Fusing
        # piece by piece also keeps two parts that merely touch — a seat
        # resting on its legs — from being welded into one.
        scene.groups.append(_pieces_group(
            path.stem, pieces, _face_attrs, tick))
        scene.version += 1
        tick(1.0, "Done")
        return

    if len(pending) > _MAX_FUSE_LOOPS:
        from core.group import Group
        from core.mesh import Mesh
        from formats.fuse import fuse_coplanar_loops, soften_smooth_edges
        target = Mesh()
        raw = [(loop, _face_attrs(mat, loop, loop_uv, sm))
               for loop, mat, loop_uv, sm, _piece in pending]
        tick(0.5, "Merging coplanar faces…")
        fused = fuse_coplanar_loops(raw)
        n = max(len(fused), 1)
        for k, item in enumerate(fused):
            if progress is not None and k % 8192 == 0:
                tick(0.6 + 0.3 * k / n, "Building the model…")
            _add_fused(target, [item])
        tick(0.92, "Smoothing edges…")
        soften_by_smoothing_group(target)
        soften_smooth_edges(target)
        drop_smoothing_groups(target)
        scene.groups.append(Group(target))
        scene.version += 1
        tick(1.0, "Done")
        return

    target = scene.mesh
    seed: set = set()
    new_faces = set()
    for loop, mat, loop_uv, sm, _piece in pending:
        try:
            face = target.add_face(loop)
        except Exception:  # noqa: BLE001 — skip a degenerate polygon
            continue
        new_faces.add(face)
        attrs = _face_attrs(mat, loop, loop_uv, sm)
        if attrs:
            face.attrs.update(attrs)
        for v in loop:
            seed.add(_key(v))

    # Weld coincident vertices and fuse the coplanar triangles back into the
    # polygons they were exported from (a triangulated cube → 6 quads). The
    # coplanar merge is winding-tolerant, so give a closed result a
    # consistent outward orientation — what the engine and STL re-export
    # expect. (Big models took the reference-group path above.)
    run_stitch(scene.mesh, seed, new_faces, coplanar_merge=True)
    orient_outward(scene.mesh)
    soften_by_smoothing_group(scene.mesh)
    drop_smoothing_groups(scene.mesh)
    scene.version += 1


def _piece_name(key: tuple, number: int) -> str:
    """What a piece is called: the file's group name, else its object name.
    Exporters often number their groups (``g 1``, ``g 2``…), and a bare
    number reads as nothing in a list of parts, so it becomes «Part 1»."""
    from core.i18n import tr
    obj_name, group_name = key
    name = _tidy_blender_name((group_name or obj_name).strip())
    if not name:
        return tr("Part {n}", n=number)
    if not any(ch.isalpha() for ch in name):
        return tr("Part {n}", n=name)
    return name


def _tidy_blender_name(name: str) -> str:
    """Blender writes an object as ``<object>_<mesh>`` and numbers copies
    ``.001``: «Base-unit-Box-Right_Cube.002», «Door.001_Cube.007». The
    object's own name is the one a person gave; the mesh part (a capitalised
    word, a default like Cube or Sphere) and the copy numbers are Blender's
    bookkeeping. «Sphere.021_Sphere.005» keeps «Sphere»: that is all it is."""
    import re
    head, sep, tail = name.rpartition("_")
    if sep and head and re.fullmatch(r"[A-Z][A-Za-z]*(\.\d+)?", tail):
        name = head
    return re.sub(r"(\.\d{3})+$", "", name).strip() or name


def _pieces_group(stem: str, pieces: dict, face_attrs, tick):
    """The container an OBJ made of parts imports as: an instance at
    identity with an empty mesh of its own (the same shape 3D text takes,
    see :func:`core.text3d.make_text_group`), one child per piece."""
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group
    from core.mesh import Mesh
    from formats.dae import _add_fused
    from formats.fuse import (drop_smoothing_groups, fuse_coplanar_loops,
                              soften_by_smoothing_group, soften_smooth_edges)

    kids = []
    n = max(len(pieces), 1)
    for k, (key, items) in enumerate(pieces.items(), start=1):
        tick(0.5 + 0.45 * k / n, "Building the model…")
        mesh = Mesh()
        raw = [(loop, face_attrs(mat, loop, loop_uv, sm))
               for loop, mat, loop_uv, sm, _piece in items]
        _add_fused(mesh, fuse_coplanar_loops(raw))
        if not mesh.faces:
            continue
        soften_by_smoothing_group(mesh)
        soften_smooth_edges(mesh)
        drop_smoothing_groups(mesh)
        kid = Group(mesh, name=_piece_name(key, k))
        kid.xform = QMatrix4x4()
        # A part is its own geometry, shared with nothing: a group inside
        # the component, not a component of its own (issue #90).
        kid.component = False
        kids.append(kid)
    container = Group(name=stem)
    container.adopt(kids)
    return container
