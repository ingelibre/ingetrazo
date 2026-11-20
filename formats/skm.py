# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""``.skm`` material files, read only (#1482).

Many people keep folders of ``.skm`` materials, their own or downloaded;
this turns one into a :class:`core.materials.Material`, so the Materials
palette's *Import…* takes it like an ``.igmat`` (#1427).

The format is not documented. What this reads is what real ``.skm``
files, saved by the program that defines it and by third-party tools,
show:

- a ZIP holding ``document.xml`` (the material), ``documentProperties.xml``,
  ``references.xml``, ``doc_thumbnail.png`` and, for a textured material,
  the image under ``ref/``;
- in ``document.xml``, ``<mat:material name type colorRed colorGreen
  colorBlue colorizeType trans useTrans hasTexture>``, where ``type`` is
  0 colour only, 1 texture, 2 colourized texture; ``colorizeType`` 0/1 is
  shift/tint, as in the ``.skp`` format; ``trans`` runs from 0 (opaque) to
  1 (fully transparent) and counts only with ``useTrans="1"``;
- inside it, ``<mat:texture textureFilename xScale yScale avgColor>`` with
  the tile size in inches, and ``<mat:images><mat:image path=…>`` naming
  the image under ``ref/``.

Element names are matched without their namespace, and a missing piece
leaves what it carries out (no picture → the colour; no size → 1 m) rather
than failing the import.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from core.materials import Material
from formats.igmat import MaterialFileError

EXTENSION = ".skm"
_DOC_ENTRY = "document.xml"
_REF_PREFIX = "ref/"
#: Larger than any real material description: refused before it is read.
_DOC_MAX = 8 << 20
#: An image larger than this is not a material texture.
_IMAGE_MAX = 256 << 20
_INCH = 0.0254


class SkmError(MaterialFileError):
    """The file is not an ``.skm`` this build can read."""


def _local(tag: str) -> str:
    """``{namespace}name`` → ``name``."""
    return tag.rsplit("}", 1)[-1]


def _find(node, name: str):
    """The first descendant (or *node* itself) whose local name is *name*."""
    for el in node.iter():
        if _local(el.tag) == name:
            return el
    return None


def _attr(el, name: str, default=None):
    """An attribute by its local name (some writers prefix them)."""
    for key, value in el.attrib.items():
        if _local(key) == name:
            return value
    return default


def _number(el, name: str, default=None):
    try:
        return float(_attr(el, name))
    except (TypeError, ValueError):
        return default


def _image_member(zf: zipfile.ZipFile, texture) -> str | None:
    """The archive member holding the texture image: the ``mat:image``
    path under ``ref/``, else ``textureFilename`` there, else the only
    image under ``ref/``."""
    names = set(zf.namelist())
    wanted = []
    if texture is not None:
        image = _find(texture, "image")
        if image is not None:
            wanted.append(_attr(image, "path"))
        wanted.append(_attr(texture, "textureFilename"))
    for name in wanted:
        if not name:
            continue
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
        for member in (_REF_PREFIX + name, name):
            if member in names:
                return member
    refs = [n for n in names if n.startswith(_REF_PREFIX)
            and not n.endswith("/")]
    return refs[0] if len(refs) == 1 else None


def load_skm(path) -> list[Material]:
    """The material in the ``.skm`` at ``path`` (a list of one, like
    :func:`formats.igmat.load_materials`), its image extracted into the
    texture cache. Raises :class:`SkmError` for a file that is not one and
    ``OSError`` when it cannot be read."""
    from xml.etree import ElementTree

    from core.texture import cache_image, tinted_texture

    path = Path(path)
    try:
        with zipfile.ZipFile(path) as zf:
            try:
                info = zf.getinfo(_DOC_ENTRY)
            except KeyError:
                raise SkmError("no document.xml") from None
            if info.file_size > _DOC_MAX:
                raise SkmError("document.xml is too large")
            data = zf.read(info)
            # No DTD in a material: refusing one keeps entity expansion
            # (a "billion laughs" file) out of the parser altogether.
            if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
                raise SkmError("document.xml declares a DTD")
            try:
                root = ElementTree.fromstring(data)
            except ElementTree.ParseError as exc:
                raise SkmError(f"bad document.xml: {exc}") from None
            mat = _find(root, "material")
            if mat is None:
                raise SkmError("no material in document.xml")

            name = (_attr(mat, "name") or "").strip() or path.stem
            kind = int(_number(mat, "type", 0) or 0)
            rgb = tuple(max(0.0, min(255.0, _number(mat, c, 128.0))) / 255.0
                        for c in ("colorRed", "colorGreen", "colorBlue"))
            opacity = None
            if _attr(mat, "useTrans") in ("1", "true"):
                trans = _number(mat, "trans", 0.0) or 0.0
                if trans > 0.0:
                    opacity = max(0.0, min(1.0, 1.0 - trans))

            texture = None
            tex_el = _find(mat, "texture")
            has_texture = (_attr(mat, "hasTexture") in ("1", "true")
                           or kind in (1, 2) or tex_el is not None)
            member = _image_member(zf, tex_el) if has_texture else None
            if member is not None:
                if zf.getinfo(member).file_size > _IMAGE_MAX:
                    raise SkmError("texture image is too large")
                image = zf.read(member)
                try:
                    cached = cache_image(image, member.rsplit("/", 1)[-1],
                                         "skm")
                except OSError:
                    cached = None
                if cached is not None:
                    sw = _number(tex_el, "xScale") if tex_el is not None \
                        else None
                    sh = _number(tex_el, "yScale") if tex_el is not None \
                        else None
                    sw = sw * _INCH if sw and sw > 0 else None
                    sh = sh * _INCH if sh and sh > 0 else None
                    sw = sw or sh or 1.0
                    sh = sh or sw
                    texture = {"path": str(cached), "sw": sw, "sh": sh,
                               "rot": 0.0}
                    if kind == 2:
                        # A colourized texture: the stored image is the
                        # original, to be re-tinted toward the colour.
                        ctype = int(_number(mat, "colorizeType", 0) or 0)
                        texture = tinted_texture(texture, rgb,
                                                 1 if ctype == 1 else 0)
    except zipfile.BadZipFile:
        raise SkmError("not a ZIP file") from None
    return [Material(name, color=None if texture else rgb, texture=texture,
                     opacity=opacity)]
