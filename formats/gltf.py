# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""glTF 2.0 / GLB export — a single self-contained file for visual interchange.

GLB packs geometry, materials **and the texture images** into one binary file:
there is no sidecar image folder to lose, so "I sent the file and the textures
came out grey" cannot happen (the failure mode OBJ/DAE have). Solid painted
colours become PBR ``baseColorFactor``; textured faces become a
``baseColorTexture`` with the image embedded in the buffer. Opens in Blender,
Windows 3D Viewer, Babylon Sandbox, three.js, most web viewers.

glTF is **Y-up, right-handed, metres**; IngeTrazo is Z-up, so positions and
normals are baked ``(x, y, z) → (x, z, −y)`` and standard viewers show the model
upright. The scene's geographic anchor (for sun/shadow studies) rides along in
``asset.extras`` — glTF has no standard geolocation field, so a viewer that
doesn't know IngeTrazo simply ignores it, and IngeTrazo can read it back.

No external dependencies — the GLB container is written by hand with ``struct``.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from .meshexport import collect_geometry, geolocation

_F32 = 5126          # accessor componentType FLOAT
_U32 = 5125          # accessor componentType UNSIGNED_INT
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963


def _yup(v):
    """Z-up (IngeTrazo) → Y-up (glTF)."""
    return (v.x(), v.z(), -v.y())


def _mime(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    return "image/png"


def save_glb(scene, path) -> None:
    """Write the scene as a binary glTF (``.glb``) to ``path``."""
    materials_in, prims = collect_geometry(scene)

    buf = bytearray()
    buffer_views: list[dict] = []
    accessors: list[dict] = []

    def _align() -> None:
        while len(buf) % 4:
            buf.append(0)

    def _accessor(data: bytes, comp: int, count: int, type_str: str,
                  target: int | None, mn=None, mx=None) -> int:
        _align()
        view = {"buffer": 0, "byteOffset": len(buf), "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        buf.extend(data)
        buffer_views.append(view)
        acc = {"bufferView": len(buffer_views) - 1, "componentType": comp,
               "count": count, "type": type_str}
        if mn is not None:
            acc["min"] = mn
            acc["max"] = mx
        accessors.append(acc)
        return len(accessors) - 1

    # ---- materials (+ embedded images) --------------------------------------
    keys = list(prims.keys())
    gltf_materials: list[dict] = []
    images: list[dict] = []
    textures: list[dict] = []
    samplers: list[dict] = []
    mat_index: dict[tuple, int] = {}
    tex_for_image: dict[str, int] = {}

    for key in keys:
        info = materials_in[key]
        mat: dict = {"name": f"mat{len(gltf_materials)}",
                     "doubleSided": True,
                     "pbrMetallicRoughness": {"metallicFactor": 0.0,
                                              "roughnessFactor": 1.0}}
        if info.get("map"):
            src = info["src"]
            tex_idx = tex_for_image.get(str(src))
            if tex_idx is None:
                try:
                    img_bytes = Path(src).read_bytes()
                except OSError:
                    img_bytes = None
                if img_bytes is not None:
                    _align()
                    view = {"buffer": 0, "byteOffset": len(buf),
                            "byteLength": len(img_bytes)}
                    buf.extend(img_bytes)
                    buffer_views.append(view)
                    images.append({"bufferView": len(buffer_views) - 1,
                                   "mimeType": _mime(info["map"]),
                                   "name": info["map"]})
                    if not samplers:
                        samplers.append({"wrapS": 10497, "wrapT": 10497})  # REPEAT
                    textures.append({"source": len(images) - 1, "sampler": 0})
                    tex_idx = tex_for_image[str(src)] = len(textures) - 1
            if tex_idx is not None:
                mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": tex_idx}
            else:  # image unreadable → fall back to white
                mat["pbrMetallicRoughness"]["baseColorFactor"] = [1, 1, 1, 1]
        else:
            r, g, b = info["color"]
            mat["pbrMetallicRoughness"]["baseColorFactor"] = [r, g, b, 1.0]
        mat_index[key] = len(gltf_materials)
        gltf_materials.append(mat)

    # ---- geometry: one primitive per material -------------------------------
    primitives: list[dict] = []
    for key in keys:
        tris = prims[key]
        textured = key[0] == "tex"
        positions: list[tuple] = []
        normals: list[tuple] = []
        uvs: list[tuple] = []
        indices: list[int] = []
        vindex: dict[tuple, int] = {}
        for normal, verts in tris:
            nn = _yup(normal)
            for pos, uv in verts:
                p = _yup(pos)
                uvk = (round(uv[0], 6), round(uv[1], 6)) if textured else (0.0, 0.0)
                vkey = (round(p[0], 6), round(p[1], 6), round(p[2], 6),
                        round(nn[0], 4), round(nn[1], 4), round(nn[2], 4), uvk)
                idx = vindex.get(vkey)
                if idx is None:
                    idx = vindex[vkey] = len(positions)
                    positions.append(p)
                    normals.append(nn)
                    if textured:
                        # glTF texcoord origin is top-left; OBJ/COLLADA UVs are
                        # bottom-left, so flip V.
                        uvs.append((uv[0], 1.0 - uv[1]))
                indices.append(idx)
        if not positions:
            continue

        pos_bytes = b"".join(struct.pack("<3f", *p) for p in positions)
        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        zs = [p[2] for p in positions]
        pos_acc = _accessor(pos_bytes, _F32, len(positions), "VEC3",
                            _ARRAY_BUFFER,
                            [min(xs), min(ys), min(zs)],
                            [max(xs), max(ys), max(zs)])
        nrm_bytes = b"".join(struct.pack("<3f", *n) for n in normals)
        nrm_acc = _accessor(nrm_bytes, _F32, len(normals), "VEC3", _ARRAY_BUFFER)
        attrs = {"POSITION": pos_acc, "NORMAL": nrm_acc}
        if textured and uvs:
            uv_bytes = b"".join(struct.pack("<2f", *t) for t in uvs)
            attrs["TEXCOORD_0"] = _accessor(uv_bytes, _F32, len(uvs), "VEC2",
                                            _ARRAY_BUFFER)
        idx_bytes = struct.pack(f"<{len(indices)}I", *indices)
        idx_acc = _accessor(idx_bytes, _U32, len(indices), "SCALAR",
                            _ELEMENT_ARRAY_BUFFER)
        primitives.append({"attributes": attrs, "indices": idx_acc,
                           "material": mat_index[key], "mode": 4})

    # ---- assemble the glTF JSON ---------------------------------------------
    extras: dict = {"generator": "IngeTrazo"}
    geo = geolocation(scene)
    if geo is not None:
        extras["ingetrazo_geolocation"] = {"lat": geo[0], "lon": geo[1],
                                           "alt": geo[2]}

    gltf: dict = {
        "asset": {"version": "2.0", "generator": "IngeTrazo", "extras": extras},
    }
    if primitives:
        gltf["meshes"] = [{"name": "IngeTrazo", "primitives": primitives}]
        gltf["nodes"] = [{"mesh": 0, "name": "IngeTrazo"}]
        gltf["scenes"] = [{"nodes": [0]}]
        gltf["scene"] = 0
    else:
        gltf["scenes"] = [{"nodes": []}]
        gltf["scene"] = 0
    if accessors:
        gltf["accessors"] = accessors
        gltf["bufferViews"] = buffer_views
        gltf["buffers"] = [{"byteLength": len(buf)}]
    if gltf_materials:
        gltf["materials"] = gltf_materials
    if images:
        gltf["images"] = images
        gltf["textures"] = textures
        gltf["samplers"] = samplers

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((-len(json_bytes)) % 4)          # pad with spaces
    bin_bytes = bytes(buf)
    bin_bytes += b"\x00" * ((-len(bin_bytes)) % 4)          # pad with zeros

    total = 12 + 8 + len(json_bytes) + (8 + len(bin_bytes) if bin_bytes else 0)
    with open(Path(path), "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))  # "glTF", v2, length
        f.write(struct.pack("<II", len(json_bytes), 0x4E4F534A))  # "JSON"
        f.write(json_bytes)
        if bin_bytes:
            f.write(struct.pack("<II", len(bin_bytes), 0x004E4942))  # "BIN\0"
            f.write(bin_bytes)
