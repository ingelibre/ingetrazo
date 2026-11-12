# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Progresivas — stationing along a traced route (a road, a path, a canal,
a pipe…), as an IngeTrazo EXTENSION.

For roads, paths, canals and the like: the route comes from the field (a KML/KMZ track brought
in with File ▸ Import ▸ Georeference, or a path traced over the orthophoto)
and this extension marks its stations — 0+000, 0+020, 0+040… — on it.

Everything it makes is kept apart from the model, inside ONE group,
«Progresivas», on a layer of the same name: the tick marks, the station
labels (drawn over the view at a size, colour and background of your
choice, thinned out when they would overlap -- and printed on the sheets,
at a height in paper millimetres, from IngeTrazo 0.6.2) and, if asked
for, the strip itself -- the road, path or canal: a band of the width and
colour given, which can take the place of
the traced path and its node dots. Hide the layer and the drawing is as it
was; generate again and the old marks are replaced, not piled up.

Where the 3D terrain is built, strip, marks and labels sit on the ground.

Install: copy this file into the plugins folder (Extensions ▸ Open plugins
folder) and restart IngeTrazo. Select the route and run
Extensions ▸ Progresivas…
"""
from __future__ import annotations

import csv
import math
import re

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPen, QVector3D
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from core.i18n import current_language
from tools.base import Tool

KEY = "progresivas"
#: Group and layer name: document data, the same in every language.
NAME = "Progresivas"

DEFAULTS = {
    "start": 0.0,          # station of the route's first point, metres
    "interval": 20.0,      # a tick every N metres
    "label_every": 100.0,  # a label (and a long tick) every N metres
    "tick": 4.0,           # length of a short tick, metres
    "stake_color": None,   # None = a plain line; a colour = a bar of it
    "stake_width": 0.5,    # width of that bar, metres
    "side": "left",        # which side of the travel direction labels go
    "reverse": False,      # station from the route's last point instead
    # the labels
    "text_size": 10,                   # points
    "text_bold": True,
    "text_color": [20, 30, 45],
    "text_bg": [255, 255, 255],        # None = no background
    "text_bg_opacity": 85,             # percent
    "prefix": "",                      # "Km " -> "Km 3+200"
    # how a label lies: "stake" = in line with its stake, "road" = along
    # the road, "horizontal" = level on the screen
    "label_align": "stake",
    # labels written ON the ground, as geometry: what sheets, images and
    # exports show (the ones drawn over the view exist only on screen)
    "ground_text": False,
    "ground_text_height": 8.0,         # letter height, metres
    # the labels on the sheets: printed as text this tall on the paper
    "sheet_text_mm": 2.5,
    # the road
    "road": False,
    "road_width": 6.0,
    "road_color": [70, 70, 75],
    "road_opacity": 100,               # percent
    "replace_path": False,             # the traced path gives way to the road
}

#: Above the ground, so the road is not lost in the image under it, and the
#: marks are not lost in the road.
ROAD_LIFT = 0.05
BAR_LIFT = 0.08
TICK_LIFT = 0.10
TEXT_LIFT = 0.14

# An extension brings its own words — the core catalogues stay the core's.
_TEXTS = {
    "es": {
        "Stationing…": "Progresivas…",
        "Mark stations (0+020, 0+040…) along the selected route.":
            "Marca las progresivas (0+020, 0+040…) sobre la ruta seleccionada.",
        "Stationing": "Progresivas",
        "Route: {name} — {length}": "Ruta: {name} — {length}",
        "path": "trazo", "selected edges": "aristas seleccionadas",
        "Start station:": "Progresiva inicial:",
        "Tick every:": "Marca cada:",
        "Label every:": "Etiqueta cada:",
        "Tick length:": "Largo de la marca:",
        "Labels on the:": "Etiquetas a la:",
        "left": "izquierda", "right": "derecha",
        "Direction:": "Sentido:",
        "as drawn": "como se dibujó", "reversed": "invertido",
        "Labels": "Etiquetas", "Strip": "Franja", "Stations": "Progresivas",
        "Text size:": "Tamaño del texto:", "Bold": "Negrita",
        "Text colour:": "Color del texto:",
        "Background:": "Fondo:", "Background opacity:": "Opacidad del fondo:",
        "Prefix:": "Prefijo:",
        "Draw the strip (road, path, canal…)":
            "Dibujar la franja (carretera, camino, canal…)",
        "Width:": "Ancho:", "Colour:": "Color:", "Opacity:": "Opacidad:",
        "Replace the traced path by the strip":
            "Reemplazar el trazo por la franja",
        "Choose…": "Elegir…", "None": "Ninguno",
        "stored route": "ruta guardada",
        "Generate": "Generar", "Remove": "Quitar",
        "Export CSV…": "Exportar CSV…", "Close": "Cerrar",
        "Select a route first: a path, or a chain of edges.":
            "Selecciona primero una ruta: un trazo o una cadena de aristas.",
        "The selected edges are not one open chain.":
            "Las aristas seleccionadas no forman una sola cadena abierta.",
        "Write the station as 12+350 or as metres.":
            "Escribe la progresiva como 12+350 o en metros.",
        "{n} stations marked, from {a} to {b}.":
            "{n} progresivas marcadas, de {a} a {b}.",
        "Stationing removed.": "Progresivas quitadas.",
        "There is no stationing to remove.": "No hay progresivas que quitar.",
        "Stations (*.csv)": "Progresivas (*.csv)",
        "Saved {path}": "Guardado {path}",
        "Station": "Progresiva", "Metres": "Metros", "East": "Este",
        "North": "Norte", "Elevation": "Cota", "Latitude": "Latitud",
        "Longitude": "Longitud",
        "Stake colour:": "Color de la estaca:",
        "Lying:": "Orientación:",
        "in line with the stake": "alineada a la estaca",
        "along the route": "paralela al eje",
        "horizontal": "horizontal",
        "Write them on the ground as geometry":
            "Escribirlas sobre el terreno como geometría",
        "The labels are drawn over the view and printed on the sheets "
        "(IngeTrazo 0.6.2 or later), only where this extension is "
        "installed. Written on the ground they are part of the model: "
        "any IngeTrazo shows them, in images and exports too.":
            "Las etiquetas se dibujan sobre la vista y se imprimen en las "
            "láminas (IngeTrazo 0.6.2 o posterior), sólo donde esta "
            "extensión está instalada. Escritas sobre el terreno son parte "
            "del modelo: cualquier IngeTrazo las muestra, también en "
            "imágenes y exportaciones.",
        "On sheets:": "En láminas:",
        "Letter height:": "Altura de la letra:",
        "Stake width:": "Ancho de la estaca:",
        "Settings…": "Configuración…",
        "No stationing in this document yet.":
            "Este documento aún no tiene progresivas.",
        "{n} stations, {m} edited": "{n} progresivas, {m} editadas",
        "Only labelled or edited": "Sólo con etiqueta o editadas",
        "Label": "Etiqueta", "Stake": "Estaca",
        "Selected station": "Progresiva seleccionada",
        "{n} selected stations": "{n} progresivas seleccionadas",
        "Text:": "Texto:", "automatic": "automático",
        "Show the label": "Mostrar la etiqueta",
        "Show the stake": "Mostrar la estaca",
        "Stake length:": "Largo de la estaca:",
        "Auto": "Auto", "Back to automatic": "Volver a automático",
        "Restore": "Restaurar",
        "Undo every edit of the selected stations":
            "Deshace toda edición de las progresivas seleccionadas",
        "Restore all": "Restaurar todas",
        "Double-click a label to write it. To change several at once, "
        "select them and use the box above.":
            "Doble clic en una etiqueta para escribirla. Para cambiar varias "
            "a la vez, selecciónalas y usa el cuadro de arriba.",
        "Double-click a label to write it; untick a stake to hide it.":
            "Doble clic en una etiqueta para escribirla; desmarca una "
            "estaca para ocultarla.",
    },
}


def _t(text: str, **kw) -> str:
    text = _TEXTS.get(current_language(), {}).get(text, text)
    return text.format(**kw) if kw else text


# ---------------------------------------------------------------------------
# Pure geometry (no GUI, no document) — see test_progresivas.py
# ---------------------------------------------------------------------------

def fmt_station(metres: float, decimals: int = 0) -> str:
    """12350.0 -> '12+350'; 20.5 with one decimal -> '0+020.5'."""
    value = round(float(metres), decimals)
    sign = "-" if value < 0 else ""
    value = abs(value)
    km = int(value // 1000)
    rest = value - km * 1000
    if rest >= 1000 - 0.5 * 10 ** -decimals:      # 999.99 rounding up
        km, rest = km + 1, 0.0
    width = 3 + (decimals + 1 if decimals else 0)
    return f"{sign}{km}+{rest:0{width}.{decimals}f}"


def label(metres: float) -> str:
    """A station as it is written on the plan: whole metres bare
    ('3+200'), the odd one -- usually the route's end -- to the centimetre
    ('8+936.73')."""
    whole = abs(metres - round(metres)) < 5e-3
    return fmt_station(metres, 0 if whole else 2)


_STATION = re.compile(r"^\s*(-?)\s*(\d+)\s*\+\s*(\d+(?:[.,]\d+)?)\s*$")


def parse_station(text: str) -> float:
    """'12+350' -> 12350.0; a bare number is metres. ValueError otherwise."""
    match = _STATION.match(text)
    if match:
        sign, km, rest = match.groups()
        value = int(km) * 1000 + float(rest.replace(",", "."))
        return -value if sign else value
    return float(text.strip().replace(",", "."))


def chain_edges(segments) -> list:
    """Order loose ``((x, y, z), (x, y, z))`` segments into ONE open
    polyline. ValueError when they branch, close or are several chains."""
    def key(p):
        return (round(p[0], 4), round(p[1], 4), round(p[2], 4))

    ends: dict = {}
    for a, b in segments:
        ends.setdefault(key(a), []).append((a, b))
        ends.setdefault(key(b), []).append((b, a))
    if not ends or any(len(v) > 2 for v in ends.values()):
        raise ValueError("branching")
    tips = [k for k, v in ends.items() if len(v) == 1]
    if len(tips) != 2:
        raise ValueError("not one open chain")
    # start at the tip nearer the origin of the pair, for a stable result
    here = min(tips)
    chain = [ends[here][0][0]]
    seen = {here}
    while True:
        step = next(((a, b) for a, b in ends[here] if key(b) not in seen),
                    None)
        if step is None:
            break
        chain.append(step[1])
        here = key(step[1])
        seen.add(here)
    if len(chain) != len(segments) + 1:
        raise ValueError("several chains")
    return chain


def axis_length(axis) -> float:
    """Horizontal length of the polyline, as a road is stationed."""
    return sum(math.hypot(b[0] - a[0], b[1] - a[1])
               for a, b in zip(axis, axis[1:]))


def stations(axis, start: float = 0.0, interval: float = 20.0) -> list:
    """The stations of ``axis``: its first point (``start``), every round
    multiple of ``interval`` after it, and its last point.

    Each is ``(station, (x, y, z), (tx, ty))`` with the unit travel
    direction. Distances are horizontal."""
    if len(axis) < 2 or interval <= 0:
        return []
    total = axis_length(axis)
    wanted = [0.0]
    first = math.floor(start / interval + 1e-9) * interval + interval
    d = first - start
    while d < total - 1e-6:
        if d > 1e-6:
            wanted.append(d)
        d += interval
    if total > 1e-6:
        wanted.append(total)

    out = []
    walked = 0.0
    i = 0
    seg = 0
    while i < len(wanted) and seg < len(axis) - 1:
        a, b = axis[seg], axis[seg + 1]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        last = seg == len(axis) - 2
        if length <= 1e-9:
            seg += 1
            continue
        if wanted[i] <= walked + length + 1e-9 or last:
            t = min(1.0, max(0.0, (wanted[i] - walked) / length))
            point = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                     a[2] + (b[2] - a[2]) * t)
            direction = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
            out.append((start + wanted[i], point, direction))
            i += 1
        else:
            walked += length
            seg += 1
    return out


def ribbon(axis, width: float, miter_limit: float = 3.0):
    """The two sides of a band ``width`` wide along ``axis``: ``(left,
    right)`` lists of ``(x, y)``, one pair per axis point, mitred at the
    corners (a sharp one is cut short at ``miter_limit`` half-widths)."""
    half = width / 2.0
    n = len(axis)
    normals = []
    for a, b in zip(axis, axis[1:]):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        normals.append((-(b[1] - a[1]) / length, (b[0] - a[0]) / length)
                       if length > 1e-9 else None)
    for i, v in enumerate(normals):            # a zero segment: its neighbour's
        if v is None:
            normals[i] = next((w for w in normals[i:] + normals[:i][::-1]
                               if w is not None), (0.0, 1.0))
    left, right = [], []
    for i in range(n):
        before = normals[i - 1] if i > 0 else normals[0]
        after = normals[i] if i < n - 1 else normals[-1]
        mx, my = before[0] + after[0], before[1] + after[1]
        m = math.hypot(mx, my)
        if m < 1e-9:                           # a full turn back
            mx, my, scale = before[0], before[1], 1.0
        else:
            mx, my = mx / m, my / m
            cos_half = max(mx * before[0] + my * before[1], 1.0 / miter_limit)
            scale = 1.0 / cos_half
        x, y = axis[i][0], axis[i][1]
        left.append((x + mx * half * scale, y + my * half * scale))
        right.append((x - mx * half * scale, y - my * half * scale))
    return left, right


def thin_out(boxes, ranks) -> list:
    """Which labels to draw so that none overlaps another: ``boxes`` are
    ``(x, y, w, h)``, ``ranks`` their importance (lower first). Returns the
    indices kept."""
    kept: list = []
    taken: list = []
    for i in sorted(range(len(boxes)), key=lambda k: (ranks[k], k)):
        x, y, w, h = boxes[i]
        if any(x < tx + tw and tx < x + w and y < ty + th and ty < y + h
               for tx, ty, tw, th in taken):
            continue
        taken.append(boxes[i])
        kept.append(i)
    return kept


def rank(station: float) -> int:
    """How much a station matters when labels crowd: whole kilometres
    first, then half ones, then hundreds, then the rest."""
    for level, step in enumerate((1000.0, 500.0, 100.0)):
        if abs(station / step - round(station / step)) < 1e-6:
            return level
    return 3


def is_major(station: float, label_every: float) -> bool:
    if label_every <= 0:
        return False
    return abs(station / label_every - round(station / label_every)) < 1e-6


# ---------------------------------------------------------------------------
# The document side
# ---------------------------------------------------------------------------

def _pt(v) -> tuple:
    return (v.x(), v.y(), v.z())


def find_axis(scene):
    """The route to station: ``(points, description)`` or ``(None, reason)``.

    A selected path wins; then a chain of selected edges; with nothing
    selected, the document's only path."""
    from georef.geopath import GeoPath

    selection = list(scene.selection)
    paths = [e for e in selection if isinstance(e, GeoPath)]
    if not paths and not selection and len(scene.geo_paths) == 1:
        paths = list(scene.geo_paths)
    if paths:
        path = paths[0]
        points = [_pt(p) for p in path.points]
        if path.closed and len(points) > 2:
            points.append(points[0])
        return points, (path.name or _t("path"))
    # the route this extension keeps once the road took the path's place
    for group in _own_groups(scene):
        if not selection or group in selection:
            stored = (group.ext.get(KEY) or {}).get("axis")
            if stored and len(stored) >= 2:
                return [tuple(p) for p in stored], _t("stored route")
    edges = [e for e in selection if hasattr(e, "v0") and hasattr(e, "v1")]
    if edges:
        try:
            return (chain_edges([(_pt(e.v0.position), _pt(e.v1.position))
                                 for e in edges]), _t("selected edges"))
        except (ValueError, AttributeError):
            return None, _t("The selected edges are not one open chain.")
    return None, _t("Select a route first: a path, or a chain of edges.")


def _ground(scene, x: float, y: float, z: float) -> float:
    terrain = getattr(scene, "terrain", None)
    if terrain is not None:
        try:
            h = terrain.height_at(x, y)
        except Exception:                 # noqa: BLE001 - terrain mid-rebuild
            h = None
        if h is not None:
            return float(h)
    return z


def _own_groups(scene) -> list:
    return [g for g in scene.groups if KEY in (getattr(g, "ext", None) or {})]


def remove(scene) -> bool:
    """Take away the group and the labels this extension made."""
    groups = _own_groups(scene)
    labels = [lab for lab in scene.text_labels
              if getattr(lab, "layer", None) == NAME]
    for g in groups:
        scene.groups.remove(g)
    for lab in labels:
        scene.text_labels.remove(lab)
    return bool(groups or labels)


def _road(scene, mesh, axis, p) -> list:
    """The band of the road, as faces of its colour in ``mesh``."""
    left, right = ribbon(axis, p["road_width"])
    attrs = {"color": tuple(c / 255.0 for c in p["road_color"])}
    if p["road_opacity"] < 100:
        attrs["opacity"] = max(0.05, p["road_opacity"] / 100.0)
    terrain = getattr(scene, "terrain", None) is not None

    def point(xy, z):
        return QVector3D(xy[0], xy[1], _ground(scene, xy[0], xy[1], z)
                         + ROAD_LIFT)

    made = []
    for i in range(len(axis) - 1):
        a_l, a_r = point(left[i], axis[i][2]), point(right[i], axis[i][2])
        b_l = point(left[i + 1], axis[i + 1][2])
        b_r = point(right[i + 1], axis[i + 1][2])
        # on relief a quad is not flat: two triangles
        loops = ([a_r, b_r, b_l], [a_r, b_l, a_l]) if terrain \
            else ([a_r, b_r, b_l, a_l],)
        for loop in loops:
            try:
                face = mesh.add_face(loop)
            except Exception:             # noqa: BLE001 - a pinched corner
                continue
            face.attrs.update(attrs)
            made.append(face)
    # only the two sides stay drawn: the joints between pieces are soft
    side_keys = set()
    for side in (left, right):
        for a, b in zip(side, side[1:]):
            side_keys.add(frozenset((_k2(a), _k2(b))))
    for end in (0, -1):                   # and the two ends of the road
        side_keys.add(frozenset((_k2(left[end]), _k2(right[end]))))
    for edge in mesh.edges:
        ends = frozenset((_k2(_pt(edge.v0.position)),
                          _k2(_pt(edge.v1.position))))
        if ends not in side_keys:
            edge.soft = True
    return made


def _k2(p) -> tuple:
    return (round(p[0], 3), round(p[1], 3))


def station_key(station: float) -> str:
    """What an edited station is remembered by: its metres."""
    return f"{station:.3f}"


def stored_overrides(scene) -> dict:
    """The stations edited one by one: ``{station_key: {…}}``. Each may hold
    ``text``, ``label`` (shown or not), ``stake`` (False = none), ``tick``
    (its length, metres), ``text_color``, ``text_bg``, ``stake_color``."""
    for g in _own_groups(scene):
        return {k: dict(v) for k, v in
                ((g.ext.get(KEY) or {}).get("overrides") or {}).items()}
    return {}


def stored_axis(scene):
    for g in _own_groups(scene):
        axis = (g.ext.get(KEY) or {}).get("axis")
        if axis and len(axis) >= 2:
            return [tuple(pt) for pt in axis]
    return None


def _stake_bar(mesh, x, y, z, nx, ny, half, width, rgb) -> None:
    """A stake of colour: a flat bar across the route, its outline unseen."""
    tx, ty = ny, -nx
    w = width / 2.0
    loop = [QVector3D(x - nx * half - tx * w, y - ny * half - ty * w, z),
            QVector3D(x + nx * half - tx * w, y + ny * half - ty * w, z),
            QVector3D(x + nx * half + tx * w, y + ny * half + ty * w, z),
            QVector3D(x - nx * half + tx * w, y - ny * half + ty * w, z)]
    try:
        face = mesh.add_face(loop)
    except Exception:                     # noqa: BLE001 - a bar of no size
        return
    face.attrs["color"] = tuple(c / 255.0 for c in rgb)
    corners = {_k2(_pt(v)) for v in loop}
    for edge in mesh.edges:
        if face in edge.faces and len(edge.faces) == 1 \
                and _k2(_pt(edge.v0.position)) in corners \
                and _k2(_pt(edge.v1.position)) in corners:
            edge.hidden = True


def _glyph_rings(text: str, bold: bool):
    """The outline of ``text`` as ``[(outer, holes)]`` in font units, with
    its box ``(x0, y0, x1, y1)``; ``None`` where the host cannot say."""
    try:
        from core.text3d import _group_rings, _ring_area, _rings
        rings, _line = _rings(text, "", bold, False)
    except Exception:                     # noqa: BLE001 - no fonts, older host
        return None
    if not rings:
        return None
    xs = [x for ring in rings for x, _y in ring]
    ys = [y for ring in rings for _x, y in ring]
    shapes = []
    for outer, holes in _group_rings(rings):
        if _ring_area(outer) < 0:
            outer = outer[::-1]           # counter-clockwise: it faces up
        shapes.append((outer, [h if _ring_area(h) < 0 else h[::-1]
                               for h in holes]))
    return shapes, (min(xs), min(ys), max(xs), max(ys))


def _ground_label(scene, mesh, text, x, y, z, nx, ny, start, p, style) -> None:
    """``text`` lying on the ground across the route: it starts ``start``
    metres from the axis point ``(x, y)`` along ``(nx, ny)`` and reads so
    that it is never upside down on a north-up plan."""
    glyphs = _glyph_rings(text, bool(p["text_bold"]))
    if glyphs is None:
        return
    shapes, (u0, v0, u1, v1) = glyphs
    scale = p["ground_text_height"] / max(v1 - v0, 1e-9)
    width = (u1 - u0) * scale
    pad = p["ground_text_height"] * 0.25
    along = p["label_align"] == "road"
    reach = start + pad + (p["ground_text_height"] if along else width) / 2.0
    cx, cy = x + nx * reach, y + ny * reach
    dx, dy = (ny, -nx) if along else (nx, ny)
    if not (dx > 1e-9 or (abs(dx) <= 1e-9 and dy > 0)):
        dx, dy = -dx, -dy                 # reading direction
    ex, ey = -dy, dx                      # up of the letters
    half_w, half_h = width / 2.0, p["ground_text_height"] / 2.0
    level = max(_ground(scene, cx + dx * k, cy + dy * k, z)
                for k in (-half_w, 0.0, half_w))

    def at(u, v, lift):
        a = (u - (u0 + u1) / 2.0) * scale
        b = (v - (v0 + v1) / 2.0) * scale
        return QVector3D(cx + dx * a + ex * b, cy + dy * a + ey * b,
                         level + lift)

    made = []
    back = style.get("text_bg", p["text_bg"])
    if back:
        loop = [QVector3D(cx + dx * a + ex * b, cy + dy * a + ey * b,
                          level + TEXT_LIFT - 0.02)
                for a, b in ((-half_w - pad, -half_h - pad),
                             (half_w + pad, -half_h - pad),
                             (half_w + pad, half_h + pad),
                             (-half_w - pad, half_h + pad))]
        try:
            face = mesh.add_face(loop)
            face.attrs["color"] = tuple(c / 255.0 for c in back)
            if "text_bg" not in style and p["text_bg_opacity"] < 100:
                face.attrs["opacity"] = max(0.05, p["text_bg_opacity"] / 100.0)
            made.append(face)
        except Exception:                 # noqa: BLE001
            pass
    ink = tuple(c / 255.0 for c in style.get("text_color", p["text_color"]))
    for outer, holes in shapes:
        try:
            face = mesh.add_face(
                [at(u, v, TEXT_LIFT) for u, v in outer],
                hole_loops=[[at(u, v, TEXT_LIFT) for u, v in h]
                            for h in holes] or None)
        except Exception:                 # noqa: BLE001 - a degenerate glyph
            continue
        face.attrs["color"] = ink
        made.append(face)
    return made


def build(scene, axis, params: dict) -> list:
    """Replace the stationing with one made from ``axis`` and ``params``.
    Returns the stations made, for the caller's message and the CSV.

    The stations edited one by one (``params["overrides"]``) are kept from
    the stationing being replaced when the caller does not say."""
    from core.group import Group
    from core.layers import Layer
    from core.mesh import Mesh

    p = {**DEFAULTS, **params}
    overrides = params["overrides"] if "overrides" in params \
        else stored_overrides(scene)
    overrides = {k: dict(v) for k, v in (overrides or {}).items() if v}
    drawn_axis = list(axis)
    if p["reverse"]:
        axis = list(reversed(axis))
    marks = stations(axis, p["start"], p["interval"])
    remove(scene)
    if not marks:
        return []
    if scene.layer(NAME) is None:
        scene.layers.append(Layer(NAME, color=(0.95, 0.45, 0.16)))

    mesh = Mesh()
    if p["road"]:
        _road(scene, mesh, axis, p)
    side = 1.0 if p["side"] == "left" else -1.0
    out = (p["road_width"] / 2.0) if p["road"] else 0.0
    labels = []
    lettered: list = []                   # faces of the labels on the ground
    last = len(marks) - 1
    for i, (station, (x, y, z), (tx, ty)) in enumerate(marks):
        key = station_key(station)
        o = overrides.get(key) or {}
        nx, ny = -ty, tx                  # left of the travel direction
        major = is_major(station, p["label_every"]) or i in (0, last)
        reach = o["tick"] if o.get("tick") else \
            p["tick"] * (1.0 if major else 0.5)
        half = out + reach
        z = _ground(scene, x, y, z)
        if o.get("stake", True):
            colour = o.get("stake_color") or p["stake_color"]
            if colour:
                _stake_bar(mesh, x, y, z + BAR_LIFT, nx, ny, half,
                           p["stake_width"], colour)
            try:
                mesh.add_edge(
                    QVector3D(x - nx * half, y - ny * half, z + TICK_LIFT),
                    QVector3D(x + nx * half, y + ny * half, z + TICK_LIFT))
            except ValueError:
                pass                      # a zero-length tick
        if o.get("label", major):
            away = (half + p["tick"] * 0.5) * side
            own = bool(o.get("text")) or (o.get("label") and not major)
            style = {k: o[k] for k in ("text_color", "text_bg") if k in o}
            wording = o.get("text") or p["prefix"] + label(station)
            if p["ground_text"]:
                lettered.extend(_ground_label(
                    scene, mesh, wording, x, y, z, nx * side, ny * side,
                    half, p, style) or [])
            labels.append([
                round(x + nx * away, 3), round(y + ny * away, 3),
                round(z + TICK_LIFT, 3),
                wording,
                # what the user wrote himself is the last to give way
                -1 if own else (rank(station) if i not in (0, last) else 0),
                style or None, key,
                [round(nx * side, 5), round(ny * side, 5)]])
    if lettered:                          # letters are their colour alone
        own = {id(f) for f in lettered}
        for edge in mesh.edges:
            if edge.faces and all(id(f) in own for f in edge.faces):
                edge.hidden = True
    group = Group(mesh, NAME)
    group.layer = NAME
    group.ext = {KEY: {**{k: p[k] for k in DEFAULTS},
                       "axis": [[round(c, 3) for c in pt] for pt in drawn_axis],
                       "overrides": overrides,
                       "labels": labels}}
    scene.groups.append(group)
    return marks


def stored_params(scene) -> dict:
    for g in _own_groups(scene):
        stored = g.ext.get(KEY) or {}
        return {**DEFAULTS, **{k: stored[k] for k in DEFAULTS if k in stored}}
    return dict(DEFAULTS)


# ---------------------------------------------------------------------------
# The labels, drawn over the view
# ---------------------------------------------------------------------------

#: The labels of the last frame, per viewport: ``[(QRectF, station_key)]``
#: -- what a click in the view is asked against.
_drawn: dict = {}
#: The side panel, once made: its selection is ringed in the view.
_panel = None


def draw_labels(viewport, painter) -> None:
    """Every station label of the open document, in its style, thinned out
    where they would overlap. Called for each frame: keep it cheap."""
    scene = viewport.scene
    hits = _drawn[id(viewport)] = []
    for group in _own_groups(scene):
        data = group.ext.get(KEY) or {}
        labels = data.get("labels") or []
        if not labels or not scene.entity_visible(group) \
                or data.get("ground_text"):
            continue
        px, py, front = viewport.world_to_pixels(
            [(row[0], row[1], row[2]) for row in labels])
        font = QFont()
        font.setPointSize(int(data.get("text_size", DEFAULTS["text_size"])))
        font.setBold(bool(data.get("text_bold", True)))
        painter.setFont(font)
        metrics = painter.fontMetrics()
        height = metrics.height()
        width, limit = viewport.width(), viewport.height()
        align = data.get("label_align", "horizontal")
        turned = align in ("stake", "road") and all(
            len(row) > 7 for row in labels)
        if turned:
            # where a point 10 m further along the stake (or the road)
            # lands on screen says how the label lies
            ahead = []
            for row in labels:
                ux, uy = row[7] if align == "stake" else (row[7][1],
                                                          -row[7][0])
                ahead.append((row[0] + ux * 10.0, row[1] + uy * 10.0, row[2]))
            qx, qy, _front = viewport.world_to_pixels(ahead)
        shown, boxes, ranks, frames = [], [], [], []
        for i, row in enumerate(labels):
            if not front[i]:
                continue
            x, y = float(px[i]), float(py[i])
            if not (-200 < x < width + 200 and -50 < y < limit + 50):
                continue
            w = metrics.horizontalAdvance(row[3]) + 8
            h = height + 4
            angle, left = 0.0, -w / 2.0
            if turned:
                sx, sy = float(qx[i]) - x, float(qy[i]) - y
                if math.hypot(sx, sy) > 1e-3:
                    angle = math.degrees(math.atan2(sy, sx))
                    flipped = abs(angle) > 90.0     # never upside down
                    if flipped:
                        angle += 180.0
                    if align == "stake":            # it starts at the stake
                        left = -w if flipped else 0.0
            cos_a = math.cos(math.radians(angle))
            sin_a = math.sin(math.radians(angle))
            corners = [(x + u * cos_a - v * sin_a, y + u * sin_a + v * cos_a)
                       for u in (left, left + w) for v in (-h / 2.0, h / 2.0)]
            bx = min(c[0] for c in corners)
            by = min(c[1] for c in corners)
            shown.append(i)
            boxes.append((bx, by, max(c[0] for c in corners) - bx,
                          max(c[1] for c in corners) - by))
            ranks.append(row[4] if len(row) > 4 else 3)
            frames.append((x, y, angle, QRectF(left, -h / 2.0, w, h)))
        ink = data.get("text_color", DEFAULTS["text_color"])
        back = data.get("text_bg", DEFAULTS["text_bg"])
        alpha = max(0.0, min(1.0, data.get(
            "text_bg_opacity", DEFAULTS["text_bg_opacity"]) / 100.0))
        for k in thin_out(boxes, ranks):
            row = labels[shown[k]]
            style = (row[5] if len(row) > 5 else None) or {}
            x, y, angle, rect = frames[k]
            painter.save()
            painter.translate(x, y)
            painter.rotate(angle)
            fill = style.get("text_bg", back)
            if fill:
                fill = QColor(*fill)
                fill.setAlphaF(alpha if "text_bg" not in style else 1.0)
                painter.setPen(Qt.NoPen)
                painter.setBrush(fill)
                painter.drawRoundedRect(rect, 3, 3)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(*style.get("text_color", ink))))
            painter.drawText(rect, Qt.AlignCenter, row[3])
            painter.restore()
            if len(row) > 6:
                hits.append((QRectF(*boxes[k]), row[6]))
    points = getattr(_panel, "highlight", None)
    if points and getattr(_panel, "scene_shown", None) is scene:
        px, py, front = viewport.world_to_pixels(points)
        painter.setBrush(Qt.NoBrush)
        for colour, thick in ((QColor(255, 255, 255), 4.0),
                              (QColor(230, 60, 30), 2.0)):
            painter.setPen(QPen(colour, thick))
            for i in range(len(points)):
                if front[i]:
                    painter.drawEllipse(
                        QRectF(float(px[i]) - 7, float(py[i]) - 7, 14, 14))


def sheet_labels(scene, sheet) -> list:
    """The station labels for the sheets (IngeTrazo 0.6.2's
    ``add_sheet_annotations``): the same words, colours, background and
    lie as on screen, at ``sheet_text_mm`` on the paper, and thinned out
    by the sheet in the same order when they would overlap. The ticks and
    the road are geometry: the sheet draws them already. Labels written on
    the ground are geometry too, so they are not printed twice."""
    items = []
    for group in _own_groups(scene):
        data = group.ext.get(KEY) or {}
        labels = data.get("labels") or []
        if not labels or not scene.entity_visible(group) \
                or data.get("ground_text"):
            continue
        size = float(data.get("sheet_text_mm", DEFAULTS["sheet_text_mm"]))
        ink = tuple(data.get("text_color", DEFAULTS["text_color"]))
        back = data.get("text_bg", DEFAULTS["text_bg"])
        opacity = data.get("text_bg_opacity", DEFAULTS["text_bg_opacity"])
        bold = bool(data.get("text_bold", True))
        align = data.get("label_align", "horizontal")
        for row in labels:
            style = (row[5] if len(row) > 5 else None) or {}
            at = (row[0], row[1], row[2])
            item = {"text": row[3], "at": at, "size_mm": size, "bold": bold,
                    "color": tuple(style.get("text_color", ink)),
                    "priority": row[4] if len(row) > 4 else 3}
            fill = style.get("text_bg", back)
            if fill:
                item["background"] = tuple(fill)
                item["background_opacity"] = \
                    100 if "text_bg" in style else opacity
            if align in ("stake", "road") and len(row) > 7:
                ux, uy = row[7] if align == "stake" else (row[7][1],
                                                          -row[7][0])
                item["toward"] = (at[0] + ux * 10.0, at[1] + uy * 10.0, at[2])
                item["anchor"] = "start" if align == "stake" else "center"
            items.append(item)
    return items


def pick_label(viewport, px, py):
    """The station whose label is under that pixel, or ``None``."""
    for rect, key in reversed(_drawn.get(id(viewport), ())):
        if rect.contains(px, py):
            return key
    return None


def apply_overrides(viewport, changes: dict) -> bool:
    """Edit stations one by one. ``changes`` maps a station key to
    ``{field: value}`` -- a value of ``None`` takes that field back to
    automatic -- or to ``None`` to forget every edit of that station.
    One undo step."""
    from core.history import SnapshotImport

    scene = viewport.scene
    axis = stored_axis(scene)
    if axis is None or not changes:
        return False
    overrides = stored_overrides(scene)
    for key, change in changes.items():
        if change is None:
            overrides.pop(key, None)
            continue
        entry = overrides.setdefault(key, {})
        for field, value in change.items():
            if value is None:
                entry.pop(field, None)
            else:
                entry[field] = value
        if not entry:
            del overrides[key]
    params = {**stored_params(scene), "overrides": overrides}
    viewport.history.execute(
        SnapshotImport(lambda sc: build(sc, axis, params)))
    viewport.notify_scene_changed()
    viewport.update()
    return True


def setup(app) -> None:
    global _panel
    app.add_overlay(draw_labels)
    if hasattr(app, "add_sheet_annotations"):      # IngeTrazo 0.6.2 on
        app.add_sheet_annotations(sheet_labels)
    try:
        _panel = _Panel(app)
        _panel.dock = app.add_panel(_t("Stationing"), _panel)
        app.on_document_changed(_panel.refresh)
        app.add_pickable(
            pick=pick_label, on_select=_panel.select_key,
            # Supr on a label hides that label; the stake stays
            delete=lambda key: apply_overrides(
                app.viewport, {key: {"label": False}}))
    except Exception:                     # noqa: BLE001 - an older host
        import logging
        logging.getLogger(__name__).exception("stationing panel")
        _panel = None


def csv_rows(scene, marks) -> list:
    """Header and one row per station: station, metres, the local point and,
    in a located drawing, UTM and geographic coordinates."""
    datum = getattr(scene, "georef", None)
    header = [_t("Station"), _t("Metres"), "X", "Y", _t("Elevation")]
    if datum is not None:
        header += [_t("East"), _t("North"), _t("Latitude"), _t("Longitude")]
    rows = [header]
    for station, (x, y, z), _dir in marks:
        z = _ground(scene, x, y, z)
        row = [label(station), f"{station:.3f}",
               f"{x:.3f}", f"{y:.3f}", f"{z:.3f}"]
        if datum is not None:
            point = QVector3D(x, y, z)
            east, north = datum.local_to_utm(point)[:2]
            lat, lon = datum.local_to_geodetic(point)[:2]
            row += [f"{east:.3f}", f"{north:.3f}", f"{lat:.8f}", f"{lon:.8f}"]
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# The dialog
# ---------------------------------------------------------------------------

class _ColorButton(QPushButton):
    """A swatch that opens the colour dialog; ``None`` when it may be off."""

    def __init__(self, rgb, optional: bool = False) -> None:
        super().__init__()
        self.rgb = list(rgb) if rgb else None
        self.optional = optional
        self.clicked.connect(self._choose)
        self._show()

    def _show(self) -> None:
        if self.rgb is None:
            self.setText(_t("None"))
            self.setStyleSheet("")
            return
        r, g, b = self.rgb
        self.setText(_t("Choose…"))
        ink = "#000" if (r * 299 + g * 587 + b * 114) / 1000 > 140 else "#fff"
        self.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); color: {ink};")

    def _choose(self) -> None:
        start = QColor(*(self.rgb or [255, 255, 255]))
        chosen = QColorDialog.getColor(start, self)
        if chosen.isValid():
            self.rgb = [chosen.red(), chosen.green(), chosen.blue()]
        elif self.optional:
            self.rgb = None               # cancelled: no background
        self._show()


class _Dialog(QDialog):
    def __init__(self, viewport, axis, description, path=None) -> None:
        super().__init__(viewport.window())
        self.viewport = viewport
        self.axis = axis
        self.path = path                  # the GeoPath, when there is one
        self.marks: list = []
        self.setWindowTitle(_t("Stationing"))
        p = stored_params(viewport.scene)

        length = axis_length(axis)
        head = QLabel(_t("Route: {name} — {length}", name=description,
                         length=f"{length:,.2f} m"))

        self.start = QLineEdit(fmt_station(p["start"]))
        self.interval = self._metres(p["interval"], 1.0, 1000.0)
        self.label_every = self._metres(p["label_every"], 1.0, 10000.0)
        self.tick = self._metres(p["tick"], 0.1, 500.0)
        self.direction = QComboBox()
        self.direction.addItem(_t("as drawn"), False)
        self.direction.addItem(_t("reversed"), True)
        self.direction.setCurrentIndex(1 if p["reverse"] else 0)
        stations_box = QGroupBox(_t("Stations"))
        form = QFormLayout(stations_box)
        form.addRow(_t("Start station:"), self.start)
        form.addRow(_t("Tick every:"), self.interval)
        form.addRow(_t("Label every:"), self.label_every)
        form.addRow(_t("Tick length:"), self.tick)
        self.stake_color = _ColorButton(p["stake_color"], optional=True)
        self.stake_width = self._metres(p["stake_width"], 0.05, 50.0)
        form.addRow(_t("Stake colour:"), self.stake_color)
        form.addRow(_t("Stake width:"), self.stake_width)
        form.addRow(_t("Direction:"), self.direction)

        self.side = QComboBox()
        self.side.addItem(_t("left"), "left")
        self.side.addItem(_t("right"), "right")
        self.side.setCurrentIndex(0 if p["side"] == "left" else 1)
        self.prefix = QLineEdit(p["prefix"])
        self.label_align = QComboBox()
        for text, value in ((_t("in line with the stake"), "stake"),
                            (_t("along the route"), "road"),
                            (_t("horizontal"), "horizontal")):
            self.label_align.addItem(text, value)
        self.label_align.setCurrentIndex(
            max(0, self.label_align.findData(p["label_align"])))
        self.text_size = QSpinBox()
        self.text_size.setRange(6, 48)
        self.text_size.setValue(int(p["text_size"]))
        self.text_bold = QCheckBox(_t("Bold"))
        self.text_bold.setChecked(bool(p["text_bold"]))
        self.text_color = _ColorButton(p["text_color"])
        self.text_bg = _ColorButton(p["text_bg"], optional=True)
        self.text_bg_opacity = self._percent(p["text_bg_opacity"])
        self.sheet_text_mm = QDoubleSpinBox()
        self.sheet_text_mm.setRange(1.0, 20.0)
        self.sheet_text_mm.setSingleStep(0.5)
        self.sheet_text_mm.setDecimals(1)
        self.sheet_text_mm.setSuffix(" mm")
        self.sheet_text_mm.setValue(float(p["sheet_text_mm"]))
        self.ground_text = QCheckBox(
            _t("Write them on the ground as geometry"))
        self.ground_text.setChecked(bool(p["ground_text"]))
        self.ground_text.setToolTip(_t(
            "The labels are drawn over the view and printed on the sheets "
            "(IngeTrazo 0.6.2 or later), only where this extension is "
            "installed. Written on the ground they are part of the model: "
            "any IngeTrazo shows them, in images and exports too."))
        self.ground_text_height = self._metres(
            p["ground_text_height"], 0.1, 500.0)
        self.ground_text_height.setEnabled(self.ground_text.isChecked())
        self.ground_text.toggled.connect(self.ground_text_height.setEnabled)
        labels_box = QGroupBox(_t("Labels"))
        form = QFormLayout(labels_box)
        form.addRow(_t("Labels on the:"), self.side)
        form.addRow(_t("Lying:"), self.label_align)
        form.addRow(_t("Prefix:"), self.prefix)
        size_row = QHBoxLayout()
        size_row.addWidget(self.text_size)
        size_row.addWidget(self.text_bold)
        form.addRow(_t("Text size:"), size_row)
        form.addRow(_t("On sheets:"), self.sheet_text_mm)
        form.addRow(_t("Text colour:"), self.text_color)
        form.addRow(_t("Background:"), self.text_bg)
        form.addRow(_t("Background opacity:"), self.text_bg_opacity)
        form.addRow(self.ground_text)
        form.addRow(_t("Letter height:"), self.ground_text_height)

        self.road = QGroupBox(_t("Draw the strip (road, path, canal…)"))
        self.road.setCheckable(True)
        self.road.setChecked(bool(p["road"]))
        self.road_width = self._metres(p["road_width"], 0.5, 200.0)
        self.road_color = _ColorButton(p["road_color"])
        self.road_opacity = self._percent(p["road_opacity"])
        self.replace_path = QCheckBox(
            _t("Replace the traced path by the strip"))
        self.replace_path.setChecked(bool(p["replace_path"]))
        self.replace_path.setEnabled(path is not None)
        form = QFormLayout(self.road)
        form.addRow(_t("Width:"), self.road_width)
        form.addRow(_t("Colour:"), self.road_color)
        form.addRow(_t("Opacity:"), self.road_opacity)
        form.addRow(self.replace_path)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        buttons = QHBoxLayout()
        for text, slot in ((_t("Generate"), self.generate),
                           (_t("Remove"), self.remove),
                           (_t("Export CSV…"), self.export),
                           (_t("Close"), self.close)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addWidget(head)
        layout.addWidget(stations_box)
        layout.addWidget(labels_box)
        layout.addWidget(self.road)
        layout.addWidget(self.note)
        layout.addLayout(buttons)

    @staticmethod
    def _metres(value, low, high) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(low, high)
        box.setDecimals(2)
        box.setSuffix(" m")
        box.setValue(float(value))
        return box

    @staticmethod
    def _percent(value) -> QSpinBox:
        box = QSpinBox()
        box.setRange(0, 100)
        box.setSuffix(" %")
        box.setValue(int(value))
        return box

    def params(self) -> dict | None:
        try:
            start = parse_station(self.start.text())
        except ValueError:
            self.note.setText(_t("Write the station as 12+350 or as metres."))
            return None
        return {"start": start, "interval": self.interval.value(),
                "label_every": self.label_every.value(),
                "tick": self.tick.value(),
                "stake_color": self.stake_color.rgb,
                "stake_width": self.stake_width.value(),
                "side": self.side.currentData(),
                "reverse": bool(self.direction.currentData()),
                "text_size": self.text_size.value(),
                "text_bold": self.text_bold.isChecked(),
                "text_color": self.text_color.rgb or DEFAULTS["text_color"],
                "text_bg": self.text_bg.rgb,
                "text_bg_opacity": self.text_bg_opacity.value(),
                "prefix": self.prefix.text(),
                "label_align": self.label_align.currentData(),
                "ground_text": self.ground_text.isChecked(),
                "ground_text_height": self.ground_text_height.value(),
                "sheet_text_mm": self.sheet_text_mm.value(),
                "road": self.road.isChecked(),
                "road_width": self.road_width.value(),
                "road_color": self.road_color.rgb or DEFAULTS["road_color"],
                "road_opacity": self.road_opacity.value(),
                "replace_path": self.replace_path.isChecked()}

    def _run(self, mutate, drop_path: bool = False) -> None:
        from core.history import (CompoundCommand, DeleteGeoPathsCommand,
                                  SnapshotImport)

        command = SnapshotImport(mutate)
        scene = self.viewport.scene
        if drop_path and self.path is not None \
                and self.path in scene.geo_paths:
            # one step: Undo brings the path back with the marks gone
            command = CompoundCommand(
                [command, DeleteGeoPathsCommand([self.path])])
            self.replace_path.setEnabled(False)
        self.viewport.history.execute(command)
        self.viewport.notify_scene_changed()
        self.viewport.update()

    def generate(self) -> None:
        params = self.params()
        if params is None:
            return
        made: list = []
        self._run(lambda scene: made.extend(build(scene, self.axis, params)),
                  drop_path=params["road"] and params["replace_path"])
        self.marks = made
        if made:
            self.note.setText(_t(
                "{n} stations marked, from {a} to {b}.", n=len(made),
                a=label(made[0][0]), b=label(made[-1][0])))

    def remove(self) -> None:
        scene = self.viewport.scene
        if not _own_groups(scene) and not any(
                getattr(lab, "layer", None) == NAME
                for lab in scene.text_labels):
            self.note.setText(_t("There is no stationing to remove."))
            return
        self._run(remove)
        self.marks = []
        self.note.setText(_t("Stationing removed."))

    def export(self) -> None:
        params = self.params()
        if params is None:
            return
        axis = list(reversed(self.axis)) if params["reverse"] else self.axis
        marks = stations(axis, params["start"], params["interval"])
        path, _ = QFileDialog.getSaveFileName(
            self, _t("Export CSV…"), "progresivas.csv", _t("Stations (*.csv)"))
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            csv.writer(handle).writerows(csv_rows(self.viewport.scene, marks))
        self.note.setText(_t("Saved {path}", path=path))


class _AutoColor(QWidget):
    """A colour of one station; unset, the general one applies."""

    changed = Signal(object)              # [r, g, b], or None for automatic

    def __init__(self) -> None:
        super().__init__()
        self.rgb = None
        self.button = QPushButton()
        self.button.clicked.connect(self._choose)
        self.reset = QToolButton()
        self.reset.setText("×")
        self.reset.setToolTip(_t("Back to automatic"))
        self.reset.clicked.connect(self._clear)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.button, 1)
        row.addWidget(self.reset)
        self.set(None)

    def set(self, rgb) -> None:
        self.rgb = list(rgb) if rgb else None
        self.reset.setEnabled(self.rgb is not None)
        if self.rgb is None:
            self.button.setText(_t("Auto"))
            self.button.setStyleSheet("")
            return
        r, g, b = self.rgb
        self.button.setText(_t("Choose…"))
        ink = "#000" if (r * 299 + g * 587 + b * 114) / 1000 > 140 else "#fff"
        self.button.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); color: {ink};")

    def _choose(self) -> None:
        chosen = QColorDialog.getColor(
            QColor(*(self.rgb or [255, 255, 255])), self)
        if chosen.isValid():
            self.set([chosen.red(), chosen.green(), chosen.blue()])
            self.changed.emit(self.rgb)

    def _clear(self) -> None:
        self.set(None)
        self.changed.emit(None)


class _Panel(QWidget):
    """The stations of the document, to edit one by one: the text of a
    label, whether label and stake show, the stake's length, the colours."""

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.dock = None
        self.highlight: list = []         # world points ringed in the view
        self.scene_shown = None
        self._group = None                # the stationing the list shows
        self._rows: list = []             # dicts: key, station, point, major…
        self._overrides: dict = {}
        self._dialog = None

        settings = QPushButton(_t("Settings…"))
        settings.clicked.connect(self._open_settings)
        self.count = QLabel("")
        top = QHBoxLayout()
        top.addWidget(settings)
        top.addWidget(self.count, 1)
        self.only = QCheckBox(_t("Only labelled or edited"))
        self.only.toggled.connect(lambda _on: self.refresh(force=True))

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [_t("Station"), _t("Label"), _t("Stake")])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # the label is written in its cell, the stake ticked in its own
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked
                                   | QAbstractItemView.EditKeyPressed)
        self.table.itemChanged.connect(self._cell_changed)
        self.table.setToolTip(_t(
            "Double-click a label to write it; untick a stake to hide it."))
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)

        self.box = QGroupBox(_t("Selected station"))
        self.text = QLineEdit()
        self.text.editingFinished.connect(self._text_edited)
        self.show_label = QCheckBox(_t("Show the label"))
        self.show_label.clicked.connect(self._label_toggled)
        self.show_stake = QCheckBox(_t("Show the stake"))
        self.show_stake.clicked.connect(self._stake_toggled)
        self.tick = QDoubleSpinBox()
        self.tick.setRange(0.0, 500.0)
        self.tick.setDecimals(2)
        self.tick.setSuffix(" m")
        self.tick.setSpecialValueText(_t("automatic"))
        self.tick.editingFinished.connect(self._tick_edited)
        self.text_color = _AutoColor()
        self.text_bg = _AutoColor()
        self.stake_color = _AutoColor()
        for widget, field in ((self.text_color, "text_color"),
                              (self.text_bg, "text_bg"),
                              (self.stake_color, "stake_color")):
            widget.changed.connect(
                lambda rgb, f=field: self._apply({f: rgb}))
        restore = QPushButton(_t("Restore"))
        restore.setToolTip(_t("Undo every edit of the selected stations"))
        restore.clicked.connect(lambda: self._apply(None))
        restore_all = QPushButton(_t("Restore all"))
        restore_all.clicked.connect(self._restore_all)
        form = QFormLayout(self.box)
        form.addRow(_t("Text:"), self.text)
        form.addRow(self.show_label)
        form.addRow(_t("Text colour:"), self.text_color)
        form.addRow(_t("Background:"), self.text_bg)
        form.addRow(self.show_stake)
        form.addRow(_t("Stake length:"), self.tick)
        form.addRow(_t("Stake colour:"), self.stake_color)
        buttons = QHBoxLayout()
        buttons.addWidget(restore)
        buttons.addWidget(restore_all)
        form.addRow(buttons)

        self.note = QLabel(_t(
            "Double-click a label to write it. To change several at once, "
            "select them and use the box above."))
        self.note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.only)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.box)
        layout.addWidget(self.note)
        self.refresh(force=True)

    # ---- the list -----------------------------------------------------------
    def refresh(self, force: bool = False) -> None:
        """Show the stationing of the document in front. Called on every
        change of the document: nothing to do unless the stationing itself
        was replaced."""
        scene = self.app.scene
        group = next(iter(_own_groups(scene)), None)
        if group is self._group and scene is self.scene_shown and not force:
            return
        self._group, self.scene_shown = group, scene
        selected = set(self._keys())
        data = (group.ext.get(KEY) or {}) if group is not None else {}
        axis = data.get("axis") or []
        self._overrides = {k: dict(v) for k, v in
                           (data.get("overrides") or {}).items()}
        self._rows = []
        if len(axis) >= 2:
            p = {**DEFAULTS, **{k: data[k] for k in DEFAULTS if k in data}}
            shown = {row[6]: row[3] for row in data.get("labels") or []
                     if len(row) > 6}
            run = [tuple(pt) for pt in axis]
            if p["reverse"]:
                run.reverse()
            marks = stations(run, p["start"], p["interval"])
            for i, (station, (x, y, z), _dir) in enumerate(marks):
                key = station_key(station)
                self._rows.append({
                    "key": key, "station": station,
                    "point": (x, y, _ground(scene, x, y, z) + TICK_LIFT),
                    "major": is_major(station, p["label_every"])
                    or i in (0, len(marks) - 1),
                    "auto": p["prefix"] + label(station),
                    "text": shown.get(key)})

        table = self.table
        table.blockSignals(True)
        table.clearSelection()
        listed = [r for r in self._rows if not self.only.isChecked()
                  or r["text"] is not None or r["key"] in self._overrides]
        table.setRowCount(len(listed))
        for n, row in enumerate(listed):
            edited = row["key"] in self._overrides
            stake = self._overrides.get(row["key"], {}).get("stake", True)
            for column, text in enumerate((
                    label(row["station"]),
                    row["text"] if row["text"] is not None else "—", "")):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, row["key"])
                flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
                if column == 1:
                    flags |= Qt.ItemIsEditable
                elif column == 2:
                    flags |= Qt.ItemIsUserCheckable
                    item.setCheckState(Qt.Checked if stake else Qt.Unchecked)
                item.setFlags(flags)
                if edited:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                table.setItem(n, column, item)
            if row["key"] in selected:
                table.selectRow(n) if len(selected) == 1 else \
                    self._add_row_to_selection(n)
        table.blockSignals(False)
        self.count.setText(
            _t("{n} stations, {m} edited", n=len(self._rows),
               m=len(self._overrides)) if self._rows
            else _t("No stationing in this document yet."))
        self._selection_changed()

    def _cell_changed(self, item) -> None:
        """A label written in its cell, or a stake ticked in the list."""
        key = item.data(Qt.UserRole)
        row = self._row(key)
        if row is None:
            return
        if item.column() == 2:
            on = item.checkState() == Qt.Checked
            self._later({key: {"stake": None if on else False}})
            return
        text = item.text().strip()
        if text == (row["text"] if row["text"] is not None else "—"):
            return
        if text in ("", "—"):               # emptied: no label there
            change = {"text": None,
                      "label": None if not row["major"] else False}
        else:
            own = text != row["auto"]
            change = {"text": text if own else None,
                      "label": None if row["major"] else True}
        self._later({key: change})

    def _later(self, changes: dict) -> None:
        # the list is rebuilt by the edit: not while its cell is closing
        from PySide6.QtCore import QTimer
        QTimer.singleShot(
            0, self, lambda: apply_overrides(self.app.viewport, changes))

    def _add_row_to_selection(self, n: int) -> None:
        from PySide6.QtCore import QItemSelectionModel
        model = self.table.selectionModel()
        model.select(self.table.model().index(n, 0),
                     QItemSelectionModel.Select | QItemSelectionModel.Rows)

    def _keys(self) -> list:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.table.item(r, 0).data(Qt.UserRole) for r in rows
                if self.table.item(r, 0) is not None]

    def _row(self, key):
        return next((r for r in self._rows if r["key"] == key), None)

    def _selection_changed(self) -> None:
        keys = self._keys()
        self.box.setEnabled(bool(keys))
        self.box.setTitle(
            _t("{n} selected stations", n=len(keys)) if len(keys) > 1
            else _t("Selected station"))
        self.highlight = [self._row(k)["point"] for k in keys
                          if self._row(k) is not None]
        first = self._row(keys[0]) if keys else None
        o = self._overrides.get(first["key"], {}) if first else {}
        self.text.setText(o.get("text", ""))
        self.text.setPlaceholderText(
            first["auto"] if first else _t("automatic"))
        self.show_label.setChecked(bool(first and first["text"] is not None))
        self.show_stake.setChecked(bool(o.get("stake", True)))
        self.tick.setValue(float(o.get("tick") or 0.0))
        self.text_color.set(o.get("text_color"))
        self.text_bg.set(o.get("text_bg"))
        self.stake_color.set(o.get("stake_color"))
        viewport = self.app.viewport
        if viewport is not None:
            viewport.update()

    def select_key(self, key) -> None:
        """A label was clicked in the view (``None``: it was let go, and
        the list keeps its selection -- the editor is still open on it)."""
        if key is None or self._row(key) is None:
            return
        if self.only.isChecked() and not any(
                self.table.item(n, 0).data(Qt.UserRole) == key
                for n in range(self.table.rowCount())):
            self.only.setChecked(False)
        for n in range(self.table.rowCount()):
            if self.table.item(n, 0).data(Qt.UserRole) == key:
                self.table.selectRow(n)
                self.table.scrollToItem(self.table.item(n, 0))
                break
        if self.dock is not None:
            self.app.show_panel(self.dock)

    # ---- the edits ------------------------------------------------------------
    def _apply(self, change, per_key=None) -> None:
        keys = self._keys()
        if not keys:
            return
        changes = {k: (per_key(k) if per_key else change) for k in keys}
        apply_overrides(self.app.viewport, changes)

    def _text_edited(self) -> None:
        keys = self._keys()
        if not keys:
            return
        value = self.text.text().strip() or None
        if value == self._overrides.get(keys[0], {}).get("text"):
            return                        # focus left, nothing typed

        def change(key):
            row = self._row(key)
            out = {"text": value}
            # a text written for a station that had no label shows it
            if value and row is not None and row["text"] is None:
                out["label"] = True
            return out
        self._apply(None, change)

    def _label_toggled(self, on: bool) -> None:
        # the same as it would be by itself is no edit at all
        self._apply(None, lambda key: {
            "label": None if (self._row(key) or {}).get("major") == on
            else on})

    def _stake_toggled(self, on: bool) -> None:
        self._apply({"stake": None if on else False})

    def _tick_edited(self) -> None:
        keys = self._keys()
        value = self.tick.value() or None
        if keys and value != self._overrides.get(keys[0], {}).get("tick"):
            self._apply({"tick": value})

    def _restore_all(self) -> None:
        if self._overrides:
            apply_overrides(self.app.viewport,
                            {k: None for k in self._overrides})

    def _open_settings(self) -> None:
        self._dialog = open_dialog(self.app.viewport)


def open_dialog(viewport):
    """The settings of the whole stationing, for the route selected (or
    the one already stationed). Returns the dialog, or ``None``."""
    from georef.geopath import GeoPath

    scene = viewport.scene
    axis, description = find_axis(scene)
    if axis is None:
        viewport.flash_status(description, 5000)
        return None
    paths = [e for e in scene.selection if isinstance(e, GeoPath)] \
        or (list(scene.geo_paths) if len(scene.geo_paths) == 1
            and not scene.selection else [])
    dialog = _Dialog(viewport, axis, description, paths[0] if paths else None)
    dialog.setModal(False)
    dialog.show()
    return dialog


class ProgresivasTool(Tool):
    name = _t("Stationing…")
    shortcut = None
    description = _t("Mark stations (0+020, 0+040…) along the selected route.")

    def on_activate(self, viewport):
        self._dialog = open_dialog(viewport)   # kept alive while it is open
        if _panel is not None and _panel.dock is not None:
            _panel.app.show_panel(_panel.dock)

    def on_deactivate(self, viewport):
        pass
