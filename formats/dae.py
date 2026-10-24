# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""COLLADA (.dae) import + export — the bridge to other modellers, most of
which read and write COLLADA natively.

Import opens the models other programs export; :func:`save_dae` writes ours back out
(Z-up, metres, per-face colour/texture, and — when georeferenced — the standard
``<geographic_location>`` so a sun/shadow study keeps the site).

COLLADA is Khronos' open XML interchange format; parsing with the stdlib
``xml.etree`` keeps the project dependency-free. Scope (matching what
common exporters emit): ``library_geometries`` meshes (``triangles`` / ``polylist``
/ ``polygons``), the ``visual_scene`` node tree with baked transforms
(``matrix`` / ``translate`` / ``rotate`` / ``scale``), component instancing
via ``library_nodes`` / ``instance_node``, lambert/phong diffuse colours,
``up_axis`` (Y_UP → Z-up conversion) and the ``unit`` metre scale (some
exporters write inches). Textures are skipped (colour only).

Like the OBJ importer, triangles are fused back into clean editable polygons
(coplanar merge) and closed results get a consistent outward orientation.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtGui import QMatrix4x4, QVector3D

_NS = "{http://www.collada.org/2005/11/COLLADASchema}"

def _add_fused(mesh, fused) -> None:
    """Add ``fuse_coplanar_loops`` output to ``mesh``, falling back to a
    region's original loops when the fused polygon is rejected."""
    for outer, holes, attrs, originals in fused:
        try:
            f = mesh.add_face(outer, holes or None)
            if attrs:
                f.attrs.update(attrs)
        except Exception:  # noqa: BLE001 — irregular region: keep its pieces
            for pts in originals:
                try:
                    f = mesh.add_face(pts)
                    if attrs:
                        f.attrs.update(attrs)
                except Exception:  # noqa: BLE001
                    continue


# Imports up to this many polygons get the full editable-import pipeline
# (coplanar fusion + outward orientation). Bigger models come from asset
# libraries (downloaded buildings, furniture) and import as-is: the fusion
# pass is O(F²)-ish and measured minutes-to-hours at that scale (a 17k-tri
# building froze the app), while the result is reference geometry anyway.
# Mirrored in formats/obj.py — keep the two in sync.
_MAX_FUSE_LOOPS = 400


def _tag(el) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _floats(text) -> list[float]:
    return [float(t) for t in (text or "").split()]


def _ints(text) -> list[int]:
    return [int(t) for t in (text or "").split()]


# ---- Export --------------------------------------------------------------------

def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def save_dae(scene, path, project_name: str = "IngeTrazo model") -> None:
    """Write the scene as a COLLADA (``.dae``) file at ``path``, with a sibling
    folder of texture images copied next to it.

    COLLADA is imported natively by most modellers, so this is the "open it
    back elsewhere" bridge. Written Z-up (``<up_axis>Z_UP</up_axis>``) in metres.
    Solid ``Face.attrs["color"]`` become lambert diffuse colours; textured faces
    become ``<texture>`` effects with the image copied beside the ``.dae`` (same
    as the OBJ exporter — send the file *and* the folder together, or use GLB to
    avoid the split). When the scene is georeferenced, the model's location
    rides in the standard ``<asset><coverage><geographic_location>`` — the right
    place for it, so a sun/shadow study keeps the site.
    """
    import shutil
    from datetime import datetime, timezone

    from .meshexport import collect_geometry, export_names, geolocation

    path = Path(path)
    materials_in, prims = collect_geometry(scene)
    mat_names = export_names(materials_in)
    keys = list(prims.keys())

    # Deduplicated shared sources for the single <geometry>.
    positions: list[tuple] = []
    normals: list[tuple] = []
    uvs: list[tuple] = []
    pidx: dict[tuple, int] = {}
    nidx: dict[tuple, int] = {}
    uidx: dict[tuple, int] = {}

    def _pi(p) -> int:
        key = (round(p.x(), 6), round(p.y(), 6), round(p.z(), 6))
        i = pidx.get(key)
        if i is None:
            i = pidx[key] = len(positions)
            positions.append((p.x(), p.y(), p.z()))
        return i

    def _ni(n) -> int:
        key = (round(n.x(), 5), round(n.y(), 5), round(n.z(), 5))
        i = nidx.get(key)
        if i is None:
            i = nidx[key] = len(normals)
            normals.append((n.x(), n.y(), n.z()))
        return i

    def _ui(uv) -> int:
        key = (round(uv[0], 6), round(uv[1], 6))
        i = uidx.get(key)
        if i is None:
            i = uidx[key] = len(uvs)
            uvs.append((uv[0], uv[1]))
        return i

    # Per-material triangle index lists → the <p> of each <triangles>.
    tri_groups: list[tuple[tuple, bool, list]] = []
    for key in keys:
        textured = key[0] == "tex"
        p_tokens: list[str] = []
        for _flat, verts in prims[key]:
            for pos, uv, normal in verts:
                p_tokens.append(str(_pi(pos)))
                p_tokens.append(str(_ni(normal)))   # smooth across soft edges
                if textured:
                    p_tokens.append(str(_ui(uv)))
        tri_groups.append((key, textured, p_tokens))

    # Copy texture images next to the .dae so <init_from> resolves.
    from core.texture import is_image_file
    for key in keys:
        info = materials_in[key]
        if info.get("map"):
            dst = path.parent / info["map"]
            try:
                if (Path(info["src"]).resolve() != dst.resolve()
                        and is_image_file(info["src"])):
                    shutil.copy(info["src"], dst)
            except Exception:  # noqa: BLE001 — best-effort; export still valid
                pass

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out: list[str] = []
    out.append('<?xml version="1.0" encoding="utf-8"?>')
    out.append('<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" '
               'version="1.4.1">')
    out.append("<asset>")
    out.append("<contributor><authoring_tool>IngeTrazo</authoring_tool>"
               "</contributor>")
    out.append(f"<created>{now}</created><modified>{now}</modified>")
    geo = geolocation(scene)
    if geo is not None:
        lat, lon, alt = geo
        out.append("<coverage><geographic_location>")
        out.append(f"<longitude>{lon:.9f}</longitude>")
        out.append(f"<latitude>{lat:.9f}</latitude>")
        out.append(f'<altitude mode="absolute">{alt:.3f}</altitude>')
        out.append("</geographic_location></coverage>")
    out.append('<unit name="meter" meter="1"/>')
    out.append("<up_axis>Z_UP</up_axis>")
    out.append("</asset>")

    # library_images / library_effects / library_materials. COLLADA 1.4.1
    # wants at least one <image> inside <library_images>, and strict
    # importers refuse the empty element — leave it out when nothing is
    # textured.
    images = [f'<image id="img{i}" name="img{i}">'
              f"<init_from>{_xml_escape(materials_in[key]['map'])}</init_from>"
              "</image>"
              for i, key in enumerate(keys) if materials_in[key].get("map")]
    if images:
        out.append("<library_images>")
        out.extend(images)
        out.append("</library_images>")

    out.append("<library_effects>")
    for i, key in enumerate(keys):
        info = materials_in[key]
        out.append(f'<effect id="eff{i}"><profile_COMMON>')
        if info.get("map"):
            out.append(f'<newparam sid="surf{i}"><surface type="2D">'
                       f"<init_from>img{i}</init_from></surface></newparam>")
            out.append(f'<newparam sid="samp{i}"><sampler2D>'
                       f"<source>surf{i}</source></sampler2D></newparam>")
            out.append('<technique sid="common"><lambert><diffuse>'
                       f'<texture texture="samp{i}" texcoord="UVSET0"/>'
                       "</diffuse></lambert></technique>")
        else:
            r, g, b = info["color"]
            out.append('<technique sid="common"><lambert><diffuse>'
                       f"<color>{r:.4f} {g:.4f} {b:.4f} 1</color>"
                       "</diffuse></lambert></technique>")
        out.append("</profile_COMMON></effect>")
    out.append("</library_effects>")

    out.append("<library_materials>")
    for i in range(len(keys)):
        out.append(f'<material id="mat{i}" name="{mat_names[keys[i]]}">'
                   f'<instance_effect url="#eff{i}"/></material>')
    out.append("</library_materials>")

    # library_geometries — one geometry, shared sources, one <triangles>/material
    out.append("<library_geometries>")
    out.append('<geometry id="geom0" name="IngeTrazo"><mesh>')
    pos_floats = " ".join(f"{c:.6f}" for xyz in positions for c in xyz)
    out.append(f'<source id="geom0-pos"><float_array id="geom0-pos-array" '
               f'count="{len(positions) * 3}">{pos_floats}</float_array>'
               '<technique_common><accessor source="#geom0-pos-array" '
               f'count="{len(positions)}" stride="3">'
               '<param name="X" type="float"/><param name="Y" type="float"/>'
               '<param name="Z" type="float"/></accessor></technique_common>'
               "</source>")
    nrm_floats = " ".join(f"{c:.5f}" for xyz in normals for c in xyz)
    out.append(f'<source id="geom0-nrm"><float_array id="geom0-nrm-array" '
               f'count="{len(normals) * 3}">{nrm_floats}</float_array>'
               '<technique_common><accessor source="#geom0-nrm-array" '
               f'count="{len(normals)}" stride="3">'
               '<param name="X" type="float"/><param name="Y" type="float"/>'
               '<param name="Z" type="float"/></accessor></technique_common>'
               "</source>")
    if uvs:
        uv_floats = " ".join(f"{c:.6f}" for st in uvs for c in st)
        out.append(f'<source id="geom0-uv"><float_array id="geom0-uv-array" '
                   f'count="{len(uvs) * 2}">{uv_floats}</float_array>'
                   '<technique_common><accessor source="#geom0-uv-array" '
                   f'count="{len(uvs)}" stride="2">'
                   '<param name="S" type="float"/><param name="T" type="float"/>'
                   "</accessor></technique_common></source>")
    out.append('<vertices id="geom0-vertices">'
               '<input semantic="POSITION" source="#geom0-pos"/></vertices>')
    for i, (key, textured, p_tokens) in enumerate(tri_groups):
        stride = 3 if textured else 2
        count = len(p_tokens) // (3 * stride)
        out.append(f'<triangles material="sym{i}" count="{count}">')
        out.append('<input semantic="VERTEX" source="#geom0-vertices" offset="0"/>')
        out.append('<input semantic="NORMAL" source="#geom0-nrm" offset="1"/>')
        if textured:
            out.append('<input semantic="TEXCOORD" source="#geom0-uv" '
                       'offset="2" set="0"/>')
        out.append("<p>" + " ".join(p_tokens) + "</p>")
        out.append("</triangles>")
    out.append("</mesh></geometry>")
    out.append("</library_geometries>")

    # visual_scene — geometry MUST sit inside a <node> or importers skip it.
    out.append("<library_visual_scenes>")
    out.append('<visual_scene id="scene"><node id="model" '
               f'name="{_xml_escape(project_name)}">')
    out.append('<instance_geometry url="#geom0"><bind_material>'
               "<technique_common>")
    for i, (key, textured, _p) in enumerate(tri_groups):
        gi = keys.index(key)
        out.append(f'<instance_material symbol="sym{i}" target="#mat{gi}">')
        if textured:
            out.append('<bind_vertex_input semantic="UVSET0" '
                       'input_semantic="TEXCOORD" input_set="0"/>')
        out.append("</instance_material>")
    out.append("</technique_common></bind_material></instance_geometry>")
    out.append("</node></visual_scene></library_visual_scenes>")
    out.append('<scene><instance_visual_scene url="#scene"/></scene>')
    out.append("</COLLADA>")

    Path(path).write_text("\n".join(out), encoding="utf-8")


class _Dae:
    """One parsed document: id-indexed libraries + resolved world geometry."""

    def __init__(self, root, base_dir=None) -> None:
        self.root = root
        self.base_dir = base_dir
        self._img_colors: dict = {}
        # Parsed <source> float arrays and UV tuple lists, keyed by element
        # identity: sources are shared across primitives and instanced
        # geometry, and re-splitting a big TEXCOORD array text per primitive
        # turned a 19 s import into a 4-minute one.
        self._src_cache: dict = {}
        self._uv_cache: dict = {}
        self._img_alpha: dict = {}
        self._polys_cache: dict = {}
        # How many times each library node is instanced — reused targets are
        # components and import as shared-prototype instances.
        from collections import Counter
        self.inst_counts = Counter(
            (el.get("url") or "") for el in root.iter(f"{_NS}instance_node"))
        self.by_id: dict = {}
        for el in root.iter():
            i = el.get("id")
            if i is not None:
                self.by_id[i] = el
        asset = root.find(f"{_NS}asset")
        self.scale = 1.0
        self.up = "Z_UP"
        if asset is not None:
            unit = asset.find(f"{_NS}unit")
            if unit is not None and unit.get("meter"):
                self.scale = float(unit.get("meter"))
            up = asset.find(f"{_NS}up_axis")
            if up is not None and up.text:
                self.up = up.text.strip()

    def ref(self, url: str):
        return self.by_id.get((url or "").lstrip("#"))

    def polys_of(self, node_el, depth: int = 0) -> int:
        cached = self._polys_cache.get(id(node_el))
        if cached is None:
            cached = self._polys_cache[id(node_el)] = _subtree_count(
                self, node_el, depth)
        return cached

    def zup_matrix(self) -> QMatrix4x4:
        """:meth:`to_zup` as a matrix (unit scale + axis permutation) — used
        to conjugate instance transforms into Z-up space."""
        s = self.scale
        if self.up == "Y_UP":
            return QMatrix4x4(s, 0, 0, 0,
                              0, 0, -s, 0,
                              0, s, 0, 0,
                              0, 0, 0, 1)
        if self.up == "X_UP":
            return QMatrix4x4(0, s, 0, 0,
                              s, 0, 0, 0,
                              0, 0, s, 0,
                              0, 0, 0, 1)
        m = QMatrix4x4()
        m.scale(s)
        return m

    def to_zup(self, p: QVector3D) -> QVector3D:
        s = self.scale
        if self.up == "Y_UP":
            return QVector3D(p.x() * s, -p.z() * s, p.y() * s)
        if self.up == "X_UP":
            return QVector3D(p.y() * s, p.x() * s, p.z() * s)
        return QVector3D(p.x() * s, p.y() * s, p.z() * s)


def _source_floats(dae: _Dae, source_el) -> tuple[list[float], int]:
    cached = dae._src_cache.get(id(source_el))
    if cached is not None:
        return cached
    arr = source_el.find(f"{_NS}float_array")
    data = _floats(arr.text if arr is not None else "")
    stride = 3
    tc = source_el.find(f"{_NS}technique_common")
    if tc is not None:
        acc = tc.find(f"{_NS}accessor")
        if acc is not None and acc.get("stride"):
            stride = int(acc.get("stride"))
    dae._src_cache[id(source_el)] = (data, stride)
    return data, stride


def _positions(dae: _Dae, mesh_el) -> list[QVector3D]:
    verts = mesh_el.find(f"{_NS}vertices")
    if verts is None:
        return []
    for inp in verts.findall(f"{_NS}input"):
        if inp.get("semantic") == "POSITION":
            src = dae.ref(inp.get("source"))
            if src is None:
                return []
            data, stride = _source_floats(dae, src)
            return [QVector3D(data[i], data[i + 1], data[i + 2])
                    for i in range(0, len(data) - 2, stride)]
    return []


def _prim_inputs(prim_el) -> tuple[int, int | None, str | None, int]:
    """``(vertex_offset, texcoord_offset, texcoord_source_url, stride)`` of
    the interleaved ``<p>`` stream (stride = max offset + 1)."""
    v_off, uv_off, uv_src, max_off = 0, None, None, 0
    for inp in prim_el.findall(f"{_NS}input"):
        off = int(inp.get("offset", "0"))
        max_off = max(max_off, off)
        sem = inp.get("semantic")
        if sem == "VERTEX":
            v_off = off
        elif sem == "TEXCOORD" and uv_off is None:
            uv_off = off
            uv_src = inp.get("source")
    return v_off, uv_off, uv_src, max_off + 1


def _prim_loops(prim_el, positions, uv_count: int = 0) -> list:
    """``(vertex_loop, uv_loop_or_None)`` pairs of one ``triangles`` /
    ``polylist`` / ``polygons`` primitive. UV loops are only produced when
    the primitive has a TEXCOORD input and ``uv_count`` > 0."""
    kind = _tag(prim_el)
    v_off, uv_off, _src, stride = _prim_inputs(prim_el)
    take_uv = uv_off is not None and uv_count > 0
    loops: list = []

    def emit(idx, start, nverts):
        vl = [idx[start + j * stride + v_off] for j in range(nverts)]
        ul = ([idx[start + j * stride + uv_off] for j in range(nverts)]
              if take_uv else None)
        loops.append((vl, ul))

    if kind == "triangles":
        p = prim_el.find(f"{_NS}p")
        idx = _ints(p.text if p is not None else "")
        verts_per = 3 * stride
        for k in range(0, len(idx) - verts_per + 1, verts_per):
            emit(idx, k, 3)
    elif kind == "polylist":
        vc = prim_el.find(f"{_NS}vcount")
        p = prim_el.find(f"{_NS}p")
        counts = _ints(vc.text if vc is not None else "")
        idx = _ints(p.text if p is not None else "")
        pos = 0
        for c in counts:
            if pos + c * stride <= len(idx):
                emit(idx, pos, c)
            pos += c * stride
    elif kind == "polygons":
        for p in prim_el.findall(f"{_NS}p"):
            idx = _ints(p.text)
            emit(idx, 0, len(idx) // stride)
    out = []
    for vl, ul in loops:
        if len(vl) < 3 or not all(0 <= i < len(positions) for i in vl):
            continue
        if ul is not None and not all(0 <= i < uv_count for i in ul):
            ul = None
        out.append((vl, ul))
    return out


def _image_color(dae: _Dae, image_el):
    """Representative RGB of a texture image: the average colour when the
    file exists next to the ``.dae`` (exporters often write a ``<name>/``
    folder), else a stable light tint derived from the path — either way,
    distinct materials get distinct colours, so the fusion pass keeps their
    boundaries (a plaza's curb lines must not melt into the paving)."""
    init = image_el.find(f"{_NS}init_from")
    ref = (init.text or "").strip() if init is not None else ""
    if not ref:
        return None
    cached = dae._img_colors.get(ref)
    if cached is not None:
        return cached
    color = None
    if dae.base_dir is not None:
        from urllib.parse import unquote
        candidate = Path(dae.base_dir) / unquote(ref)
        if candidate.is_file():
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QImage
            img = QImage(str(candidate))
            if not img.isNull():
                px = img.scaled(1, 1, Qt.IgnoreAspectRatio,
                                Qt.SmoothTransformation)
                c = px.pixelColor(0, 0)
                color = [c.redF(), c.greenF(), c.blueF()]
    if color is None:
        # Missing image: a deterministic light tint keeps the material
        # boundary visible without inventing loud colours.
        h = hash(ref)
        color = [0.78 + ((h >> s) & 15) / 100.0 for s in (0, 4, 8)]
    dae._img_colors[ref] = color
    return color


def _effect_diffuse(dae: _Dae, material_el):
    """``(rgb_or_None, image_el_or_None)`` of a material's diffuse: the
    literal colour, or the diffuse texture's ``<image>`` element."""
    ie = material_el.find(f"{_NS}instance_effect")
    effect = dae.ref(ie.get("url")) if ie is not None else None
    if effect is None:
        return None, None
    for shader in ("lambert", "phong", "blinn", "constant"):
        for el in effect.iter(f"{_NS}{shader}"):
            diffuse = el.find(f"{_NS}diffuse")
            if diffuse is None:
                continue
            col = diffuse.find(f"{_NS}color")
            if col is not None:
                vals = _floats(col.text)
                if len(vals) >= 3:
                    return vals[:3], None
            tex = diffuse.find(f"{_NS}texture")
            if tex is not None:
                # Chase sampler → surface → image (some exporters put
                # the image id directly in texture/@texture).
                sid = tex.get("texture") or ""
                target = dae.by_id.get(sid)
                if target is None or _tag(target) != "image":
                    for np_el in effect.iter(f"{_NS}newparam"):
                        if np_el.get("sid") != sid:
                            continue
                        s2d = np_el.find(f"{_NS}sampler2D")
                        src = (s2d.find(f"{_NS}source")
                               if s2d is not None else None)
                        surf_sid = (src.text or "").strip() if src is not None else ""
                        for np2 in effect.iter(f"{_NS}newparam"):
                            if np2.get("sid") != surf_sid:
                                continue
                            surf = np2.find(f"{_NS}surface")
                            init = (surf.find(f"{_NS}init_from")
                                    if surf is not None else None)
                            if init is not None and init.text:
                                target = dae.by_id.get(init.text.strip())
                        break
                if target is not None and _tag(target) == "image":
                    return None, target
    return None, None


def _image_file(dae: _Dae, image_el):
    """Absolute path of a texture image when it exists next to the ``.dae``
    (exporters often write a ``<name>/`` folder), else ``None``."""
    init = image_el.find(f"{_NS}init_from")
    ref = (init.text or "").strip() if init is not None else ""
    if not ref or dae.base_dir is None:
        return None
    from urllib.parse import unquote
    candidate = Path(dae.base_dir) / unquote(ref)
    return str(candidate) if candidate.is_file() else None


def _material_map(dae: _Dae, inst_geom_el) -> dict:
    """symbol → ``{"color": rgb_or_None, "path": image_path_or_None}`` for one
    ``instance_geometry``'s bound materials. ``path`` is set only when the
    image file actually exists on disk; the representative colour always
    rides along as the fallback (missing TEXCOORD, missing file)."""
    out: dict = {}
    for im in inst_geom_el.iter(f"{_NS}instance_material"):
        mat = dae.ref(im.get("target"))
        if mat is None:
            continue
        color, img = _effect_diffuse(dae, mat)
        path = _image_file(dae, img) if img is not None else None
        if color is None and img is not None:
            color = _image_color(dae, img)
        if color is not None or path is not None:
            out[im.get("symbol")] = {"color": color, "path": path}
    return out


def _face_attrs(zpts, color, tex):
    """Face attrs for one imported polygon: a real texture (world→UV affine
    map fitted from the file's own texture coordinates, evaluated in final
    Z-up world space) when the image exists, else the diffuse colour."""
    if tex is not None:
        path, uvs = tex
        from core.texture import fit_uv_affine
        m = fit_uv_affine(zpts, uvs)
        if m is not None:
            import math as _math
            glu = _math.hypot(m[0], m[1], m[2])
            glv = _math.hypot(m[4], m[5], m[6])
            # A mesh format paints a triangle, not a side: the material
            # shows from both sides (``back = True``), as every COLLADA
            # viewer draws it and as it drew here before faces had sides.
            return {"texture": {
                "path": path, "uvw": m,
                # Display/export tile size derived from the UV gradients.
                "sw": (1.0 / glu) if glu > 1e-9 else 1.0,
                "sh": (1.0 / glv) if glv > 1e-9 else 1.0,
            }, "back": True}
    if color is not None:
        return {"color": [float(c) for c in color[:3]], "back": True}
    return None


def _node_matrix(node_el) -> QMatrix4x4:
    m = QMatrix4x4()
    for el in node_el:
        t = _tag(el)
        if t == "matrix":
            vals = _floats(el.text)
            if len(vals) == 16:
                mm = QMatrix4x4(*vals)     # COLLADA matrices are row-major
                m = m * mm
        elif t == "translate":
            v = _floats(el.text)
            if len(v) >= 3:
                m.translate(v[0], v[1], v[2])
        elif t == "rotate":
            v = _floats(el.text)
            if len(v) >= 4:
                m.rotate(v[3], v[0], v[1], v[2])
        elif t == "scale":
            v = _floats(el.text)
            if len(v) >= 3:
                m.scale(v[0], v[1], v[2])
    return m


def _prim_uvs(dae: _Dae, prim_el) -> list:
    """The TEXCOORD source of a primitive as ``(s, t)`` tuples (empty when
    the primitive carries no texture coordinates)."""
    _v, uv_off, uv_src, _s = _prim_inputs(prim_el)
    if uv_off is None or not uv_src:
        return []
    src = dae.ref(uv_src)
    if src is None:
        return []
    cached = dae._uv_cache.get(id(src))
    if cached is None:
        data, stride = _source_floats(dae, src)
        stride = max(stride, 2)
        cached = dae._uv_cache[id(src)] = [
            (data[i], data[i + 1])
            for i in range(0, len(data) - stride + 1, stride)]
    return cached


def _collect_direct(dae: _Dae, node_el, m: QMatrix4x4, out: list) -> None:
    """The ``instance_geometry`` carried directly by ``node_el`` (no
    recursion), transformed by the already-composed matrix ``m``. Emits
    ``(points, color, tex)`` — ``tex`` is ``(image_path, uvs)`` when the
    material has an on-disk image and the primitive carries TEXCOORDs."""
    for el in node_el:
        if _tag(el) != "instance_geometry":
            continue
        geom = dae.ref(el.get("url"))
        if geom is None:
            continue
        mats = _material_map(dae, el)
        mesh_el = geom.find(f"{_NS}mesh")
        if mesh_el is None:
            continue
        positions = _positions(dae, mesh_el)
        world = [m.map(p) for p in positions]
        for prim in mesh_el:
            kind = _tag(prim)
            if kind not in ("triangles", "polylist", "polygons"):
                continue
            mat = mats.get(prim.get("material")) or {}
            color = mat.get("color")
            path = mat.get("path")
            uvpts = _prim_uvs(dae, prim) if path is not None else []
            for lp, ul in _prim_loops(prim, world, uv_count=len(uvpts)):
                tex = None
                if ul is not None and path is not None:
                    tex = (path, [uvpts[i] for i in ul])
                out.append(([world[i] for i in lp], color, tex))


def _prim_segments(prim_el, count: int) -> list:
    """Index pairs of one ``lines`` / ``linestrips`` primitive."""
    v_off, _uv, _src, stride = _prim_inputs(prim_el)
    pairs: list = []
    strips = ([prim_el.find(f"{_NS}p")] if _tag(prim_el) == "lines"
              else prim_el.findall(f"{_NS}p"))
    for p in strips:
        idx = _ints(p.text if p is not None else "")
        verts = [idx[k + v_off] for k in range(0, len(idx) - stride + 1,
                                               stride)]
        if _tag(prim_el) == "lines":
            pairs.extend(zip(verts[0::2], verts[1::2]))
        else:
            pairs.extend(zip(verts, verts[1:]))
    return [(a, b) for a, b in pairs
            if a != b and 0 <= a < count and 0 <= b < count]


def _collect_lines(dae: _Dae, node_el, xform: QMatrix4x4, out: list,
                   depth: int = 0) -> None:
    """The loose lines (``lines`` / ``linestrips``) of a node tree, as
    world ``(a, b)`` segments — a drawing's 2D lines, which the polygon
    walk never read, so they were dropped on import (#633)."""
    if depth > 32:
        return
    m = xform * _node_matrix(node_el)
    for el in node_el:
        t = _tag(el)
        if t == "instance_geometry":
            geom = dae.ref(el.get("url"))
            mesh_el = geom.find(f"{_NS}mesh") if geom is not None else None
            if mesh_el is None:
                continue
            prims = [pr for pr in mesh_el
                     if _tag(pr) in ("lines", "linestrips")]
            if not prims:
                continue
            world = [m.map(p) for p in _positions(dae, mesh_el)]
            for pr in prims:
                for a, b in _prim_segments(pr, len(world)):
                    out.append((world[a], world[b]))
        elif t == "node":
            _collect_lines(dae, el, m, out, depth)
        elif t == "instance_node":
            target = dae.ref(el.get("url"))
            if target is not None:
                _collect_lines(dae, target, m, out, depth + 1)


def _image_has_cutout(dae: _Dae, path: str) -> bool:
    """Whether the image carries REAL transparency (some pixels see-through)
    — the signature of a photo sprite (a person/animal/tree cutout PNG),
    versus an opaque photo panel (a sign or mural)."""
    cached = dae._img_alpha.get(path)
    if cached is not None:
        return cached
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    img = QImage(path)
    ok = False
    if not img.isNull() and img.hasAlphaChannel():
        small = img.scaled(32, 32, Qt.IgnoreAspectRatio,
                           Qt.FastTransformation)
        for yy in range(small.height()):
            for xx in range(small.width()):
                if small.pixelColor(xx, yy).alpha() < 32:
                    ok = True
                    break
            if ok:
                break
    dae._img_alpha[path] = ok
    return ok


def _looks_faceme(dae: _Dae, loops) -> bool:
    """Whether a component subtree reads as a face-me sprite: every
    polygon textured with the SAME image, all coplanar on ONE near-vertical
    plane (in final Z-up coordinates), and either a cut silhouette (more
    than 4 distinct corners) or a rectangle whose image has REAL
    transparency (2D people/animals/trees are alpha-cutout PNGs on a
    rectangle; an opaque photo panel — a sign, a mural — stays static).
    COLLADA drops the 'always face camera' flag, so these are the only
    signals left to keep sprites turning toward the camera."""
    from formats.fuse import _key, _newell
    if not 1 <= len(loops) <= 400:
        return False
    path = None
    n_ref = None
    corners: set = set()
    for pts, _color, tex in loops:
        if tex is None:
            return False
        if path is None:
            path = tex[0]
        elif tex[0] != path:
            return False
        zpts = [dae.to_zup(p) for p in pts]
        n = _newell(zpts)
        ln = n.length()
        if ln < 1e-12:
            continue
        n = n / ln
        if abs(n.z()) > 0.08:
            return False                     # not vertical
        if n_ref is None:
            n_ref = n
        elif abs(QVector3D.dotProduct(n, n_ref)) < 0.99:
            return False                     # not one plane
        for p in zpts:
            corners.add(_key(p))
    if n_ref is None:
        return False
    return len(corners) > 4 or _image_has_cutout(dae, path)


def _collect(dae: _Dae, node_el, xform: QMatrix4x4, out: list,
             depth: int = 0, faceme: list | None = None,
             instances: list | None = None) -> None:
    """Walk a node tree, baking transforms; instances recurse into
    ``library_nodes`` (components). With ``faceme`` given, a child
    component whose geometry is a face-me silhouette is pulled out into it
    as ``(name, loops)`` instead of flattening into the parent. With
    ``instances`` given, a reused component worth sharing is pulled out as
    ``(name, target_node, pre_xform, depth)`` instead of baking a copy."""
    if depth > 32:
        return                                     # cyclic instance guard
    m = xform * _node_matrix(node_el)
    _collect_direct(dae, node_el, m, out)
    for el in node_el:
        t = _tag(el)
        target = None
        d2 = depth
        if t == "node":
            target = el
        elif t == "instance_node":
            target = dae.ref(el.get("url"))
            d2 = depth + 1
            if target is not None and instances is not None:
                cnt = dae.inst_counts.get(el.get("url") or "", 1)
                polys = dae.polys_of(target, d2)
                if cnt >= 2 and polys >= _INST_MIN_POLYS \
                        and polys * (cnt - 1) >= _INST_MIN_SAVED:
                    instances.append((el.get("name") or _node_label(target),
                                      target, m, d2))
                    continue
        if target is None:
            continue
        if faceme is not None:
            sub: list = []
            _collect(dae, target, m, sub, d2, faceme, instances)
            if sub and _looks_faceme(dae, sub):
                faceme.append((el.get("name") or _node_label(target), sub))
            else:
                out.extend(sub)
        else:
            _collect(dae, target, m, out, d2, None, instances)


def _prim_count(prim) -> int:
    """Cheap polygon count of a primitive from its attributes (no ``<p>``
    parsing) — used only to decide where to split groups."""
    kind = _tag(prim)
    if kind in ("triangles", "polylist"):
        try:
            return int(prim.get("count", "0"))
        except ValueError:
            return 0
    if kind == "polygons":
        return len(prim.findall(f"{_NS}p"))
    return 0


def _direct_count(dae: _Dae, node_el) -> int:
    n = 0
    for el in node_el:
        if _tag(el) != "instance_geometry":
            continue
        geom = dae.ref(el.get("url"))
        mesh_el = geom.find(f"{_NS}mesh") if geom is not None else None
        if mesh_el is not None:
            n += sum(_prim_count(p) for p in mesh_el)
    return n


def _subtree_count(dae: _Dae, node_el, depth: int = 0) -> int:
    if depth > 32:
        return 0
    n = _direct_count(dae, node_el)
    for el in node_el:
        t = _tag(el)
        if t == "node":
            n += _subtree_count(dae, el, depth)
        elif t == "instance_node":
            target = dae.ref(el.get("url"))
            if target is not None:
                n += _subtree_count(dae, target, depth + 1)
    return n


_UNBUILT = object()   # sentinel: component prototype not built yet

# A reused component is pulled out as a shared instance only when sharing
# saves at least _INST_MIN_SAVED polygons ((copies - 1) x polys) AND the
# component itself is at least _INST_MIN_POLYS — a 1-face leaf repeated 900
# times would otherwise become 900 groups of per-group overhead; micro
# components stay flattened into their parent (and when the PARENT tree is
# itself a reused component, they are flattened into its prototype once).
_INST_MIN_SAVED = 400
_INST_MIN_POLYS = 60


# Reference imports mirror the source's group structure: every DAE assembly
# (group / component instance) can become its own Group, so the user selects,
# moves and edits a farola or a pérgola as a unit instead of one monolithic
# 160k-face blob (exploding THAT into the loose mesh melts the editing
# engine). The splitter is greedy — always split the largest splittable
# bucket — bounded by _MAX_GROUPS (per-group render/pick overhead is real)
# and _SPLIT_MIN (a small bench stays one piece even if internally grouped).
_MAX_GROUPS = 250
_SPLIT_MIN = 4000


def _node_label(node_el) -> str:
    return node_el.get("name") or node_el.get("id") or "node"


def _bucketize(dae: _Dae, top_nodes, faceme: list | None = None,
               instances: list | None = None) -> list:
    """Split the visual scene into ``(name, loops)`` buckets along the DAE
    node hierarchy (groups/components). Returns at most
    ``_MAX_GROUPS`` buckets, largest assemblies split first. Face-me
    silhouettes found anywhere in the tree land in ``faceme`` instead."""
    import heapq
    from itertools import count as _count
    tie = _count()
    # Heap entries: (-tris, tie, kind, node_el, xform, depth, name)
    # kind "subtree": xform is the PRE-entry matrix (node's own applies at
    # collect). kind "direct": xform is the composed matrix, no recursion.
    # via_inst marks entries that came through an instance_node — a target
    # reached that way ≥2 times is a component: its geometry is
    # built ONCE and every copy becomes a shared-prototype instance.
    heap = []
    for nd in top_nodes:
        n = _subtree_count(dae, nd)
        if n > 0:
            heapq.heappush(heap, (-n, next(tie), "subtree", nd,
                                  QMatrix4x4(), 0, _node_label(nd), False))
    final: list = []
    while heap and (len(final) + len(heap)) < _MAX_GROUPS:
        entry = heapq.heappop(heap)
        neg, _t, kind, node_el, xform, depth, name, _via = entry
        if -neg <= _SPLIT_MIN:
            heapq.heappush(heap, entry)
            break                      # largest left is small: all are done
        kids = [el for el in node_el if _tag(el) == "node"]
        insts = [el for el in node_el if _tag(el) == "instance_node"]
        if kind == "direct" or depth > 32 or (not kids and not insts):
            final.append(entry)        # big but unsplittable: keep as-is
            continue
        m = xform * _node_matrix(node_el)
        dg = _direct_count(dae, node_el)
        if dg > 0:
            heapq.heappush(heap, (-dg, next(tie), "direct", node_el, m,
                                  depth, name, False))
        for el in kids:
            n = _subtree_count(dae, el, depth)
            if n > 0:
                heapq.heappush(heap, (-n, next(tie), "subtree", el, m,
                                      depth, _node_label(el), False))
        for el in insts:
            target = dae.ref(el.get("url"))
            if target is None:
                continue
            n = _subtree_count(dae, target, depth + 1)
            if n > 0:
                nm = el.get("name") or _node_label(target)
                heapq.heappush(heap, (-n, next(tie), "subtree", target, m,
                                      depth + 1, nm, True))
    entries = sorted(final + heap)
    bucket_inst: dict = {}
    for _neg, _t, kind, node_el, _x, _d, _nm, via in entries:
        if via and kind == "subtree":
            bucket_inst[id(node_el)] = bucket_inst.get(id(node_el), 0) + 1
    buckets = []
    for neg, _t, kind, node_el, xform, depth, name, via in entries:
        if (instances is not None and via and kind == "subtree"
                and bucket_inst.get(id(node_el), 0) >= 2):
            instances.append((name, node_el, xform, depth))
            continue
        loops: list = []
        if kind == "direct":
            _collect_direct(dae, node_el, xform, loops)
        else:
            _collect(dae, node_el, xform, loops, depth, faceme, instances)
            if faceme is not None and loops and _looks_faceme(dae, loops):
                faceme.append((name, loops))   # the bucket itself is a sprite
                continue
        if loops:
            buckets.append((name, loops))
    return buckets


# ---- Survey coordinates: move a far-out file near the origin -------------------
#
# The importer composes node transforms and maps vertices in single precision
# (QMatrix4x4, QVector3D): a file at a UTM northing of 8,500,000 m has lost the
# metre before the first face is made. So, before anything else reads the
# document, this pass measures the scene in DOUBLE precision and — when it
# reaches past formats.recenter.RECENTER_BEYOND_M — rewrites the document
# itself so the offset is gone: the rest of the importer then reads a file
# that simply sits near the origin.
#
# The offset is taken out where the large numbers first appear going down
# the node tree: a node whose own translation is far out absorbs it (its
# transform is rewritten as one double-precision <matrix>); otherwise it is
# carried down, expressed in each node's frame, and finally subtracted from
# the vertex positions of the geometry that holds it. A geometry or a library
# node reached with two different shifts (one model placed twice) is copied
# for the second, so no copy moves the other.

_TRANSFORM_TAGS = ("matrix", "translate", "rotate", "scale", "lookat", "skew")


def _node_matrix64(node_el):
    """:func:`_node_matrix` in double precision (NumPy, row-major)."""
    import math

    import numpy as np
    m = np.eye(4)
    for el in node_el:
        t = _tag(el)
        if t == "matrix":
            vals = _floats(el.text)
            if len(vals) == 16:
                m = m @ np.array(vals, dtype=np.float64).reshape(4, 4)
        elif t == "translate":
            v = _floats(el.text)
            if len(v) >= 3:
                tm = np.eye(4)
                tm[:3, 3] = v[:3]
                m = m @ tm
        elif t == "rotate":
            v = _floats(el.text)
            if len(v) >= 4:
                axis = np.array(v[:3], dtype=np.float64)
                n = np.linalg.norm(axis)
                if n > 0:
                    x, y, z = axis / n
                    a = math.radians(v[3])
                    c, s = math.cos(a), math.sin(a)
                    rm = np.eye(4)
                    rm[:3, :3] = [
                        [c + x * x * (1 - c), x * y * (1 - c) - z * s,
                         x * z * (1 - c) + y * s],
                        [y * x * (1 - c) + z * s, c + y * y * (1 - c),
                         y * z * (1 - c) - x * s],
                        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s,
                         c + z * z * (1 - c)]]
                    m = m @ rm
        elif t == "scale":
            v = _floats(el.text)
            if len(v) >= 3:
                m = m @ np.diag([v[0], v[1], v[2], 1.0])
    return m


def _zup3(dae: _Dae):
    """:meth:`_Dae.to_zup` as a 3×3 double-precision matrix."""
    import numpy as np
    s = dae.scale
    if dae.up == "Y_UP":
        return np.array([[s, 0, 0], [0, 0, -s], [0, s, 0]], dtype=np.float64)
    if dae.up == "X_UP":
        return np.array([[0, s, 0], [s, 0, 0], [0, 0, s]], dtype=np.float64)
    return np.eye(3) * s


def _position_source(dae: _Dae, mesh_el):
    """The ``<source>`` holding a mesh's POSITION array, or ``None``."""
    verts = mesh_el.find(f"{_NS}vertices")
    if verts is None:
        return None
    for inp in verts.findall(f"{_NS}input"):
        if inp.get("semantic") == "POSITION":
            return dae.ref(inp.get("source"))
    return None


def _local_points(dae: _Dae, geom_el):
    """A geometry's vertex positions as an ``(n, 3)`` double array."""
    import numpy as np
    mesh_el = geom_el.find(f"{_NS}mesh")
    src = _position_source(dae, mesh_el) if mesh_el is not None else None
    if src is None:
        return np.zeros((0, 3))
    arr = src.find(f"{_NS}float_array")
    data = _floats(arr.text if arr is not None else "")
    stride = 3
    acc = src.find(f"{_NS}technique_common/{_NS}accessor")
    if acc is not None and acc.get("stride"):
        stride = max(int(acc.get("stride")), 3)
    n = len(data) // stride
    if n == 0:
        return np.zeros((0, 3))
    return np.array(data[:n * stride], dtype=np.float64).reshape(n, stride)[:, :3]


def _scene_box(dae: _Dae, top_nodes):
    """The scene's box in Z-up metres, double precision: every geometry's
    own box corners carried through its full chain of node transforms."""
    import numpy as np

    from formats.recenter import Bounds
    box = Bounds()
    zup = _zup3(dae)
    corner_cache: dict = {}

    def corners(geom_el):
        got = corner_cache.get(id(geom_el))
        if got is None:
            pts = _local_points(dae, geom_el)
            if len(pts):
                lo, hi = pts.min(axis=0), pts.max(axis=0)
                got = np.array([[x, y, z] for x in (lo[0], hi[0])
                                for y in (lo[1], hi[1])
                                for z in (lo[2], hi[2])])
            else:
                got = np.zeros((0, 3))
            corner_cache[id(geom_el)] = got
        return got

    def walk(node_el, parent, depth):
        if depth > 32:
            return
        m = parent @ _node_matrix64(node_el)
        for el in node_el:
            t = _tag(el)
            if t == "instance_geometry":
                geom = dae.ref(el.get("url"))
                if geom is None:
                    continue
                c = corners(geom)
                if len(c):
                    world = c @ m[:3, :3].T + m[:3, 3]
                    box.add_array(world @ zup.T)
            elif t == "node":
                walk(el, m, depth)
            elif t == "instance_node":
                target = dae.ref(el.get("url"))
                if target is not None:
                    walk(target, m, depth + 1)

    for nd in top_nodes:
        walk(nd, np.eye(4), 0)
    return box


def _fmt(values) -> str:
    return " ".join(repr(float(v)) for v in values)


def _clone(dae: _Dae, el, parent):
    """A deep copy of ``el`` appended to ``parent``, every ``id`` inside it
    renamed and every internal ``#reference`` to those ids rewired."""
    import copy
    dup = copy.deepcopy(el)
    dae._clones = getattr(dae, "_clones", 0) + 1
    suffix = f"-recentred{dae._clones}"
    renamed = {}
    for sub in dup.iter():
        old = sub.get("id")
        if old is not None:
            renamed[old] = old + suffix
            sub.set("id", old + suffix)
    for sub in dup.iter():
        for attr in ("source", "url", "target"):
            ref = sub.get(attr)
            if ref and ref.startswith("#") and ref[1:] in renamed:
                sub.set(attr, "#" + renamed[ref[1:]])
    parent.append(dup)
    for sub in dup.iter():
        if sub.get("id") is not None:
            dae.by_id[sub.get("id")] = sub
    return dup


def _set_node_matrix(node_el, m) -> None:
    """Replace a node's transform elements with one ``<matrix>``."""
    for el in [el for el in node_el if _tag(el) in _TRANSFORM_TAGS]:
        node_el.remove(el)
    mat = ET.Element(f"{_NS}matrix")
    mat.text = _fmt(m.reshape(-1))
    at = 1 if len(node_el) and _tag(node_el[0]) == "asset" else 0
    node_el.insert(at, mat)


def _shift_geometry(dae: _Dae, geom_el, r) -> None:
    """Subtract ``r`` (in the geometry's own frame) from its positions."""
    import numpy as np
    mesh_el = geom_el.find(f"{_NS}mesh")
    src = _position_source(dae, mesh_el) if mesh_el is not None else None
    arr = src.find(f"{_NS}float_array") if src is not None else None
    if arr is None:
        return
    data = np.array(_floats(arr.text), dtype=np.float64)
    stride = 3
    acc = src.find(f"{_NS}technique_common/{_NS}accessor")
    if acc is not None and acc.get("stride"):
        stride = max(int(acc.get("stride")), 3)
    n = len(data) // stride
    view = data[:n * stride].reshape(n, stride)
    view[:, :3] -= r
    arr.text = _fmt(data)
    dae._src_cache.pop(id(src), None)


def _recenter_dom(root):
    """Move a COLLADA document in survey coordinates near the origin, in
    place and in double precision (see the notes above). Returns the
    ``(x, y, z)`` offset in Z-up metres, or ``None`` when the file sits
    near enough the origin to be read as it is."""
    import numpy as np

    from formats.recenter import RECENTER_BEYOND_M
    dae = _Dae(root)
    top_nodes: list = []
    for vs in root.iter(f"{_NS}visual_scene"):
        top_nodes.extend(vs.findall(f"{_NS}node"))
    offset = _scene_box(dae, top_nodes).offset()
    if offset is None:
        return None
    zup = _zup3(dae)
    far = RECENTER_BEYOND_M / 2 / max(abs(dae.scale), 1e-12)
    # What each shared element was shifted by: a second, different shift
    # works on a copy.
    shifted: dict = {}

    def claim(el, r, parent):
        key = id(el)
        done = shifted.get(key)
        if done is None:
            shifted[key] = r
            return el
        if np.allclose(done, r, rtol=0.0, atol=1e-9):
            return None                      # already shifted by this much
        dup = _clone(dae, el, parent)
        shifted[id(dup)] = r
        return dup

    def apply(node_el, r, depth):
        """Take ``r`` (a vector in the node's PARENT frame) out of the
        node's subtree."""
        if depth > 32 or not np.any(r):
            return
        m = _node_matrix64(node_el)
        t = m[:3, 3]
        if np.max(np.abs(t)) > far:
            m[:3, 3] = t - r                 # the node itself is far out
            _set_node_matrix(node_el, m)
            return
        try:
            r_local = np.linalg.solve(m[:3, :3], r)
        except np.linalg.LinAlgError:
            return
        for el in node_el:
            tag = _tag(el)
            if tag == "instance_geometry":
                geom = dae.ref(el.get("url"))
                if geom is None:
                    continue
                own = claim(geom, r_local, _parent_of(geom))
                if own is None:
                    continue
                if own is not geom:
                    el.set("url", "#" + own.get("id"))
                _shift_geometry(dae, own, r_local)
            elif tag == "node":
                apply(el, r_local, depth)
            elif tag == "instance_node":
                target = dae.ref(el.get("url"))
                if target is None:
                    continue
                own = claim(target, r_local, _parent_of(target))
                if own is None:
                    continue
                if own is not target:
                    el.set("url", "#" + own.get("id"))
                apply(own, r_local, depth + 1)   # a library node: same rules

    parents = {id(c): p for p in root.iter() for c in p}

    def _parent_of(el):
        return parents.get(id(el), root)

    off_dae = np.linalg.solve(zup, np.array(offset, dtype=np.float64))
    for nd in top_nodes:
        apply(nd, off_dae, 0)
    return offset


def _adopt_geolocation(scene, root) -> None:
    """If the COLLADA carries ``<asset><coverage><geographic_location>`` and the
    scene has no datum yet, anchor the scene there — so a georeferenced model
    (e.g. one exported with its site) brings its location in, keeping sun/shadow
    studies meaningful. Never overrides a datum the user already set."""
    if getattr(scene, "georef", None) is not None:
        return
    asset = root.find(f"{_NS}asset")
    if asset is None:
        return
    geo = asset.find(f"{_NS}coverage/{_NS}geographic_location")
    if geo is None:
        return
    lat_el = geo.find(f"{_NS}latitude")
    lon_el = geo.find(f"{_NS}longitude")
    if lat_el is None or lon_el is None or not lat_el.text or not lon_el.text:
        return
    alt_el = geo.find(f"{_NS}altitude")
    try:
        lat = float(lat_el.text)
        lon = float(lon_el.text)
        alt = float(alt_el.text) if (alt_el is not None and alt_el.text) else 0.0
    except ValueError:
        return
    from georef.datum import SceneDatum
    scene.georef = SceneDatum(lat, lon, alt)


def _add_lines(mesh, dae: _Dae, lines: list) -> None:
    """Add the file's loose lines to ``mesh`` (Z-up). Only the small,
    editable import takes them: in the reference import (big files) an
    exporter that writes every edge as a line would double the model."""
    for a, b in lines:
        a, b = dae.to_zup(a), dae.to_zup(b)
        if (a - b).length() < 1e-6:
            continue
        try:
            mesh.add_edge(a, b)
        except Exception:  # noqa: BLE001 — skip a degenerate line
            continue


def load_dae(scene, path, progress=None):
    """See :func:`_load_dae_inner`. Wrapped to run with the generational GC off —
    mass vertex/edge/face construction ahead (see formats.skp.apply_payload);
    collection is merely deferred to the re-enable. Returns the survey offset
    the file was moved by (formats/recenter.py), or ``None``."""
    import gc
    _gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        return _load_dae_inner(scene, path, progress=progress)
    finally:
        if _gc_was_enabled:
            gc.enable()


def _load_dae_inner(scene, path, progress=None):
    """Add the geometry of a COLLADA file at ``path`` to ``scene``.

    Small models (≤ ``_MAX_FUSE_LOOPS`` polygons) go into the loose mesh and
    get the full editable pipeline — triangle fusion + outward orientation.
    Bigger models are *reference* geometry: they land in their own
    :class:`~core.group.Group` (isolated mesh), so the
    editing engine — snap, edge splitting, auto-face, heals — never scans
    their thousands of triangles while the user draws beside them. The
    caller wraps this for undo (``SnapshotImport`` handles the group).

    ``progress``, when given, is called as ``progress(fraction, text)`` at
    milestones so the UI can show an import progress bar."""
    from core.history import run_stitch
    from core.orient import orient_outward
    from core.topology import _key

    def tick(frac, text):
        if progress is not None:
            progress(frac, text)

    tick(0.02, "Reading file…")
    root = ET.parse(Path(path)).getroot()
    # Survey coordinates come out of the document first, in double
    # precision, before anything below turns them single precision.
    offset = _recenter_dom(root)
    dae = _Dae(root, base_dir=Path(path).parent)
    _adopt_geolocation(scene, root)
    top_nodes: list = []
    for vs in root.iter(f"{_NS}visual_scene"):
        top_nodes.extend(vs.findall(f"{_NS}node"))
    total_polys = sum(_subtree_count(dae, nd) for nd in top_nodes)

    if total_polys > _MAX_FUSE_LOOPS:
        # Reference import, structured: one Group per DAE assembly
        # (group / component instance) via the greedy splitter, so elements
        # stay individually selectable/movable/editable and the loose-mesh
        # engine never has to swallow the whole model.
        from core.group import Group
        from core.mesh import Mesh
        from formats.fuse import fuse_coplanar_loops, soften_smooth_edges
        tick(0.1, "Collecting geometry…")
        faceme: list = []
        instances: list = []
        buckets = _bucketize(dae, top_nodes, faceme, instances)
        if not buckets and not faceme and not instances:
            raise ValueError("No geometry found in the COLLADA file")

        def build_mesh(loops, local: bool = False):
            raw = []
            for loop, color, tex in loops:
                zpts = [dae.to_zup(p) for p in loop]
                raw.append((zpts, _face_attrs(zpts, color, tex)))
            target = Mesh()
            for item in fuse_coplanar_loops(raw):
                _add_fused(target, [item])
            soften_smooth_edges(target)
            return target

        zm = dae.zup_matrix()
        zm_inv = zm.inverted()[0]
        n_polys = sum(len(lp) for _n, lp in buckets)
        n_polys += sum(dae.polys_of(t[1], t[3]) for t in instances)
        n_polys += sum(len(lp) for _n, lp in faceme)
        total_loops = max(n_polys, 1)
        done = 0
        for name, loops in buckets:
            tick(0.15 + 0.8 * done / total_loops, f"Building {name}…")
            target = build_mesh(loops)
            if target.faces:
                scene.groups.append(Group(target, name=name))
            done += len(loops)
        # Components (a reused library node, found at any depth):
        # ONE prototype mesh in Z-up LOCAL coordinates, shared by every copy;
        # each copy is a Group with only a local->world matrix. A component
        # carrying a face-me sprite inside falls back to per-copy geometry
        # (the sprite must be extracted at its world spot).
        protos: dict = {}      # id(node_el) -> Mesh | None (None = fallback)
        for name, node_el, xform, depth in instances:
            tick(0.15 + 0.8 * done / total_loops, f"Building {name}…")
            done += dae.polys_of(node_el, depth)
            proto = protos.get(id(node_el), _UNBUILT)
            if proto is _UNBUILT:
                probe: list = []
                local_loops: list = []
                _collect(dae, node_el, QMatrix4x4(), local_loops,
                         depth, probe)
                if probe:
                    proto = None           # sprites inside: per-copy fallback
                else:
                    proto = build_mesh(local_loops)
                    if not proto.faces:
                        proto = None
                protos[id(node_el)] = proto
            if proto is not None:
                g = Group(proto, name=name)
                g.xform = zm * xform * zm_inv
                scene.groups.append(g)
                continue
            # Fallback: bake this copy in world coords (sprites and all).
            loops = []
            _collect(dae, node_el, xform, loops, depth, faceme)
            if loops and _looks_faceme(dae, loops):
                faceme.append((name, loops))
                continue
            target = build_mesh(loops)
            if target.faces:
                scene.groups.append(Group(target, name=name))
        for name, loops in faceme:
            tick(0.15 + 0.8 * done / total_loops, f"Building {name}…")
            target = build_mesh(loops)
            if target.faces:
                g = Group(target, name=name)
                g.billboard = "mesh"   # geometry turns toward the camera
                scene.groups.append(g)
            done += len(loops)
        scene.version += 1
        tick(1.0, "Done")
        return offset

    pending: list = []
    faceme: list = []
    lines: list = []
    for node in top_nodes:
        _collect_lines(dae, node, QMatrix4x4(), lines)
        sub: list = []
        _collect(dae, node, QMatrix4x4(), sub, faceme=faceme)
        if sub and _looks_faceme(dae, sub):
            faceme.append((_node_label(node), sub))   # top node IS a sprite
        else:
            pending.extend(sub)
    if faceme:
        # Face-me sprites become billboard groups even in a small import.
        from core.group import Group
        from core.mesh import Mesh
        from formats.fuse import fuse_coplanar_loops, soften_smooth_edges
        for name, loops in faceme:
            raw = []
            for loop, color, tex in loops:
                zpts = [dae.to_zup(p) for p in loop]
                raw.append((zpts, _face_attrs(zpts, color, tex)))
            target = Mesh()
            for item in fuse_coplanar_loops(raw):
                _add_fused(target, [item])
            soften_smooth_edges(target)
            if target.faces:
                g = Group(target, name=name)
                g.billboard = "mesh"
                scene.groups.append(g)
    if not pending and not faceme:
        # No visual scene (bare geometry library): import it un-instanced.
        for geom in root.iter(f"{_NS}geometry"):
            mesh_el = geom.find(f"{_NS}mesh")
            if mesh_el is None:
                continue
            positions = _positions(dae, mesh_el)
            for prim in mesh_el:
                if _tag(prim) in ("triangles", "polylist", "polygons"):
                    for lp, _ul in _prim_loops(prim, positions):
                        pending.append(([positions[i] for i in lp],
                                        None, None))
    if not pending:
        if faceme or lines:
            _add_lines(scene.mesh, dae, lines)
            scene.version += 1
            tick(1.0, "Done")
            return offset
        raise ValueError("No geometry found in the COLLADA file")

    if len(pending) > _MAX_FUSE_LOOPS:
        # Bare geometry library (no visual scene) too big for the editable
        # pipeline: import as ONE reference group.
        from core.group import Group
        from core.mesh import Mesh
        from formats.fuse import fuse_coplanar_loops, soften_smooth_edges
        tick(0.35, "Transforming…")
        raw = []
        for loop, color, tex in pending:
            zpts = [dae.to_zup(p) for p in loop]
            raw.append((zpts, _face_attrs(zpts, color, tex)))
        tick(0.5, "Merging coplanar faces…")
        fused = fuse_coplanar_loops(raw)
        target = Mesh()
        n = max(len(fused), 1)
        for k, item in enumerate(fused):
            if progress is not None and k % 8192 == 0:
                tick(0.6 + 0.3 * k / n, "Building the model…")
            _add_fused(target, [item])
        tick(0.92, "Smoothing edges…")
        soften_smooth_edges(target)
        scene.groups.append(Group(target, name=Path(path).stem))
        scene.version += 1
        tick(1.0, "Done")
        return offset

    target = scene.mesh
    seed: set = set()
    new_faces = set()
    for loop, color, tex in pending:
        pts = [dae.to_zup(p) for p in loop]
        try:
            face = target.add_face(pts)
        except Exception:  # noqa: BLE001 — skip a degenerate polygon
            continue
        new_faces.add(face)
        attrs = _face_attrs(pts, color, tex)
        if attrs:
            face.attrs.update(attrs)
        for p in pts:
            seed.add(_key(p))

    # Fuse the exported triangles back into clean polygons and give a closed
    # result a consistent outward orientation — same pipeline as OBJ import.
    # (Big models took the reference-group path above with the fast fusion.)
    run_stitch(scene.mesh, seed, new_faces, coplanar_merge=True)
    orient_outward(scene.mesh)
    # Loose lines after the faces: one lying on a face edge is that edge
    # (add_edge finds it), the rest stay as the drawing's own lines.
    _add_lines(scene.mesh, dae, lines)
    scene.version += 1
    return offset
