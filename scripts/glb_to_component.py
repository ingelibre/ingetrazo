# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Convert a (CC0/CC-BY!) glTF/GLB model into a bundled starter component.

    venv/bin/python scripts/glb_to_component.py model.glb key \
        [--max-faces 60000] [--tex-size 1024] [--height H]

Reads the GLB with the app's own importer (formats/glb.py), decimates
toward ``--max-faces`` — UV-preserving quadric collapse for connected
meshes (``pip install fast-simplification``, dev tool only, NOT a runtime
dep) and leaf-CARD thinning for disconnected foliage soups (quadric
bottoms out there; surviving cards grow to keep canopy density) —
downscales textures to ``--tex-size``, grounds and centres the model and
writes a compact ``resources/components/<key>.glb`` (textures embedded,
normals dropped; the app inserts it through its own GLB importer).
Prints the embedded Sketchfab attribution — copy it into
resources/components/SOURCES.md; bundle ONLY CC0 or CC-BY models.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    app = QApplication([])
    app.setOrganizationName("IngeTrazoTools")
    app.setApplicationName("glb-to-component")

import numpy as np  # noqa: E402


def _indexed(tris, uvs):
    """Corner soup → indexed mesh (verts, per-vertex uv, faces): corners
    welded by (position, uv) so texture seams keep their duplicated verts."""
    n = len(tris)
    pos = tris.reshape(-1, 3)
    uv = (uvs.reshape(-1, 2) if uvs is not None
          else np.zeros((n * 3, 2)))
    key = np.round(np.concatenate([pos, uv], axis=1), 5)
    _uniq, first, inv = np.unique(key, axis=0, return_index=True,
                                  return_inverse=True)
    verts = pos[first]
    vuv = uv[first]
    faces = inv.reshape(-1, 3)
    ok = ((faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2])
          & (faces[:, 0] != faces[:, 2]))
    return verts, vuv, faces[ok]


def _face_components(n_verts, faces):
    """Connected-component label per face (union-find over shared verts)."""
    parent = list(range(n_verts))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, c in faces.tolist():
        ra, rb, rc = find(a), find(b), find(c)
        parent[rb] = ra
        parent[find(rc)] = ra
    return np.array([find(int(a)) for a in faces[:, 0]], dtype=np.int64)


def _thin_cards(verts, vuv, faces, keep_ratio, rng):
    """Foliage thinning: drop whole disconnected cards at random, grow the
    survivors around their centroids so the canopy keeps its density."""
    labels = _face_components(len(verts), faces)
    comps = np.unique(labels)
    kept_comps = comps[rng.random(len(comps)) < keep_ratio]
    mask = np.isin(labels, kept_comps)
    faces = faces[mask]
    used = np.unique(faces)
    remap = np.full(len(verts), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    verts2, vuv2, faces2 = verts[used].copy(), vuv[used], remap[faces]
    grow = min(1.8, 1.0 / max(np.sqrt(keep_ratio), 1e-3))
    labels2 = _face_components(len(verts2), faces2)
    lab_of_vert = np.full(len(verts2), -1, dtype=np.int64)
    lab_of_vert[faces2.ravel()] = np.repeat(labels2, 3)
    for lab in np.unique(labels2):
        vs = np.where(lab_of_vert == lab)[0]
        centre = verts2[vs].mean(axis=0)
        span = np.linalg.norm(verts2[vs].max(axis=0) - verts2[vs].min(axis=0))
        if span < 1.0:      # grow leaf cards only, never big planes
            verts2[vs] = centre + (verts2[vs] - centre) * grow
    return verts2, vuv2, faces2


def _decimate(verts, vuv, faces, keep_ratio):
    import fast_simplification as fs
    out = fs.simplify(verts.astype(np.float32), faces.astype(np.int64),
                      target_reduction=1.0 - keep_ratio,
                      return_collapses=True)
    new_pts, new_faces, collapses = out
    _p, _f, mapping = fs.replay_simplification(
        verts.astype(np.float32), faces.astype(np.int64), collapses)
    rep = np.full(len(new_pts), -1, dtype=np.int64)
    rep[mapping[::-1]] = np.arange(len(mapping) - 1, -1, -1)
    new_uv = vuv[rep]
    return new_pts.astype(np.float64), new_uv, new_faces


def _alpha_bleed(img):
    """Fill transparent texels with nearby opaque RGB: cutout foliage keeps
    black under alpha 0, and mip/bilinear sampling mixes it in — a tree
    canopy renders as a dark silhouette without this."""
    from PySide6.QtGui import QImage
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    h, w = img.height(), img.width()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, w, 4).copy()
    rgb = a[..., :3].astype(np.float64)
    known = a[..., 3] > 16
    if known.all() or not known.any():
        return img
    for _ in range(8):
        padk = np.pad(known, 1)
        padc = np.pad(rgb, ((1, 1), (1, 1), (0, 0)))
        acc = np.zeros((h, w, 3))
        cnt = np.zeros((h, w))
        for dy, dx in ((0, 1), (2, 1), (1, 0), (1, 2)):
            nb = padk[dy:dy + h, dx:dx + w]
            acc += padc[dy:dy + h, dx:dx + w] * nb[..., None]
            cnt += nb
        grow = (~known) & (cnt > 0)
        if not grow.any():
            break
        rgb[grow] = acc[grow] / cnt[grow, None]
        known |= grow
    if not known.all():
        rgb[~known] = rgb[known].mean(axis=0)
    a[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    return QImage(np.ascontiguousarray(a).data, w, h, w * 4,
                  QImage.Format.Format_RGBA8888).copy()


def _auto_exposure(img, target=125.0, max_gain=2.0):
    """PBR albedo is authored to be LIT; IngeTrazo displays SketchUp-style
    (texel × orientation shade), so dark-baked foliage reads near black.
    Lift dark textures toward a mid luminance with a soft shoulder."""
    from PySide6.QtGui import QImage
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    h, w = img.height(), img.width()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, w, 4).copy()
    opaque = a[..., 3] > 128
    if not opaque.any():
        return img
    lum = a[..., :3][opaque].astype(np.float64).mean()
    gain = min(max_gain, target / max(lum, 1.0))
    if gain < 1.15:
        return img
    x = a[..., :3].astype(np.float64) * gain
    a[..., :3] = np.clip(x, 0, 255).astype(np.uint8)
    return QImage(np.ascontiguousarray(a).data, w, h, w * 4,
                  QImage.Format.Format_RGBA8888).copy()


def _shrink_texture(path, tex_size, out_dir):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    img = QImage(str(path))
    if img.isNull():
        return str(path)
    has_alpha = img.hasAlphaChannel()
    if max(img.width(), img.height()) > tex_size:
        img = img.scaled(min(img.width(), tex_size),
                         min(img.height(), tex_size),
                         Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    img = _auto_exposure(img)
    if has_alpha:
        img = _alpha_bleed(img)
    out = Path(out_dir) / (Path(path).stem + (".png" if has_alpha else ".jpg"))
    img.save(str(out), None if has_alpha else "JPG", -1 if has_alpha else 88)
    return str(out)


def _write_glb(out_path, indexed_batches, extras, key):
    """Minimal valid glTF 2.0 binary: one buffer, one mesh, one primitive
    per material batch, embedded images, no normals (the importer computes
    face normals). Positions stored glTF Y-up."""
    bin_parts: list = []
    buffer_views: list = []

    def add_buf(blob, target=None):
        off = sum(len(b) for b in bin_parts)
        pad = (-off) % 4
        if pad:
            bin_parts.append(b"\x00" * pad)
            off += pad
        bin_parts.append(blob)
        bv = {"buffer": 0, "byteOffset": off, "byteLength": len(blob)}
        if target:
            bv["target"] = target
        buffer_views.append(bv)
        return len(buffer_views) - 1

    accessors: list = []
    images: list = []
    textures: list = []
    materials: list = []
    prims: list = []
    tex_index: dict = {}
    for verts, vuv, faces, (tex_path, rgba, opacity) in indexed_batches:
        yup = np.stack([verts[:, 0], verts[:, 2], -verts[:, 1]], axis=1)
        pos = np.ascontiguousarray(yup, dtype="<f4")
        idx = np.ascontiguousarray(faces.reshape(-1), dtype="<u4")
        bv_p = add_buf(pos.tobytes(), 34962)
        acc_p = len(accessors)
        accessors.append({"bufferView": bv_p, "componentType": 5126,
                          "count": len(pos), "type": "VEC3",
                          "min": pos.min(axis=0).tolist(),
                          "max": pos.max(axis=0).tolist()})
        bv_i = add_buf(idx.tobytes(), 34963)
        acc_i = len(accessors)
        accessors.append({"bufferView": bv_i, "componentType": 5125,
                          "count": int(idx.size), "type": "SCALAR"})
        attrs = {"POSITION": acc_p}
        mat = {"doubleSided": True,
               "pbrMetallicRoughness": {"metallicFactor": 0.0,
                                        "roughnessFactor": 1.0}}
        if tex_path:
            uvf = np.ascontiguousarray(vuv, dtype="<f4")
            bv_t = add_buf(uvf.tobytes(), 34962)
            acc_t = len(accessors)
            accessors.append({"bufferView": bv_t, "componentType": 5126,
                              "count": len(uvf), "type": "VEC2"})
            attrs["TEXCOORD_0"] = acc_t
            if tex_path not in tex_index:
                blob = Path(tex_path).read_bytes()
                mime = ("image/png" if blob[:4] == b"\x89PNG"
                        else "image/jpeg")
                bv_img = add_buf(blob)
                images.append({"bufferView": bv_img, "mimeType": mime})
                textures.append({"source": len(images) - 1})
                tex_index[tex_path] = (len(textures) - 1, mime)
            ti, mime = tex_index[tex_path]
            mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": ti}
            if mime == "image/png":
                mat["alphaMode"] = "MASK"
                mat["alphaCutoff"] = 0.5
        else:
            base = list(rgba[:3]) if rgba else [1.0, 1.0, 1.0]
            a = opacity if opacity is not None else (
                rgba[3] if rgba and len(rgba) > 3 else 1.0)
            mat["pbrMetallicRoughness"]["baseColorFactor"] = base + [a]
            if opacity is not None:
                mat["alphaMode"] = "BLEND"
        materials.append(mat)
        prims.append({"attributes": attrs, "indices": acc_i,
                      "material": len(materials) - 1})

    bin_blob = b"".join(bin_parts)
    bin_blob += b"\x00" * ((-len(bin_blob)) % 4)
    js = {"asset": {"version": "2.0",
                    "generator": "IngeTrazo glb_to_component",
                    "extras": {k: extras.get(k)
                               for k in ("title", "author", "license",
                                         "source") if extras.get(k)}},
          "scene": 0, "scenes": [{"nodes": [0]}],
          "nodes": [{"mesh": 0, "name": key}],
          "meshes": [{"primitives": prims}],
          "accessors": accessors, "bufferViews": buffer_views,
          "materials": materials,
          "buffers": [{"byteLength": len(bin_blob)}]}
    if images:
        js["images"] = images
        js["textures"] = textures
    jbytes = json.dumps(js, separators=(",", ":")).encode()
    jbytes += b" " * ((-len(jbytes)) % 4)
    total = 12 + 8 + len(jbytes) + 8 + len(bin_blob)
    with open(out_path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(jbytes), 0x4E4F534A))
        f.write(jbytes)
        f.write(struct.pack("<II", len(bin_blob), 0x004E4942))
        f.write(bin_blob)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("key")
    ap.add_argument("--max-faces", type=int, default=60000)
    ap.add_argument("--tex-size", type=int, default=1024)
    ap.add_argument("--height", type=float, default=None,
                    help="rescale so the model is this many metres tall")
    args = ap.parse_args()

    from formats import glb as glb_mod

    batches, js = glb_mod.read_triangles(Path(args.glb))
    extras = (js.get("asset", {}).get("extras", {}) or {})
    s = glb_mod._guess_scale(batches)
    batches = [(tris * s, uvs, r) for tris, uvs, r in batches]

    total = sum(len(t) for t, _u, _r in batches)
    keep = min(1.0, args.max_faces / max(total, 1))
    tmp = tempfile.mkdtemp(prefix=f"component-{args.key}-")
    rng = np.random.default_rng(42)
    tex_map: dict = {}
    indexed_batches = []
    for tris, uvs, (tex_path, rgba, opacity) in batches:
        verts, vuv, faces = _indexed(tris, uvs)
        if keep < 1.0 and len(faces) > 400:
            budget = keep * len(faces)
            labels = _face_components(len(verts), faces)
            n_comp = len(np.unique(labels))
            if n_comp > max(50, len(faces) // 8):
                verts, vuv, faces = _thin_cards(verts, vuv, faces, keep, rng)
            else:
                verts, vuv, faces = _decimate(verts, vuv, faces, keep)
                if len(faces) > budget * 1.3:
                    # Quadric bottomed out (foliage collapses into many
                    # small disconnected cards) — thin the remainder.
                    verts, vuv, faces = _thin_cards(
                        verts, vuv, faces, budget / len(faces), rng)
        if tex_path is not None and tex_path not in tex_map:
            tex_map[tex_path] = _shrink_texture(tex_path, args.tex_size, tmp)
        indexed_batches.append(
            (verts, vuv, faces, (tex_map.get(tex_path), rgba, opacity)))

    # Ground + centre (+ optional height rescale) on the vertex arrays.
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    for verts, _u, _f, _r in indexed_batches:
        lo = np.minimum(lo, verts.min(axis=0))
        hi = np.maximum(hi, verts.max(axis=0))
    scale = 1.0
    if args.height:
        scale = args.height / max(hi[2] - lo[2], 1e-9)
    offset = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    indexed_batches = [((verts - offset) * scale, vuv, faces, r)
                       for verts, vuv, faces, r in indexed_batches]

    out = (Path(__file__).resolve().parent.parent / "resources"
           / "components" / f"{args.key}.glb")
    _write_glb(out, indexed_batches, extras, args.key)
    n_faces = sum(len(f) for _v, _u, f, _r in indexed_batches)
    kb = out.stat().st_size // 1024
    print(f"{args.key}: {total} -> {n_faces} faces, {kb} KB")
    print(f"  title:   {extras.get('title')}")
    print(f"  author:  {extras.get('author')}")
    print(f"  license: {extras.get('license')}")
    print(f"  source:  {extras.get('source')}")


if __name__ == "__main__":
    main()
