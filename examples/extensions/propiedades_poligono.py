# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rony Leonel Janampa Monago
# Adapted to IngeTrazo's extension API (selection, holes, composite
# sections, document units, translations) by the IngeTrazo maintainers.
"""Polygon properties — area, centroid and second moments of the selected faces.

Select one face (or several faces in the same plane: a section drawn in
pieces) and run Extensions ▸ Polygon properties, or right-click ▸ Polygon
properties. Read-only: it never touches the document or the undo history.

What it reports, in the document's units: area, perimeter, centroid (in the
face's plane and in the model), second moments Ix, Iy, Ixy about the
centroid and about the model's axes, principal moments I1, I2 and their
angle, radii of gyration and the local bounding box. Holes count: a slab
with an opening, or a hollow section, gives its net properties.

The plane's axes are the drawing's: u follows the red axis (green when the
face faces red), v = normal × u. On a floor, Ix is about an axis parallel
to red, as a structural engineer reads it.

Contributed by Rony Leonel Janampa Monago (issue #229), MIT licence.
"""
from __future__ import annotations

import math

KEY = "propiedades_poligono"

_TEXTS = {
    "es": {
        "Polygon properties": "Propiedades del polígono",
        "Area, centroid and second moments of the selected faces.":
            "Área, centroide y momentos de segundo orden de las caras seleccionadas.",
        "Select a face (or several faces in one plane) first.":
            "Primero seleccione una cara (o varias caras en un mismo plano).",
        "The selected faces are not in one plane.":
            "Las caras seleccionadas no están en un mismo plano.",
        "The polygon is degenerate (area ≈ 0).":
            "El polígono es degenerado (área ≈ 0).",
        "Faces": "Caras",
        "Vertices": "Vértices",
        "Holes": "Huecos",
        "Area": "Área",
        "Perimeter": "Perímetro",
        "Centroid": "Centroide",
        "in the face's plane": "en el plano de la cara",
        "in the model": "en el modelo",
        "About the centroid": "Respecto al centroide",
        "About the model's axes (projected on the plane)":
            "Respecto a los ejes del modelo (proyectados al plano)",
        "Principal moments": "Momentos principales",
        "angle of I1 from u": "ángulo de I1 desde u",
        "Radii of gyration": "Radios de giro",
        "Bounding box in the plane": "Caja envolvente en el plano",
        "Plane": "Plano",
        "normal": "normal",
        "Copy": "Copiar",
        "Close": "Cerrar",
        "Copied to the clipboard.": "Copiado al portapapeles.",
        "Contributed by Rony Leonel Janampa Monago.":
            "Aporte de Rony Leonel Janampa Monago.",
    },
    "pt-BR": {
        "Polygon properties": "Propriedades do polígono",
        "Area, centroid and second moments of the selected faces.":
            "Área, centroide e momentos de segunda ordem das faces selecionadas.",
        "Select a face (or several faces in one plane) first.":
            "Selecione primeiro uma face (ou várias faces num mesmo plano).",
        "The selected faces are not in one plane.":
            "As faces selecionadas não estão num mesmo plano.",
        "The polygon is degenerate (area ≈ 0).":
            "O polígono é degenerado (área ≈ 0).",
        "Faces": "Faces",
        "Vertices": "Vértices",
        "Holes": "Furos",
        "Area": "Área",
        "Perimeter": "Perímetro",
        "Centroid": "Centroide",
        "in the face's plane": "no plano da face",
        "in the model": "no modelo",
        "About the centroid": "Em relação ao centroide",
        "About the model's axes (projected on the plane)":
            "Em relação aos eixos do modelo (projetados no plano)",
        "Principal moments": "Momentos principais",
        "angle of I1 from u": "ângulo de I1 a partir de u",
        "Radii of gyration": "Raios de giração",
        "Bounding box in the plane": "Caixa envolvente no plano",
        "Plane": "Plano",
        "normal": "normal",
        "Copy": "Copiar",
        "Close": "Fechar",
        "Copied to the clipboard.": "Copiado para a área de transferência.",
        "Contributed by Rony Leonel Janampa Monago.":
            "Contribuição de Rony Leonel Janampa Monago.",
    },
    "it": {
        "Polygon properties": "Proprietà del poligono",
        "Area, centroid and second moments of the selected faces.":
            "Area, baricentro e momenti del secondo ordine delle facce selezionate.",
        "Select a face (or several faces in one plane) first.":
            "Seleziona prima una faccia (o più facce sullo stesso piano).",
        "The selected faces are not in one plane.":
            "Le facce selezionate non sono sullo stesso piano.",
        "The polygon is degenerate (area ≈ 0).":
            "Il poligono è degenere (area ≈ 0).",
        "Faces": "Facce",
        "Vertices": "Vertici",
        "Holes": "Fori",
        "Area": "Area",
        "Perimeter": "Perimetro",
        "Centroid": "Baricentro",
        "in the face's plane": "nel piano della faccia",
        "in the model": "nel modello",
        "About the centroid": "Rispetto al baricentro",
        "About the model's axes (projected on the plane)":
            "Rispetto agli assi del modello (proiettati sul piano)",
        "Principal moments": "Momenti principali",
        "angle of I1 from u": "angolo di I1 da u",
        "Radii of gyration": "Raggi d'inerzia",
        "Bounding box in the plane": "Riquadro di delimitazione nel piano",
        "Plane": "Piano",
        "normal": "normale",
        "Copy": "Copia",
        "Close": "Chiudi",
        "Copied to the clipboard.": "Copiato negli appunti.",
        "Contributed by Rony Leonel Janampa Monago.":
            "Contributo di Rony Leonel Janampa Monago.",
    },
    "zh-CN": {
        "Polygon properties": "多边形属性",
        "Area, centroid and second moments of the selected faces.":
            "所选面的面积、形心和二阶矩。",
        "Select a face (or several faces in one plane) first.":
            "请先选择一个面（或同一平面上的多个面）。",
        "The selected faces are not in one plane.": "所选的面不在同一平面上。",
        "The polygon is degenerate (area ≈ 0).": "多边形退化（面积 ≈ 0）。",
        "Faces": "面",
        "Vertices": "顶点",
        "Holes": "孔洞",
        "Area": "面积",
        "Perimeter": "周长",
        "Centroid": "形心",
        "in the face's plane": "在面的平面内",
        "in the model": "在模型中",
        "About the centroid": "关于形心",
        "About the model's axes (projected on the plane)": "关于模型坐标轴（投影到平面）",
        "Principal moments": "主惯性矩",
        "angle of I1 from u": "I1 与 u 的夹角",
        "Radii of gyration": "回转半径",
        "Bounding box in the plane": "平面内的包围盒",
        "Plane": "平面",
        "normal": "法线",
        "Copy": "复制",
        "Close": "关闭",
        "Copied to the clipboard.": "已复制到剪贴板。",
        "Contributed by Rony Leonel Janampa Monago.": "由 Rony Leonel Janampa Monago 贡献。",
    },
    "id": {
        "Polygon properties": "Properti poligon",
        "Area, centroid and second moments of the selected faces.":
            "Luas, titik berat, dan momen orde kedua dari muka yang dipilih.",
        "Select a face (or several faces in one plane) first.":
            "Pilih dulu satu muka (atau beberapa muka dalam satu bidang).",
        "The selected faces are not in one plane.":
            "Muka yang dipilih tidak berada dalam satu bidang.",
        "The polygon is degenerate (area ≈ 0).": "Poligon degenerasi (luas ≈ 0).",
        "Faces": "Muka",
        "Vertices": "Titik sudut",
        "Holes": "Lubang",
        "Area": "Luas",
        "Perimeter": "Keliling",
        "Centroid": "Titik berat",
        "in the face's plane": "pada bidang muka",
        "in the model": "pada model",
        "About the centroid": "Terhadap titik berat",
        "About the model's axes (projected on the plane)":
            "Terhadap sumbu model (diproyeksikan ke bidang)",
        "Principal moments": "Momen utama",
        "angle of I1 from u": "sudut I1 dari u",
        "Radii of gyration": "Jari-jari girasi",
        "Bounding box in the plane": "Kotak pembatas pada bidang",
        "Plane": "Bidang",
        "normal": "normal",
        "Copy": "Salin",
        "Close": "Tutup",
        "Copied to the clipboard.": "Disalin ke papan klip.",
        "Contributed by Rony Leonel Janampa Monago.":
            "Kontribusi dari Rony Leonel Janampa Monago.",
    },
}


def _tr(text: str) -> str:
    """``text`` in the interface language."""
    try:
        from core.i18n import current_language
        lang = current_language()
    except Exception:  # noqa: BLE001
        lang = "en"
    return _TEXTS.get(lang, {}).get(text, text)


class PolygonError(Exception):
    """A user-facing refusal (nothing selected, faces in different planes)."""


# ---------------------------------------------------------------------------
# 1. The mathematics — plain Python, no document: Green's theorem over
#    closed loops. Rony's formulas, extended to several loops with a sign:
#    outer boundaries add, holes subtract.
# ---------------------------------------------------------------------------

def _loop_sums(pts):
    """Signed sums of one closed loop ``[(u, v), ...]`` in its own winding:
    (2A, Sx·6, Sy·6, Ix·12, Iy·12, Ixy·24, perimeter), all about the
    plane's origin. Counter-clockwise → positive area."""
    a2 = sx = sy = ix = iy = ixy = per = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        c = x0 * y1 - x1 * y0
        a2 += c
        sx += (x0 + x1) * c
        sy += (y0 + y1) * c
        ix += (y0 * y0 + y0 * y1 + y1 * y1) * c
        iy += (x0 * x0 + x0 * x1 + x1 * x1) * c
        # Coefficients 1, 2, 2, 1 — checked against a unit square (Ixy = 1/4).
        ixy += (x0 * y1 + 2 * x0 * y0 + 2 * x1 * y1 + x1 * y0) * c
        per += math.hypot(x1 - x0, y1 - y0)
    return a2, sx, sy, ix, iy, ixy, per


def region_properties(outers, holes=()):
    """Properties of a planar region: ``outers`` and ``holes`` are lists of
    loops ``[(u, v), ...]`` (the loop closes itself; do not repeat the first
    point). Whatever their winding, an outer loop adds and a hole
    subtracts. Returns a dict in the loops' units (m → m², m⁴)."""
    tot = [0.0] * 6
    per = 0.0
    n_vert = 0
    for sign, loops in ((1.0, outers), (-1.0, holes)):
        for loop in loops:
            pts = [(float(x), float(y)) for (x, y) in loop]
            if len(pts) < 3:
                continue
            n_vert += len(pts)
            s = _loop_sums(pts)
            k = sign * (1.0 if s[0] >= 0.0 else -1.0)   # own winding → sign
            for i in range(6):
                tot[i] += k * s[i]
            per += s[6]
    a = 0.5 * tot[0]
    if a < 1e-12:
        raise PolygonError(_tr("The polygon is degenerate (area ≈ 0)."))
    cx, cy = tot[1] / (6.0 * a), tot[2] / (6.0 * a)
    ix_o, iy_o, ixy_o = tot[3] / 12.0, tot[4] / 12.0, tot[5] / 24.0
    # Parallel axis theorem: everything to the centroid.
    ixc = ix_o - a * cy * cy
    iyc = iy_o - a * cx * cx
    ixyc = ixy_o - a * cx * cy
    # Principal moments = eigenvalues of [[Ixc, Ixyc], [Ixyc, Iyc]].
    avg, diff = 0.5 * (ixc + iyc), 0.5 * (ixc - iyc)
    r = math.hypot(diff, ixyc)
    # The axis of I1, from u. (The original had +2·Ixy here, which put the
    # axis of a bar at 30° at +60°, not across the bar at −60°.)
    theta = 0.5 * math.atan2(-2.0 * ixyc, ixc - iyc)
    if theta <= -math.pi / 2 + 1e-12:
        theta += math.pi                   # an axis: (−90°, 90°]
    us = [p[0] for lp in outers for p in lp]
    vs = [p[1] for lp in outers for p in lp]
    return {
        "vertices": n_vert,
        "area": a,
        "perimeter": per,
        "centroid": (cx, cy),
        "Ix_origin": ix_o, "Iy_origin": iy_o, "Ixy_origin": ixy_o,
        "Ix_centroid": ixc, "Iy_centroid": iyc, "Ixy_centroid": ixyc,
        "I1": avg + r, "I2": avg - r, "theta": theta,
        "rx": math.sqrt(max(ixc, 0.0) / a),
        "ry": math.sqrt(max(iyc, 0.0) / a),
        "bbox": (min(us), min(vs), max(us), max(vs)),
    }


def polygon_properties(pts):
    """Rony's original entry point: one simple polygon ``[(x, y), ...]``."""
    return region_properties([pts])


# ---------------------------------------------------------------------------
# 2. Reading the selection
# ---------------------------------------------------------------------------

def _selected_faces(scene):
    from core.mesh import Face
    faces = scene.mesh.faces
    return [e for e in scene.selection if isinstance(e, Face) and e in faces]


def faces_plane(faces):
    """``(origin, u, v, n)`` of the plane shared by ``faces``: the model's
    origin projected onto it, and the drawing's axes in it."""
    from PySide6.QtGui import QVector3D
    from core.axes import plane_axes
    n = QVector3D(faces[0].normal())
    if n.length() < 1e-9:
        raise PolygonError(_tr("The polygon is degenerate (area ≈ 0)."))
    n = n.normalized()
    p0 = QVector3D(faces[0].vertices[0])
    d0 = QVector3D.dotProduct(p0, n)
    for f in faces[1:]:
        fn = QVector3D(f.normal())
        if fn.length() < 1e-9:
            continue
        if abs(abs(QVector3D.dotProduct(fn.normalized(), n)) - 1.0) > 1e-6 or \
                any(abs(QVector3D.dotProduct(QVector3D(p), n) - d0) > 1e-4
                    for p in f.vertices):
            raise PolygonError(_tr("The selected faces are not in one plane."))
    u, v = plane_axes(n)
    return n * d0, u, v, n


def selection_properties(scene):
    """``(props, plane, counts)`` for the faces selected in ``scene``."""
    from PySide6.QtGui import QVector3D
    faces = _selected_faces(scene)
    if not faces:
        raise PolygonError(_tr("Select a face (or several faces in one plane) first."))
    o, u, v, n = faces_plane(faces)

    def uv(p):
        d = QVector3D(p) - o
        return (QVector3D.dotProduct(d, u), QVector3D.dotProduct(d, v))

    outers = [[uv(p) for p in f.vertices] for f in faces]
    holes = [[uv(p) for p in h] for f in faces for h in f.holes]
    props = region_properties(outers, holes)
    cu, cv = props["centroid"]
    props["centroid_world"] = o + u * cu + v * cv
    return props, (o, u, v, n), (len(faces), len(holes))


# ---------------------------------------------------------------------------
# 3. The report
# ---------------------------------------------------------------------------

def format_report(props, plane, counts) -> str:
    from core import units
    unit = units.model_unit()
    metric = unit in ("m", "cm", "mm")
    f = {"m": 1.0, "cm": 100.0, "mm": 1000.0}.get(unit, 1.0)
    L = units.fmt_len_fine
    A = units.fmt_area

    def moment(val):
        if metric:
            return f"{val * f ** 4:.6g} {unit}⁴"
        in4 = 0.0254 ** 4
        return f"{val / in4:.6g} in⁴"

    _o, u, v, n = plane
    cw = props["centroid_world"]
    cu, cv = props["centroid"]
    x0, y0, x1, y1 = props["bbox"]
    t = _tr
    in_plane, in_model = t("in the face's plane"), t("in the model")
    about_axes = t("About the model's axes (projected on the plane)")
    rows = [
        t("Polygon properties"),
        "=" * 56,
        f"{t('Faces')}: {counts[0]}    {t('Holes')}: {counts[1]}    "
        f"{t('Vertices')}: {props['vertices']}",
        f"{t('Plane')}: u = ({u.x():.3f}, {u.y():.3f}, {u.z():.3f})  "
        f"v = ({v.x():.3f}, {v.y():.3f}, {v.z():.3f})  "
        f"{t('normal')} = ({n.x():.3f}, {n.y():.3f}, {n.z():.3f})",
        "",
        f"{t('Area')}:       {A(props['area'])}",
        f"{t('Perimeter')}:  {L(props['perimeter'])}",
        "",
        f"{t('Centroid')} ({in_plane}):",
        f"  u = {L(cu)}    v = {L(cv)}",
        f"{t('Centroid')} ({in_model}):",
        f"  x = {L(cw.x())}    y = {L(cw.y())}    z = {L(cw.z())}",
        "",
        f"{t('About the centroid')}:",
        f"  Ix  = {moment(props['Ix_centroid'])}",
        f"  Iy  = {moment(props['Iy_centroid'])}",
        f"  Ixy = {moment(props['Ixy_centroid'])}",
        f"{about_axes}:",
        f"  Ix  = {moment(props['Ix_origin'])}",
        f"  Iy  = {moment(props['Iy_origin'])}",
        f"  Ixy = {moment(props['Ixy_origin'])}",
        "",
        f"{t('Principal moments')}:",
        f"  I1 = {moment(props['I1'])}",
        f"  I2 = {moment(props['I2'])}",
        f"  θ  = {math.degrees(props['theta']):.4g}°  ({t('angle of I1 from u')})",
        "",
        f"{t('Radii of gyration')}:",
        f"  rx = {L(props['rx'])}    ry = {L(props['ry'])}",
        "",
        f"{t('Bounding box in the plane')}:",
        f"  u: {L(x0)} … {L(x1)}   (Δ {L(x1 - x0)})",
        f"  v: {L(y0)} … {L(y1)}   (Δ {L(y1 - y0)})",
        "",
        t("Contributed by Rony Leonel Janampa Monago."),
    ]
    return "\n".join(rows)


def show_properties(viewport) -> None:
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QPlainTextEdit,
                                   QVBoxLayout)
    try:
        props, plane, counts = selection_properties(viewport.scene)
    except PolygonError as exc:
        viewport.flash_status(f"{_tr('Polygon properties')}: {exc}", 6000)
        return
    text = format_report(props, plane, counts)
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(_tr("Polygon properties"))
    dlg.resize(620, 640)
    lay = QVBoxLayout(dlg)
    box = QPlainTextEdit(dlg)
    box.setReadOnly(True)
    box.setPlainText(text)
    box.setStyleSheet("font-family: monospace;")
    lay.addWidget(box)
    btns = QDialogButtonBox(dlg)
    copy = btns.addButton(_tr("Copy"), QDialogButtonBox.ActionRole)
    close = btns.addButton(_tr("Close"), QDialogButtonBox.RejectRole)

    def _copy():
        QGuiApplication.clipboard().setText(text)
        viewport.flash_status(_tr("Copied to the clipboard."), 3000)

    copy.clicked.connect(_copy)
    close.clicked.connect(dlg.reject)
    lay.addWidget(btns)
    from core import units
    viewport.flash_status(
        f"{_tr('Polygon properties')}: {_tr('Area')} {units.fmt_area(props['area'])}, "
        f"{_tr('Perimeter')} {units.fmt_len_fine(props['perimeter'])}", 5000)
    dlg.exec()


def setup(app) -> None:
    """Extensions ▸ Polygon properties, and the same entry in the viewport's
    right-click menu when faces are selected."""
    app.add_menu_action(
        _tr("Polygon properties"), lambda: show_properties(app.viewport),
        tip=_tr("Area, centroid and second moments of the selected faces."))

    def context(menu, selection) -> None:
        if not _selected_faces(app.viewport.scene):
            return
        menu.addSeparator()
        act = menu.addAction(_tr("Polygon properties"))
        act.triggered.connect(lambda _c=False: show_properties(app.viewport))

    app.add_context_menu(context)
