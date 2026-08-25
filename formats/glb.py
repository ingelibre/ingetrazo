# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""glTF 2.0 / GLB import — Sketchfab's universal download format.

Reads a binary ``.glb`` (or JSON ``.gltf`` with an external ``.bin``) and
adds its geometry to the scene as a *reference* Group, the same structure
the big-DAE path builds: triangles bulk-welded in world Z-up metres,
textures extracted to the app texture cache and mapped through per-triangle
world→UV affine maps (exact for triangles), facet seams softened so
smooth-shaded models read smooth. Stdlib + NumPy only.

Supported: TRIANGLES primitives, u8/u16/u32 indices, float/normalized-int
attributes with byteStride, node hierarchies (matrix or TRS), embedded and
external images, pbrMetallicRoughness + the KHR_materials_pbrSpecularGlossiness
legacy (old Sketchfab uploads), KHR_texture_transform offset/scale,
alphaMode BLEND → face opacity (MASK rides on the texture's own alpha).
Not supported: Draco-compressed meshes (clear error), skinning/animation
(imported at bind pose), sparse accessors.
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct
from pathlib import Path

from PySide6.QtGui import QVector3D

_COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
         5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def parse_container(path: Path):
    """(gltf json, list of buffer bytes). Handles .glb and .gltf."""
    data = Path(path).read_bytes()
    if data[:4] == b"glTF":
        _magic, _ver, _length = struct.unpack("<III", data[:12])
        off = 12
        js = None
        bin_chunk = b""
        while off + 8 <= len(data):
            clen, ctype = struct.unpack("<II", data[off:off + 8])
            chunk = data[off + 8:off + 8 + clen]
            if ctype == 0x4E4F534A:      # 'JSON'
                js = json.loads(chunk)
            elif ctype == 0x004E4942:    # 'BIN'
                bin_chunk = chunk
            off += 8 + clen + (-clen) % 4 if clen % 4 else 8 + clen
        if js is None:
            raise ValueError("GLB without a JSON chunk")
        default = bin_chunk
    else:
        js = json.loads(data)
        default = b""
    buffers = []
    for buf in js.get("buffers", []):
        uri = buf.get("uri")
        if uri is None:
            buffers.append(default)
        elif uri.startswith("data:"):
            buffers.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            buffers.append((Path(path).parent / uri).read_bytes())
    return js, buffers


def _accessor(js, buffers, idx):
    """Accessor ``idx`` as a float64 (or int64 for indices) NumPy array of
    shape (count, ncomp). Normalized integers are scaled to 0..1/-1..1."""
    import numpy as np
    acc = js["accessors"][idx]
    if "sparse" in acc:
        raise ValueError("sparse accessors are not supported")
    fmt, size = _COMP[acc["componentType"]]
    n = _NCOMP[acc["type"]]
    count = acc["count"]
    bv = js["bufferViews"][acc["bufferView"]]
    buf = buffers[bv.get("buffer", 0)]
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride") or size * n
    dt = np.dtype("<" + fmt)
    if stride == size * n:
        arr = np.frombuffer(buf, dtype=dt, count=count * n,
                            offset=start).reshape(count, n)
    else:
        raw = np.frombuffer(buf, dtype=np.uint8,
                            count=stride * count - (stride - size * n),
                            offset=start)
        rows = np.lib.stride_tricks.as_strided(
            raw, shape=(count, size * n), strides=(stride, 1))
        arr = rows.copy().view(dt).reshape(count, n)
    if acc["componentType"] == 5125 or fmt in ("H", "B") and n == 1:
        return arr.astype(np.int64)
    out = arr.astype(np.float64)
    if acc.get("normalized"):
        peak = {"b": 127.0, "B": 255.0, "h": 32767.0, "H": 65535.0}.get(fmt)
        if peak:
            out = out / peak
    return out


def _node_transforms(js):
    """[(node index, 4x4 world matrix)] for every node, glTF column-major
    composed down the scene hierarchy."""
    import numpy as np

    def local(nd):
        if "matrix" in nd:
            return np.array(nd["matrix"], dtype=np.float64).reshape(4, 4).T
        m = np.eye(4)
        if "scale" in nd:
            m = m @ np.diag(list(nd["scale"]) + [1.0])
        if "rotation" in nd:
            x, y, z, w = nd["rotation"]
            r = np.array([
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            rm = np.eye(4)
            rm[:3, :3] = r
            m = rm @ m
        if "translation" in nd:
            tm = np.eye(4)
            tm[:3, 3] = nd["translation"]
            m = tm @ m
        return m

    nodes = js.get("nodes", [])
    roots = []
    for sc in js.get("scenes", []) or [{}]:
        roots.extend(sc.get("nodes", []))
    if not roots:
        roots = list(range(len(nodes)))
    out = []

    def walk(i, parent):
        nd = nodes[i]
        world = parent @ local(nd)
        out.append((i, world))
        for c in nd.get("children", []):
            walk(c, world)

    import numpy as np
    for r in roots:
        walk(r, np.eye(4))
    return out


def _extract_images(js, buffers, path: Path):
    """Write embedded/external images to the texture cache; image index →
    file path (or None). Content-addressed by the source file."""
    from core.texture import texture_cache_root
    stem = Path(path).stem[:40]
    st = Path(path).stat()
    # Content-sensitive tag (path + size + mtime, like the .skp cache):
    # re-exporting the same file must re-extract its textures.
    tag = hashlib.sha1(
        f"{path}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:10]
    out_dir = texture_cache_root() / "glb" / f"{stem}-{tag}"
    paths = []
    for i, img in enumerate(js.get("images", [])):
        try:
            if "bufferView" in img:
                bv = js["bufferViews"][img["bufferView"]]
                buf = buffers[bv.get("buffer", 0)]
                start = bv.get("byteOffset", 0)
                blob = buf[start:start + bv["byteLength"]]
            elif img.get("uri", "").startswith("data:"):
                blob = base64.b64decode(img["uri"].split(",", 1)[1])
            elif img.get("uri"):
                blob = (Path(path).parent / img["uri"]).read_bytes()
            else:
                paths.append(None)
                continue
            ext = ".png" if blob[:4] == b"\x89PNG" else ".jpg"
            out_dir.mkdir(parents=True, exist_ok=True)
            fp = out_dir / f"img_{i}{ext}"
            if not fp.exists():
                fp.write_bytes(blob)
            paths.append(str(fp))
        except Exception:  # noqa: BLE001 — a broken image loses its texture only
            paths.append(None)
    return paths


def _material_recipe(js, mat_idx, image_paths):
    """(texture path | None, uv transform (ox, oy, sx, sy), rgba) for a
    material index, honouring the specular-glossiness legacy."""
    mats = js.get("materials", [])
    if mat_idx is None or mat_idx >= len(mats):
        return None, (0.0, 0.0, 1.0, 1.0), None, 0, None
    mat = mats[mat_idx]
    sg = (mat.get("extensions", {})
          .get("KHR_materials_pbrSpecularGlossiness"))
    if sg is not None:
        tex_info = sg.get("diffuseTexture")
        rgba = sg.get("diffuseFactor")
    else:
        pbr = mat.get("pbrMetallicRoughness", {})
        tex_info = pbr.get("baseColorTexture")
        rgba = pbr.get("baseColorFactor")
    tex_path = None
    uvt = (0.0, 0.0, 1.0, 1.0)
    uv_set = 0
    if tex_info is not None:
        tex = js.get("textures", [])[tex_info["index"]]
        src = tex.get("source")
        if src is not None and src < len(image_paths):
            tex_path = image_paths[src]
        uv_set = tex_info.get("texCoord", 0)
        tt = tex_info.get("extensions", {}).get("KHR_texture_transform")
        if tt:
            ox, oy = tt.get("offset", [0.0, 0.0])
            sx, sy = tt.get("scale", [1.0, 1.0])
            uvt = (ox, oy, sx, sy)
    opacity = None
    if mat.get("alphaMode") == "BLEND":
        a = rgba[3] if rgba and len(rgba) > 3 else 1.0
        if a < 0.999:
            opacity = float(a)
        elif tex_path is None:
            opacity = 0.999   # blend-flagged plain material: keep a hint
    return tex_path, uvt, rgba, uv_set, opacity


def read_triangles(path: Path):
    """Parse the file into world-space Z-up triangle soup:
    (positions (N,3,3) float64 metres, per-triangle recipe index,
    recipes: [(tex_path|None, rgba|None, opacity|None)], uvs (N,3,2) or
    None per recipe batch). Returned as a list of batches
    [(tris, uvs|None, recipe)] to keep memory reasonable."""
    import numpy as np
    js, buffers = parse_container(path)
    for ext in js.get("extensionsRequired", []):
        if "draco" in ext.lower():
            raise ValueError(
                "Draco-compressed GLB — re-export/download uncompressed")
    image_paths = _extract_images(js, buffers, Path(path))
    zup = np.array([[1.0, 0.0, 0.0],
                    [0.0, 0.0, -1.0],
                    [0.0, 1.0, 0.0]])
    batches = []
    meshes = js.get("meshes", [])
    for node_idx, world in _node_transforms(js):
        nd = js["nodes"][node_idx]
        mi = nd.get("mesh")
        if mi is None or mi >= len(meshes):
            continue
        for prim in meshes[mi].get("primitives", []):
            if prim.get("mode", 4) != 4:
                continue
            attr = prim.get("attributes", {})
            if "POSITION" not in attr:
                continue
            pos = _accessor(js, buffers, attr["POSITION"])[:, :3]
            if "indices" in prim:
                idx = _accessor(js, buffers, prim["indices"]).reshape(-1)
            else:
                idx = np.arange(len(pos), dtype=np.int64)
            idx = idx.astype(np.int64)[:(len(idx) // 3) * 3].reshape(-1, 3)
            tex_path, uvt, rgba, uv_set, opacity = _material_recipe(
                js, prim.get("material"), image_paths)
            world_pts = pos @ world[:3, :3].T + world[:3, 3]
            world_pts = world_pts @ zup.T
            tris = world_pts[idx]                      # (N, 3, 3)
            uvs = None
            uv_key = f"TEXCOORD_{uv_set}"
            if tex_path is not None and uv_key in attr:
                uv = _accessor(js, buffers, attr[uv_key])[:, :2]
                ox, oy, sx, sy = uvt
                uv = uv * (sx, sy) + (ox, oy)
                uvs = uv[idx]                          # (N, 3, 2)
            elif tex_path is not None:
                tex_path = None                        # texture without UVs
            batches.append((tris, uvs, (tex_path, rgba, opacity)))
    return batches, js


def _triangle_uvws(tris, uvs):
    """Vectorized world→UV affine per triangle: solves gu·e1=du1, gu·e2=du2,
    gu·n=0 (and gv likewise) for all triangles at once. Returns
    (uvw (N,8), valid mask)."""
    import numpy as np
    p0, p1, p2 = tris[:, 0], tris[:, 1], tris[:, 2]
    e1, e2 = p1 - p0, p2 - p0
    n = np.cross(e1, e2)
    A = np.stack([e1, e2, n], axis=1)                  # (N,3,3)
    det = np.linalg.det(A)
    ok = np.abs(det) > 1e-18
    gu = np.zeros((len(tris), 3))
    gv = np.zeros((len(tris), 3))
    if ok.any():
        bu = np.stack([uvs[ok, 1, 0] - uvs[ok, 0, 0],
                       uvs[ok, 2, 0] - uvs[ok, 0, 0],
                       np.zeros(ok.sum())], axis=1)
        bv = np.stack([uvs[ok, 1, 1] - uvs[ok, 0, 1],
                       uvs[ok, 2, 1] - uvs[ok, 0, 1],
                       np.zeros(ok.sum())], axis=1)
        gu[ok] = np.linalg.solve(A[ok], bu[..., None])[..., 0]
        gv[ok] = np.linalg.solve(A[ok], bv[..., None])[..., 0]
    cu = uvs[:, 0, 0] - np.einsum("ij,ij->i", gu, p0)
    cv = uvs[:, 0, 1] - np.einsum("ij,ij->i", gv, p0)
    uvw = np.concatenate([gu, cu[:, None], gv, cv[:, None]], axis=1)
    return uvw, ok


#: Above this many edges the O(E) Python soften pass is skipped — imports
#: this big are decimated component sources or one-off references anyway.
_SOFTEN_EDGE_CAP = 500_000


def build_mesh(batches, progress=None):
    """One Mesh from read_triangles() batches: bulk-welded, textured via
    per-triangle affine maps, facet seams softened."""
    import numpy as np
    from core.mesh import Mesh
    from formats.fuse import soften_smooth_edges

    mesh = Mesh()
    flat_parts = []
    attrs_list = []
    total = sum(len(t) for t, _u, _r in batches) or 1
    done = 0
    for tris, uvs, (tex_path, rgba, opacity) in batches:
        flat_parts.append(tris.reshape(-1, 3))
        base = None
        if tex_path is None:
            color = ([float(c) for c in rgba[:3]] if rgba else None)
            base = {}
            if color is not None and color != [1.0, 1.0, 1.0]:
                base["color"] = color
            if opacity is not None:
                base["opacity"] = opacity
            attrs_list.extend([dict(base) if base else None] * len(tris))
        else:
            uvw, okm = _triangle_uvws(tris, uvs)
            glu = np.linalg.norm(uvw[:, 0:3], axis=1)
            glv = np.linalg.norm(uvw[:, 4:7], axis=1)
            sw = np.where(glu > 1e-9, 1.0 / np.maximum(glu, 1e-9), 1.0)
            sh = np.where(glv > 1e-9, 1.0 / np.maximum(glv, 1e-9), 1.0)
            for i in range(len(tris)):
                a = {"texture": {"path": tex_path,
                                 "uvw": [float(x) for x in uvw[i]],
                                 "sw": float(sw[i]), "sh": float(sh[i])}} \
                    if okm[i] else None
                if a is not None and opacity is not None:
                    a["opacity"] = opacity
                attrs_list.append(a)
        done += len(tris)
        if progress is not None:
            progress(0.3 + 0.4 * done / total, "Preparing geometry…")
    if not flat_parts:
        raise ValueError("No triangle geometry found in the glTF file")
    flat = np.concatenate(flat_parts, axis=0)
    # Quantize like the interactive weld tolerance so shared corners merge.
    vobjs, inverse = mesh.bulk_weld(np.asarray(flat, dtype=np.float64))
    n_faces = len(flat) // 3
    if progress is not None:
        progress(0.75, "Building the model…")
    mesh.add_faces_welded(vobjs, inverse,
                          np.full(n_faces, 3, dtype=np.int64),
                          np.ones(n_faces, dtype=np.int64),
                          attrs_list)
    if len(mesh.edges) <= _SOFTEN_EDGE_CAP:
        if progress is not None:
            progress(0.9, "Smoothing seams…")
        soften_smooth_edges(mesh)
    _hide_cutout_card_edges(mesh)
    return mesh


def _hide_cutout_card_edges(mesh) -> None:
    """Foliage cards: the visible outline of a leaf card is its texture,
    not its quad — thousands of drawn quad borders read as a near-black
    canopy (hunted on the molle tree). A texture is foliage-like when it
    carries alpha (cutout) or when its faces are confetti (mean area under
    0.02 m²); edges whose faces are all foliage-like go soft (hidden)."""
    from PySide6.QtGui import QImage
    stats: dict = {}
    for f in mesh.faces:
        t = f.attrs.get("texture") if f.attrs else None
        if t and t.get("path"):
            n, area = stats.get(t["path"], (0, 0.0))
            stats[t["path"]] = (n + 1, area + f.area())
    foliage: dict = {}
    for path, (n, area) in stats.items():
        img = QImage(path)
        foliage[path] = ((not img.isNull() and img.hasAlphaChannel())
                         or (n > 200 and area / n < 0.02))

    def is_foliage(face) -> bool:
        t = face.attrs.get("texture") if face.attrs else None
        return bool(t and foliage.get(t.get("path")))

    if not any(foliage.values()):
        return
    for e in mesh.edges:
        if e.faces and all(is_foliage(f) for f in e.faces):
            e.hidden = True


def load_glb(scene, path, progress=None) -> None:
    """Add the glTF/GLB at ``path`` to ``scene`` as a reference Group named
    after the file (or the embedded Sketchfab title). GC off during the
    bulk build, like every mass import."""
    import gc
    was = gc.isenabled()
    gc.disable()
    try:
        _load_glb_inner(scene, path, progress=progress)
    finally:
        if was:
            gc.enable()


def _guess_scale(batches) -> float:
    """glTF says metres, Sketchfab authors say whatever: pick the first of
    metres / inches / centimetres / millimetres that lands the model's
    largest dimension in a plausible prop-to-building range."""
    import numpy as np
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    for tris, _uvs, _r in batches:
        pts = tris.reshape(-1, 3)
        lo = np.minimum(lo, pts.min(axis=0))
        hi = np.maximum(hi, pts.max(axis=0))
    dim = float((hi - lo).max())
    if dim <= 0:
        return 1.0
    for s in (1.0, 0.0254, 0.01, 0.001):
        if 0.2 <= dim * s <= 40.0:
            return s
    return 1.0


def _load_glb_inner(scene, path, progress=None) -> None:
    from core.group import Group

    def tick(frac, text):
        if progress is not None:
            progress(frac, text)

    tick(0.05, "Reading file…")
    batches, js = read_triangles(Path(path))
    s = _guess_scale(batches)
    if s != 1.0:
        batches = [(tris * s, uvs, r) for tris, uvs, r in batches]
    mesh = build_mesh(batches, progress=progress)
    title = (js.get("asset", {}).get("extras", {}) or {}).get("title")
    name = (title or Path(path).stem)[:60]
    group = Group(mesh, name=name)
    scene.groups.append(group)
