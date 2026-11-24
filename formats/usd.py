# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""USD export — the model as Universal Scene Description, ``.usda`` or ``.usdz``.

USD is the open scene format of film and visualisation pipelines; Blender,
usdview and many renderers and engines open it. The file keeps the model's
structure, as the GLB export does (:func:`formats.gltf._file_hierarchy`):

* one ``Xform`` per group and component, nested as in the model, with its
  transform, and the loose geometry as an ``Xform`` of its own;
* the copies of a component share ONE prototype: an ``instanceable`` prim
  referencing it, so the file does not grow with every copy;
* every mesh is triangles with per-corner normals (smooth across soft
  edges, flat elsewhere) and, on textured faces, ``primvars:st``; one
  ``GeomSubset`` per material binds its faces;
* every material is a ``UsdPreviewSurface`` under its own name, with its
  colour, opacity, finish and image (``UsdUVTexture``).

USD states its axes and units, so the model goes out as it is: ``upAxis =
"Z"``, ``metersPerUnit = 1`` — no change of axes as the glTF export needs.
The scene's geographic anchor rides along in the layer's
``customLayerData``, like the GLB's ``asset.extras``.

``.usda`` is the text layer, with the images copied to a folder beside it.
``.usdz`` is the single-file package: an uncompressed zip whose first file
is that layer, the images after it, every file's data starting on a 64-byte
boundary as the package format asks.

No external dependencies — both are written by hand.
"""
from __future__ import annotations

import json
import struct
import unicodedata
import zipfile
from pathlib import Path

from .meshexport import base_material_key, export_names, geolocation

#: Image types a USD package may carry as they are; any other picture is
#: converted to PNG.
_PACKAGE_IMAGES = (".png", ".jpg", ".jpeg")

#: Alignment of every file's data inside a ``.usdz``.
_USDZ_ALIGN = 64

#: The id of the zip "extra field" that pads a file's data to the boundary,
#: the one the reference implementation writes.
_USDZ_PAD_ID = 0x1986


# ---- small writers ------------------------------------------------------------

def _num(v) -> str:
    """A float for a ``float`` attribute: short, and never ``-0``."""
    v = float(v)
    if v == 0.0:
        return "0"
    return format(v, ".9g")


def _dbl(v) -> str:
    """A float for a ``double`` value: every digit it has."""
    v = float(v)
    if v == 0.0:
        return "0"
    return repr(v)


def _vec(t) -> str:
    return "(" + ", ".join(_num(c) for c in t) + ")"


def _string(s: str) -> str:
    """A USD string literal (the layer is UTF-8)."""
    return json.dumps(str(s), ensure_ascii=False)


def _ident(name: str, used: set) -> str:
    """``name`` as a USD prim name unique in ``used``: ASCII letters, digits
    and ``_``, never starting with a digit — accents dropped (``Muro_sur``
    from «Muro sur», ``Cocina`` from «Cocína»), ``_2`` on a repeat."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    base = "".join(c if (c.isascii() and c.isalnum()) else "_" for c in text)
    base = "_".join(p for p in base.split("_") if p) or "Prim"
    if base[0].isdigit():
        base = "_" + base
    ident, n = base, 2
    while ident in used:
        ident = f"{base}_{n}"
        n += 1
    used.add(ident)
    return ident


def _file_name(name: str, used: set) -> str:
    """A safe, unique file name for a picture inside the package or the
    images folder (it goes between ``@`` in the layer)."""
    p = Path(name)
    stem = _ident(p.stem, set()).strip("_") or "image"
    ext = p.suffix.lower() if p.suffix.lower() in _PACKAGE_IMAGES else ".png"
    out, n = f"{stem}{ext}", 2
    while out.lower() in used:
        out = f"{stem}_{n}{ext}"
        n += 1
    used.add(out.lower())
    return out


def _matrix(m) -> str:
    """A ``QMatrix4x4`` as a USD ``matrix4d``. Qt keeps it column-major for
    column vectors; USD writes rows for row vectors — the same sixteen
    numbers in the same order, four to a row."""
    d = [float(v) for v in m.data()]
    rows = [d[i:i + 4] for i in range(0, 16, 4)]
    return "( " + ", ".join(
        "(" + ", ".join(_dbl(v) for v in r) + ")" for r in rows) + " )"


class _Out:
    """An indented text buffer."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.depth = 0

    def __call__(self, text: str = "") -> None:
        self.lines.append(("    " * self.depth + text) if text else "")

    def open(self, head: str, meta: list[str] | None = None) -> None:
        if meta:
            self(head + " (")
            self.depth += 1
            for m in meta:
                self(m)
            self.depth -= 1
            self(")")
        else:
            self(head)
        self("{")
        self.depth += 1

    def close(self) -> None:
        self.depth -= 1
        self("}")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


# ---- images --------------------------------------------------------------------

def _image_bytes(src) -> tuple[bytes, bool] | None:
    """The picture at ``src`` as bytes a USD reader takes — PNG and JPEG as
    they are, anything else converted to PNG — and whether it was
    converted. ``None`` when it cannot be read."""
    from core.texture import is_image_bytes
    try:
        data = Path(src).read_bytes()
    except OSError:
        return None
    if not is_image_bytes(data):
        return None
    if Path(src).suffix.lower() in _PACKAGE_IMAGES:
        return data, False
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage
    img = QImage()
    if not img.loadFromData(data):
        return None
    out = QByteArray()
    buf = QBuffer(out)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(out), True


# ---- the layer -------------------------------------------------------------------

def _usage(tree) -> dict:
    """How many nodes draw each mesh key."""
    count: dict = {}
    stack = list(tree)
    while stack:
        part = stack.pop()
        if part["mesh"] is not None:
            count[part["mesh"]] = count.get(part["mesh"], 0) + 1
        stack.extend(part["children"])
    return count


def build_layer(scene, image_dir: str, only=None):
    """The scene as the text of a ``.usda`` layer and the pictures it uses:
    ``(text, {file name: bytes})``. ``image_dir`` is the folder the layer
    points its images at (relative to the layer). ``only`` as in
    :func:`formats.gltf.save_glb`."""
    from core.finish import PBR
    from core.texture import image_has_cutout
    from .gltf import _file_hierarchy

    materials, meshes, tree = _file_hierarchy(scene, only)
    names = export_names(materials)
    # One side of a two-sided face (#1270) keeps its material's name.
    for key in names:
        base = base_material_key(key)
        if base != key and base in names:
            names[key] = names[base]

    # ---- pictures: one file per source image -------------------------------
    images: dict[str, bytes] = {}
    image_for_src: dict[str, str | None] = {}
    used_files: set = set()
    for info in materials.values():
        if not info.get("map"):
            continue
        src = str(info["src"])
        if src in image_for_src:
            continue
        got = _image_bytes(src)
        if got is None:
            image_for_src[src] = None
            continue
        data, converted = got
        fname = _file_name(info["map"] if not converted
                           else Path(info["map"]).with_suffix(".png").name,
                           used_files)
        images[fname] = data
        image_for_src[src] = fname

    out = _Out()

    # ---- layer header --------------------------------------------------------
    out("#usda 1.0")
    out("(")
    out.depth += 1
    out("customLayerData = {")
    out.depth += 1
    out('string generator = "IngeTrazo"')
    geo = geolocation(scene)
    if geo is not None:
        out("dictionary ingetrazo_geolocation = {")
        out.depth += 1
        out(f"double alt = {_dbl(geo[2])}")
        out(f"double lat = {_dbl(geo[0])}")
        out(f"double lon = {_dbl(geo[1])}")
        out.depth -= 1
        out("}")
    out.depth -= 1
    out("}")
    out('defaultPrim = "Model"')
    out("metersPerUnit = 1")
    out('upAxis = "Z"')
    out.depth -= 1
    out(")")
    out()

    # ---- materials -------------------------------------------------------------
    def material(key, path: str, used: set) -> str:
        """Write one material under ``path``; return its prim path."""
        info = materials[key]
        ident = _ident(names[key], used)
        mpath = f"{path}/{ident}"
        # The name as the document writes it, when the prim's had to change.
        shown = (info.get("mat") or "").strip() or names[key]
        meta = []
        items = []
        if info.get("finish"):
            items.append(f"string ingetrazo_finish = "
                         f"{_string(info['finish'])}")
        if shown != ident:
            items.append(f"string ingetrazo_name = {_string(shown)}")
        if items:
            meta.append("customData = { " + "; ".join(items) + " }")
        out.open(f'def Material "{ident}"', meta)
        out(f"token outputs:surface.connect = "
            f"<{mpath}/PreviewSurface.outputs:surface>")
        out()
        image = image_for_src.get(str(info["src"])) if info.get("map") else None
        cutout = bool(image) and image_has_cutout(str(info["src"]))
        out.open('def Shader "PreviewSurface"')
        out('uniform token info:id = "UsdPreviewSurface"')
        if image:
            out(f"color3f inputs:diffuseColor.connect = "
                f"<{mpath}/Image.outputs:rgb>")
        elif info.get("map"):
            out("color3f inputs:diffuseColor = (1, 1, 1)")
        else:
            out(f"color3f inputs:diffuseColor = "
                f"{_vec(tuple(info['color'])[:3])}")
        rough, metal, ior = 1.0, 0.0, 1.5
        if info.get("finish"):
            rough, metal, _trans, ior = PBR[info["finish"]]
        out(f"float inputs:roughness = {_num(rough)}")
        out(f"float inputs:metallic = {_num(metal)}")
        out(f"float inputs:ior = {_num(ior)}")
        op = info.get("opacity")
        if op is not None:                    # glass and the like
            out(f"float inputs:opacity = {_num(op)}")
        elif cutout:                          # leaves, face-me figures
            out(f"float inputs:opacity.connect = <{mpath}/Image.outputs:a>")
            out("float inputs:opacityThreshold = 0.5")
        out("token outputs:surface")
        out.close()
        if image:
            out()
            out.open('def Shader "TexCoords"')
            out('uniform token info:id = "UsdPrimvarReader_float2"')
            out('string inputs:varname = "st"')
            out("float2 outputs:result")
            out.close()
            out()
            out.open('def Shader "Image"')
            out('uniform token info:id = "UsdUVTexture"')
            out(f"asset inputs:file = @{image_dir}/{image}@")
            out(f"float2 inputs:st.connect = <{mpath}/TexCoords.outputs:result>")
            out('token inputs:sourceColorSpace = "sRGB"')
            out('token inputs:wrapS = "repeat"')
            out('token inputs:wrapT = "repeat"')
            out("float3 outputs:rgb")
            out("float outputs:a")
            out.close()
        out.close()
        return mpath

    def materials_scope(keys, path: str) -> dict:
        """A ``Materials`` scope under ``path`` with ``keys``; returns key →
        material path."""
        if not keys:
            return {}
        scope = f"{path}/Materials"
        out.open('def Scope "Materials"')
        used: set = set()
        paths = {}
        for i, key in enumerate(keys):
            if i:
                out()
            paths[key] = material(key, scope, used)
        out.close()
        return paths

    # ---- meshes ----------------------------------------------------------------
    def mesh_prims(source: dict, path: str, mat_path: dict, used: set) -> None:
        """``source`` (material key → triangles) as Mesh prims under
        ``path``: one double-sided, one single-sided for the sides of a
        face painted differently on each side."""
        double = [k for k in source if not materials[k].get("single_sided")]
        single = [k for k in source if materials[k].get("single_sided")]
        for keys, sided, name in ((double, True, "Mesh"),
                                  (single, False, "Mesh_one_sided")):
            keys = [k for k in keys if source[k]]
            if keys:
                one_mesh(source, keys, sided, _ident(name, used), path,
                         mat_path)

    def one_mesh(source, keys, double_sided, ident, path, mat_path) -> None:
        points: list = []
        pindex: dict = {}
        indices: list[int] = []
        normals: list = []
        sts: list = []
        textured = False
        faces_of: dict = {}
        face = 0
        for key in keys:
            for _flat, corners in source[key]:
                for pos, uv, normal in corners:
                    p = (pos.x(), pos.y(), pos.z())
                    pk = (round(p[0], 6), round(p[1], 6), round(p[2], 6))
                    i = pindex.get(pk)
                    if i is None:
                        i = pindex[pk] = len(points)
                        points.append(p)
                    indices.append(i)
                    normals.append((normal.x(), normal.y(), normal.z()))
                    if uv is not None:
                        textured = True
                        sts.append((uv[0], uv[1]))
                    else:
                        sts.append((0.0, 0.0))
                faces_of.setdefault(key, []).append(face)
                face += 1
        mpath = f"{path}/{ident}"
        out.open(f'def Mesh "{ident}"',
                 ['prepend apiSchemas = ["MaterialBindingAPI"]'])
        lo = [min(p[k] for p in points) for k in range(3)]
        hi = [max(p[k] for p in points) for k in range(3)]
        out(f"float3[] extent = [{_vec(lo)}, {_vec(hi)}]")
        out(f"int[] faceVertexCounts = [{', '.join(['3'] * face)}]")
        out(f"int[] faceVertexIndices = [{', '.join(map(str, indices))}]")
        out(f"normal3f[] normals = [{', '.join(_vec(n) for n in normals)}] ("
            '\n' + "    " * (out.depth + 1) + 'interpolation = "faceVarying"'
            '\n' + "    " * out.depth + ")")
        out(f"point3f[] points = [{', '.join(_vec(p) for p in points)}]")
        if textured:
            out(f"texCoord2f[] primvars:st = "
                f"[{', '.join(_vec(t) for t in sts)}] ("
                '\n' + "    " * (out.depth + 1) +
                'interpolation = "faceVarying"'
                '\n' + "    " * out.depth + ")")
        out(f"uniform bool doubleSided = {1 if double_sided else 0}")
        out('uniform token orientation = "rightHanded"')
        out('uniform token subdivisionScheme = "none"')
        if len(keys) == 1:
            out(f"rel material:binding = <{mat_path[keys[0]]}>")
        else:
            out('uniform token subsetFamily:materialBind:familyType = '
                '"nonOverlapping"')
            used: set = set()
            for key in keys:
                out()
                out.open(f'def GeomSubset "{_ident(names[key], used)}"',
                         ['prepend apiSchemas = ["MaterialBindingAPI"]'])
                out('uniform token elementType = "face"')
                out('uniform token familyName = "materialBind"')
                out(f"int[] indices = [{', '.join(map(str, faces_of[key]))}]")
                out(f"rel material:binding = <{mat_path[key]}>")
                out.close()
        out.close()

    # ---- the tree -------------------------------------------------------------
    usage = _usage(tree)
    shared = [k for k, n in usage.items() if n > 1 and meshes.get(k)]
    proto_of: dict = {}
    proto_used: set = set()
    for k in shared:
        proto_of[k] = "/Prototypes/" + _ident(
            "Proto_" + _ident(_proto_name(k, tree), set()), proto_used)

    # Materials of the meshes written in place, under /Model/Materials.
    model_keys: list = []
    stack = list(tree)
    while stack:
        part = stack.pop(0)
        key = part["mesh"]
        if key is not None and key not in proto_of:
            model_keys += [k for k in meshes.get(key, ()) if k not in model_keys]
        stack.extend(part["children"])

    out.open('def Xform "Model"', ['kind = "assembly"'])
    model_mats = materials_scope(model_keys, "/Model")

    def node(part, path: str, used: set) -> None:
        ident = _ident(part["name"], used)
        npath = f"{path}/{ident}"
        meta = []
        items = []
        if part["name"] != ident:
            items.append(f"string ingetrazo_name = {_string(part['name'])}")
        faceme = (part.get("extras") or {}).get("ingetrazo_faceme")
        if faceme:
            items.append("double[] ingetrazo_faceme = ["
                         + ", ".join(_dbl(v) for v in faceme) + "]")
        if items:
            meta.append("customData = { " + "; ".join(items) + " }")
        out()
        out.open(f'def Xform "{ident}"', meta)
        m = part.get("matrix")
        if m is not None and not m.isIdentity():
            out(f"matrix4d xformOp:transform = {_matrix(m)}")
            out('uniform token[] xformOpOrder = ["xformOp:transform"]')
        kids: set = set()
        key = part["mesh"]
        if key is not None and meshes.get(key):
            if key in proto_of:
                out.open(f'def "{_ident("Geometry", kids)}"',
                         ["instanceable = true",
                          f"prepend references = <{proto_of[key]}>"])
                out.close()
            else:
                mesh_prims(meshes[key], npath, model_mats, kids)
        for child in part["children"]:
            node(child, npath, kids)
        out.close()

    top: set = {"Materials"}
    for part in tree:
        node(part, "/Model", top)
    out.close()

    # ---- prototypes: each with the materials it wears ------------------------
    if shared:
        out()
        out.open('class "Prototypes"')
        for i, key in enumerate(shared):
            if i:
                out()
            ppath = proto_of[key]
            out.open(f'def Xform "{ppath.rsplit("/", 1)[1]}"')
            mats = materials_scope(list(meshes[key]), ppath)
            out()
            mesh_prims(meshes[key], ppath, mats, {"Materials"})
            out.close()
        out.close()
    return out.text(), images


def _proto_name(key, tree) -> str:
    """The name of the first node that draws mesh ``key``."""
    stack = list(tree)
    while stack:
        part = stack.pop(0)
        if part["mesh"] == key:
            return part["name"]
        stack.extend(part["children"])
    return "Mesh"


# ---- files -----------------------------------------------------------------------

def save_usda(scene, path, only=None) -> None:
    """Write the scene as a text USD layer ``path`` (.usda); its pictures go
    to the folder ``<name>_textures`` beside it — send both, or use
    :func:`save_usdz`."""
    path = Path(path)
    folder = f"{path.stem}_textures"
    text, images = build_layer(scene, f"./{folder}", only)
    if images:
        (path.parent / folder).mkdir(parents=True, exist_ok=True)
        for name, data in images.items():
            (path.parent / folder / name).write_bytes(data)
    path.write_text(text, encoding="utf-8", newline="\n")


def save_usdz(scene, path, only=None) -> None:
    """Write the scene as a USD package ``path`` (.usdz): one file with the
    layer first and its pictures after it, stored uncompressed, every
    file's data on a 64-byte boundary."""
    path = Path(path)
    text, images = build_layer(scene, "textures", only)
    layer = _ident(path.stem, set()) + ".usda"
    entries = [(layer, text.encode("utf-8"))]
    entries += [(f"textures/{n}", d) for n, d in images.items()]
    write_package(path, entries)


def write_package(path, entries) -> None:
    """``entries`` (``(name, bytes)``, the layer first) as a ``.usdz``: an
    uncompressed zip whose every file's data starts on a multiple of 64
    bytes — padded through the local header's extra field."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            offset = zf.fp.tell()
            start = offset + 30 + len(name.encode("utf-8"))
            pad = (-(start + 4)) % _USDZ_ALIGN
            info.extra = struct.pack("<HH", _USDZ_PAD_ID, pad) + b"\0" * pad
            zf.writestr(info, data)
