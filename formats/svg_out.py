# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SVG writer for view exports: the hidden-line view as a vector drawing
to finish in an illustration program.

It takes the very groups the DXF export writes — ``(layer, segments[,
linetype[, rgb[, weight_mm]]])`` with the segments ``(x0, y0, x1, y1)`` in
metres — and writes one SVG layer per group (a top-level ``<g>`` named
after it, tagged as a layer the way the free vector editors read it), its
lines in the layer's colour, line type and pen. The drawing goes out at
paper size: ``scale_n`` is the 1:N the metres are drawn at, in
millimetres.

Segments that continue one another (the pieces of one edge, the facets of
an arc) are chained into one path; a corner or a junction ends it, so each
edge comes apart on its own.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import quoteattr

#: Dash patterns in paper millimetres, by the DXF line type names the
#: groups carry (the hidden lines' DASHED matches the sheets' 1.5 / 0.8).
_DASHES = {
    "DASHED": "1.5 0.8",
    "HIDDEN": "0.8 0.4",
    "DASHEDX2": "3 1.5",
    "DOT": "0 0.6",
    "DASHDOT": "1.5 0.6 0 0.6",
    "DIVIDE": "1.5 0.6 0 0.6 0 0.6",
    "CENTER": "4 0.8 0.8 0.8",
    "PHANTOM": "4 0.8 0.8 0.8 0.8 0.8",
    "BORDER": "1.5 0.6 1.5 0.6 0 0.6",
}

#: The pen of a group by its line class when it brings none of its own:
#: the vector style's cut / profile / edge weights, in paper millimetres.
DEFAULT_PENS = {"cut": 0.5, "profile": 0.35, "edge": 0.18}

#: Paper margin around the drawing, in millimetres.
_MARGIN = 10.0

_INKSCAPE = "http://www.inkscape.org/namespaces/inkscape"


def _line_class(name: str) -> str:
    upper = name.upper()
    if upper.endswith("-CORTE"):
        return "cut"
    if upper.endswith("-PERFIL"):
        return "profile"
    return "edge"


def _hex(rgb) -> str:
    if rgb is None:
        return "#000000"
    r, g, b = (max(0, min(255, round(float(c) * 255.0))) for c in rgb[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def _xml_id(name: str, taken: set) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]", "_", name.strip()) or "capa"
    if not re.match(r"[A-Za-z_]", base):
        base = "_" + base
    out, i = base, 2
    while out in taken:
        out, i = f"{base}_{i}", i + 1
    taken.add(out)
    return out


#: The sharpest turn two segments may make and still be one line: the
#: pieces of one edge the hidden-line pass split, and the facets of an arc
#: or a circle. A sharper bend is a corner — two lines.
MAX_TURN_DEG = 30.0


def chain_segments(segments, tol: float = 1e-6) -> list:
    """Join the segments that continue one another into polylines: only
    where exactly two meet and the line turns no more than
    :data:`MAX_TURN_DEG`. A corner or a junction of three or more ends the
    line there, so every edge of a drawing comes apart on its own in an
    illustration program — chaining round corners welded a wall's outline
    and the lines branching off it into one stroke.

    Returns a list of ``(points, closed)`` with ``points`` a list of
    (x, y); a chain that comes back to its start (a circle) is ``closed``
    and does not repeat it. Ends closer than ``tol`` count as the same
    point."""
    import math
    segs = [tuple(map(float, s)) for s in segments]
    if not segs:
        return []
    inv = 1.0 / tol
    cos_max = math.cos(math.radians(MAX_TURN_DEG))

    def key(x, y):
        return (round(x * inv), round(y * inv))

    at = defaultdict(list)
    for i, (x0, y0, x1, y1) in enumerate(segs):
        if key(x0, y0) == key(x1, y1):
            continue                          # a dot: nothing to draw
        at[key(x0, y0)].append(i)
        at[key(x1, y1)].append(i)
    used = [False] * len(segs)

    def walk(pts):
        """Extend ``pts`` (≥ 2 points) past its last point while the line
        goes on straight enough through a two-way node."""
        while True:
            here = at[key(*pts[-1])]
            if len(here) != 2:
                return
            nxt = next((j for j in here if not used[j]), None)
            if nxt is None:
                return
            x0, y0, x1, y1 = segs[nxt]
            far = (x1, y1) if key(x0, y0) == key(*pts[-1]) else (x0, y0)
            ax, ay = pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]
            bx, by = far[0] - pts[-1][0], far[1] - pts[-1][1]
            la, lb = math.hypot(ax, ay), math.hypot(bx, by)
            if la * lb == 0.0 or (ax * bx + ay * by) / (la * lb) < cos_max:
                return                        # a corner: the line ends
            used[nxt] = True
            pts.append(far)

    chains = []
    for i, (x0, y0, x1, y1) in enumerate(segs):
        if used[i] or key(x0, y0) == key(x1, y1):
            continue
        used[i] = True
        fwd = [(x0, y0), (x1, y1)]
        walk(fwd)
        back = [(x1, y1), (x0, y0)]
        walk(back)
        back = back[1:]
        pts = back[:0:-1] + fwd
        closed = len(pts) > 3 and key(*pts[0]) == key(*pts[-1])
        if closed:
            pts = pts[:-1]
        chains.append((pts, closed))
    return chains


def save_svg_layers(path: str | Path, groups, scale_n: float = 100.0,
                    pens: dict | None = None, faces=None,
                    line_colours: bool = True, image=None,
                    paper=None) -> int:
    """Write the view ``groups`` (as :func:`formats.dxf_out.save_dxf_layers`
    takes them) to an SVG at 1:``scale_n``, one layer per non-empty group
    — see :func:`svg_text` for the rest. Returns the number of line
    segments written."""
    text, n = svg_text(groups, scale_n, pens, faces, line_colours, image,
                       paper)
    Path(path).write_text(text, encoding="utf-8")
    return n


def svg_text(groups, scale_n: float = 100.0, pens: dict | None = None,
             faces=None, line_colours: bool = True, image=None, paper=None,
             bake_px_per_mm: float | None = None, window=None,
             margin: float | None = None, seam_mm: float | None = None):
    """The SVG of a view as ``(text, line segments)``.

    ``pens`` overrides :data:`DEFAULT_PENS` (``cut`` / ``profile`` /
    ``edge`` in mm); a group's own fifth element, its weight in mm, wins
    over both.

    ``faces`` — the view's filled faces (:func:`core.vista_caras.view_faces`,
    in the same plane as the lines) go UNDER the lines, one layer per model
    layer («<layer>-CARAS»; the see-through ones on «<layer>-CARAS-TRANSP»
    above the opaque ones, the sun's shadows on «<layer>-SOMBRAS» over
    them). Each face is one shape filled with its colour or its texture
    laid out as the view shows it (see :func:`_face_layers`).
    ``line_colours`` off: every line in black, whatever its layer's
    colour (the «Default colour only» export); line types and pens stay.

    ``image`` — ``(QImage, (x0, y0, x1, y1))``: a picture of the view and
    the window it shows, in the drawing's plane; it goes under everything
    on a layer of its own, and the page is that window.

    ``paper`` — ``(width_mm, height_mm)``: the page is that sheet and the
    drawing is fitted into it, centred, within the margin — at whatever
    scale fits (the ``desc`` says which); without it the page is the
    drawing at 1:``scale_n`` plus the margin. ``bake_px_per_mm`` draws the
    textures coarser (a preview).

    ``window`` — ``(x0, y0, x1, y1)`` in the drawing's plane: the part of
    it the page shows (what the screen shows, say) instead of the whole
    drawing; ``margin`` — the page's margin in mm (10 by default; 0 to
    fill the page with the window edge to edge). ``seam_mm``: the hair
    of colour round each face (a small preview wants it wider)."""
    pens = {**DEFAULT_PENS, **(pens or {})}
    margin = _MARGIN if margin is None else float(margin)
    groups = [g for g in groups if len(g[1])]
    faces = list(faces or ())
    if window is not None:
        min_x, min_y, max_x, max_y = window
    elif image is not None:
        min_x, min_y, max_x, max_y = image[1]
    else:
        xs, ys = [], []
        for g in groups:
            for x0, y0, x1, y1 in g[1]:
                xs += (x0, x1)
                ys += (y0, y1)
        for f in faces:
            for r in f.rings:
                xs += list(map(float, r[:, 0]))
                ys += list(map(float, r[:, 1]))
        if xs:
            min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
        else:
            min_x = max_x = min_y = max_y = 0.0
    bw, bh = max(max_x - min_x, 1e-9), max(max_y - min_y, 1e-9)
    if paper is not None:
        width, height = float(paper[0]), float(paper[1])
        k = min((width - 2 * margin) / bw, (height - 2 * margin) / bh)
        k = max(k, 1e-9)
        scale_n = 1000.0 / k
        off_x = (width - bw * k) / 2.0
        off_y = (height - bh * k) / 2.0
    else:
        k = 1000.0 / max(1e-9, float(scale_n))     # metres → paper mm
        width = (max_x - min_x) * k + 2 * margin
        height = (max_y - min_y) * k + 2 * margin
        off_x = off_y = margin

    def px(x):
        return (x - min_x) * k + off_x

    def py(y):                                 # SVG's y grows downwards
        return (max_y - y) * k + off_y

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'xmlns:inkscape="{_INKSCAPE}" version="1.1" '
        f'width="{width:.3f}mm" height="{height:.3f}mm" '
        f'viewBox="0 0 {width:.3f} {height:.3f}">\n',
        f"<desc>{_esc(_scale_label(scale_n))}</desc>\n"]
    taken: set = {"pagina"}
    clip = ""
    if window is not None:
        # What lies past the window stays out of sight: each layer is cut
        # to the page.
        out.append(f'<defs><clipPath id="pagina"><rect x="0" y="0" '
                   f'width="{width:.3f}" height="{height:.3f}"/></clipPath>'
                   f'</defs>\n')
        clip = ' clip-path="url(#pagina)"'
    if image is not None and image[0] is not None and not image[0].isNull():
        # On its own window: a sheet of another shape widens the page's
        # window round it, the picture stays where it was taken.
        ix0, iy0, ix1, iy1 = image[1]
        name = "VISTA-IMAGEN"
        out.append(f'<g id="{_xml_id(name, taken)}" '
                   f'inkscape:groupmode="layer" '
                   f'inkscape:label={quoteattr(name)}{clip}>\n'
                   f'<image x="{px(ix0):.3f}" y="{py(iy1):.3f}" '
                   f'width="{(ix1 - ix0) * k:.3f}" '
                   f'height="{(iy1 - iy0) * k:.3f}" '
                   f'preserveAspectRatio="none" '
                   f'xlink:href="{_encode(image[0])}"/>\n</g>\n')
    if faces:
        out += _face_layers(faces, px, py, taken, bake_px_per_mm, clip,
                            (width, height), seam_mm or _SEAM_MM)
    n = 0
    for g in groups:
        name, segs = str(g[0] or "VISTA"), g[1]
        ltype = g[2] if len(g) > 2 and g[2] else "CONTINUOUS"
        rgb = g[3] if len(g) > 3 and line_colours else None
        weight = g[4] if len(g) > 4 and g[4] else pens[_line_class(name)]
        attrs = (f' fill="none" stroke="{_hex(rgb)}" '
                 f'stroke-width="{float(weight):g}" '
                 'stroke-linecap="round" stroke-linejoin="round"')
        dash = _DASHES.get(str(ltype).upper())
        if dash:
            attrs += f' stroke-dasharray="{dash}"'
        out.append(f'<g id="{_xml_id(name, taken)}" '
                   f'inkscape:groupmode="layer" '
                   f'inkscape:label={quoteattr(name)}{attrs}{clip}>\n')
        for pts, closed in chain_segments(segs):
            d = "M" + " L".join(f"{px(x):.3f},{py(y):.3f}" for x, y in pts)
            out.append(f'<path d="{d}{" Z" if closed else ""}"/>\n')
        n += len(segs)
        out.append("</g>\n")
    out.append("</svg>\n")
    return "".join(out), n


def _scale_label(scale_n: float) -> str:
    """``1:100`` — rounded to what a person would write for a fitted one."""
    n = float(scale_n)
    n = round(n) if n >= 10 else round(n, 1)
    return f"1:{n:g}"


#: Longest side, in pixels, a texture is read at: enough for a sheet,
#: and a 4k photo texture does not make the file ten times heavier.
MAX_TEXTURE_PX = 1024

#: How finely a textured face's fill is drawn: pixels per paper
#: millimetre (8 ≈ 200 dpi), and at most this many pixels a side.
BAKE_PX_PER_MM = 8.0
MAX_BAKE_PX = 2048

#: A hair of the face's own colour round each opaque face, so two
#: neighbours leave no light seam between them in a viewer.
_SEAM_MM = 0.15


def _face_layers(faces, px, py, taken, bake_px_per_mm=None,
                 clip: str = "", page=(1.0e5, 1.0e5),
                 seam_mm: float = _SEAM_MM) -> list:
    """The ``<defs>`` with the textured faces' fills and the face layers.

    A textured face is filled with its texture already laid out as the view
    shows it — repeated, turned and slanted onto the face, darkened by its
    light — drawn here into one image over the face's box on the page. The
    fill needs no pattern transform, which the illustration programs read
    unevenly (the bricks came in level and unslanted where the view has
    them along the wall)."""
    defs: list = []
    textures: dict = {}        # (path, shade) → QImage, or None
    layers: dict = {}          # (layer, see-through) → [path elements]
    shadows: dict = {}         # layer → [path elements]
    ground: list = []          # the shadows on the bare ground

    def path_d(rings):
        return " ".join(
            "M" + " L".join(f"{px(x):.3f},{py(y):.3f}" for x, y in ring)
            + " Z" for ring in rings)

    def texture(path, shade):
        key = (str(path), round(float(shade), 5))
        if key not in textures:
            textures[key] = _shaded_texture(path, shade)
        return textures[key]

    for f in faces:
        d = path_d(f.rings)
        if f.extra.get("ground_shadow"):
            ground.append(f'<path d="{d}" fill="#000000" '
                          f'fill-opacity="{f.opacity:.3g}"/>\n')
            continue
        if f.shadow:
            # A black veil as dark as the shadow settings say: over the
            # face's colour or texture it gives the shaded tone, and stays
            # one shape to recolour, fade or switch off with its layer.
            shadows.setdefault(f.layer, []).append(
                f'<path d="{path_d(f.shadow)}" fill="#000000" '
                f'fill-opacity="{f.shadow_alpha:.3g}"/>\n')
        fill = _hex(f.rgb)
        tex = f.texture
        if tex is not None:
            img = texture(tex["path"], tex.get("shade", 1.0))
            m = _uv_to_page(tex["uv"], px, py) if img is not None else None
            baked = (_bake(img, m, f.rings, px, py, bake_px_per_mm)
                     if m is not None else None)
            if baked is not None:
                bx, by, bw, bh, uri = baked
                pid = _xml_id(f"cara_{len(defs) + 1}", taken)
                # The tile is the whole page from its origin and the image
                # sits where the face is: a tile starting at the face's box
                # with the image at its corner is placed one way by some
                # renderers and another by others (the preview showed the
                # bricks shifted, the page through the gaps).
                pw, ph = page
                defs.append(
                    f'<pattern id="{pid}" patternUnits="userSpaceOnUse" '
                    f'x="0" y="0" width="{pw:.3f}" height="{ph:.3f}">'
                    f'<image x="{bx:.3f}" y="{by:.3f}" '
                    f'width="{bw:.3f}" height="{bh:.3f}" '
                    f'preserveAspectRatio="none" xlink:href="{uri}"/>'
                    f'</pattern>\n')
                fill = f"url(#{pid})"
        attrs = f'fill="{fill}"'
        see_through = f.opacity < 0.999
        if see_through:
            attrs += f' fill-opacity="{f.opacity:.3g}"'
        else:
            attrs += (f' stroke="{_hex(f.rgb)}" stroke-width="{seam_mm:g}" '
                      'stroke-linejoin="round"')
        layers.setdefault((f.layer, see_through), []).append(
            f'<path d="{d}" {attrs}/>\n')
    out = []
    if defs:
        out += ["<defs>\n", *defs, "</defs>\n"]

    def layer(name, paths):
        out.append(f'<g id="{_xml_id(name, taken)}" '
                   f'inkscape:groupmode="layer" '
                   f'inkscape:label={quoteattr(name)}{clip} '
                   'fill-rule="evenodd">\n')
        out.extend(paths)
        out.append("</g>\n")

    if ground:
        layer("SOMBRAS-SUELO", ground)
    for see in (False, True):
        for (name_of, flag), paths in layers.items():
            if flag == see:
                layer(f"{name_of}-CARAS" + ("-TRANSP" if see else ""), paths)
    for name_of, paths in shadows.items():
        layer(f"{name_of}-SOMBRAS", paths)
    return out


def _uv_to_page(pins, px, py):
    """The map (a ``QTransform``) taking a texture tile's own coordinates
    — (u, −v), so the image's top row sits at v = 1 as the viewport draws
    it — to the page, through the four pinned points: projective, so a
    face seen in perspective gets its texture exactly as the viewport lays
    it (an affine map only guesses it). ``None`` for a degenerate face."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF, QTransform
    src = QPolygonF([QPointF(u, -v) for _xy, (u, v) in pins])
    dst = QPolygonF([QPointF(px(x), py(y)) for (x, y), _uv in pins])
    t = QTransform()
    if not QTransform.quadToQuad(src, dst, t):
        return None
    return t


def _bake(img, m, rings, px, py, px_per_mm=None):
    """The texture ``img`` laid onto the page by ``m`` (tile → page),
    drawn into an image over the box of the face's ``rings``:
    ``(x, y, w, h, uri)`` in page millimetres, or ``None`` for a face too
    small to draw. The painter works in the tile's own coordinates and
    fills the face's own outline taken back there — never the box, whose
    far corners a perspective map can throw past the horizon."""
    import math

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import (QBrush, QImage, QPainter, QPainterPath,
                               QPolygonF, QTransform)
    xs = [px(x) for r in rings for x in r[:, 0]]
    ys = [py(y) for r in rings for y in r[:, 1]]
    bx, by = min(xs), min(ys)
    bw, bh = max(xs) - bx, max(ys) - by
    if bw <= 1e-6 or bh <= 1e-6:
        return None
    back, ok = m.inverted()
    if not ok:
        return None
    s = min(px_per_mm or BAKE_PX_PER_MM, MAX_BAKE_PX / max(bw, bh))
    w, h = max(1, math.ceil(bw * s)), max(1, math.ceil(bh * s))
    alpha = img.hasAlphaChannel()
    out = QImage(w, h, QImage.Format_ARGB32 if alpha
                 else QImage.Format_RGB32)
    out.fill(Qt.transparent if alpha else Qt.white)
    # The face, a hair wider so its edge pixels are filled too, in tile
    # coordinates.
    grow = 1.0 / s
    face = QPainterPath()
    face.setFillRule(Qt.OddEvenFill)
    for r in rings:
        pts = [QPointF(px(x), py(y)) for x, y in r]
        cx = sum(p.x() for p in pts) / len(pts)
        cy = sum(p.y() for p in pts) / len(pts)
        wide = []
        for p in pts:
            dx, dy = p.x() - cx, p.y() - cy
            d = math.hypot(dx, dy) or 1.0
            wide.append(back.map(QPointF(p.x() + dx / d * grow,
                                         p.y() + dy / d * grow)))
        face.addPolygon(QPolygonF(wide))
        face.closeSubpath()
    # A tile that comes out smaller than the image: shrink the image to
    # about twice the pixels the tile will take first, smoothly — sampled
    # straight, a fine texture far away broke into stripes (moiré), which
    # the viewport's mipmaps never show.
    o = m.map(QPointF(0.0, 0.0))
    tile_px = [math.hypot(q.x() - o.x(), q.y() - o.y()) * s
               for q in (m.map(QPointF(1.0, 0.0)), m.map(QPointF(0.0, 1.0)))]
    tw = max(4, min(img.width(), math.ceil(2.0 * tile_px[0])))
    th = max(4, min(img.height(), math.ceil(2.0 * tile_px[1])))
    if tw < img.width() or th < img.height():
        img = img.scaled(tw, th, Qt.IgnoreAspectRatio,
                         Qt.SmoothTransformation)
    brush = QBrush(img)
    brush.setTransform(QTransform.fromScale(1.0 / img.width(),
                                            1.0 / img.height()))
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setRenderHint(QPainter.Antialiasing)
    # Tile → page → this image's pixels.
    p.setTransform(m * QTransform.fromTranslate(-bx, -by)
                   * QTransform.fromScale(s, s))
    p.setPen(Qt.NoPen)
    p.setBrush(brush)
    p.drawPath(face)
    p.end()
    return bx, by, bw, bh, _encode(out)


def _shaded_texture(path, shade: float):
    """The texture at ``path`` darkened by ``shade`` (the face's light) and
    kept within :data:`MAX_TEXTURE_PX`, or ``None`` if it cannot be read."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    src = QImage(str(path))
    if src.isNull():
        return None
    if max(src.width(), src.height()) > MAX_TEXTURE_PX:
        src = src.scaled(MAX_TEXTURE_PX, MAX_TEXTURE_PX, Qt.KeepAspectRatio,
                         Qt.SmoothTransformation)
    alpha = src.hasAlphaChannel()
    img = src.convertToFormat(QImage.Format_ARGB32 if alpha
                              else QImage.Format_RGB32)
    if shade < 0.999:
        p = QPainter(img)
        p.setCompositionMode(QPainter.CompositionMode_Multiply)
        g = max(0, min(255, round(255 * float(shade))))
        p.fillRect(img.rect(), QColor(g, g, g))
        if alpha:                   # Multiply fills the clear pixels too
            p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            p.drawImage(0, 0, src)
        p.end()
    return img


def _encode(img) -> str:
    """``img`` as a ``data:`` URI: JPEG unless it has transparency."""
    import base64

    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    alpha = img.hasAlphaChannel()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG" if alpha else "JPG", -1 if alpha else 90)
    buf.close()
    mime = "image/png" if alpha else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(bytes(data)).decode()


def _image_uri(path, shade: float):
    """The shaded texture at ``path`` as a ``data:`` URI, or ``None``."""
    img = _shaded_texture(path, shade)
    return None if img is None else _encode(img)


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
