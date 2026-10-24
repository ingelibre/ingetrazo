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

from core.texture import is_image_bytes
from .meshexport import collect_geometry, export_names, geolocation

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


def _yup_matrix(m) -> list:
    """A Z-up placement matrix as the matching glTF node matrix — the same
    change of axes the vertices get (:func:`_yup`) on both sides, column
    major as glTF wants it."""
    from PySide6.QtGui import QMatrix4x4
    c = QMatrix4x4(1, 0, 0, 0,
                   0, 0, 1, 0,
                   0, -1, 0, 0,
                   0, 0, 0, 1)
    return [float(v) for v in (c * m * c.transposed()).data()]


def _mesh_name(key, tree) -> str:
    """The name of the first node that draws mesh ``key``."""
    stack = list(tree)
    while stack:
        part = stack.pop(0)
        if part["mesh"] == key:
            return part["name"]
        stack.extend(part["children"])
    return "Mesh"


#: Where a face-me figure looks in a file with no camera: toward the Front
#: view, the side the model is usually opened from.
_FILE_FACING = (0.0, -1.0, 0.0)


def _file_hierarchy(scene, only=None):
    """The model as a tree for a file: ``(materials, meshes, roots)``.

    ``meshes`` maps a key to the triangles of ONE mesh in its own
    coordinates, grouped by material (see :func:`formats.meshexport.
    collect_geometry`); the key of a component's prototype is shared by
    all its copies. ``roots`` are the top nodes: ``{"name", "matrix"
    (QMatrix4x4 Z-up, or None), "mesh" (a key or None), "children",
    "extras"}``. A face-me figure is a world-space root standing toward
    :data:`_FILE_FACING`, with ``ingetrazo_faceme`` = feet and heading,
    as the Render with Blender export writes it."""
    import math
    from PySide6.QtGui import QVector3D
    from core.group import transformed_mesh
    from core.i18n import tr
    from core.materials import material_sig
    from .meshexport import (SmoothNormals, _add_face, _facing_quad, _feet,
                             _piece_paint, _resolve_finishes, _shown,
                             _turned_toward)
    smoother = SmoothNormals()
    materials: dict = {}
    meshes: dict = {}
    roots: list = []
    figures: list = []
    facing = QVector3D(*_FILE_FACING)

    def toward(_anchor):
        return facing

    loose = [f for f in scene.loose_mesh.faces
             if scene.entity_visible(f) and (only is None or f in only)]
    if loose:
        prims: dict = {}
        for f in loose:
            _add_face(f, materials, prims, smoother=smoother)
        meshes["loose"] = prims
        roots.append({"name": tr("Loose geometry"), "matrix": None,
                      "mesh": "loose", "children": []})

    def part(g, base, top):
        m = getattr(g, "xform", None)
        world = m if base is None else (base if m is None else base * m)
        # What the piece's unpainted faces show: its own paint, else the
        # top-level object's — as the viewport draws it.
        paint = _piece_paint(g, top)
        kind = getattr(g, "billboard", False)
        if kind:
            mesh = g.mesh if world is None else transformed_mesh(g.mesh, world)
            feet = _feet(mesh)
            if feet is None:
                return None
            turned = (_turned_toward(mesh, toward) if kind == "mesh"
                      else _facing_quad(mesh, toward))
            prims = {}
            for f in turned.faces:
                _add_face(f, materials, prims, _shown(f, paint), smoother)
            if prims:
                key = ("figure", len(figures))
                meshes[key] = prims
                figures.append({
                    "name": getattr(g, "name", "") or tr("Figure"),
                    "matrix": None, "mesh": key, "children": [],
                    "extras": {"ingetrazo_faceme": [
                        feet.x(), feet.y(), feet.z(),
                        math.atan2(facing.y(), facing.x())]}})
            return None
        # Copies of a component share ONE mesh in the file — unless they
        # wear different paint, which makes them different meshes.
        key = (id(g.mesh), material_sig(paint))
        if key not in meshes:
            prims = {}
            for f in g.mesh.faces:
                _add_face(f, materials, prims, _shown(f, paint), smoother)
            meshes[key] = prims
        node = {"name": getattr(g, "name", "") or tr("Group"),
                "matrix": m, "mesh": key if meshes[key] else None,
                "children": []}
        for child in getattr(g, "children", None) or ():
            sub = part(child, world, top)
            if sub is not None:
                node["children"].append(sub)
        return node

    for g in getattr(scene, "groups", []):
        if not scene.entity_visible(g):
            continue
        if only is not None and g not in only:
            continue
        node = part(g, None, g)
        if node is not None:
            roots.append(node)
    roots.extend(figures)
    _resolve_finishes(scene, materials)
    return materials, meshes, roots


def save_glb(scene, path, face_me=None, only=None) -> None:
    """Write the scene as a binary glTF (``.glb``) to ``path``.

    ``face_me`` turns the face-me figures toward a camera and brings them
    along (see :func:`formats.meshexport.world_faces`); Render with Blender
    passes its camera (#181).

    Without a camera — a file for other programs — the model keeps its
    structure (#304): one node per group and component, nested as in the
    model, with its name and transform, the copies of a component sharing
    one mesh; the loose geometry is a node of its own, and every face-me
    figure stands facing the Front view as a node with its feet and
    heading in extras (#353: they were left out, or came out mirrored
    from inside a group). ``only`` (a set of selected entities) writes
    just those: loose faces and top-level groups."""
    # With a camera the face-me figures travel as nodes of their own, each
    # with its feet and heading in extras: a renderer that moves the camera
    # (Render ▸ sync with the view) turns them instead of re-exporting.
    figures: list = []
    tree = None
    if face_me is not None:
        from formats.meshexport import collect_geometry_split
        materials_in, prims, figures = collect_geometry_split(scene, face_me)
    else:
        materials_in, mesh_prims, tree = _file_hierarchy(scene, only)
        prims = {}

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
    for fig in figures:
        keys += [k for k in fig["prims"] if k not in keys]
    if tree is not None:
        for source in mesh_prims.values():
            keys += [k for k in source if k not in keys]
    gltf_materials: list[dict] = []
    images: list[dict] = []
    textures: list[dict] = []
    samplers: list[dict] = []
    mat_index: dict[tuple, int] = {}
    tex_for_image: dict[str, int] = {}

    names = export_names(materials_in)
    used_ext: set = set()
    for key in keys:
        info = materials_in[key]
        mat: dict = {"name": names[key],
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
                if img_bytes is not None and not is_image_bytes(img_bytes):
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
                # A cut-out image (a face-me figure, leaves) stays cut out:
                # without this its transparent texels rendered as a solid
                # card (#181).
                from core.texture import image_has_cutout
                if image_has_cutout(str(src)):
                    mat["alphaMode"] = "MASK"
                    mat["alphaCutoff"] = 0.5
            else:  # image unreadable → fall back to white
                mat["pbrMetallicRoughness"]["baseColorFactor"] = [1, 1, 1, 1]
        else:
            # A colour may carry an alpha (an imported model's): the
            # exporter refused the whole file over it (pileta.igz).
            r, g, b = tuple(info["color"])[:3]
            mat["pbrMetallicRoughness"]["baseColorFactor"] = [r, g, b, 1.0]
        # The finish (core.finish): plain glTF for every program, and the
        # name in extras for Render with Blender's full materials.
        finish = info.get("finish")
        if finish:
            from core.finish import PBR
            rough, metal, trans, ior = PBR[finish]
            pbr = mat["pbrMetallicRoughness"]
            pbr["roughnessFactor"], pbr["metallicFactor"] = rough, metal
            mat["extras"] = {"ingetrazo_finish": finish}
            ext = {}
            if trans:
                ext["KHR_materials_transmission"] = {
                    "transmissionFactor": trans}
            if ior != 1.5:
                ext["KHR_materials_ior"] = {"ior": ior}
            if ext:
                mat["extensions"] = ext
                used_ext.update(ext)
        op = info.get("opacity")
        if op is not None:                     # glass and the like
            factor = mat["pbrMetallicRoughness"].setdefault(
                "baseColorFactor", [1.0, 1.0, 1.0, 1.0])
            factor[3] = float(op)
            mat["alphaMode"] = "BLEND"
            mat.pop("alphaCutoff", None)
        mat_index[key] = len(gltf_materials)
        gltf_materials.append(mat)

    # ---- geometry: one primitive per material -------------------------------
    def _primitives(source: dict) -> list[dict]:
        primitives: list[dict] = []
        for key in keys:
            if key not in source:
                continue
            tris = source[key]
            textured = key[0] == "tex"
            positions: list[tuple] = []
            normals: list[tuple] = []
            uvs: list[tuple] = []
            indices: list[int] = []
            vindex: dict[tuple, int] = {}
            for _flat, verts in tris:
                for pos, uv, normal in verts:
                    p = _yup(pos)
                    nn = _yup(normal)      # smooth across soft edges
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
        return primitives

    primitives = _primitives(prims)
    figure_meshes = []
    for fig in figures:
        fp = _primitives(fig["prims"])
        if fp:
            figure_meshes.append((fp, fig))

    # ---- assemble the glTF JSON ---------------------------------------------
    extras: dict = {"generator": "IngeTrazo"}
    geo = geolocation(scene)
    if geo is not None:
        extras["ingetrazo_geolocation"] = {"lat": geo[0], "lon": geo[1],
                                           "alt": geo[2]}

    gltf: dict = {
        "asset": {"version": "2.0", "generator": "IngeTrazo", "extras": extras},
    }
    meshes: list[dict] = []
    nodes: list[dict] = []
    if tree is not None:
        mesh_index: dict = {}
        for key, source in mesh_prims.items():
            prim_list = _primitives(source)
            if prim_list:
                mesh_index[key] = len(meshes)
                meshes.append({"name": _mesh_name(key, tree), "primitives": prim_list})

        def _emit(part) -> int:
            node: dict = {"name": part["name"]}
            mi = mesh_index.get(part["mesh"])
            if mi is not None:
                node["mesh"] = mi
            m = part.get("matrix")
            if m is not None and not m.isIdentity():
                node["matrix"] = _yup_matrix(m)
            if part.get("extras"):
                node["extras"] = part["extras"]
            nodes.append(node)
            idx = len(nodes) - 1
            kids = [_emit(c) for c in part["children"]]
            if kids:
                nodes[idx]["children"] = kids
            return idx

        roots = [_emit(part) for part in tree]
        if meshes:
            gltf["meshes"] = meshes
        if nodes:
            gltf["nodes"] = nodes
        gltf["scenes"] = [{"nodes": roots}]
        gltf["scene"] = 0
    if tree is None and primitives:
        meshes.append({"name": "IngeTrazo", "primitives": primitives})
        nodes.append({"mesh": 0, "name": "IngeTrazo"})
    for i, (fp, fig) in enumerate(figure_meshes if tree is None else (), 1):
        feet = fig["feet"]
        meshes.append({"name": f"Figure {i}", "primitives": fp})
        nodes.append({"mesh": len(meshes) - 1, "name": f"Figure {i}",
                      "extras": {"ingetrazo_faceme": [
                          feet.x(), feet.y(), feet.z(), fig["yaw"]]}})
    if tree is None:
        if meshes:
            gltf["meshes"] = meshes
            gltf["nodes"] = nodes
        gltf["scenes"] = [{"nodes": list(range(len(nodes)))}]
        gltf["scene"] = 0
    if accessors:
        gltf["accessors"] = accessors
        gltf["bufferViews"] = buffer_views
        gltf["buffers"] = [{"byteLength": len(buf)}]
    if gltf_materials:
        gltf["materials"] = gltf_materials
    if used_ext:
        gltf["extensionsUsed"] = sorted(used_ext)
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
