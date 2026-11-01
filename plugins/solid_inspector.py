# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Solid Inspector plugin — find out WHY a solid is not watertight, and
repair what can be repaired without guessing.

IngeTrazo's engine guarantees hermetic solids and its BIM layer only
reports a volume when the object is closed. When Model Info (or the BIM
tray) says "(not watertight)", this plugin answers the next question:
*where is the hole?*

One row per solid candidate (the geometry you are editing, plus every
group). For each: face/edge counts, verdict, a breakdown of the exact
problems, and the volume when the object is closed. **Highlight** selects
the offending edges right in the viewport (orange, like any selection),
so you can see the hole instead of hunting for it; **Next problem** walks
them one at a time and zooms the view onto each.

Diagnosis (per edge, counting non-interior incident faces):

- ``0`` faces  → a **stray edge**: loose drawing, not part of any surface.
- ``1`` face   → an **open border**: the rim of a hole in the skin.
- ``>2`` faces → **overconnected**: an internal wall / T-junction the
  boundary should not have.

And per face:

- **internal**: a second face over the same corners as another, or a
  partition whose every edge is overconnected — a wall inside the solid
  that is not marked as one (:func:`core.orient.orient_outward` marks the
  ones the engine builds itself).
- **reversed**: on a closed object, a face whose front looks inward — the
  faces the engine's own orientation pass would turn.

Watertight = every edge has exactly 2. The volume comes from
:func:`core.bim.face_set_volume` — the same computation behind the BIM
quantities, so this dialog and your takeoff can never disagree.

**Repair** (one undo step, also on a group you are not inside) does only
what has a single right answer: erases stray edges and duplicated faces,
closes holes whose rim is flat, marks partitions as interior and turns
reversed faces outward. A non-flat hole or an edge shared by two solids
needs a decision, so it stays listed for you.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QVector3D
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core import bim
from core.history import Command
from core.i18n import tr
from tools.base import Tool


# ---------------------------------------------------------------------------
# Diagnosis (pure data, no GUI — see tests/test_solid_inspector_plugin.py)
# ---------------------------------------------------------------------------

def _live(face) -> bool:
    """A face that is part of the skin (an interior partition is not)."""
    return not getattr(face, "interior", False)


def _steps(face):
    """Every boundary step of ``face`` as a pair of vertices."""
    for lp in (face.loop, *face.hole_loops):
        n = len(lp)
        for i in range(n):
            yield lp[i], lp[(i + 1) % n]


def _step_key(a, b) -> frozenset:
    return frozenset((id(a), id(b)))


def _face_key(face) -> tuple:
    """Same key ⇔ same corners, whatever the starting point or winding."""
    return (frozenset(id(v) for v in face.loop),
            frozenset(frozenset(id(v) for v in h) for h in face.hole_loops))


def internal_faces(mesh) -> list:
    """Faces inside the solid that are not marked as partitions.

    First every face repeating another one's corners (only the first copy
    stays: a doubled top is still a top, not two). Then, among the rest,
    every face whose edges ALL see more than two faces — a wall with skin
    on both of its sides."""
    seen: set = set()
    duplicates, rest = [], []
    for f in mesh.faces:
        if not _live(f):
            continue
        key = _face_key(f)
        if key in seen:
            duplicates.append(f)
        else:
            seen.add(key)
            rest.append(f)
    counts: dict = {}
    for f in rest:
        for a, b in _steps(f):
            k = _step_key(a, b)
            counts[k] = counts.get(k, 0) + 1
    walls = [f for f in rest
             if all(counts[_step_key(a, b)] > 2 for a, b in _steps(f))]
    return duplicates + walls


def _copy_faces(faces):
    """A throwaway mesh of ``faces``, and the original of each copied face —
    for asking a mutating pass what it WOULD do."""
    from core.mesh import Mesh
    copy = Mesh()
    origin = {}
    for f in faces:
        g = copy.add_face([v.position for v in f.loop],
                          [[v.position for v in h] for h in f.hole_loops])
        g.interior = f.interior
        origin[id(g)] = f
    return copy, origin


def reversed_faces(mesh) -> list:
    """The faces of a closed mesh whose front looks inward: exactly the ones
    :func:`core.orient.orient_outward` would turn. Asked on a copy, so
    inspecting never changes the model. An open mesh has no inside, so
    nothing on it is reversed."""
    from core.orient import (_face_components, _incoherent_edges, is_closed,
                             orient_outward)
    if not is_closed(mesh):
        return []
    # The parity pass costs seconds on thousands of faces, and almost every
    # piece is fine: one whose shared edges all agree and whose signed
    # volume is positive already looks out. Only the others are asked.
    pieces: dict = {}
    for f, c in _face_components(mesh).items():
        pieces.setdefault(c, []).append(f)
    suspect = []
    for faces in pieces.values():
        skin = [f for f in faces if _live(f)]
        if _incoherent_edges(skin) or _signed_volume(skin) <= 0.0:
            suspect.extend(faces)
    if not suspect:
        return []
    copy, origin = _copy_faces(suspect)
    return [origin[id(g)] for g in orient_outward(copy)]


def _signed_volume(faces) -> float:
    """Signed volume of ``faces`` as wound (positive = looking out). The
    partitions are skipped: they are not skin."""
    total = 0.0
    for f in faces:
        if not _live(f):
            continue
        for a, b, c in f.triangulate():
            total += QVector3D.dotProduct(a, QVector3D.crossProduct(b, c))
    return total / 6.0


def inspect_mesh(mesh) -> dict:
    """Classify every edge and face of *mesh* and compute the closed volume.

    Returns ``{"faces", "edges", "stray", "open", "over", "internal",
    "reversed", "watertight", "volume"}`` where the edge problems are lists
    of Edge objects, ``internal``/``reversed`` lists of Face objects and
    ``volume`` is in m³ (or ``None`` when the mesh is not closed, or
    closed with faces turned inward).
    """
    stray, open_borders, over = [], [], []
    for e in mesh.edges:
        n = sum(1 for f in e.faces if _live(f))
        if n == 0:
            stray.append(e)
        elif n == 1:
            open_borders.append(e)
        elif n > 2:
            over.append(e)

    watertight = (not stray and not open_borders and not over
                  and bool(mesh.faces))
    turned = reversed_faces(mesh)
    volume = None
    if watertight and not turned:
        # A reversed face makes the signed sum lie (a 2 m cube with its
        # top turned reads 2.667 m³), so a volume is only given once
        # every face looks out.
        volume = bim.face_set_volume([f for f in mesh.faces if _live(f)])

    return {
        "faces": len(mesh.faces),
        "edges": len(mesh.edges),
        "stray": stray,
        "open": open_borders,
        "over": over,
        "internal": internal_faces(mesh) if over else [],
        "reversed": turned,
        "watertight": watertight,
        "volume": volume,
    }


def is_sound(report: dict) -> bool:
    """Watertight AND every face looking out: a solid with nothing to fix."""
    return report["watertight"] and not report["reversed"]


def _problem_text(report: dict) -> str:
    """Human breakdown of the problems, empty string when there are none."""
    parts = []
    if report["open"]:
        parts.append(tr("{n} open borders", n=len(report["open"])))
    if report["stray"]:
        parts.append(tr("{n} stray edges", n=len(report["stray"])))
    if report["over"]:
        parts.append(tr("{n} overconnected", n=len(report["over"])))
    if report.get("internal"):
        parts.append(tr("{n} internal faces", n=len(report["internal"])))
    if report.get("reversed"):
        parts.append(tr("{n} reversed faces", n=len(report["reversed"])))
    return " · ".join(parts)


def _edge_clusters(edges) -> list:
    """``edges`` split into the runs that touch each other — a hole's whole
    rim is one problem, not one per edge."""
    parent: dict = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        parent[find(id(e.v0))] = find(id(e.v1))
    runs: dict = {}
    for e in edges:
        runs.setdefault(find(id(e.v0)), []).append(e)
    return list(runs.values())


#: How each kind of problem is named and coloured on screen, in the order
#: :func:`problem_items` walks them.
KINDS = {
    "open": ("Open border (hole)", QColor(230, 40, 40)),
    "stray": ("Stray edges", QColor(255, 140, 0)),
    "over": ("Overconnected edges", QColor(150, 60, 220)),
    "internal": ("Internal face", QColor(30, 130, 255)),
    "reversed": ("Reversed face", QColor(230, 0, 160)),
}


def problem_items(report: dict) -> list:
    """The problems one at a time, as ``{"kind", "ents"}`` dicts (``ents``
    the edges or faces to blame): each hole rim, each run of stray edges,
    each internal or reversed face, and each run of overconnected edges
    that no internal face explains — the edges of a doubled face or of an
    unmarked partition are ITS problem, solved with it."""
    items = []
    for key in ("open", "stray"):
        items.extend({"kind": key, "ents": run}
                     for run in _edge_clusters(report[key]))
    explained = {_step_key(a, b) for f in report.get("internal", ())
                 for a, b in _steps(f)}
    rest = [e for e in report["over"]
            if _step_key(e.v0, e.v1) not in explained]
    items.extend({"kind": "over", "ents": run}
                 for run in _edge_clusters(rest))
    for key in ("internal", "reversed"):
        items.extend({"kind": key, "ents": [f]} for f in report.get(key, ()))
    return items


def _item_points(item) -> list:
    pts = []
    for ent in item["ents"]:
        if hasattr(ent, "loop"):
            pts.extend(v.position for v in ent.loop)
        else:
            pts.extend((ent.v0.position, ent.v1.position))
    return pts


# ---------------------------------------------------------------------------
# Repair (mutates the mesh — run it through RepairSolidsCommand for undo)
# ---------------------------------------------------------------------------

def _border_loops(mesh, edges=None) -> list:
    """Closed rims of open borders (of ``edges`` only, when given), each as
    its vertex loop. A rim that branches (a vertex with more than two open
    edges) is skipped: which way it closes is a choice, not a repair."""
    open_edges = [e for e in (mesh.edges if edges is None else edges)
                  if sum(1 for f in e.faces if _live(f)) == 1]
    at: dict = {}
    for e in open_edges:
        at.setdefault(id(e.v0), []).append(e)
        at.setdefault(id(e.v1), []).append(e)
    used: set = set()
    loops = []
    for e in open_edges:
        if id(e) in used:
            continue
        used.add(id(e))
        start, cur = e.v0, e.v1
        loop = [start]
        ok = len(at[id(start)]) == 2
        while ok and cur is not start:
            ways = at[id(cur)]
            nxt = [x for x in ways if id(x) not in used]
            if len(ways) != 2 or not nxt:
                ok = False
                break
            loop.append(cur)
            used.add(id(nxt[0]))
            cur = nxt[0].v1 if nxt[0].v0 is cur else nxt[0].v0
        if ok and len(loop) >= 3:
            loops.append(loop)
    return loops


def _flat(points, tolerance: float) -> bool:
    """Do ``points`` lie on one plane (and span some area)?"""
    nx = ny = nz = 0.0
    n = len(points)
    for i in range(n):
        p, q = points[i], points[(i + 1) % n]
        nx += (p.y() - q.y()) * (p.z() + q.z())
        ny += (p.z() - q.z()) * (p.x() + q.x())
        nz += (p.x() - q.x()) * (p.y() + q.y())
    length = (nx * nx + ny * ny + nz * nz) ** 0.5
    if length < 1e-12:
        return False
    nx, ny, nz = nx / length, ny / length, nz / length
    c = [sum(p.x() for p in points) / n, sum(p.y() for p in points) / n,
         sum(p.z() for p in points) / n]
    return all(abs((p.x() - c[0]) * nx + (p.y() - c[1]) * ny
                   + (p.z() - c[2]) * nz) <= tolerance for p in points)


def _agree_with_neighbour(mesh, face) -> None:
    """Wind a new cap so it walks its rim against the face beside it — the
    way two faces of one skin meet — even where the mesh is still open and
    the orientation pass cannot decide."""
    a, b = face.loop[0], face.loop[1]
    edge = mesh.find_edge(a, b)
    other = next((f for f in (edge.faces if edge else ())
                  if f is not face and _live(f)), None)
    if other is None:
        return
    if any(x is a and y is b for x, y in _steps(other)):
        face.loop.reverse()


def _cap(mesh, loop):
    """Close the hole ``loop`` rims with a face, wound like its neighbours;
    ``None`` (and nothing done) when the rim is not flat."""
    from core.topology import _PLANAR_TOLERANCE
    pts = [v.position for v in loop]
    if not _flat(pts, _PLANAR_TOLERANCE):
        return None
    cap = mesh.add_face([QVector3D(p) for p in pts])
    _agree_with_neighbour(mesh, cap)
    return cap


def why_not_repairable(mesh, item) -> Optional[str]:
    """Why ``item`` has no single right repair, or ``None`` when it has."""
    kind = item["kind"]
    if kind == "open":
        loops = _border_loops(mesh, item["ents"])
        if len(loops) != 1 or len(loops[0]) != len(item["ents"]):
            return tr("This hole branches: close it by drawing its faces")
        from core.topology import _PLANAR_TOLERANCE
        if not _flat([v.position for v in loops[0]], _PLANAR_TOLERANCE):
            return tr("This hole is not flat: close it by drawing its faces")
    elif kind == "over":
        return tr("Edges shared by more than two faces: separate the "
                  "solids or erase a face by hand")
    return None


def repair_item(mesh, item) -> dict:
    """Repair ONE problem of :func:`problem_items`, in place. Returns the
    same counts as :func:`repair_mesh`; all zero when it had no single
    right repair (see :func:`why_not_repairable`)."""
    done = {"stray": 0, "duplicates": 0, "holes": 0, "partitions": 0,
            "reversed": 0}
    if why_not_repairable(mesh, item) is not None:
        return done
    kind, ents = item["kind"], item["ents"]
    if kind == "open":
        if _cap(mesh, _border_loops(mesh, ents)[0]) is not None:
            done["holes"] = 1
    elif kind == "stray":
        for e in ents:
            if not e.faces and e in mesh.edges:
                mesh.remove_edge(e)
                done["stray"] += 1
        mesh.prune_orphan_vertices()
    elif kind == "internal":
        face = ents[0]
        key = _face_key(face)
        if any(f is not face and _face_key(f) == key for f in mesh.faces):
            mesh.remove_face(face)
            done["duplicates"] = 1
        else:
            face.interior = True
            done["partitions"] = 1
    elif kind == "reversed":
        from core.mesh import turn_face_over
        turn_face_over(ents[0])
        mesh._winding_rev = getattr(mesh, "_winding_rev", 0) + 1
        done["reversed"] = 1
    return done


def repair_mesh(mesh) -> dict:
    """Fix what has one right answer, in place. Returns how many of each
    repair were made: ``{"stray", "duplicates", "holes", "partitions",
    "reversed"}``."""
    from core.orient import orient_outward
    done = {"stray": 0, "duplicates": 0, "holes": 0, "partitions": 0,
            "reversed": 0}

    # 1. Stray edges: no face at all (an edge holding only interior
    #    partitions is part of them, not loose drawing).
    for e in [e for e in mesh.edges if not e.faces]:
        mesh.remove_edge(e)
        done["stray"] += 1

    # 2. Duplicated faces: the second copy of the same corners.
    seen: set = set()
    for f in list(mesh.faces):
        key = _face_key(f)
        if key in seen:
            mesh.remove_face(f)
            done["duplicates"] += 1
        else:
            seen.add(key)

    # 3. Holes with a flat rim get their cap back.
    for loop in _border_loops(mesh):
        if _cap(mesh, loop) is not None:
            done["holes"] += 1

    # 4. The engine's own pass: partitions marked interior, the skin
    #    turned outward (on a closed mesh; an open one has no outside).
    before = {id(f) for f in mesh.faces if not _live(f)}
    flipped = orient_outward(mesh)
    done["reversed"] = len(flipped)
    done["partitions"] = sum(1 for f in mesh.faces
                             if not _live(f) and id(f) not in before)
    if flipped:
        mesh._winding_rev = getattr(mesh, "_winding_rev", 0) + 1

    mesh.prune_orphan_vertices()
    return done


class RepairSolidsCommand(Command):
    """Repair several meshes (the loose one, closed groups' prototypes) as
    ONE undo step. Snapshot undo per mesh: the repairs weld, split and
    turn too much for a clean inverse, and the snapshot keeps every Face
    object, so references held elsewhere stay valid."""

    def __init__(self, meshes, fix=None) -> None:
        self.meshes = list(meshes)
        #: ``fix(mesh) -> counts``: :func:`repair_mesh` unless one problem
        #: alone is being repaired (:func:`repair_item`).
        self.fix = fix or repair_mesh
        self.before: list = []
        self.after: list = []
        self.interior_before: list = []
        self.interior_after: list = []
        self.done: dict = {}

    @staticmethod
    def _interior(mesh) -> dict:
        # The snapshot does not carry the partition marks; they are a
        # repair's output, so undo must give them back too.
        return {f: f.interior for f in mesh.faces}

    def do(self, scene) -> None:
        if not self.after:
            total = {}
            for m in self.meshes:
                self.before.append(m.capture_state())
                self.interior_before.append(self._interior(m))
                for k, v in self.fix(m).items():
                    total[k] = total.get(k, 0) + v
                self.after.append(m.capture_state())
                self.interior_after.append(self._interior(m))
            self.done = total
        else:
            self._restore(scene, self.after, self.interior_after)
            return
        self._touch(scene)

    def undo(self, scene) -> None:
        self._restore(scene, self.before, self.interior_before)

    def _restore(self, scene, snaps, marks) -> None:
        for m, snap, flags in zip(self.meshes, snaps, marks):
            m.restore_state(snap)
            for f, value in flags.items():
                f.interior = value
            m._winding_rev = getattr(m, "_winding_rev", 0) + 1
        self._touch(scene)

    @staticmethod
    def _touch(scene) -> None:
        # Edges and faces the repair erased must not stay selected.
        alive = set(scene.mesh.edges) | set(scene.mesh.faces)
        for s in [s for s in scene.selection
                  if (hasattr(s, "v0") or hasattr(s, "loop"))
                  and s not in alive]:
            scene.selection.discard(s)
        from core.history import _dirty_group_chunks
        _dirty_group_chunks(scene)
        scene.version += 1


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

def _group_rows(scene) -> list:
    """One row per group mesh to inspect, nested groups included: the
    pieces of an imported model live one level down, inside a container
    whose own mesh is empty. Each row knows the top-level object (what a
    click selects from outside) and the matrix that places it.

    A component's instances share one mesh: it is listed once, under the
    first instance — repairing it repairs them all. Billboards (scale
    figures, 2D cut-out trees/people) are flat by design — listing them as
    "not watertight" would be noise in every single model."""
    rows, seen = [], {id(scene.mesh)}      # the open group: the live row

    def walk(g, top, path, base):
        if getattr(g, "billboard", False):
            return
        m = getattr(g, "xform", None)
        if base is not None:
            m = base if m is None else base * m
        name = path + [g.name]
        mesh = g.mesh
        hollow = (not mesh.faces and not mesh.edges
                  and getattr(g, "children", None))
        if not hollow and id(mesh) not in seen:
            seen.add(id(mesh))
            rows.append({"name": " ▸ ".join(name), "kind": "group",
                         "group": g, "top": top, "matrix": m,
                         "mesh": mesh})
        for child in getattr(g, "children", None) or ():
            walk(child, top, name, m)

    for g in scene.groups:
        walk(g, g, [], None)
    return rows


def _matrix_of(scene, group):
    """The world matrix placing ``group`` (``None`` = already in world
    coordinates), wherever it is nested."""
    if group is None:
        return None
    from core.group import iter_placements
    for top in scene.groups:
        for g, m in iter_placements(top):
            if g is group:
                return m
    return getattr(group, "xform", None)


def _frame(vp, pts) -> None:
    """Fly the camera onto world points ``pts``, with room around them: a
    single short edge framed edge to edge gives no idea of where in the
    model it is."""
    lo = QVector3D(min(p.x() for p in pts), min(p.y() for p in pts),
                   min(p.z() for p in pts))
    hi = QVector3D(max(p.x() for p in pts), max(p.y() for p in pts),
                   max(p.z() for p in pts))
    pad = max((hi - lo).length() * 0.75, 0.05)
    vp.camera.fit_box(lo - QVector3D(pad, pad, pad),
                      hi + QVector3D(pad, pad, pad))


_OK = QColor(76, 160, 92)          # a closed, sound solid
_BAD = QColor(214, 84, 56)         # an object with problems


def _chip(color: QColor) -> QLabel:
    """A rounded count tinted in ``color`` — the verdict at a glance."""
    chip = QLabel()
    r, g, b = color.red(), color.green(), color.blue()
    chip.setStyleSheet(
        f"QLabel {{ background: rgba({r}, {g}, {b}, 46);"
        f" color: rgb({r}, {g}, {b}); border: 1px solid rgba({r}, {g}, {b}, 120);"
        " border-radius: 11px; padding: 3px 11px; font-weight: bold; }")
    chip.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return chip


def _section(title: str) -> QLabel:
    """A section title as the side tray draws them: bold, a thin rule
    under it, no bar."""
    label = QLabel(title)
    label.setStyleSheet("QLabel { font-weight: bold; padding: 2px 0 4px 0;"
                        " border-bottom: 1px solid palette(mid); }")
    return label


def _nav_button(arrow, tip: str) -> QToolButton:
    btn = QToolButton()
    from views.rtl import set_arrow
    set_arrow(btn, arrow)
    btn.setToolTip(tip)
    btn.setAutoRaise(True)
    btn.setFixedSize(30, 28)
    btn.setStyleSheet(
        "QToolButton { border: 1px solid palette(mid); border-radius: 4px; }"
        "QToolButton:hover { background: palette(midlight); }")
    return btn


def _icon_button(key: str, text: str) -> QPushButton:
    """A button with one of IngeTrazo's own icons, repainted when the
    theme changes (the ``icon_key`` property)."""
    from views.icons import tool_icon
    btn = QPushButton(tool_icon(key), text)
    btn.setProperty("icon_key", key)
    return btn


class SolidInspectorPanel(QWidget):
    """The inspector, a tab of the side tray: click an object to fly to
    it, walk its problems one by one — each framed and painted in its own
    colour — and repair them one at a time, or everything at once. The
    model stays in view beside it.

    Laid out for the narrow tray: the list keeps the object and its
    verdict, and what is wrong with the chosen one reads under it; with
    room to spare (a floating tab) the other columns come back."""

    #: Below this width the list shows only Object and Status.
    WIDE = 560

    @property
    def _viewport(self):
        """The viewport of the project in front (projects in tabs, #1066):
        the one handed in at setup may be a tab in the back, or closed."""
        return self._live_viewport()

    def __init__(self, viewport, parent=None) -> None:
        super().__init__(parent)
        from views.documents import live_viewport
        self._live_viewport = live_viewport(viewport)
        self._rows: list = []          # payload per table row
        #: The problem on screen: {"name", "index", "count", "item",
        #: "mesh", "matrix"} — or None.
        self._current: Optional[dict] = None
        #: Highlight problems: every problem of one object, painted at once
        #: (each in its kind's colour), and the matrix placing them.
        self._painted: list = []
        self._painted_matrix = None
        self._filling = False          # refresh() is rebuilding the table
        self.setWindowTitle(tr("Solid Inspector"))
        self._build_ui()
        self.refresh()
        overlays = getattr(viewport, "_ext_overlays", None)
        if overlays is not None:
            overlays.append(self._paint)

    def _let_go(self) -> None:
        """Nothing painted any more (the tab hidden, the window closed)."""
        if self._current is not None or self._painted:
            self._current = None
            self._painted = []
            self._show_label()
            self._viewport.update()

    def showEvent(self, event) -> None:  # noqa: N802 — Qt override
        # The tab brought forward: the model may have changed meanwhile.
        super().showEvent(event)
        self.refresh()

    def hideEvent(self, event) -> None:  # noqa: N802 — Qt override
        # Another tab in front: the colours of a panel nobody sees would
        # only puzzle.
        self._let_go()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt override
        overlays = getattr(self._viewport, "_ext_overlays", None)
        if overlays is not None and self._paint in overlays:
            overlays.remove(self._paint)
        self._let_go()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt override
        super().resizeEvent(event)
        self._fit_columns()

    def _fit_columns(self) -> None:
        wide = self.width() >= self.WIDE
        for col in (1, 3, 4):
            self._table.setColumnHidden(col, not wide)
        self._detail.setVisible(not wide)

    def _build_ui(self) -> None:
        from views.theme import style as theme_style

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        subtitle = QLabel(tr(
            "Finds why an object is not a closed solid, and repairs it."))
        subtitle.setWordWrap(True)
        theme_style(subtitle, "color:{muted}; font-size:11px;")
        layout.addWidget(subtitle)
        # The verdict at a glance, in two counts.
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self._ok_chip = _chip(_OK)
        self._bad_chip = _chip(_BAD)
        chips.addWidget(self._ok_chip)
        chips.addWidget(self._bad_chip)
        chips.addStretch(1)
        layout.addLayout(chips)
        # The verdict in words, for whoever reads it aloud or in a test.
        self._summary = QLabel()
        self._summary.setVisible(False)
        layout.addWidget(self._summary)

        layout.addWidget(_section(tr("Objects")))
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(
            [tr("Object"), tr("Faces"), tr("Status"), tr("Problems"),
             tr("Volume")])
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setHighlightSections(False)
        header.setMinimumSectionSize(40)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(24)
        self._table.setShowGrid(False)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._table.setWordWrap(False)
        self._table.setTextElideMode(Qt.ElideRight)
        self._table.setFrameShape(QFrame.NoFrame)
        self._table.setMinimumHeight(120)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget { border: 1px solid palette(mid);"
            " border-radius: 4px; }"
            "QTableWidget::item { padding: 0 4px; }"
            "QHeaderView::section { font-weight: bold; padding: 4px;"
            " border: none; border-bottom: 1px solid palette(mid);"
            " background: palette(window); }")
        # One click on a row: its first problem on screen, ready to repair
        # (a double click was a gesture nobody finds); a sound object is
        # simply flown to.
        self._table.cellClicked.connect(lambda _r, _c: self.focus_object())
        self._table.currentCellChanged.connect(
            lambda *_a: self._show_detail())
        layout.addWidget(self._table, stretch=1)
        # What is wrong with the chosen object, when the list is too narrow
        # for its own Problems and Volume columns.
        self._detail = QLabel()
        self._detail.setWordWrap(True)
        theme_style(self._detail, "color:{muted}; font-size:11px;")
        layout.addWidget(self._detail)

        # The problem on screen, as a card edged in its kind's colour:
        # which one, why it cannot be repaired here when it cannot, and
        # the buttons that walk and repair them one at a time.
        layout.addWidget(_section(tr("Problem by problem")))
        self._card = QFrame()
        self._card.setObjectName("problemCard")
        card = QVBoxLayout(self._card)
        card.setContentsMargins(10, 6, 6, 6)
        card.setSpacing(6)
        self._problem_label = QLabel()
        self._problem_label.setTextFormat(Qt.RichText)
        self._problem_label.setWordWrap(True)
        card.addWidget(self._problem_label)
        step = QHBoxLayout()
        step.setSpacing(4)
        self._prev_btn = _nav_button(Qt.LeftArrow, tr("Previous problem"))
        self._prev_btn.clicked.connect(self.previous_problem)
        step.addWidget(self._prev_btn)
        self._next_btn = _nav_button(Qt.RightArrow, tr("Next problem"))
        self._next_btn.setToolTip(
            tr("Next problem") + "\n"
            + tr("Select the next problem and zoom to it"))
        self._next_btn.clicked.connect(self.next_problem)
        step.addWidget(self._next_btn)
        self._fix_btn = QPushButton(tr("Repair this problem"))
        self._fix_btn.setObjectName("primary")
        self._fix_btn.setToolTip(tr(
            "Repair only the problem on screen and go on to the next one"))
        self._fix_btn.clicked.connect(self.repair_current)
        step.addWidget(self._fix_btn, 1)
        card.addLayout(step)
        layout.addWidget(self._card)

        # Foot: looking on top, repairing under it.
        look = QHBoxLayout()
        look.setSpacing(6)
        refresh_btn = _icon_button("refresh", tr("Refresh"))
        refresh_btn.clicked.connect(self.refresh)
        look.addWidget(refresh_btn, 1)
        self._hl_btn = _icon_button("zoom_selection", tr("Highlight problems"))
        self._hl_btn.setToolTip(tr(
            "Paint every problem of the chosen object, each in its colour"))
        self._hl_btn.clicked.connect(self.highlight)
        look.addWidget(self._hl_btn, 1)
        layout.addLayout(look)
        fix = QHBoxLayout()
        fix.setSpacing(6)
        self._repair_btn = QPushButton(tr("Repair"))
        self._repair_btn.setToolTip(tr(
            "Erase stray edges and duplicated faces, close flat holes, "
            "turn reversed faces outward"))
        self._repair_btn.clicked.connect(self.repair)
        fix.addWidget(self._repair_btn, 1)
        self._repair_all_btn = QPushButton(tr("Repair all"))
        self._repair_all_btn.setObjectName("primary")
        self._repair_all_btn.clicked.connect(self.repair_all)
        fix.addWidget(self._repair_all_btn, 1)
        layout.addLayout(fix)

        # IngeTrazo's blue marks the buttons that change the model.
        # (A template: theme_style fills {muted} again on every theme change.)
        theme_style(self,
            "QPushButton {{ padding: 5px 10px; }}"
            "QPushButton#primary {{ background: rgb(42, 93, 143);"
            " color: white; border: 1px solid rgb(42, 93, 143);"
            " border-radius: 4px; padding: 5px 10px; font-weight: bold; }}"
            "QPushButton#primary:hover {{ background: rgb(55, 112, 168); }}"
            "QPushButton#primary:pressed {{ background: rgb(33, 74, 114); }}"
            "QPushButton#primary:disabled {{ background: palette(midlight);"
            " border: 1px solid palette(mid); color: {muted}; }}")
        self._show_label()
        self._fit_columns()

    def _show_detail(self) -> None:
        row = self._selected_row()
        if row is None:
            self._detail.setText("")
            return
        rep = row["report"]
        from core.units import fmt_volume
        parts = [row["name"] + ":", _problem_text(rep) or tr("watertight")]
        if rep["volume"] is not None:
            parts.append("· " + fmt_volume(rep["volume"]))
        self._detail.setText(" ".join(parts))

    # ---- Data --------------------------------------------------------------
    def refresh(self) -> None:
        """Inspect everything again. The problem on screen is let go: what
        it pointed at may have changed."""
        scene = self._viewport.scene
        current = self._selected_row()
        current_name = current["name"] if current else None
        self._rows = []

        # The mesh you are editing right now: the open group's, or the
        # loose one. Problem edges here CAN be highlighted directly.
        if scene.edit_group is not None:
            active_name = tr("Open group: {name}",
                             name=scene.edit_group.name)
        else:
            active_name = tr("Loose geometry")
        self._rows.append({"name": active_name, "kind": "active",
                           "mesh": scene.mesh,
                           "matrix": _matrix_of(scene, scene.edit_group),
                           "report": inspect_mesh(scene.mesh)})

        # Every group, nested ones included (the one being edited is the
        # live row above; skip it here to avoid the duplicate).
        for row in _group_rows(scene):
            row["report"] = inspect_mesh(row["mesh"])
            self._rows.append(row)

        table = self._table
        self._filling = True
        table.setRowCount(len(self._rows))
        ok, bad = _OK, _BAD
        solids = problems = 0
        from core.units import fmt_volume
        for i, row in enumerate(self._rows):
            rep = row["report"]
            table.setItem(i, 0, QTableWidgetItem(row["name"]))
            table.setItem(i, 1, QTableWidgetItem(f"{rep['faces']:,}"))
            if not rep["faces"] and not rep["edges"]:
                status = QTableWidgetItem(tr("(empty)"))
            elif is_sound(rep):
                status = QTableWidgetItem("✔ " + tr("watertight"))
                status.setForeground(ok)
                solids += 1
            else:
                status = QTableWidgetItem(
                    "✘ " + (tr("faces reversed") if rep["watertight"]
                            else tr("not watertight")))
                status.setForeground(bad)
                problems += 1
            table.setItem(i, 2, status)
            table.setItem(i, 3, QTableWidgetItem(_problem_text(rep)))
            vol = (fmt_volume(rep['volume'])
                   if rep["volume"] is not None else "—")
            table.setItem(i, 4, QTableWidgetItem(vol))
        names = [r["name"] for r in self._rows]
        if current_name in names:
            table.setCurrentCell(names.index(current_name), 0)
        self._filling = False

        self._summary.setText(
            tr("{ok} watertight solids, {bad} with problems",
               ok=solids, bad=problems))
        self._ok_chip.setText("✔ " + tr("{n} solids", n=solids))
        self._bad_chip.setText("✘ " + tr("{n} with problems", n=problems))
        self._bad_chip.setVisible(problems > 0)
        self._ok_chip.setToolTip(self._summary.text())
        self._bad_chip.setToolTip(self._summary.text())
        self._current = None
        self._painted = []
        self._show_label()
        self._show_detail()
        self._viewport.update()

    # ---- Highlight ---------------------------------------------------------
    def _selected_row(self) -> dict | None:
        i = self._table.currentRow()
        if 0 <= i < len(self._rows):
            return self._rows[i]
        return None

    def focus_object(self) -> bool:
        """What a click on the list does: an object with problems shows its
        first one — framed, painted, «Repair this problem» ready — and a
        sound one is flown to and selected. False when there is nothing to
        show (an empty row, or the table being rebuilt)."""
        row = self._selected_row()
        vp = self._viewport
        if row is None or self._filling:
            return False
        if problem_items(row["report"]):
            return self.show_problem(0) is not None
        self._current = None
        self._painted = []
        self._show_label()
        pts = [v.position for v in row["mesh"].vertices if v.edges]
        m = row["matrix"]
        if m is not None:
            pts = [m.map(p) for p in pts]
        scene = vp.scene
        scene.selection.clear()
        if row["kind"] != "active":
            scene.selection.add(row["top"])
        if not pts:
            vp.update()
            return False
        _frame(vp, pts)
        self._show_label(tr("No problems left in this object"))
        vp.update()
        return True

    def highlight(self) -> Optional[list]:
        """Paint EVERY problem of the chosen row at once, each in its
        kind's colour, and frame them all — the whole picture before going
        through them one by one. Returns the problems painted (None when
        there are none).

        The problems are also selected when they are the geometry you are
        editing; on a group you are not inside, the group is selected and
        the colours show its problems through it."""
        row = self._selected_row()
        vp = self._viewport
        if row is None:
            return None
        items = problem_items(row["report"])
        self._current = None
        if not items:
            self._painted = []
            if row["kind"] != "active":
                vp.scene.selection.clear()
                vp.scene.selection.add(row["top"])
            self._show_label(tr("No problems left in this object"))
            vp.flash_status(tr("Nothing to highlight — watertight"))
            vp.update()
            return None
        self._painted = items
        self._painted_matrix = row["matrix"]
        scene = vp.scene
        scene.selection.clear()
        if row["kind"] == "active":
            for item in items:
                scene.selection.update(item["ents"])
        else:
            scene.selection.add(row["top"])
        pts = [p for item in items for p in _item_points(item)]
        m = row["matrix"]
        if m is not None:
            pts = [m.map(p) for p in pts]
        _frame(vp, pts)
        self._show_label()
        vp.flash_status(tr("{n} problems highlighted", n=len(items)))
        vp.update()
        return items

    # ---- One problem at a time ---------------------------------------------
    def next_problem(self) -> Optional[dict]:
        """Show the chosen row's next problem (the first, the first time).
        Returns it — ``{"kind", "ents"}`` — or None when there is none."""
        return self._step(+1)

    def previous_problem(self) -> Optional[dict]:
        return self._step(-1)

    def _step(self, delta: int) -> Optional[dict]:
        row = self._selected_row()
        if row is None:
            return None
        cur = self._current
        if cur is not None and cur["name"] == row["name"]:
            index = cur["index"] + delta
        else:
            index = 0 if delta > 0 else -1
        return self.show_problem(index)

    def show_problem(self, index: int) -> Optional[dict]:
        """Frame problem ``index`` of the chosen row (wrapping round), paint
        it in its kind's colour and select it.

        On a group you are not inside, the group is what gets selected —
        the view still flies to the problem, in the group's placement, and
        the colour shows it through the group."""
        row = self._selected_row()
        vp = self._viewport
        if row is None:
            return None
        items = problem_items(row["report"])
        if not items:
            self._current = None
            self._painted = []
            self._show_label(tr("No problems left in this object"))
            vp.flash_status(tr("Nothing to highlight — watertight"))
            vp.update()
            return None
        index %= len(items)
        item = items[index]
        self._current = {"name": row["name"], "index": index,
                         "count": len(items), "item": item,
                         "mesh": row["mesh"], "matrix": row["matrix"]}
        self._painted = []

        pts = _item_points(item)
        m = row["matrix"]
        if m is not None:
            pts = [m.map(p) for p in pts]
        scene = vp.scene
        scene.selection.clear()
        if row["kind"] == "active":
            scene.selection.update(item["ents"])
        else:
            scene.selection.add(row["top"])
        _frame(vp, pts)
        self._show_label()
        vp.flash_status(tr("Problem {i} of {n}", i=index + 1, n=len(items)))
        vp.update()
        return item

    def _edge(self, color: Optional[QColor]) -> None:
        """Edge the problem card in ``color`` (a neutral rule when None)."""
        edge = color.name() if color is not None else "palette(mid)"
        self._card.setStyleSheet(
            "QFrame#problemCard { background: palette(base);"
            " border: 1px solid palette(mid); border-radius: 4px;"
            f" border-left: 4px solid {edge}; }}")

    def _show_label(self, note: str = "") -> None:
        cur = self._current
        if cur is None and self._painted and not note:
            counts: dict = {}
            for item in self._painted:
                counts[item["kind"]] = counts.get(item["kind"], 0) + 1
            parts = []
            for kind, (name, color) in KINDS.items():
                if kind in counts:
                    parts.append(
                        f'<span style="color:{color.name()}; '
                        f'font-size:16px">■</span> {tr(name)} '
                        f'({counts[kind]})')
            self._problem_label.setText("&nbsp;&nbsp; ".join(parts))
            self._fix_btn.setEnabled(False)
            self._edge(QColor(243, 115, 41))      # IngeTrazo orange
            return
        if cur is None:
            text = note or tr(
                "Click an object to see its first problem; the arrows "
                "walk the others.")
            self._problem_label.setText(text)
            self._fix_btn.setEnabled(False)
            self._edge(None)
            return
        name, color = KINDS[cur["item"]["kind"]]
        text = (f'<span style="color:{color.name()}; font-size:16px">■</span> '
                + tr("Problem {i} of {n}: {kind}", i=cur["index"] + 1,
                     n=cur["count"], kind=tr(name)))
        reason = why_not_repairable(cur["mesh"], cur["item"])
        if reason:
            text += f'<br><span style="color:#c85a3c">{reason}</span>'
        self._problem_label.setText(text)
        self._fix_btn.setEnabled(reason is None)
        self._edge(color)

    def _paint(self, vp, painter) -> None:
        """Viewport overlay: the problem on screen (or, after Highlight
        problems, all of them) in its kind's colour —
        thick lines on edges, a see-through fill on faces — drawn over the
        model, so it shows inside a group and behind other geometry."""
        cur = self._current
        if self._painted:
            items, m = self._painted, self._painted_matrix
        elif cur is not None:
            items, m = [cur["item"]], cur["matrix"]
        else:
            return
        from PySide6.QtGui import QPainter
        painter.setRenderHint(QPainter.Antialiasing)
        for item in items:
            self._paint_item(vp, painter, item, m)

    @staticmethod
    def _paint_item(vp, painter, item, m) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPen, QPolygonF
        _name, color = KINDS[item["kind"]]

        def px(p):
            q = vp.world_to_pixel(m.map(p) if m is not None else p)
            return None if q is None else QPointF(*q)

        fill = QColor(color)
        fill.setAlpha(110)
        for ent in item["ents"]:
            if hasattr(ent, "loop"):
                pts = [px(v.position) for v in ent.loop]
                if any(q is None for q in pts):
                    continue
                painter.setPen(QPen(color, 3))
                painter.setBrush(fill)
                painter.drawPolygon(QPolygonF(pts))
            else:
                a, b = px(ent.v0.position), px(ent.v1.position)
                if a is None or b is None:
                    continue
                painter.setPen(QPen(color, 5, Qt.SolidLine, Qt.RoundCap))
                painter.drawLine(a, b)
                painter.setBrush(color)
                painter.setPen(Qt.NoPen)
                for q in (a, b):
                    painter.drawEllipse(q, 4.0, 4.0)

    def repair_current(self) -> Optional[dict]:
        """Repair the problem on screen (one undo step) and show the next
        one of the same object. None when there was nothing to repair or
        it has no single right repair (the reason is shown)."""
        cur = self._current
        vp = self._viewport
        if cur is None:
            vp.flash_status(tr("Press Next problem first"))
            return None
        reason = why_not_repairable(cur["mesh"], cur["item"])
        if reason:
            vp.flash_status(reason, 5000)
            return None
        item = cur["item"]
        cmd = RepairSolidsCommand([cur["mesh"]],
                                  fix=lambda mesh: repair_item(mesh, item))
        vp.history.execute(cmd)
        if vp.history.last_error:
            vp.flash_status(vp.history.last_error)
            self.refresh()
            return None
        index = cur["index"]
        self.refresh()
        # The repaired problem left the list: the one now in its place is
        # the next one.
        row = self._selected_row()
        left = problem_items(row["report"]) if row else []
        self.show_problem(min(index, len(left) - 1) if left else 0)
        vp.flash_status(tr("Repaired — {n} problems left in this object",
                           n=len(left)), 4000)
        return cmd.done

    # ---- Repair ------------------------------------------------------------
    def _repair_rows(self, rows) -> Optional[dict]:
        meshes, seen = [], set()
        for row in rows:
            if is_sound(row["report"]) or not row["report"]["edges"]:
                continue
            if id(row["mesh"]) not in seen:   # instances share a prototype
                seen.add(id(row["mesh"]))
                meshes.append(row["mesh"])
        vp = self._viewport
        if not meshes:
            vp.flash_status(tr("Nothing to repair"))
            return None
        cmd = RepairSolidsCommand(meshes)
        vp.history.execute(cmd)
        if vp.history.last_error:
            vp.flash_status(vp.history.last_error)
            self.refresh()
            return None
        d = cmd.done
        vp.flash_status(tr(
            "Repaired: {stray} stray edges, {dup} duplicated faces, "
            "{holes} holes closed, {inner} partitions, {rev} faces turned",
            stray=d["stray"], dup=d["duplicates"], holes=d["holes"],
            inner=d["partitions"], rev=d["reversed"]), 5000)
        vp.update()
        self.refresh()
        return d

    def repair(self) -> Optional[dict]:
        """Repair the chosen row's object (one undo step)."""
        row = self._selected_row()
        return self._repair_rows([row]) if row is not None else None

    def repair_all(self) -> Optional[dict]:
        """Repair every listed object with problems (one undo step)."""
        return self._repair_rows(self._rows)


# ---------------------------------------------------------------------------
# Tool registration (the plugin entry point)
# ---------------------------------------------------------------------------

#: The tests and older code name it by its dialog-era name.
SolidInspectorDialog = SolidInspectorPanel


class SolidInspectorTool(Tool):
    """Extensions-menu entry that brings the inspector's tab forward (or,
    in a window without the side tray, opens it as a window of its own)."""
    name = "Solid Inspector"
    shortcut = None
    description = (
        "Find out why a group is not a solid, show the edges to blame and "
        "repair what has one right answer.")
    uses_snap = False

    def on_activate(self, viewport) -> None:
        window = viewport.window()
        panel = getattr(window, "_solid_inspector", None)
        dock = getattr(window, "_solid_inspector_dock", None)
        if panel is not None and dock is not None:
            show = getattr(window, "set_tray_shown", None)
            if show is not None:
                show(dock, True)
            dock.raise_()
            panel.refresh()
            return
        if panel is None or not panel.isVisible():
            panel = SolidInspectorPanel(viewport, parent=window)
            panel.setWindowFlags(Qt.Tool)
            panel.resize(380, 560)
            window._solid_inspector = panel
            panel.show()
        else:
            panel.refresh()
            panel.raise_()
            panel.activateWindow()

    def on_deactivate(self, viewport) -> None:
        pass


def _join_tray(window, dock) -> bool:
    """Tab ``dock`` with the side tray when it stands alone on the tray's
    side. Returns whether it did.

    ``setup`` runs before the window restores the user's saved layout, and
    that restore puts back the panels IT knows — leaving the inspector,
    when it was not among them (or was saved apart that way), alone on a
    strip of its own above the tabs; the layout saved next keeps it there.
    Alone on the tray's side is never a place the tray's tabs let anyone
    choose, so it always rejoins them; moved to the other side, it stays
    there."""
    tray = getattr(window, "tray", None)
    if (tray is None or dock.isFloating() or dock.isHidden()
            or window.tabifiedDockWidgets(dock)
            or window.dockWidgetArea(dock) != window.dockWidgetArea(tray)):
        return False
    window.tabifyDockWidget(tray, dock)
    getattr(tray, "raise_", lambda: None)()   # Properties stays in front
    return True


def setup(app) -> None:
    """The inspector lives in the side tray, beside Properties and BIM,
    so the model it points at stays in view; Extensions ▸ Solid Inspector
    brings the tab forward."""
    from PySide6.QtCore import QTimer
    panel = SolidInspectorPanel(app.viewport)
    dock = app.add_panel(tr("Solid Inspector"), panel)
    app.window._solid_inspector = panel
    app.window._solid_inspector_dock = dock
    # Once the window has restored the saved layout (after every setup).
    QTimer.singleShot(0, lambda: _join_tray(app.window, dock))
