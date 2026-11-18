# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""``.igmat`` — material files: materials kept apart from any document (#1427).

The point is to set a material up once (an MDF panel with its name, picture
and real tile size) and use it in every project, the way SketchUp's ``.skm``
files work. A file holds one material or several, so one ``.igmat`` can also
be a small library.

The shape is the ``.igz`` container's, reduced to what a material needs::

    material.json   {"format": 1, "materials": [Material.to_dict(), ...]}
    textures/       the images, "<hash>-<name>", stored as-is

The texture entries are rewritten ``"path"`` → ``"embed"`` (and a tinted
texture's untinted source ``"base"`` → ``"base_embed"``) by the same helpers
the ``.igz`` writer uses, so a material leaves and comes back exactly as it
is in a document. Reading extracts each image into the app's texture cache
and points the entry back at that file.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from core.materials import Material

EXTENSION = ".igmat"
FORMAT = 1                      # the newest this build reads
_DOC_ENTRY = "material.json"
#: Larger than any real material description: a file claiming more is not
#: one, and is refused before it is read into memory.
_DOC_MAX = 8 << 20


class MaterialFileError(ValueError):
    """The file is not an ``.igmat`` this build can read."""


def save_materials(path, materials) -> dict:
    """Write ``materials`` (an iterable of :class:`Material`) to ``path``.

    Returns ``{"embedded", "missing"}`` like ``igz.save_scene``: images
    packed, and images that could not be read (those keep their ``"path"``,
    which another machine will not find — the material then paints
    untextured there)."""
    from formats.igz import _ZIP_EPOCH, _pack_textures, _write_atomic

    payload = {"format": FORMAT,
               "materials": [m.to_dict() for m in materials]}
    blobs, missing = _pack_textures(payload)
    doc = json.dumps(payload, ensure_ascii=False, indent=1)

    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo(_DOC_ENTRY, date_time=_ZIP_EPOCH)
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, doc)
        for member in sorted(blobs):
            info = zipfile.ZipInfo(member, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_STORED
            zf.writestr(info, blobs[member])
    _write_atomic(Path(path), buf.getvalue())
    return {"embedded": len(blobs), "missing": missing}


def load_materials(path) -> list[Material]:
    """The materials in the ``.igmat`` at ``path``, their images extracted
    into the texture cache. An image the file lost leaves its material
    without a picture rather than failing the read.

    Raises :class:`MaterialFileError` for a file that is not one (not a ZIP,
    no ``material.json``, a newer format) and ``OSError`` when it cannot be
    read at all."""
    from formats.igz import _unpack_textures

    try:
        with zipfile.ZipFile(Path(path)) as zf:
            try:
                info = zf.getinfo(_DOC_ENTRY)
            except KeyError:
                raise MaterialFileError("no material.json") from None
            if info.file_size > _DOC_MAX:
                raise MaterialFileError("material.json is too large")
            try:
                payload = json.loads(zf.read(info).decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise MaterialFileError(f"bad material.json: {exc}") from None
            if not isinstance(payload, dict):
                raise MaterialFileError("material.json is not an object")
            fmt = payload.get("format")
            if not isinstance(fmt, int) or fmt > FORMAT:
                raise MaterialFileError(f"unsupported format {fmt!r}")
            raw = payload.get("materials")
            if not isinstance(raw, list):
                raise MaterialFileError("no materials list")
            raw = [r for r in raw if isinstance(r, dict)
                   and isinstance(r.get("name"), str) and r["name"].strip()]
            _unpack_textures(raw, zf)
    except zipfile.BadZipFile:
        raise MaterialFileError("not a ZIP file") from None
    out = []
    for r in raw:
        if r.get("texture") is not None and not r["texture"].get("path"):
            # Its image was missing from the file: keep the rest of it.
            r = {k: v for k, v in r.items() if k != "texture"}
        try:
            mat = Material.from_dict(r)
        except (TypeError, ValueError):
            continue
        if mat.color is None and mat.texture is None:
            continue                    # nothing left to paint with
        mat.name = mat.name.strip()
        out.append(mat)
    return out


def file_stem(name: str) -> str:
    """A file name (without extension) for a material called ``name``:
    letters, digits, spaces and ``._-`` kept, clipped to 80 characters."""
    safe = "".join(c for c in (name or "") if c.isalnum() or c in " ._-")
    return safe.strip(" .")[:80].rstrip(" .") or "Material"


def user_materials_dir() -> Path:
    """*My materials*: the user's own ``.igmat`` files, beside the rest of
    the app's data, shown in the Materials palette in every project."""
    from core.autosave import _app_data_base
    return _app_data_base() / "materials"


def user_material_files() -> list[Path]:
    """The ``.igmat`` files in :func:`user_materials_dir`, by name."""
    d = user_materials_dir()
    try:
        return sorted((p for p in d.iterdir()
                       if p.suffix.lower() == EXTENSION and p.is_file()),
                      key=lambda p: p.name.lower())
    except OSError:
        return []


def add_user_material(mat: Material) -> Path:
    """Save ``mat`` into *My materials* and return its file. The file is
    named after the material; a name that already has a file replaces it
    (saving a material again after changing it is the common case)."""
    d = user_materials_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{file_stem(mat.name)}{EXTENSION}"
    save_materials(path, [mat])
    return path
