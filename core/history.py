# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Undo / redo history using the command pattern, over the shared-vertex mesh.

Every mutation that should be reversible goes through a :class:`Command`
subclass. The viewport owns a :class:`History` that maintains the undo and redo
stacks. Tools call ``viewport.history.execute(...)`` rather than mutating the
scene directly.

Commands mutate ``scene.mesh`` (welding, incidence) and resolve the geometry
they act on **by position at do-time**, so the position-based plans that
:mod:`core.edits` builds (against a throwaway simulation) execute correctly
onto the real mesh — and undo re-links the very objects that were removed,
preserving identity for any references other commands hold.

Why a command stack and not snapshots? Commands store only the delta, so memory
cost stays proportional to the action, not to the model size.
"""
from __future__ import annotations

import os as _os
import time as _time_mod
from abc import ABC, abstractmethod
from pathlib import Path as _Path
from typing import Iterable, Optional

_PERF = bool(_os.environ.get("INGETRAZO_PERF"))
_perf_file = None


def _plog(tag: str, ms: float, extra: str = "", floor: float = 100.0) -> None:
    """Same log the viewport telemetry writes (P0): any COMMAND slower than
    the floor lands here with its class name, so a sticky edit names its
    culprit without a profiler round-trip.

    Every line carries the writer's **pid**. One log file collects whatever is
    running — a second window opened to compare a fix, an offscreen repro
    script — and without it two builds' numbers interleave into one
    indistinguishable stream (which has already sent one reading the wrong
    way). ``$INGETRAZO_PERF_LOG`` overrides the path when a run wants its own
    file."""
    global _perf_file
    if not _PERF or ms < floor:
        return
    if _perf_file is None:
        path = _os.environ.get("INGETRAZO_PERF_LOG")
        _perf_file = open(_Path(path) if path
                          else _Path.home() / "ingetrazo-perf.log",
                          "a", buffering=1)
    _perf_file.write(f"{_time_mod.strftime('%H:%M:%S')} [{_os.getpid()}] "
                     f"{tag} {ms:.0f}ms"
                     f"{' ' + extra if extra else ''}\n")

from PySide6.QtGui import QVector3D

from core.group import Group
from core.materials import has_own_material
from core.mesh import (PAINT_KEYS, Edge, Face, Mesh, Vertex, edge_flags,
                       edge_is_plain, stamp_edge_flags)
from core.topology import (
    _key,
    _loop_edges,
    carve_loop_by_chords,
    find_containing_face,
    fold_nonplanar_faces,
    heal_overlapping_faces,
    loop_inside_face,
    orphaned_edges_at,
    subtract_loop_from_face,
)


def _find_face_by_loop(mesh, loop_positions) -> Optional[Face]:
    """The mesh face whose outer loop matches ``loop_positions`` (by key), or
    ``None``. Used to resolve a command's target face against the live mesh."""
    target = frozenset(_key(p) for p in loop_positions)
    for f in mesh.faces:
        if frozenset(_key(p) for p in f.vertices) == target:
            return f
    return None


class Command(ABC):
    """Abstract reversible operation against a :class:`Scene`."""

    @abstractmethod
    def do(self, scene) -> None:
        """Apply the operation."""

    @abstractmethod
    def undo(self, scene) -> None:
        """Reverse the operation."""


class SetPluginDataCommand(Command):
    """Replace one extension's document data (``scene.plugin_data[key]``),
    undoably. ``value`` None removes the key. Values are copied through JSON
    both ways, so neither the caller nor the history can alias them."""

    def __init__(self, key: str, value) -> None:
        import json
        self.key = str(key)
        self.value = None if value is None else json.loads(json.dumps(value))
        self._had = False
        self._before = None

    def do(self, scene) -> None:
        import json
        data = scene.plugin_data
        self._had = self.key in data
        self._before = (json.loads(json.dumps(data[self.key]))
                        if self._had else None)
        if self.value is None:
            data.pop(self.key, None)
        else:
            data[self.key] = json.loads(json.dumps(self.value))
        scene.version += 1

    def undo(self, scene) -> None:
        import json
        if self._had:
            scene.plugin_data[self.key] = json.loads(json.dumps(self._before))
        else:
            scene.plugin_data.pop(self.key, None)
        scene.version += 1


class History:
    """Undo/redo stacks. ``execute`` is TRANSACTIONAL: if a command throws
    mid-mutation, the mesh is restored to its pre-command state, the failure
    is logged (stderr + ``error_log`` file), and nothing lands on the undo
    stack — a failed operation must be a no-op, never a half-committed mess
    (an aas.igz-style aborted draw left a quarter circle, an unsplit face and
    a duplicated edge behind, with the traceback swallowed by the Qt event
    loop). Same fail-safe doctrine as the BIM push guard, one level up."""

    #: Where failed-command tracebacks are appended: the user's log folder
    #: (core.paths.user_log_dir — writable even when the app is installed
    #: under Program Files), so the user can just send the file.
    error_log = "ingetrazo-errors.log"

    @staticmethod
    def default_error_log() -> str:
        from core.paths import user_log_dir
        return str(user_log_dir() / "ingetrazo-errors.log")

    #: How many steps back the history keeps; the oldest fall off the
    #: front. Every command carries a mesh snapshot, so on a big model the
    #: stack is where the memory goes (issue #56, @pacaeiro: «an option to
    #: control number of Undo Steps, start thinking in ways of improving
    #: performance»). Preferences ▸ General sets it; 0 = unlimited.
    max_steps: int = 200

    def __init__(self, scene) -> None:
        self.scene = scene
        self.undo_stack: list[Command] = []
        self.redo_stack: list[Command] = []
        #: Message describing the last rolled-back failure (UI may flash it).
        self.last_error: Optional[str] = None

    def execute(self, cmd: Command) -> None:
        _t0 = _time_mod.perf_counter() if _PERF else 0.0
        snapshot = self.scene.mesh.capture_state()
        if _PERF:
            _plog("command.snapshot",
                  (_time_mod.perf_counter() - _t0) * 1000.0,
                  extra=type(cmd).__name__)
        try:
            cmd.do(self.scene)
        except Exception as exc:
            self.scene.mesh.restore_state(snapshot)
            self.scene.selection.clear()
            self.scene.version += 1
            self.last_error = f"{type(cmd).__name__}: {exc}"
            self._log_failure(cmd, exc)
            return
        self.last_error = None
        if _PERF:
            _plog("command", (_time_mod.perf_counter() - _t0) * 1000.0,
                  extra=type(cmd).__name__)
        # Remember which mesh was active (the loose one, or a group being
        # edited): undo/redo re-enter that context so a snapshot restore never
        # lands on the wrong mesh after the user exits the group.
        cmd._history_mesh = self.scene.mesh
        self.undo_stack.append(cmd)
        cap = int(getattr(self, "max_steps", 0) or 0)
        if cap > 0 and len(self.undo_stack) > cap:
            del self.undo_stack[:len(self.undo_stack) - cap]
        self.redo_stack.clear()
        self._rebind_dimensions()

    def _rebind_dimensions(self) -> None:
        """After every command, undo and redo: a dimension whose vertex
        changed meshes (Make Group, Explode, a component conversion) takes
        the vertex now standing where its endpoint was — BEFORE anything
        else moves it. Leaving it to the next read was too late when a
        scale followed in the same breath. Cheap: a hold that is alive is
        a dictionary lookup and an identity test."""
        for dim in getattr(self.scene, "dimensions", None) or ():
            refresh = getattr(dim, "refresh_anchors", None)
            if refresh is not None:
                refresh(self.scene)

    def _log_failure(self, cmd: Command, exc: Exception) -> None:
        import datetime
        import sys
        import traceback

        text = (f"[{datetime.datetime.now().isoformat(timespec='seconds')}] "
                f"command {type(cmd).__name__} failed and was rolled back:\n"
                f"{''.join(traceback.format_exception(exc))}\n")
        if sys.stderr is not None:
            print(text, file=sys.stderr)
        path = self.error_log
        if path == History.error_log:            # the default: user log dir
            try:
                path = self.default_error_log()
            except Exception:  # noqa: BLE001 — logging never breaks a command
                path = self.error_log
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            pass

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        cmd = self.undo_stack.pop()
        self._in_command_mesh(cmd, lambda: cmd.undo(self.scene))
        self.redo_stack.append(cmd)
        self._rebind_dimensions()
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        cmd = self.redo_stack.pop()
        self._in_command_mesh(cmd, lambda: cmd.do(self.scene))
        self.undo_stack.append(cmd)
        self._rebind_dimensions()
        return True

    def _in_command_mesh(self, cmd, fn) -> None:
        """Run ``fn`` with ``scene.mesh`` pointing at the mesh the command was
        executed against (group-edit context correctness)."""
        target = getattr(cmd, "_history_mesh", None)
        if target is None or target is self.scene.mesh:
            fn()
            return
        current = self.scene.mesh
        self.scene.mesh = target
        try:
            fn()
        finally:
            self.scene.mesh = current

    def clear(self) -> None:
        self.undo_stack.clear()
        self.redo_stack.clear()


# ---- Concrete commands ------------------------------------------------------

class AddEdgeCommand(Command):
    """Add a single edge. The mesh always welds and dedups, so a coincident
    edge is reused rather than duplicated; ``_owned`` records whether this
    command actually created the edge, so undo only removes an edge it owns
    (never the pre-existing one it merged into)."""

    def __init__(self, a: QVector3D, b: QVector3D, merge: bool = True,
                 soft: bool | None = None, curve: int | None = None) -> None:
        self.a = QVector3D(a)
        self.b = QVector3D(b)
        self.merge = merge  # kept for API parity; the mesh never duplicates
        # Optional flags stamped on the resulting edge — used when a split
        # replaces a curve/soft edge with sub-edges, so the pieces inherit.
        self.soft = soft
        self.curve = curve
        self.edge: Optional[Edge] = None
        self._owned = False

    def _stamp(self, edge) -> None:
        if self.soft is not None:
            edge.soft = self.soft
        if self.curve is not None:
            edge.curve = self.curve

    def do(self, scene) -> None:
        m = scene.mesh
        if self._owned and self.edge is not None:
            m.relink_edge(self.edge)  # redo of an edge this command owns
            self._stamp(self.edge)
            scene.version += 1
            return
        v0 = m.vertex_at(self.a)
        v1 = m.vertex_at(self.b)
        pre = m.find_edge(v0, v1) if (v0 is not None and v1 is not None) else None
        if pre is not None:
            # The mesh already has this edge — merged no-op. Own nothing, so
            # ``self.edge`` stays None and undo leaves the pre-existing edge.
            self._stamp(pre)
            scene.version += 1
            return
        self.edge = m.add_edge(self.a, self.b)
        self._owned = True
        self._stamp(self.edge)
        scene.version += 1

    def undo(self, scene) -> None:
        if not self._owned or self.edge is None:
            return
        scene.mesh.remove_edge(self.edge)
        scene.selection.discard(self.edge)
        scene.version += 1


class DeleteEdgesCommand(Command):
    """Erase edges (resolved by endpoint position). A face can't outlive a
    bounding edge — SketchUp erases an edge and its faces go with it — so every
    face that used a deleted edge on its *outer* boundary is removed too (its
    other edges stay, now free). Hole edges are left alone."""

    def __init__(self, edges: Iterable, cascade_faces: bool = True) -> None:
        self._endpoints = [(QVector3D(e.a), QVector3D(e.b)) for e in edges]
        self.cascade_faces = cascade_faces
        self.removed_edges: list[Edge] = []
        self.removed_faces: list[Face] = []

    def do(self, scene) -> None:
        m = scene.mesh
        self.removed_edges = []
        for a, b in self._endpoints:
            v0 = m.vertex_at(a)
            v1 = m.vertex_at(b)
            edge = m.find_edge(v0, v1) if (v0 is not None and v1 is not None) else None
            if edge is not None:
                self.removed_edges.append(edge)

        if self.cascade_faces:
            gone = {frozenset((_key(a), _key(b))) for a, b in self._endpoints}
            self.removed_faces = [
                f for f in m.faces if set(_loop_edges(f.vertices)) & gone
            ]
            for f in self.removed_faces:
                m.remove_face(f)
                scene.selection.discard(f)

        for edge in self.removed_edges:
            m.remove_edge(edge)
            scene.selection.discard(edge)
        scene.version += 1

    def undo(self, scene) -> None:
        m = scene.mesh
        for edge in self.removed_edges:
            m.relink_edge(edge)
        for face in self.removed_faces:
            m.relink_face(face)
        self.removed_faces = []
        scene.version += 1


class EraseSelectionCommand(Command):
    """Erase selected edges and faces, SketchUp-style.

    An edge that divides two *coplanar* faces is dissolved and the faces merge
    back into one (rubbing out a face's split line reunites it). Any other erased
    edge takes the faces it bounds with it (a non-planar pair can't become one
    face). Undo restores an identity-preserving snapshot — the merge restructures
    connectivity too much for a clean per-edge inverse."""

    def __init__(self, edges: Iterable, faces: Iterable = ()) -> None:
        self._edge_endpoints = [(QVector3D(e.a), QVector3D(e.b)) for e in edges]
        self._face_loops = [[QVector3D(v) for v in f.vertices] for f in faces]
        self.snapshot: Optional[dict] = None

    def do(self, scene) -> None:
        m = scene.mesh
        self.snapshot = m.capture_state()
        # Loop->face lookups through ONE index: _find_face_by_loop scans the
        # whole mesh per call, and deleting thousands of box-selected faces
        # froze for ~26 s on a 28k-face mesh (piscina.igz report, round 2).
        by_loop: dict = {}
        for f in m.faces:
            by_loop.setdefault(
                frozenset(_key(p) for p in f.vertices), []).append(f)
        for loop in self._face_loops:
            bucket = by_loop.get(frozenset(_key(p) for p in loop))
            f = bucket.pop(0) if bucket else None
            if f is not None:
                m.remove_face(f)
                scene.selection.discard(f)
        # One segment->faces index for the cascade below: the per-edge scan
        # over every face was O(edges x faces) — deleting a curved tiled
        # wall (hundreds of curve segments) took 30+ s on an exploded
        # 28k-face mesh (piscina.igz report). Kept live as faces merge/die.
        seg_faces: dict = {}

        def _index_face(f) -> None:
            for ek in _loop_edges(f.vertices):
                seg_faces.setdefault(ek, []).append(f)

        for f in m.faces:
            _index_face(f)
        dead_faces: set = set()
        slit_planes: list = []
        for a, b in self._edge_endpoints:
            v0 = m.vertex_at(a)
            v1 = m.vertex_at(b)
            edge = m.find_edge(v0, v1) if (v0 is not None and v1 is not None) else None
            if edge is None:
                continue
            faces = list(edge.faces)
            merged = None
            if len(faces) == 2 and faces[0] is faces[1]:
                # Slit edge: ONE face walks it twice — a fence line joining an
                # inner boundary to the outline turns the ring into a cut-open
                # walk. Dissolving "the face with itself" deleted the face and
                # kept the line (ss.igz report). Erasing the line must keep
                # the face: drop only the edge and re-derive the plane's
                # regions below (the ring comes back as outer + hole; other
                # fence pieces survive as free edges).
                f = faces[0]
                slit_planes.append((QVector3D(f.vertices[0]), f.normal()))
                m.remove_edge(edge)
                scene.selection.discard(edge)
                continue
            if len(faces) == 2 and QVector3D.dotProduct(
                faces[0].normal(), faces[1].normal()
            ) > 0.999:
                merged = m.dissolve_coplanar_region(faces)  # reunite the split
                if merged is not None:
                    dead_faces.update(id(f) for f in faces)
                    _index_face(merged)
            if merged is None:
                # Cascade: the edge and every face bounding it (a face can't
                # outlive a bounding edge) go away.
                ekey = frozenset((_key(edge.v0.position), _key(edge.v1.position)))
                for f in seg_faces.get(ekey, ()):
                    if id(f) in dead_faces:
                        continue
                    dead_faces.add(id(f))
                    m.remove_face(f)
                    scene.selection.discard(f)
                m.remove_edge(edge)
            scene.selection.discard(edge)
        # Slit removals re-derive their plane from the arrangement while the
        # cut-ring face is still present to provide coverage (it re-emits as
        # outer + hole, attrs intact; uncovered regions stay empty).
        done_planes: list = []
        for origin, normal in slit_planes:
            nn = normal.normalized()
            if any(abs(QVector3D.dotProduct(nn, n)) > 0.999 and
                   abs(QVector3D.dotProduct(origin - o, n)) < 1e-4
                   for o, n in done_planes):
                continue
            done_planes.append((origin, nn))
            RebuildPlaneFacesCommand(origin, nn).do(scene)
        # Deleting a curved surface takes its hidden seams with it: a soft edge
        # left bordering no face is a dangling curve segment (a cylinder side's
        # vertical seam) — prune it so no stray vertical lines remain. Hard
        # orphan edges stay (an erased flat face keeps its outline, SketchUp).
        for e in list(m.edges):
            if e.soft and not e.faces:
                m.remove_edge(e)
        # A merge can leave the big enclosing face overlapping its subdivisions;
        # drop any such redundant mother (covered by the snapshot undo above).
        for f in heal_overlapping_faces(m):
            scene.selection.discard(f)
        # And the endpoints go with them. remove_edge only detaches, so an
        # erase used to leave its vertices in the mesh: invisible, ignored by
        # bounds(), and written into the .igz. Nine of them 16 km out were
        # all Marco's document had left after deleting a stray line, which is
        # why zoom-to-extents could not bring him back (2026-09-18).
        m.prune_orphan_vertices()
        scene.version += 1

    def undo(self, scene) -> None:
        if self.snapshot is not None:
            scene.mesh.restore_state(self.snapshot)
            scene.version += 1


class TagCurveCommand(Command):
    """Mark the edges of a drawn circle/arc loop as one curve (shared id), so
    selecting a segment selects the whole curve. Runs as the last step of the
    draw so the id is captured in the enclosing snapshot (redo keeps it); undo is
    a no-op because that snapshot restores the pre-draw state."""

    def __init__(self, loop_points, closed: bool = True) -> None:
        self.pts = [QVector3D(p) for p in loop_points]
        self.closed = closed

    def do(self, scene) -> None:
        scene.mesh.tag_curve(self.pts, self.closed)

    def undo(self, scene) -> None:
        pass


def _inherit_paint(face, mother) -> None:
    """Give ``face`` the paint of the ``mother`` it was drawn on, for the keys
    it does not already carry itself.

    A face drawn on a painted one is part of that surface: a door outlined on
    a textured wall comes out textured in SketchUp, and lines up with the wall
    because both keep the same world→UV map. Only the remainder of a carved
    mother inherited here, so the cut-out itself came back bare (Marco,
    2026-08-27). Verbatim, map included — the two are coplanar, so the image
    has to run straight across the outline.

    Whatever the face already declares wins: a rectangle drawn with a material
    active, or one the caller stamped (the chord split hands its halves the
    mother's attrs directly), keeps what it was given.
    """
    src = getattr(mother, "attrs", None)
    if not src:
        return
    for k in PAINT_KEYS:
        if k in src and k not in face.attrs:
            v = src[k]
            face.attrs[k] = dict(v) if isinstance(v, dict) else v


class AddFaceCommand(Command):
    """Add a face, dividing any coplanar face it lands strictly inside.

    When the new loop falls wholly within an existing face, that mother face
    gains a hole so it no longer overlaps the new face. The hole is recorded so
    undo removes exactly the loop this command punched.
    """

    def __init__(
        self,
        vertices: Iterable[QVector3D],
        auto: bool = True,
        holes: Optional[Iterable[Iterable[QVector3D]]] = None,
        attrs: Optional[dict] = None,
    ) -> None:
        self.vertices = [QVector3D(v) for v in vertices]
        self.preset_holes = (
            [[QVector3D(v) for v in loop] for loop in holes] if holes else None
        )
        self.auto = auto
        # Attrs stamped onto the face at creation (paste carries the copied
        # colour/texture); they stay on the object across undo/redo.
        self.attrs = dict(attrs) if attrs else None
        self.face: Optional[Face] = None
        # (face_that_gained_a_hole, the vertex loop punched) for undo.
        self._punches: list[tuple[Face, list]] = []
        self._subdiv_mother: Optional[Face] = None
        self._subdiv_remainder: Optional[list] = None

    def do(self, scene) -> None:
        m = scene.mesh
        if self.face is None:
            holes = (
                [list(loop) for loop in self.preset_holes]
                if self.preset_holes else None
            )
            self.face = m.add_face(self.vertices, holes)
            if self.attrs:
                self.face.attrs.update(self.attrs)
        else:
            m.relink_face(self.face)  # redo

        if not self.auto:
            scene.version += 1
            return

        # Direction A: the new face falls inside an existing mother → the mother
        # gains the new loop as a hole.
        mother = find_containing_face(m.faces, self.face.vertices, exclude=self.face)
        if mother is not None:
            loop = m.add_hole(mother, self.face.vertices)
            self._punches.append((mother, loop))
            _inherit_paint(self.face, mother)

        # Direction B: the new face encloses existing smaller faces → it gains
        # each of them as a hole.
        for other in list(m.faces):
            if other is self.face:
                continue
            if loop_inside_face(self.face, other.vertices):
                loop = m.add_hole(self.face, other.vertices)
                self._punches.append((self.face, loop))

        # Direction C: drawn against an existing face's boundary (corner / edge
        # rectangle) → carve a connected sub-region. Only when no hole applied.
        if not self._punches:
            for other in list(m.faces):
                if other is self.face:
                    continue
                remainder = subtract_loop_from_face(other, self.face.vertices)
                pieces = ([remainder] if remainder is not None
                          else carve_loop_by_chords(other, self.face.vertices))
                if not pieces:
                    continue
                # Each hole of the mother goes to the piece that holds it; a
                # hole straddling a cut leaves the mother alone.
                piece_holes: list[list[list[QVector3D]]] = [[] for _ in pieces]
                straddle = False
                for hole in other.holes:
                    for k, piece in enumerate(pieces):
                        if loop_inside_face(Face([Vertex(v) for v in piece]), hole):
                            piece_holes[k].append([QVector3D(v) for v in hole])
                            break
                    else:
                        straddle = True
                        break
                if straddle:
                    continue
                m.remove_face(other)
                self._subdiv_remainder = []
                for piece, holes in zip(pieces, piece_holes):
                    rem_face = m.add_face(piece, holes or None)
                    rem_face.attrs = dict(other.attrs)  # carved mother continues
                    self._subdiv_remainder.append(rem_face)
                _inherit_paint(self.face, other)    # ...and so does the cut-out
                self._subdiv_mother = other
                break

        scene.version += 1

    def undo(self, scene) -> None:
        m = scene.mesh
        if self._subdiv_mother is not None:
            for rem in self._subdiv_remainder or ():
                m.remove_face(rem)
            m.relink_face(self._subdiv_mother)
            self._subdiv_mother = None
            self._subdiv_remainder = None
        for face, loop in self._punches:
            m.remove_hole(face, loop)
        self._punches = []
        if self.face is not None:
            m.remove_face(self.face)
        scene.version += 1


class DeleteFaceCommand(Command):
    """Remove a face (resolved by its outer loop). Holes travel with it, so undo
    restores them via relink."""

    def __init__(self, face) -> None:
        self._loop = [QVector3D(v) for v in face.vertices]
        self.face: Optional[Face] = None

    def do(self, scene) -> None:
        self.face = _find_face_by_loop(scene.mesh, self._loop)
        if self.face is not None:
            scene.mesh.remove_face(self.face)
            scene.selection.discard(self.face)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.face is not None:
            scene.mesh.relink_face(self.face)
        scene.version += 1


def _dirty_group_chunks(scene) -> None:
    """Attr edits bypass the mesh mutation primitives — flag every group
    mesh so the viewport's cached chunks re-validate their materials.

    Two flags, because they answer different questions. ``_chunk_dirty`` is
    "something touched this mesh"; ``_attrs_dirty`` is "a MATERIAL changed",
    and only the second can be told apart from a move. The viewport's
    translation fast path reuses a cached chunk's texture buckets after
    checking geometry alone, so without this a repaint that happened in the
    same breath as a drag stayed invisible outside the group — the flagstone
    corner of Plaza Yanque kept its neighbour's grey (Marco, 2026-09-10).

    Nested placements are flagged too: their meshes render as part of the
    parent, and walking scene.groups as a flat list never reached them.
    """
    from core.group import iter_placements
    for g in getattr(scene, "groups", []):
        for pg, _m in iter_placements(g):
            pg.mesh._chunk_dirty = True
            pg.mesh._attrs_dirty = True


class FlipFacesCommand(Command):
    """Reverse the winding of a set of faces — SketchUp's "Reverse Faces".

    Reversing the loops flips the geometric normal while keeping the *same*
    ``Face`` objects and their shared edges/incidence (identity preserved, so
    selection and snapshots stay valid). The operation is an involution:
    undo simply flips again. Faces may live in the loose mesh or inside a
    group's mesh — the flip is per-object, so both work."""

    def __init__(self, faces) -> None:
        self._faces = [f for f in faces if hasattr(f, "loop")]

    def _flip(self, scene) -> None:
        for f in self._faces:
            f.loop.reverse()
            for h in getattr(f, "hole_loops", []) or []:
                h.reverse()
        _dirty_group_chunks(scene)
        scene.version += 1

    def do(self, scene) -> None:
        self._flip(scene)

    def undo(self, scene) -> None:
        self._flip(scene)


class AssignLayerCommand(Command):
    """Move entities onto a layer — SketchUp's Tag field in Entity Info.

    Faces, edges, groups and annotations alike (``core.layers.assign_layer``
    knows where each one keeps its label). Previous labels are captured at
    ``do`` time, so a mixed selection undoes exactly. A layer that does not
    exist yet is created (Rafael's «no sé cómo cambiar el objeto de capa»,
    2026-09-16 — the panel's button was the only road and it was not
    understood; this is what Entity Info and the right-click go through)."""

    def __init__(self, entities, layer: str) -> None:
        self._entities = list(entities)
        self._layer = layer
        self._prev: list = []
        self._created = False

    def do(self, scene) -> None:
        from core.layers import Layer, assign_layer, layer_of
        if scene.layer(self._layer) is None:
            scene.layers.append(Layer(self._layer))
            self._created = True
        self._prev = [layer_of(e) for e in self._entities]
        for e in self._entities:
            assign_layer(e, self._layer)
        _dirty_group_chunks(scene)
        scene.version += 1

    def undo(self, scene) -> None:
        from core.layers import assign_layer
        for e, prev in zip(self._entities, self._prev):
            assign_layer(e, prev)
        if self._created:
            ly = scene.layer(self._layer)
            if ly is not None:
                scene.layers.remove(ly)
        _dirty_group_chunks(scene)
        scene.version += 1


def _is_hidden(entity) -> bool:
    attrs = getattr(entity, "attrs", None)
    if attrs is not None:                          # Face
        return bool(attrs.get("hidden"))
    return bool(getattr(entity, "hidden", False))


def _set_hidden(entity, hidden: bool) -> None:
    attrs = getattr(entity, "attrs", None)
    if attrs is not None:                          # Face
        if hidden:
            attrs["hidden"] = True
        else:
            attrs.pop("hidden", None)
    else:
        entity.hidden = hidden


class HideCommand(Command):
    """Hide (or unhide) objects, faces and edges — SketchUp's Edit ▸ Hide
    and Edit ▸ Unhide.

    An OBJECT (group or component, ``Group.hidden``) and a FACE
    (``attrs["hidden"]``) disappear from every consumer that asks
    ``Scene.entity_visible``: render, pick, snap, bounds, export; an
    object's nested placements go with it, and a group's chunk leaves its
    hidden faces out. A hidden EDGE stays in the topology (its faces keep
    their boundary) but draws neither as a line nor as a profile /
    silhouette. Previous per-entity flags are captured at ``do`` time, so
    a mixed selection (some already hidden) undoes exactly."""

    def __init__(self, entities, hidden: bool = True) -> None:
        self._entities = [e for e in entities
                          if hasattr(e, "hidden") or hasattr(e, "attrs")]
        self._hidden = hidden
        self._prev: list[bool] = []

    @property
    def entities(self) -> list:
        return list(self._entities)

    @property
    def hides(self) -> bool:
        return self._hidden

    def do(self, scene) -> None:
        self._prev = [_is_hidden(e) for e in self._entities]
        for e in self._entities:
            _set_hidden(e, self._hidden)
            if self._hidden:
                # An invisible entity must not linger in the selection: every
                # selection consumer (move, delete, paint) assumes it can see
                # what it operates on.
                scene.selection.discard(e)
        _dirty_group_chunks(scene)
        scene.version += 1

    def undo(self, scene) -> None:
        for e, prev in zip(self._entities, self._prev):
            _set_hidden(e, prev)
        _dirty_group_chunks(scene)
        scene.version += 1


class HideEdgesCommand(HideCommand):
    """The edges-only spelling, kept for callers that grew up with it."""

    def __init__(self, edges, hidden: bool = True) -> None:
        super().__init__(edges, hidden=hidden)


class SetFaceColorCommand(Command):
    """Paint a set of faces with an RGB colour (or clear it with ``None``),
    stored in each face's ``attrs["color"]`` — the first user-facing use of the
    generic per-region attrs (A.3), so the colour rides through push/pull and
    the plane rebuild. Painting changes no topology, so a direct attrs swap
    inverts it exactly — no snapshot needed. Faces are held by reference (the
    paint click resolves them live); undo restores each face's prior colour."""

    def __init__(self, faces, color) -> None:
        self._faces = list(faces)
        self._color = list(color) if color is not None else None
        self._old: Optional[list] = None  # captured on first do

    def do(self, scene) -> None:
        if self._old is None:
            self._old = [f.attrs.get("color") for f in self._faces]
        for f in self._faces:
            if self._color is None:
                f.attrs.pop("color", None)
            else:
                f.attrs["color"] = list(self._color)
        _dirty_group_chunks(scene)
        scene.version += 1

    def undo(self, scene) -> None:
        for f, old in zip(self._faces, self._old or []):
            if old is None:
                f.attrs.pop("color", None)
            else:
                f.attrs["color"] = list(old)
        _dirty_group_chunks(scene)
        scene.version += 1


class SetFaceOpacityCommand(Command):
    """Set (or clear with ``None``) ``attrs["opacity"]`` on a set of faces —
    the translucency channel (glass): the render's blend pass reads it for
    coloured and textured faces alike. Same direct-attrs-swap inversion as
    the colour command."""

    def __init__(self, faces, opacity) -> None:
        self._faces = list(faces)
        self._opacity = float(opacity) if opacity is not None else None
        self._old: Optional[list] = None

    def do(self, scene) -> None:
        if self._old is None:
            self._old = [f.attrs.get("opacity") for f in self._faces]
        for f in self._faces:
            if self._opacity is None:
                f.attrs.pop("opacity", None)
            else:
                f.attrs["opacity"] = self._opacity
        _dirty_group_chunks(scene)
        scene.version += 1

    def undo(self, scene) -> None:
        for f, old in zip(self._faces, self._old or []):
            if old is None:
                f.attrs.pop("opacity", None)
            else:
                f.attrs["opacity"] = old
        _dirty_group_chunks(scene)
        scene.version += 1


class SetFaceMaterialTagCommand(Command):
    """Set (or clear with ``None``) the registry identity ``attrs["mat"]``
    on a set of faces — the companion of the colour/texture stamp, so a
    paint stroke carries the material's NAME (core.materials) and the
    per-material takeoff stays truthful. Painting anonymously clears the
    tag: a red face is no longer "Concreto visto".

    When ``material`` is given, ``do`` also ensures it exists in the scene
    registry (a library swatch registers itself on first use); ``undo``
    removes it again only if this very command added it."""

    def __init__(self, faces, name, material=None) -> None:
        self._faces = list(faces)
        self._name = name
        self._material = material
        self._old: Optional[list] = None
        self._registered = False

    def do(self, scene) -> None:
        if self._old is None:
            self._old = [f.attrs.get("mat") for f in self._faces]
        if (self._material is not None and self._name
                and self._name not in getattr(scene, "materials", {})):
            scene.materials[self._name] = self._material
            self._registered = True
        for f in self._faces:
            if self._name is None:
                f.attrs.pop("mat", None)
            else:
                f.attrs["mat"] = self._name
        scene.version += 1

    def undo(self, scene) -> None:
        for f, old in zip(self._faces, self._old or []):
            if old is None:
                f.attrs.pop("mat", None)
            else:
                f.attrs["mat"] = old
        if self._registered:
            scene.materials.pop(self._name, None)
            self._registered = False
        scene.version += 1


class RestampMaterialCommand(Command):
    """Edit a registry material and RESTAMP every face that wears it.

    "Change the concrete everywhere": the registry entry is replaced by
    ``new_material`` (same name) and each face across the loose mesh and
    every group whose ``attrs["mat"]`` carries that name receives the new
    recipe — colour/texture/opacity — in one undoable step. Keys absent
    from the new recipe are removed (a material edited from textured to
    plain colour drops its texture). Undo restores the registry entry and
    each face's previous values exactly."""

    def __init__(self, name, new_material) -> None:
        self._name = name
        self._new = new_material
        self._old_material = None
        self._old_faces: Optional[list] = None   # (face, {key: old value})

    _KEYS = ("color", "texture", "opacity")

    def _targets(self, scene):
        # Nested placements included: walking scene.groups as a flat list
        # left every face INSIDE a component wearing the old recipe, so
        # "change the concrete everywhere" changed it almost nowhere in an
        # imported model. Sibling instances share one prototype mesh, hence
        # the identity dedupe.
        from core.group import iter_placements
        seen: set = set()
        meshes = [scene.loose_mesh]
        for g in scene.groups:
            for pg, _m in iter_placements(g):
                if id(pg.mesh) not in seen:
                    seen.add(id(pg.mesh))
                    meshes.append(pg.mesh)
        for mesh in meshes:
            if mesh is None:
                continue
            for f in mesh.faces:
                if f.attrs.get("mat") == self._name:
                    yield f

    def do(self, scene) -> None:
        stamp = self._new.face_attrs()
        if self._old_faces is None:
            self._old_material = scene.materials.get(self._name)
            self._old_faces = [
                (f, {k: f.attrs.get(k) for k in self._KEYS})
                for f in self._targets(scene)]
        scene.materials[self._name] = self._new
        for f, _old in self._old_faces:
            for k in self._KEYS:
                if k in stamp:
                    f.attrs[k] = stamp[k]
                else:
                    f.attrs.pop(k, None)
        _dirty_group_chunks(scene)
        scene.version += 1

    def undo(self, scene) -> None:
        if self._old_material is None:
            scene.materials.pop(self._name, None)
        else:
            scene.materials[self._name] = self._old_material
        for f, old in self._old_faces or []:
            for k in self._KEYS:
                if old[k] is None:
                    f.attrs.pop(k, None)
                else:
                    f.attrs[k] = old[k]
        _dirty_group_chunks(scene)
        scene.version += 1


class PurgeUnusedCommand(Command):
    """SketchUp's "Purge Unused", for layers and/or materials.

    Layers are labels, not owners (core.layers), so emptying one cannot
    delete it — an explicit sweep is the only honest way to clear what an
    import left behind. What goes is decided ONCE, on the first ``do``:
    redo must remove exactly what the original run removed, not re-survey a
    model the user has since drawn on.

    Layers come back at their original indices so the panel order survives
    a round trip, and materials return to the registry with their recipe
    intact — the faces never changed, since a purged material is by
    definition one no face wears.
    """

    def __init__(self, layers: bool = True, materials: bool = True) -> None:
        self._do_layers = bool(layers)
        self._do_materials = bool(materials)
        #: (index, Layer) and (name, Material), captured on the first do.
        self._layers: Optional[list] = None
        self._materials: Optional[list] = None

    def _survey(self, scene) -> None:
        from core.purge import unused_layers, unused_materials
        current = list(getattr(scene, "layers", None) or ())
        self._layers = ([(current.index(ly), ly)
                         for ly in unused_layers(scene)]
                        if self._do_layers else [])
        self._materials = ([(n, scene.materials[n])
                            for n in unused_materials(scene)]
                           if self._do_materials else [])

    def counts(self, scene) -> tuple[int, int]:
        """What a run would remove — for the confirmation the panel shows."""
        if self._layers is None:
            self._survey(scene)
        return len(self._layers or []), len(self._materials or [])

    def do(self, scene) -> None:
        if self._layers is None:
            self._survey(scene)
        for _index, ly in self._layers or []:
            if ly in scene.layers:
                scene.layers.remove(ly)
        for name, _material in self._materials or []:
            scene.materials.pop(name, None)
        scene.version += 1

    def undo(self, scene) -> None:
        for index, ly in sorted(self._layers or [], key=lambda p: p[0]):
            if ly not in scene.layers:
                scene.layers.insert(min(index, len(scene.layers)), ly)
        for name, material in self._materials or []:
            scene.materials[name] = material
        scene.version += 1


class AddDimensionCommand(Command):
    """Add a dimension annotation to ``scene.dimensions``, anchored to the
    vertices under its endpoints (if any) so it follows the geometry."""

    def __init__(self, dimension) -> None:
        self.dimension = dimension

    def do(self, scene) -> None:
        if hasattr(self.dimension, "bind"):
            self.dimension.bind(scene)
        scene.dimensions.append(self.dimension)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.dimension in scene.dimensions:
            scene.dimensions.remove(self.dimension)
        scene.version += 1


class DeleteDimensionsCommand(Command):
    """Remove a set of dimensions from ``scene.dimensions``."""

    def __init__(self, dimensions) -> None:
        self._dims = list(dimensions)
        self._restore: list[tuple[int, object]] = []

    def do(self, scene) -> None:
        self._restore = [(scene.dimensions.index(d), d)
                         for d in self._dims if d in scene.dimensions]
        for d in self._dims:
            if d in scene.dimensions:
                scene.dimensions.remove(d)
            scene.selection.discard(d)
        scene.version += 1

    def undo(self, scene) -> None:
        for i, d in sorted(self._restore):
            scene.dimensions.insert(i, d)
        scene.version += 1


class AddTextLabelCommand(Command):
    """Add a leader-text annotation to ``scene.text_labels``."""

    def __init__(self, label) -> None:
        self.label = label

    def do(self, scene) -> None:
        scene.text_labels.append(self.label)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.label in scene.text_labels:
            scene.text_labels.remove(self.label)
        scene.selection.discard(self.label)
        scene.version += 1


class MoveTextLabelsCommand(Command):
    """Translate the floating label of leader texts: the label end moves,
    the anchor stays pinned and the leader stretches (SketchUp's Move-on-
    text behaviour)."""

    def __init__(self, labels, delta) -> None:
        self._labels = list(labels)
        self._delta = QVector3D(delta)

    def do(self, scene) -> None:
        for t in self._labels:
            t.offset = t.offset + self._delta
        scene.version += 1

    def undo(self, scene) -> None:
        for t in self._labels:
            t.offset = t.offset - self._delta
        scene.version += 1


class MoveDimensionsCommand(Command):
    """Move dimensions with the Move tool. A dimension ANCHORED at both
    ends slides its LINE by the delta (minus any component along the
    measured segment, so the line stays parallel and the extension lines
    stay square) while the endpoints keep holding their vertices —
    SketchUp's Move-on-dimension, «mover la cota conservando la línea guía»
    (Marco, 2026-09-20). A dimension with a free endpoint moves that
    endpoint rigidly instead. ``modes`` maps each dimension to ``"line"``
    or ``"rigid"``, decided by the tool at grab time."""

    def __init__(self, modes: dict, delta) -> None:
        self._modes = dict(modes)
        self._delta = QVector3D(delta)

    @staticmethod
    def shift(dim, mode: str, step: QVector3D) -> None:
        """Apply one step — the tool's live preview uses it too."""
        if mode == "line":
            ab = dim.b - dim.a
            length = ab.length()
            if length > 1e-9:
                d = ab / length
                step = step - d * QVector3D.dotProduct(step, d)
            dim.offset = dim.offset + step
        else:
            if dim.anchor_a is None:
                dim.a = dim.a + step
            if dim.anchor_b is None:
                dim.b = dim.b + step

    def do(self, scene) -> None:
        for dim, mode in self._modes.items():
            self.shift(dim, mode, self._delta)
        scene.version += 1

    def undo(self, scene) -> None:
        for dim, mode in self._modes.items():
            self.shift(dim, mode, -self._delta)
        scene.version += 1


class EditTextLabelCommand(Command):
    """Change the text of a leader-text annotation."""

    def __init__(self, label, text: str) -> None:
        self.label = label
        self._new = text
        self._old = label.text

    def do(self, scene) -> None:
        self.label.text = self._new
        scene.version += 1

    def undo(self, scene) -> None:
        self.label.text = self._old
        scene.version += 1


class EditDimensionTextCommand(Command):
    """Change a dimension's custom text (``None`` = back to the measured
    value) — SketchUp's double-click on the dimension text."""

    def __init__(self, dim, text) -> None:
        self.dim = dim
        self._new = text or None
        self._old = getattr(dim, "text", None)

    def do(self, scene) -> None:
        self.dim.text = self._new
        scene.version += 1

    def undo(self, scene) -> None:
        self.dim.text = self._old
        scene.version += 1


class DeleteTextLabelsCommand(Command):
    """Remove a set of text labels from ``scene.text_labels``."""

    def __init__(self, labels) -> None:
        self._labels = list(labels)
        self._restore: list[tuple[int, object]] = []

    def do(self, scene) -> None:
        self._restore = [(scene.text_labels.index(t), t)
                         for t in self._labels if t in scene.text_labels]
        for t in self._labels:
            if t in scene.text_labels:
                scene.text_labels.remove(t)
            scene.selection.discard(t)
        scene.version += 1

    def undo(self, scene) -> None:
        for i, t in sorted(self._restore):
            scene.text_labels.insert(i, t)
        scene.version += 1


class AddGuideCommand(Command):
    """Add a construction guide (Tape Measure) to ``scene.guides``."""

    def __init__(self, guide) -> None:
        self.guide = guide

    def do(self, scene) -> None:
        scene.guides.append(self.guide)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.guide in scene.guides:
            scene.guides.remove(self.guide)
        scene.version += 1


class PlaceSectionPlaneCommand(Command):
    """Place a section plane. SketchUp: the new plane immediately becomes
    the ACTIVE cut of the context; undo restores the previous one."""

    def __init__(self, plane) -> None:
        self.plane = plane
        self._prev_active = None

    def do(self, scene) -> None:
        self._prev_active = scene.active_section()
        scene.section_planes.append(self.plane)
        scene.set_active_section(self.plane)
        scene.selection.clear()
        scene.selection.add(self.plane)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.plane in scene.section_planes:
            scene.section_planes.remove(self.plane)
        scene.selection.discard(self.plane)
        prev = self._prev_active
        scene.set_active_section(
            prev if prev in scene.section_planes else None)
        scene.version += 1


class DeleteSectionPlanesCommand(Command):
    """Remove section planes; undo restores them at their positions with
    their active state."""

    def __init__(self, planes) -> None:
        self._planes = list(planes)
        self._restore: list[tuple[int, object]] = []

    def do(self, scene) -> None:
        self._restore = [(scene.section_planes.index(p), p)
                         for p in self._planes if p in scene.section_planes]
        for p in self._planes:
            if p in scene.section_planes:
                scene.section_planes.remove(p)
            scene.selection.discard(p)
        scene.version += 1

    def undo(self, scene) -> None:
        for i, p in sorted(self._restore):
            scene.section_planes.insert(i, p)
        scene.version += 1


class ReverseSectionPlaneCommand(Command):
    """SketchUp's Reverse: flip which side the plane hides."""

    def __init__(self, plane) -> None:
        self.plane = plane

    def do(self, scene) -> None:
        self.plane.flip()
        scene.version += 1

    def undo(self, scene) -> None:
        self.plane.flip()
        scene.version += 1


class SetActiveSectionCommand(Command):
    """Make ``plane`` the active cut (or ``None`` to deactivate) — SketchUp's
    Active Cut toggle / double-click."""

    def __init__(self, plane) -> None:
        self.plane = plane
        self._prev = None

    def do(self, scene) -> None:
        self._prev = scene.active_section()
        scene.set_active_section(self.plane)
        scene.version += 1

    def undo(self, scene) -> None:
        prev = self._prev
        scene.set_active_section(
            prev if prev in scene.section_planes else None)
        scene.version += 1


class MoveSectionPlanesCommand(Command):
    """Translate section planes (the Move tool)."""

    def __init__(self, planes, delta: QVector3D) -> None:
        self._planes = list(planes)
        self.delta = QVector3D(delta)

    def do(self, scene) -> None:
        for p in self._planes:
            p.point = p.point + self.delta
        scene.version += 1

    def undo(self, scene) -> None:
        for p in self._planes:
            p.point = p.point - self.delta
        scene.version += 1


class RotateSectionPlanesCommand(Command):
    """Rotate section planes about ``centre``/``axis`` (the Rotate tool):
    the origin orbits and the normal turns."""

    def __init__(self, planes, centre: QVector3D, axis: QVector3D,
                 deg: float) -> None:
        self._planes = list(planes)
        self.centre = QVector3D(centre)
        self.axis = QVector3D(axis)
        self.deg = float(deg)

    def _apply(self, scene, deg: float) -> None:
        m = rotation_matrix(self.centre, self.axis, deg)
        for p in self._planes:
            p.point = m.map(p.point)
            n = m.mapVector(p.normal)
            if n.length() > 1e-12:
                p.normal = n.normalized()
        scene.version += 1

    def do(self, scene) -> None:
        self._apply(scene, self.deg)

    def undo(self, scene) -> None:
        self._apply(scene, -self.deg)


class ChangeGuideCommand(Command):
    """Re-aim an existing guide line (Protractor hot retype: after the guide
    is created, a typed angle updates it until the next click/command)."""

    def __init__(self, guide, direction) -> None:
        self.guide = guide
        self.new = QVector3D(direction).normalized()
        self.old: Optional[QVector3D] = None

    def do(self, scene) -> None:
        self.old = self.guide.direction
        self.guide.direction = QVector3D(self.new)
        scene.version += 1

    def undo(self, scene) -> None:
        self.guide.direction = self.old
        scene.version += 1


class DeleteGuidesCommand(Command):
    """Remove construction guides (the Eraser, or Edit ▸ Delete Guides)."""

    def __init__(self, guides) -> None:
        self._guides = list(guides)
        self._restore: list[tuple[int, object]] = []

    def do(self, scene) -> None:
        self._restore = [(scene.guides.index(g), g)
                         for g in self._guides if g in scene.guides]
        for g in self._guides:
            if g in scene.guides:
                scene.guides.remove(g)
            scene.selection.discard(g)
        scene.version += 1

    def undo(self, scene) -> None:
        for i, g in sorted(self._restore):
            scene.guides.insert(i, g)
        scene.version += 1


class AddImagePlaneCommand(Command):
    """Place an imported reference image (``File ▸ Import ▸ Image``).

    The image lands on its own layer so it can be switched off without taking
    the drawing with it (the reasoning behind ``layers.SURVEY_LAYER``); the
    command creates that layer when missing and takes it back on undo, so
    importing and undoing leaves the document exactly as it was.
    """

    def __init__(self, image) -> None:
        self.image = image
        self._made_layer = False

    def do(self, scene) -> None:
        from core.layers import Layer
        name = getattr(self.image, "layer", None)
        self._made_layer = False
        if name and scene.layer(name) is None:
            scene.layers.append(Layer(name))
            self._made_layer = True
        scene.image_planes.append(self.image)
        scene.selection.clear()
        scene.selection.add(self.image)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.image in scene.image_planes:
            scene.image_planes.remove(self.image)
        scene.selection.discard(self.image)
        if self._made_layer:
            name = getattr(self.image, "layer", None)
            ly = scene.layer(name) if name else None
            if ly is not None:
                scene.layers.remove(ly)
            self._made_layer = False
        scene.version += 1


class DeleteImagePlanesCommand(Command):
    """Remove reference images (Delete / the Eraser). Positions are restored
    so undo puts each one back where it sat in the stacking order."""

    def __init__(self, images) -> None:
        self._images = list(images)
        self._restore: list[tuple[int, object]] = []

    def do(self, scene) -> None:
        self._restore = [(scene.image_planes.index(im), im)
                         for im in self._images if im in scene.image_planes]
        for im in self._images:
            if im in scene.image_planes:
                scene.image_planes.remove(im)
            scene.selection.discard(im)
        scene.version += 1

    def undo(self, scene) -> None:
        for i, im in sorted(self._restore, key=lambda t: t[0]):
            scene.image_planes.insert(i, im)
        scene.version += 1


class TransformImagePlaneCommand(Command):
    """Set an image's corner and edge vectors — the one undoable step behind
    scaling, moving and rotating it. Callers compute the new frame (e.g.
    ``ImagePlane.scaled``) and hand it over; the command only swaps it in, so
    every way of reshaping an image shares one reversible operation."""

    def __init__(self, image, origin=None, u=None, v=None) -> None:
        from PySide6.QtGui import QVector3D
        self.image = image
        self._new = (
            QVector3D(origin) if origin is not None else None,
            QVector3D(u) if u is not None else None,
            QVector3D(v) if v is not None else None,
        )
        self._old: tuple | None = None

    def do(self, scene) -> None:
        from PySide6.QtGui import QVector3D
        im = self.image
        self._old = (QVector3D(im.origin), QVector3D(im.u), QVector3D(im.v))
        origin, u, v = self._new
        if origin is not None:
            im.origin = QVector3D(origin)
        if u is not None:
            im.u = QVector3D(u)
        if v is not None:
            im.v = QVector3D(v)
        scene.version += 1

    def undo(self, scene) -> None:
        from PySide6.QtGui import QVector3D
        if self._old is None:
            return
        origin, u, v = self._old
        self.image.origin = QVector3D(origin)
        self.image.u = QVector3D(u)
        self.image.v = QVector3D(v)
        scene.version += 1


class SetImagePlaneOpacityCommand(Command):
    """Fade a reference image (a scan you trace over, an orthomosaic under
    the model) — one undoable step."""

    def __init__(self, image, opacity: float) -> None:
        self.image = image
        self.opacity = max(0.0, min(1.0, float(opacity)))
        self._old = float(getattr(image, "opacity", 1.0))

    def do(self, scene) -> None:
        self.image.opacity = self.opacity
        scene.version += 1

    def undo(self, scene) -> None:
        self.image.opacity = self._old
        scene.version += 1


class MoveImagePlanesCommand(Command):
    """Translate reference images (the Move tool). Only the origin corner
    moves — the edge vectors carry size and orientation, so a move can never
    resize or turn the picture by accident."""

    def __init__(self, images, delta: QVector3D) -> None:
        self._images = list(images)
        self.delta = QVector3D(delta)

    def _apply(self, scene, delta: QVector3D) -> None:
        for im in self._images:
            im.origin = im.origin + delta
        scene.version += 1

    def do(self, scene) -> None:
        self._apply(scene, self.delta)

    def undo(self, scene) -> None:
        self._apply(scene, -self.delta)


class RotateImagePlanesCommand(Command):
    """Rotate reference images about ``centre``/``axis`` (the Rotate tool):
    the origin orbits and both edge vectors turn with it, so the picture keeps
    its size and its proportions and simply faces a new way. Rotating about an
    axis off the image's own plane tilts it, which is how a facade photo gets
    stood up against a wall."""

    def __init__(self, images, centre: QVector3D, axis: QVector3D,
                 deg: float) -> None:
        self._images = list(images)
        self.centre = QVector3D(centre)
        self.axis = QVector3D(axis)
        self.deg = float(deg)

    def _apply(self, scene, deg: float) -> None:
        m = rotation_matrix(self.centre, self.axis, deg)
        for im in self._images:
            im.origin = m.map(im.origin)
            im.u = m.mapVector(im.u)
            im.v = m.mapVector(im.v)
        scene.version += 1

    def do(self, scene) -> None:
        self._apply(scene, self.deg)

    def undo(self, scene) -> None:
        self._apply(scene, -self.deg)


class ScaleImagePlanesCommand(Command):
    """Uniformly scale reference images about ``anchor`` (the Scale tool).

    Both edge vectors take the same factor, so the picture is never distorted
    — which is the whole reason a scan is worth scaling: you set it against a
    distance you know and everything else on it becomes measurable. A negative
    factor mirrors the image through the anchor, as it does for geometry.
    """

    def __init__(self, images, anchor: QVector3D, factor, axes=None) -> None:
        self._images = list(images)
        self.axes = axes
        self.anchor = QVector3D(anchor)
        # A float scales uniformly; a 3-tuple per axis (the grip box).
        self.factor = (tuple(float(f) for f in factor)
                       if isinstance(factor, (tuple, list)) else float(factor))

    def _apply(self, scene, factor: float) -> None:
        m = scale_matrix(self.anchor, factor, self.axes)
        for im in self._images:
            im.origin = m.map(im.origin)
            im.u = m.mapVector(im.u)
            im.v = m.mapVector(im.v)
        scene.version += 1

    def do(self, scene) -> None:
        self._apply(scene, self.factor)

    def undo(self, scene) -> None:
        self._apply(scene, invert_scale_factor(self.factor))


class AddGeoPathCommand(Command):
    """Add a traced georef path to ``scene.geo_paths`` (Track G)."""

    def __init__(self, path) -> None:
        self.path = path

    def do(self, scene) -> None:
        scene.geo_paths.append(self.path)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.path in scene.geo_paths:
            scene.geo_paths.remove(self.path)
        scene.selection.discard(self.path)
        scene.version += 1


class AutoTagDrawnFacesCommand(Command):
    """Tag-as-you-draw (BIM active class): the final step of a draw plan when
    ``scene.active_ifc`` is set. Stamps the active tag on the faces the plan
    itself created — the drawn polygon, auto-closed cycles, chord halves —
    identified through their ``AddFaceCommand``s, so churn re-emissions
    (``auto=False``) and neighbouring rebuilt faces are never touched. A face
    that inherited a tag from a tagged mother keeps it.

    Each draw commit becomes its OWN BIM object (a fresh id is allocated at
    execution time; the activation only fixes class + name): a wall drawn per
    trace = one object per wall, so the largest-face metrado stays honest —
    one shared id across many walls would under-report (the panel/IFC read
    the biggest face of the whole set).

    Runs inside the draw's :class:`SnapshotCompound`, before the after-state
    snapshot, so undo/redo restore the tags exactly; its own undo is a no-op
    (the snapshot restore reverts the attrs)."""

    def __init__(self, face_commands, tag: dict) -> None:
        self._face_cmds = list(face_commands)
        self._tag = dict(tag)

    def do(self, scene) -> None:
        from core.bim import next_object_id
        tag = dict(self._tag)
        tag["id"] = next_object_id(scene)
        live = scene.mesh.faces
        for fc in self._face_cmds:
            f = getattr(fc, "face", None)
            if f is not None and f in live and not f.attrs.get("ifc"):
                f.attrs["ifc"] = dict(tag)

    def undo(self, scene) -> None:
        pass


class AddGeoPointsCommand(Command):
    """Import a batch of survey points into ``scene.geo_points`` (Track G).
    When the import also anchored the scene datum (first georef action on the
    document), the datum travels with the command so undo restores the
    previous one."""

    def __init__(self, points, datum=None) -> None:
        self._points = list(points)
        self._datum = datum
        self._prev_datum = None

    def do(self, scene) -> None:
        if self._datum is not None:
            self._prev_datum = scene.georef
            scene.georef = self._datum
        scene.geo_points.extend(self._points)
        scene.version += 1

    def undo(self, scene) -> None:
        for p in self._points:
            if p in scene.geo_points:
                scene.geo_points.remove(p)
        if self._datum is not None:
            scene.georef = self._prev_datum
        scene.version += 1


class DeleteGeoPointsCommand(Command):
    """Remove survey points from ``scene.geo_points``."""

    def __init__(self, points) -> None:
        self._points = list(points)
        self._restore: list[tuple[int, object]] = []

    def do(self, scene) -> None:
        self._restore = [(scene.geo_points.index(p), p)
                         for p in self._points if p in scene.geo_points]
        for p in self._points:
            if p in scene.geo_points:
                scene.geo_points.remove(p)
        scene.version += 1

    def undo(self, scene) -> None:
        for i, p in sorted(self._restore):
            scene.geo_points.insert(i, p)
        scene.version += 1


class DeleteGeoPathsCommand(Command):
    """Remove georef paths from ``scene.geo_paths``."""

    def __init__(self, paths) -> None:
        self._paths = list(paths)
        self._restore: list[tuple[int, object]] = []

    def do(self, scene) -> None:
        self._restore = [(scene.geo_paths.index(p), p)
                         for p in self._paths if p in scene.geo_paths]
        for p in self._paths:
            if p in scene.geo_paths:
                scene.geo_paths.remove(p)
            scene.selection.discard(p)
        scene.version += 1

    def undo(self, scene) -> None:
        for i, p in sorted(self._restore):
            scene.geo_paths.insert(i, p)
        scene.version += 1


class ToggleGeoPathClosedCommand(Command):
    """Flip open ↔ closed (loop) on a set of georef paths."""

    def __init__(self, paths) -> None:
        self._paths = list(paths)

    def _flip(self, scene) -> None:
        for p in self._paths:
            p.closed = not p.closed
        scene.version += 1

    do = _flip
    undo = _flip


class SetGeoPathSurfaceCommand(Command):
    """Set the terrain-surface mode (None/"flat"/"draped") on georef paths.

    A surface implies a closed polygon, so this also closes the path; undo
    restores the prior mode and closed flag. Built triangles are recomputed
    outside (they depend on the DEM), so they're just cleared here.
    """

    def __init__(self, paths, mode) -> None:
        self.mode = mode
        self._paths = list(paths)
        self._prev: list = []

    def do(self, scene) -> None:
        self._prev = [(p, p.surface, p.closed) for p in self._paths]
        for p in self._paths:
            p.surface = self.mode
            if self.mode:
                p.closed = True
            p._surface_tris = None
        scene.version += 1

    def undo(self, scene) -> None:
        for p, surface, closed in self._prev:
            p.surface = surface
            p.closed = closed
            p._surface_tris = None
        scene.version += 1


class MoveGeoPathNodeCommand(Command):
    """Move one node of a georef path to a new position (undoable)."""

    def __init__(self, path, index, new_point) -> None:
        from PySide6.QtGui import QVector3D
        self.path = path
        self.index = index
        self._new = QVector3D(new_point)
        self._old = None

    def do(self, scene) -> None:
        from PySide6.QtGui import QVector3D
        self._old = QVector3D(self.path.points[self.index])
        self.path.points[self.index] = QVector3D(self._new)
        scene.version += 1

    def undo(self, scene) -> None:
        from PySide6.QtGui import QVector3D
        self.path.points[self.index] = QVector3D(self._old)
        scene.version += 1


class SetFaceTextureCommand(Command):
    """Apply an image texture (``{"path","sw","sh"}``) to a set of faces, or
    clear it with ``None`` — stored in each face's ``attrs["texture"]`` (rides
    the rebuild like the colour). Topology-free, so the attrs swap inverts it."""

    def __init__(self, faces, texture) -> None:
        self._faces = list(faces)
        self._tex = dict(texture) if texture is not None else None
        self._old: Optional[list] = None

    def do(self, scene) -> None:
        if self._old is None:
            self._old = [f.attrs.get("texture") for f in self._faces]
        for f in self._faces:
            if self._tex is None:
                f.attrs.pop("texture", None)
            else:
                f.attrs["texture"] = dict(self._tex)
        _dirty_group_chunks(scene)
        scene.version += 1

    def undo(self, scene) -> None:
        for f, old in zip(self._faces, self._old or []):
            if old is None:
                f.attrs.pop("texture", None)
            else:
                f.attrs["texture"] = dict(old)
        _dirty_group_chunks(scene)
        scene.version += 1


class SetFaceBackCommand(Command):
    """Paint the BACK side of a set of faces: ``attrs["back"]`` becomes the
    given material dict (``color``/``texture``/``opacity``/``mat``, the same
    keys the front uses), or the side goes back to the style's default with
    ``None``. Per face, because a positioned texture keeps its ``uvw`` only
    on the plane it was fitted for (see the Paint tool). Topology-free, so
    the attrs swap inverts it — the old value may be ``True`` (a two-sided
    face) and comes back as such."""

    def __init__(self, faces, backs) -> None:
        self._faces = list(faces)
        # One dict per face, or None for all.
        if backs is None or isinstance(backs, dict):
            backs = [backs] * len(self._faces)
        self._backs = [dict(b) if isinstance(b, dict) else None for b in backs]
        self._old: Optional[list] = None

    @staticmethod
    def _put(f, value) -> None:
        if value is None:
            f.attrs.pop("back", None)
        else:
            f.attrs["back"] = dict(value) if isinstance(value, dict) else value

    def do(self, scene) -> None:
        if self._old is None:
            self._old = [f.attrs.get("back") for f in self._faces]
        for f, b in zip(self._faces, self._backs):
            self._put(f, b)
        _dirty_group_chunks(scene)
        scene.version += 1

    def undo(self, scene) -> None:
        for f, old in zip(self._faces, self._old or []):
            self._put(f, old)
        _dirty_group_chunks(scene)
        scene.version += 1


def translate_points(scene, keys: set, delta: QVector3D) -> None:
    """Move every shared vertex whose position key is in ``keys`` by ``delta``.

    Because vertices are shared, every edge and face referencing a moved vertex
    follows for free — the mechanic behind raising a ridge into a gable roof.
    Shared by :class:`MoveVerticesCommand` and the Push/Pull live preview.
    """
    moving = [v for v in scene.mesh.vertices if _key(v.position) in keys]
    for v in moving:
        scene.mesh.move_vertex(v, delta)
    scene.version += 1


class MoveVerticesCommand(Command):
    """Translate every shared vertex at a set of positions by ``delta``, then
    **autofold**: any face the move warped out of its plane is split into
    planar pieces along fold edges (SketchUp behaviour — a quad with a lifted
    corner becomes two triangles, not a fake bent "face").

    Undo/redo restore identity-preserving snapshots. The old "cheap" inverse
    translation resolved vertices *by position*, so when a moved corner landed
    exactly on another vertex (an endpoint snap does this constantly) the undo
    dragged the innocent coincident vertex along too, warping the drawing. The
    before-snapshot was already being captured every time — restoring it is the
    exact inverse for every case (plain move, fold, landed-on-vertex)."""

    def __init__(self, positions: Iterable[QVector3D], delta: QVector3D) -> None:
        self.src = [QVector3D(p) for p in positions]
        self.delta = QVector3D(delta)
        self._before: Optional[dict] = None
        self._after: Optional[dict] = None

    def do(self, scene) -> None:
        if self._after is not None:  # redo
            scene.mesh.restore_state(self._after)
            scene.version += 1
            return
        self._before = scene.mesh.capture_state()
        translate_points(scene, {_key(p) for p in self.src}, self.delta)
        fold_nonplanar_faces(scene.mesh)
        self._after = scene.mesh.capture_state()

    def undo(self, scene) -> None:
        if self._before is not None:
            scene.mesh.restore_state(self._before)
            scene.version += 1


def rotation_matrix(center: QVector3D, axis: QVector3D, degrees: float):
    """Rigid rotation of ``degrees`` around ``axis`` through ``center``."""
    from PySide6.QtGui import QMatrix4x4
    m = QMatrix4x4()
    m.translate(center)
    m.rotate(degrees, axis.normalized())
    m.translate(-center)
    return m


def rotate_points(scene, keys: set, matrix) -> None:
    """Rotate every shared vertex whose position key is in ``keys`` by the
    rigid ``matrix`` (the rotation twin of :func:`translate_points`). Shared
    by :class:`RotateVerticesCommand` and the Rotate tool's live preview."""
    moving = [v for v in scene.mesh.vertices if _key(v.position) in keys]
    for v in moving:
        scene.mesh.move_vertex(v, matrix.map(v.position) - v.position)
    scene.version += 1


def mirror_matrix(centre: QVector3D, axis: QVector3D):
    """Reflection about the plane through ``centre`` with normal ``axis``
    (Householder), as a QMatrix4x4 — SketchUp's Flip."""
    from PySide6.QtGui import QMatrix4x4
    n = QVector3D(axis).normalized()
    r = QMatrix4x4(
        1 - 2 * n.x() * n.x(), -2 * n.x() * n.y(), -2 * n.x() * n.z(), 0,
        -2 * n.y() * n.x(), 1 - 2 * n.y() * n.y(), -2 * n.y() * n.z(), 0,
        -2 * n.z() * n.x(), -2 * n.z() * n.y(), 1 - 2 * n.z() * n.z(), 0,
        0, 0, 0, 1)
    t_in = QMatrix4x4()
    t_in.translate(-centre)
    t_out = QMatrix4x4()
    t_out.translate(centre)
    return t_out * r * t_in


class FlipGroupsCommand(Command):
    """Flip whole groups about an axis plane (SketchUp's Flip). Instances
    compose the reflection into their transform (O(1)); classic groups map
    their vertices and re-reverse every face loop so the mirrored solid
    keeps its faces pointing OUT. A reflection is an involution: undo flips
    again."""

    def __init__(self, groups, centre: QVector3D, axis: QVector3D) -> None:
        self._groups = list(groups)
        self.centre = QVector3D(centre)
        self.axis = QVector3D(axis)

    def _flip(self, scene) -> None:
        m = mirror_matrix(self.centre, self.axis)
        for g in self._groups:
            if getattr(g, "xform", None) is not None:
                g.xform = m * g.xform
                continue
            for v in list(g.mesh.vertices):
                g.mesh.move_vertex(v, m.map(v.position) - v.position)
            from core.group import carry_axes
            carry_axes(g, m)                  # an involution, like the rest
            for f in g.mesh.faces:
                f.loop.reverse()
                for h in getattr(f, "hole_loops", []) or []:
                    h.reverse()
        _dirty_group_chunks(scene)
        scene.version += 1

    def do(self, scene) -> None:
        self._flip(scene)

    def undo(self, scene) -> None:
        self._flip(scene)


class FlipVerticesCommand(Command):
    """Mirror loose positions about an axis plane and re-reverse the fully
    selected faces' windings (their normals would flip inward otherwise).
    Snapshot undo, the exact mirror of RotateVerticesCommand."""

    def __init__(self, positions: Iterable[QVector3D], centre: QVector3D,
                 axis: QVector3D, faces=()) -> None:
        self.src = [QVector3D(p) for p in positions]
        self.centre = QVector3D(centre)
        self.axis = QVector3D(axis)
        self._faces = list(faces)
        self._before: Optional[dict] = None
        self._after: Optional[dict] = None

    def do(self, scene) -> None:
        if self._after is not None:  # redo
            scene.mesh.restore_state(self._after)
            scene.version += 1
            return
        self._before = scene.mesh.capture_state()
        m = mirror_matrix(self.centre, self.axis)
        rotate_points(scene, {_key(p) for p in self.src}, m)
        for f in self._faces:
            if hasattr(f, "loop"):
                f.loop.reverse()
                for h in getattr(f, "hole_loops", []) or []:
                    h.reverse()
        fold_nonplanar_faces(scene.mesh)
        self._after = scene.mesh.capture_state()

    def undo(self, scene) -> None:
        if self._before is not None:
            scene.mesh.restore_state(self._before)
            scene.version += 1


class RotateVerticesCommand(Command):
    """Rotate every shared vertex at a set of positions around ``axis``
    through ``center`` by ``degrees``, then **autofold** (a partial rotation
    can warp attached faces out of plane, same as Move). Undo/redo restore
    identity-preserving snapshots — the exact mirror of
    :class:`MoveVerticesCommand`."""

    def __init__(self, positions: Iterable[QVector3D], center: QVector3D,
                 axis: QVector3D, degrees: float) -> None:
        self.src = [QVector3D(p) for p in positions]
        self.center = QVector3D(center)
        self.axis = QVector3D(axis)
        self.degrees = degrees
        self._before: Optional[dict] = None
        self._after: Optional[dict] = None

    def do(self, scene) -> None:
        if self._after is not None:  # redo
            scene.mesh.restore_state(self._after)
            scene.version += 1
            return
        self._before = scene.mesh.capture_state()
        m = rotation_matrix(self.center, self.axis, self.degrees)
        rotate_points(scene, {_key(p) for p in self.src}, m)
        fold_nonplanar_faces(scene.mesh)
        self._after = scene.mesh.capture_state()

    def undo(self, scene) -> None:
        if self._before is not None:
            scene.mesh.restore_state(self._before)
            scene.version += 1


class RotateGroupCommand(Command):
    """Rotate a whole group's isolated mesh (rigid — nothing folds). Snapshot
    undo/redo on the group's own mesh."""

    def __init__(self, group, center: QVector3D, axis: QVector3D,
                 degrees: float) -> None:
        self.group = group
        self.center = QVector3D(center)
        self.axis = QVector3D(axis)
        self.degrees = degrees
        self._before: Optional[dict] = None
        self._after: Optional[dict] = None

    def do(self, scene) -> None:
        if getattr(self.group, "xform", None) is not None:
            m = rotation_matrix(self.center, self.axis, self.degrees)
            self.group.xform = m * self.group.xform
            scene.version += 1
            return
        gmesh = self.group.mesh
        if self._after is not None:  # redo
            gmesh.restore_state(self._after)
            self.group.axes = self._axes_after
            scene.version += 1
            return
        self._before = gmesh.capture_state()
        self._axes_before = self.group.axes
        m = rotation_matrix(self.center, self.axis, self.degrees)
        for v in list(gmesh.vertices):
            gmesh.move_vertex(v, m.map(v.position) - v.position)
        from core.group import _remap_uvws, carry_axes
        _remap_uvws(gmesh, m)                 # the texture turns with it
        carry_axes(self.group, m)             # and so do its axes (#44)
        self._axes_after = self.group.axes
        self._after = gmesh.capture_state()
        scene.version += 1

    def undo(self, scene) -> None:
        if getattr(self.group, "xform", None) is not None:
            m = rotation_matrix(self.center, self.axis, -self.degrees)
            self.group.xform = m * self.group.xform
            scene.version += 1
            return
        if self._before is not None:
            self.group.mesh.restore_state(self._before)
            self.group.axes = self._axes_before
            scene.version += 1


def scale_matrix(center: QVector3D, factor, axes=None):
    """Scale about ``center``: a float scales uniformly, a 3-tuple scales each
    axis by its own factor (SketchUp's edge/face grips). A negative factor
    mirrors through the centre along that axis (SketchUp allows it — dragging
    a grip past its anchor, or typing -1).

    ``axes`` = ``(red, green, blue)`` unit vectors: the three factors act
    along THOSE instead of the world's — the grip box of a turned group, on
    its own axes (issue #44). ``None`` is the world, exactly as before."""
    from PySide6.QtGui import QMatrix4x4
    if axes is not None and isinstance(factor, (tuple, list)):
        from core.axes import frame_matrix
        rot = frame_matrix(QVector3D(0.0, 0.0, 0.0), *axes)
        inv = rot.transposed()
        s = QMatrix4x4()
        s.scale(float(factor[0]), float(factor[1]), float(factor[2]))
        m = QMatrix4x4()
        m.translate(center)
        m = m * rot * s * inv
        back = QMatrix4x4()
        back.translate(-center)
        return m * back
    m = QMatrix4x4()
    m.translate(center)
    if isinstance(factor, (tuple, list)):
        m.scale(float(factor[0]), float(factor[1]), float(factor[2]))
    else:
        m.scale(float(factor))
    m.translate(-center)
    return m


def invert_scale_factor(factor):
    """The factor that undoes ``factor`` — per-axis for tuples. Zero factors
    (already rejected upstream) invert to 1.0 instead of dividing by zero."""
    def inv(f):
        return 1.0 / f if abs(f) > 1e-12 else 1.0
    if isinstance(factor, (tuple, list)):
        return tuple(inv(float(f)) for f in factor)
    return inv(float(factor))


class ScaleVerticesCommand(Command):
    """Uniformly scale every shared vertex at a set of positions about
    ``center`` by ``factor``, then autofold (scaling a subset of connected
    geometry can warp attached faces). Snapshot undo/redo — the mirror of
    Move/RotateVerticesCommand."""

    def __init__(self, positions: Iterable[QVector3D], center: QVector3D,
                 factor: float, axes=None) -> None:
        self.src = [QVector3D(p) for p in positions]
        self.center = QVector3D(center)
        self.factor = factor
        self.axes = axes
        self._before: Optional[dict] = None
        self._after: Optional[dict] = None

    def do(self, scene) -> None:
        if self._after is not None:  # redo
            scene.mesh.restore_state(self._after)
            scene.version += 1
            return
        self._before = scene.mesh.capture_state()
        m = scale_matrix(self.center, self.factor, self.axes)
        rotate_points(scene, {_key(p) for p in self.src}, m)  # generic mapper
        fold_nonplanar_faces(scene.mesh)
        self._after = scene.mesh.capture_state()

    def undo(self, scene) -> None:
        if self._before is not None:
            scene.mesh.restore_state(self._before)
            scene.version += 1


class ScaleGroupCommand(Command):
    """Uniformly scale a whole group's isolated mesh about ``center``.
    Snapshot undo/redo on the group's own mesh."""

    def __init__(self, group, center: QVector3D, factor: float,
                 axes=None) -> None:
        self.group = group
        self.center = QVector3D(center)
        self.factor = factor
        self.axes = axes
        self._before: Optional[dict] = None
        self._after: Optional[dict] = None

    def do(self, scene) -> None:
        if getattr(self.group, "xform", None) is not None:
            self.group.xform = scale_matrix(
                self.center, self.factor, self.axes) * self.group.xform
            scene.version += 1
            return
        gmesh = self.group.mesh
        if self._after is not None:  # redo
            gmesh.restore_state(self._after)
            self.group.axes = self._axes_after
            scene.version += 1
            return
        self._before = gmesh.capture_state()
        self._axes_before = self.group.axes
        m = scale_matrix(self.center, self.factor, self.axes)
        for v in list(gmesh.vertices):
            gmesh.move_vertex(v, m.map(v.position) - v.position)
        from core.group import _remap_uvws, carry_axes
        _remap_uvws(gmesh, m)                 # the texture scales with it
        carry_axes(self.group, m)             # the origin moves with it (#44)
        self._axes_after = self.group.axes
        self._after = gmesh.capture_state()
        scene.version += 1

    def undo(self, scene) -> None:
        if getattr(self.group, "xform", None) is not None:
            self.group.xform = scale_matrix(
                self.center, invert_scale_factor(self.factor),
                self.axes) * self.group.xform
            scene.version += 1
            return
        if self._before is not None:
            self.group.mesh.restore_state(self._before)
            self.group.axes = self._axes_before
            scene.version += 1


class PruneOrphanEdgesCommand(Command):
    """Remove edges incident to ``vertices`` that, once the rest of a compound
    has run, border no face — the dangling lines left where push/pull carved
    geometry away. Computed at ``do`` time so it reflects the real post-carve
    scene; ``undo`` re-links the swept edges."""

    def __init__(self, vertices: Iterable[QVector3D]) -> None:
        self.vertices = [QVector3D(v) for v in vertices]
        self.removed: list[Edge] = []

    def do(self, scene) -> None:
        self.removed = orphaned_edges_at(scene.edges, scene.faces, self.vertices)
        for edge in self.removed:
            scene.mesh.remove_edge(edge)
            scene.selection.discard(edge)
        if self.removed:
            scene.version += 1

    def undo(self, scene) -> None:
        for edge in self.removed:
            scene.mesh.relink_edge(edge)
        if self.removed:
            scene.version += 1
        self.removed = []


class CoplanarMergeCommand(Command):
    """Dissolve coplanar seams left by push/pull, SketchUp-style.

    After a wall is pushed flush against an adjacent one, the shared edge borders
    two faces in the same plane and carries no silhouette — a phantom line. This
    command sweeps the edges incident to the operation's vertices and merges any
    such redundant pair into one face (the "L"), so the result reads as a clean
    solid. Seeded with the operation's vertices (not the whole model) so a
    *deliberately* drawn coplanar edge elsewhere is left alone.

    Each merge is recorded as ``(face_a, face_b, edge, merged_face)`` so undo
    restores the exact objects other commands may reference.
    """

    def __init__(self, seed_positions: Iterable[QVector3D]) -> None:
        self.seed = [QVector3D(p) for p in seed_positions]
        self.merges: list[tuple[Face, Face, Edge, Face]] = []

    def do(self, scene) -> None:
        mesh = scene.mesh
        seedkeys = {_key(p) for p in self.seed}
        progress = True
        while progress:
            progress = False
            for edge in list(mesh.edges):
                if len(edge.faces) != 2:
                    continue
                if (_key(edge.v0.position) not in seedkeys
                        and _key(edge.v1.position) not in seedkeys):
                    continue
                face_a, face_b = edge.faces[0], edge.faces[1]
                merged = mesh.dissolve_edge(edge)
                if merged is None:
                    continue
                self.merges.append((face_a, face_b, edge, merged))
                progress = True
                break  # mesh mutated — restart the scan
        if self.merges:
            scene.version += 1

    def undo(self, scene) -> None:
        mesh = scene.mesh
        for face_a, face_b, edge, merged in reversed(self.merges):
            mesh.remove_face(merged)
            mesh.relink_edge(edge)
            mesh.relink_face(face_a)
            mesh.relink_face(face_b)
        if self.merges:
            scene.version += 1
        self.merges = []


class StitchSolidCommand(Command):
    """Make a solid watertight again after push/pull, SketchUp-style.

    Repeated pushes leave three kinds of connectivity debris: edges that run past
    a vertex belonging to a neighbour (a *T-junction* — the two sides share a
    line but no edge, so the seam reads as a naked crack), redundant valence-2
    collinear vertices left by mismatched subdivision, and coplanar faces that
    should be one. This runs in three phases:

    1. **Resolve T-junctions** (seeded): split every edge that reaches the
       operation's own bounds at any vertex on its interior, so mismatched
       subdivisions share edges → no naked cracks.
    2. **Collapse collinear vertices** (global): drop spurious valence-2 points.
    3. **Coplanar-merge** (seeded): fuse coplanar faces around the operation
       into one — seeded so a deliberately drawn coplanar line elsewhere stays.

    Phases 1–2 only repair connectivity (no shape change). The splits,
    collapses and merges interact too tightly for a clean per-op inverse, so
    undo restores an identity-preserving snapshot taken before the pass —
    robust, and it keeps the surrounding delta commands' object references
    valid (this command runs last in the push/pull compound).
    """

    def __init__(self, seed_positions: Iterable[QVector3D]) -> None:
        self.seed = [QVector3D(p) for p in seed_positions]
        self.snapshot: Optional[dict] = None

    def do(self, scene) -> None:
        self.snapshot = scene.mesh.capture_state()
        run_stitch(scene.mesh, {_key(p) for p in self.seed})
        scene.version += 1

    def undo(self, scene) -> None:
        if self.snapshot is not None:
            scene.mesh.restore_state(self.snapshot)
            scene.version += 1


def run_stitch(mesh, seedkeys: set, new_faces: Optional[set] = None,
               coplanar_merge: bool = True, dedupe: bool = True) -> None:
    """Three-phase watertight cleanup (no undo bookkeeping — the caller snapshots).
    See :class:`StitchSolidCommand` for the rationale of each phase.

    ``seedkeys`` are the operation's own positions (``core.topology._key``
    tuples). They bound phase 1 — only an edge reaching that box can be split,
    which is every T-junction the op can have created and none of the ones it
    found lying around — and seed phase 3.

    ``new_faces`` (when given) are the faces this operation created; phase 3 only
    fuses a coplanar component that contains one of them, so a seam a push just
    made is merged while a pre-existing coplanar split (a user's diagonal) is
    left intact. ``None`` means merge any seeded component (manual stitch).

    ``coplanar_merge=False`` runs only phases 0–2 (connectivity repair). Solid
    push/pull uses this: its seams are dissolved by the deterministic per-plane
    rebuild (:mod:`core.cap_rebuild`) instead of the winding-tolerant merge,
    which only remains for raw/open geometry where outwardness is undefined.

    ``dedupe=False`` skips the identical-cycle face dedupe of phase 0. The
    solid path's *first* stitch needs that: a flush-collapse sweep quad lands
    identical to the face it must annihilate *with*, and the per-plane rebuild
    is what decides whether the pair means "keep one" (a shared wall built
    twice — material on both sides) or "drop both" (an emptied region) — by
    parity, where the pair's two crossings cancel. Deduping it early restores
    the material reading and the collapse never classifies."""
    # Phase 0 — weld coincident vertices (a translated cap landing flush on the
    # ring it came from); merges duplicate edges, drops degenerated faces. Then
    # drop faces stacked on an identical cycle (a shared wall built twice).
    mesh.weld_coincident()
    if dedupe:
        mesh.dedupe_faces()
    # Phase 1 — resolve T-junctions (global). Batch form: the per-edge
    # ``interior_vertex_on`` walked EVERY vertex in Python and the loop
    # restarted from edge zero after each split — O(splits × E × V). An
    # imported brick barbecue (3k faces, T-junctions everywhere) hung the
    # push preview for minutes per drag frame (SIGUSR1 autopsy: two stacks
    # pinned at interior_vertex_on).
    #
    # Now the sweep is ONE vectorised pass, and it is **scoped to the
    # operation**: only edges whose box meets the seed's box can be split.
    #
    # That scope is a correctness fix as much as a speed one. Sweeping every
    # edge made a push *silently re-topologise geometry it never touched* —
    # on an imported barbecue, pushing one brick split ten edges, eight of
    # them a metre away on an unrelated plane, and since a drag preview
    # reverts each frame it redid that same distant repair on every mouse
    # move. A stitch repairs what its operation disturbed; a T-junction the
    # op did not create is not its business.
    #
    # The scope is exact for what the op *can* create: a split needs the
    # splitting vertex to lie on the edge, and either the vertex is the op's
    # (so it is in the seed box, and the edge's box must reach it) or the
    # edge is the op's (so its box is inside the seed box). Either way the
    # edge's box meets the seed box.
    from core.topology import sweep_tjunctions
    sweep_tjunctions(mesh, seedkeys)
    # Phase 2 — collapse redundant valence-2 collinear vertices (global).
    while True:
        collapsed = False
        for v in list(mesh.vertices):
            if mesh.collapsible_vertex(v):
                mesh.collapse_vertex(v)
                collapsed = True
                break
        if not collapsed:
            break
    if not coplanar_merge:
        return
    # Phase 3 — coplanar-merge, seeded to the operation. Fuses the whole coplanar
    # component (every shared edge, any number of faces) at once, but only when it
    # includes a face this operation created (so user diagonals survive).
    while True:
        merged = False
        ncache: dict = {}
        scache: dict = {}
        for f0 in list(mesh.faces):
            comp = _coplanar_component(mesh, f0, seedkeys, ncache, scache)
            if len(comp) < 2:
                continue
            if new_faces is not None and not (comp & new_faces):
                continue
            region = mesh.dissolve_coplanar_region(comp)
            if region is not None:
                if new_faces is not None:
                    new_faces -= comp
                    new_faces.add(region)
                merged = True
                break
        if not merged:
            break


def _coplanar_component(mesh, f0, seedkeys: set,
                        ncache: Optional[dict] = None,
                        scache: Optional[dict] = None) -> set:
    """Maximal set of coplanar, edge-connected faces that touch the operation's
    seed. Whether the component is actually merged is gated separately on it
    containing a face the operation created (see ``run_stitch``).

    An edge that also carries a *non-coplanar* face is a **crease** — a wall
    standing under the seam — and the component never crosses it: two roof
    slabs over a dividing wall stay two faces with a visible ridge,
    SketchUp-style, instead of fusing into one slab floating over the wall.

    ``ncache``/``scache`` memoise per-face normalized normals and seed tests
    within one (mutation-free) scan — Newell normals recomputed per comparison
    dominated the push drag preview."""
    if ncache is None:
        ncache = {}
    if scache is None:
        scache = {}

    def nrm(f):
        v = ncache.get(f)
        if v is None:
            v = f.normal().normalized()
            ncache[f] = v
        return v

    def seeded(f):
        v = scache.get(f)
        if v is None:
            v = any(_key(p) in seedkeys for p in f.vertices)
            scache[f] = v
        return v

    if not seeded(f0):
        return set()
    n0 = nrm(f0)
    comp = {f0}
    stack = [f0]
    while stack:
        f = stack.pop()
        for loop in (f.loop, *f.hole_loops):
            for a, b in zip(loop, loop[1:] + loop[:1]):
                e = mesh.find_edge(a, b)
                if e is None:
                    continue
                if any(abs(QVector3D.dotProduct(n0, nrm(h))) < 0.999
                       for h in e.faces):
                    continue  # crease: a perpendicular face holds this edge
                for g in e.faces:
                    if g in comp or not seeded(g):
                        continue
                    # Coplanar regardless of winding sign — a push/pull can leave
                    # a fragment wound the opposite way (a prism floor cap +Z vs a
                    # bump strip -Z); same surface, so it belongs to the region.
                    if abs(QVector3D.dotProduct(n0, g.normal())) > 0.999:
                        comp.add(g)
                        stack.append(g)
    return comp


class SnapshotMutation(Command):
    """Wrap an arbitrary mesh mutation with snapshot undo. The push/pull live
    preview applies the *same* mutation each drag frame (then reverts via its own
    snapshot), so the forming solid renders exactly as it will commit — clean,
    already stitched — instead of flashing the pre-stitch seams.

    Redo restores the captured *result* rather than re-running the mutation: the
    closure usually closes over tool state (``base_face`` etc.) that is reset
    right after commit, so re-running it on redo would crash — and re-running the
    deterministic plane rebuild on stale state would be wasteful besides.

    ``mesh`` (when given) is the mesh to snapshot instead of the scene's loose
    one — a push/pull aimed at a Group edits that group's isolated mesh."""

    def __init__(self, mutate, mesh: Optional[Mesh] = None) -> None:
        self.mutate = mutate
        self._mesh = mesh
        self.before: Optional[dict] = None
        self.after: Optional[dict] = None

    def _target(self, scene) -> Mesh:
        return self._mesh if self._mesh is not None else scene.mesh

    def do(self, scene) -> None:
        mesh = self._target(scene)
        if self.after is None:
            self.before = mesh.capture_state()
            self.mutate(scene)
            self.after = mesh.capture_state()
        else:
            mesh.restore_state(self.after)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.before is not None:
            self._target(scene).restore_state(self.before)
            scene.version += 1


class SnapshotImport(Command):
    """Wrap a file import that may add loose geometry AND/OR reference groups
    (big DAE/OBJ models land as a Group). SnapshotMutation only snapshots the
    mesh, so a group added by the loader would survive undo — this also
    remembers and reverts the groups the import appended."""

    def __init__(self, mutate) -> None:
        self.mutate = mutate
        self.before: Optional[dict] = None
        self.after: Optional[dict] = None
        self.added_groups: list = []
        self.added_layers: list = []
        self.added_views: list = []
        self.added_dims: list = []
        self.added_texts: list = []

    def do(self, scene) -> None:
        m = scene.mesh
        if self.after is None:
            groups_before = list(scene.groups)
            layers_before = list(scene.layers)
            views_before = list(scene.saved_views)
            dims_before = list(scene.dimensions)
            texts_before = list(scene.text_labels)
            self.before = m.capture_state()
            try:
                self.mutate(scene)
            except BaseException:
                # History.execute restores the mesh, but a loader or AI
                # recipe that fails halfway has already appended groups
                # (extrude/revolve land one per call), layers, views,
                # dimensions or labels — leave none of them behind.
                scene.groups[:] = [g for g in scene.groups
                                   if g in groups_before]
                scene.layers[:] = [ly for ly in scene.layers
                                   if ly in layers_before]
                scene.saved_views[:] = [v for v in scene.saved_views
                                        if v in views_before]
                scene.dimensions[:] = [d for d in scene.dimensions
                                       if d in dims_before]
                scene.text_labels[:] = [t for t in scene.text_labels
                                        if t in texts_before]
                raise
            self.after = m.capture_state()
            self.added_groups = [g for g in scene.groups
                                 if g not in groups_before]
            self.added_layers = [ly for ly in scene.layers
                                 if ly not in layers_before]
            self.added_views = [v for v in scene.saved_views
                                if v not in views_before]
            self.added_dims = [d for d in scene.dimensions
                               if d not in dims_before]
            self.added_texts = [t for t in scene.text_labels
                                if t not in texts_before]
        else:
            m.restore_state(self.after)
            for g in self.added_groups:
                if g not in scene.groups:
                    scene.groups.append(g)
            for ly in self.added_layers:
                if ly not in scene.layers:
                    scene.layers.append(ly)
            for v in self.added_views:
                if v not in scene.saved_views:
                    scene.saved_views.append(v)
            for d in self.added_dims:
                if d not in scene.dimensions:
                    scene.dimensions.append(d)
            for t in self.added_texts:
                if t not in scene.text_labels:
                    scene.text_labels.append(t)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.before is not None:
            scene.mesh.restore_state(self.before)
        for g in self.added_groups:
            if g in scene.groups:
                scene.groups.remove(g)
            scene.selection.discard(g)
        for ly in self.added_layers:
            if ly in scene.layers:
                scene.layers.remove(ly)
        for v in self.added_views:
            if v in scene.saved_views:
                scene.saved_views.remove(v)
        for d in self.added_dims:
            if d in scene.dimensions:
                scene.dimensions.remove(d)
        for t in self.added_texts:
            if t in scene.text_labels:
                scene.text_labels.remove(t)
        scene.version += 1


class SnapshotCompound(Command):
    """Run a list of sub-commands under one identity-preserving snapshot, undone
    by restoring it.

    The line-draw plan splits and welds edges (and punches holes in coplanar
    faces); the per-command inverses don't compose into a clean whole — undoing
    them piecemeal leaves orphan split edges and stray vertices behind. One
    snapshot of the entire edit reverses it exactly, and because identity is
    preserved, earlier history entries keep working across this undo."""

    def __init__(self, inner: Iterable[Command]) -> None:
        self.inner = list(inner)
        self.before: Optional[dict] = None
        self.after: Optional[dict] = None

    def do(self, scene) -> None:
        if self.after is None:
            # First run: snapshot before, apply the plan, clean up any coplanar
            # overlap it created (redundant nested holes / spurious mother), then
            # snapshot the result so undo/redo restore exactly.
            self.before = scene.mesh.capture_state()
            for cmd in self.inner:
                cmd.do(scene)
            for f in heal_overlapping_faces(scene.mesh):
                scene.selection.discard(f)
            # A draw that split a curve leaves it in separate contours — break
            # the curve ids there (SketchUp), before the snapshot so redo keeps it.
            scene.mesh.resplit_curves()
            self.after = scene.mesh.capture_state()
        else:
            # Redo: re-running the delta plan wouldn't reproduce the splits, so
            # restore the captured result directly.
            scene.mesh.restore_state(self.after)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.before is not None:
            scene.mesh.restore_state(self.before)
            scene.version += 1


class MeshSnapshotCommand(Command):
    """Run a list of sub-commands plus the stitch pass under a single
    identity-preserving snapshot, undone by restoring that snapshot.

    Push/pull builds its edit as delta commands and then stitches the result
    watertight; the stitch's splits/merges restructure the very edges those
    commands own, so composing their individual undos leaves orphan edges. One
    snapshot of the whole push is exact and robust — and because it preserves
    object identity, *other* history entries (a drawn line, an earlier push) keep
    working across this undo."""

    def __init__(self, inner: Iterable[Command], stitch_seed: Iterable[QVector3D]) -> None:
        self.inner = list(inner)
        self.seed = [QVector3D(p) for p in stitch_seed]
        self.snapshot: Optional[dict] = None

    def do(self, scene) -> None:
        self.snapshot = scene.mesh.capture_state()
        before = set(self.snapshot["faces"])
        for cmd in self.inner:
            cmd.do(scene)
        new_faces = set(scene.mesh.faces) - before
        run_stitch(scene.mesh, {_key(p) for p in self.seed}, new_faces)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.snapshot is not None:
            scene.mesh.restore_state(self.snapshot)
            scene.version += 1


class MakeGroupCommand(Command):
    """Encapsulate the selected faces and edges into a new Group with its own
    mesh, removing them from the loose mesh so they no longer weld to the rest.
    Snapshot undo (geometry crosses meshes — too tangled for a per-op inverse)."""

    def __init__(self, faces: Iterable[Face], edges: Iterable[Edge],
                 component: bool = False, name: str | None = None) -> None:
        # ``component=True`` builds the fresh mesh in LOCAL coordinates
        # (origin at the selection's min corner) and hands back an INSTANCE
        # (Group with an xform) — SketchUp's Make Component: copies of it
        # share the definition through the existing prototype machinery.
        self._component = component
        self._name = name
        faces = list(faces)
        # Attrs (colour, texture, layer, IFC tag) must travel into the group's
        # fresh mesh with each face — grouping a painted set used to strip it.
        self._face_loops = [
            ([QVector3D(v) for v in f.vertices],
             [[QVector3D(v) for v in h] for h in f.holes],
             dict(f.attrs))
            for f in faces
        ]
        self._edge_ends = [(QVector3D(e.a), QVector3D(e.b)) for e in edges]
        # Edge flags must travel into the group's fresh mesh: without them,
        # grouping a smooth cylinder suddenly shows every facet seam (soft
        # edges hidden in the loose mesh, visible in the group), its rims stop
        # selecting as whole curves, and a HIDDEN edge comes back from the
        # dead — «oculté una arista, agrupo el dibujo y la arista vuelve a
        # aparecer» (Marco, 2026-09-10). They travel as one tuple now, so the
        # next flag added to an edge cannot be forgotten here.
        self._flagged: list = []

        def note(e):
            if e is not None and not edge_is_plain(e):
                self._flagged.append(
                    (QVector3D(e.a), QVector3D(e.b), edge_flags(e)))

        for f in faces:
            for lp in (f.loop, *f.hole_loops):
                n = len(lp)
                for i in range(n):
                    va, vb = lp[i], lp[(i + 1) % n]
                    note(next((k for k in va.edges if k.other(va) is vb),
                              None))
        for e in edges:
            note(e)
        self.snapshot: Optional[dict] = None
        self.group: Optional[Group] = None

    def do(self, scene) -> None:
        m = scene.mesh
        self.snapshot = m.capture_state()
        # The group is a fresh copy built from the captured positions. A
        # COMPONENT shifts them into local coordinates around the origin.
        origin = QVector3D(0.0, 0.0, 0.0)
        # Made inside a turned group, the new one lines up with THAT
        # context's axes (SketchUp; issue #44): its origin is the lowest
        # corner measured along them, not along the world's.
        frame = getattr(scene, "drawing_frame", None)
        pts = [p for loop, holes, _a in self._face_loops
               for lst in (loop, *holes) for p in lst]
        pts += [p for pair in self._edge_ends for p in pair]
        rot = None
        if frame is not None and pts:
            from core.group import frame_axes
            fo, fx, fy, fz = frame_axes(frame)

            def loc(p):
                d = QVector3D(p) - fo
                return (QVector3D.dotProduct(d, fx), QVector3D.dotProduct(d, fy),
                        QVector3D.dotProduct(d, fz))
            ls = [loc(p) for p in pts]
            lo = (min(q[0] for q in ls), min(q[1] for q in ls),
                  min(q[2] for q in ls))
            corner = fo + fx * lo[0] + fy * lo[1] + fz * lo[2]
            rot = (fx, fy, fz)
        if self._component and pts:
            if rot is not None:
                origin = corner
            else:
                origin = QVector3D(min(p.x() for p in pts),
                                   min(p.y() for p in pts),
                                   min(p.z() for p in pts))

        def L(p):
            if self._component and rot is not None:
                d = QVector3D(p) - origin       # into the context's axes
                return QVector3D(QVector3D.dotProduct(d, rot[0]),
                                 QVector3D.dotProduct(d, rot[1]),
                                 QVector3D.dotProduct(d, rot[2]))
            return QVector3D(p) - origin

        gmesh = Mesh()
        for loop, holes, attrs in self._face_loops:
            gf = gmesh.add_face([L(p) for p in loop],
                                [[L(p) for p in h] for h in holes] or None)
            if attrs:
                gf.attrs.update(attrs)
        for a, b in self._edge_ends:
            gmesh.add_edge(L(a), L(b))
        for a, b, flags in self._flagged:
            va, vb = gmesh.vertex_at(L(a)), gmesh.vertex_at(L(b))
            e = (gmesh.find_edge(va, vb)
                 if va is not None and vb is not None else None)
            if e is not None:
                stamp_edge_flags(e, flags)
        self.group = Group(gmesh, name=self._name)
        if self._component:
            from PySide6.QtGui import QMatrix4x4
            if rot is not None:
                from core.axes import frame_matrix
                self.group.xform = frame_matrix(origin, *rot)
            else:
                t = QMatrix4x4()
                t.translate(origin)
                self.group.xform = t
        elif rot is not None:
            from core.axes import frame_matrix
            self.group.axes = frame_matrix(corner, *rot)
        # Remove the grouped geometry from the loose mesh.
        face_keysets = [frozenset(_key(p) for p in loop)
                        for loop, _h, _a in self._face_loops]
        for f in list(m.faces):
            if frozenset(_key(p) for p in f.vertices) in face_keysets:
                m.remove_face(f)
                scene.selection.discard(f)
        grouped = {_key(p) for loop, holes, _a in self._face_loops
                   for lst in (loop, *holes) for p in lst}
        sel_edges = {frozenset((_key(a), _key(b))) for a, b in self._edge_ends}
        for e in list(m.edges):
            ek = frozenset((_key(e.a), _key(e.b)))
            if not e.faces and (ek in sel_edges or
                                (_key(e.a) in grouped and _key(e.b) in grouped)):
                m.remove_edge(e)
                scene.selection.discard(e)
        scene.groups.append(self.group)
        scene.selection.clear()
        scene.selection.add(self.group)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.group in scene.groups:
            scene.groups.remove(self.group)
        scene.selection.discard(self.group)
        scene.mesh.restore_state(self.snapshot)
        scene.version += 1


class ReshareInstanceCommand(Command):
    """Leaving a component instance edited in place: the session's edits go
    into the shared definition, so every copy shows them (SketchUp).

    The commands run inside the session are absorbed into this one — the
    whole edit undoes as one step, back to the definition as it was, with
    the instance shared again. Redo replays it from the edited copy."""

    def __init__(self, group, proto, xform, edited, inner=()) -> None:
        self.group = group
        self.proto = proto
        self.xform = xform
        self.edited = edited
        self.inner = list(inner)
        self._before = None

    def do(self, scene) -> None:
        if self._before is None:
            self._before = self.proto.capture_state()
        scene.share_back(self.group, self.proto, self.xform, self.edited)
        scene.version += 1

    def undo(self, scene) -> None:
        self.proto.restore_state(self._before)
        self.group.mesh = self.proto
        self.group.xform = self.xform
        scene.version += 1


class MakeUniqueCommand(Command):
    """SketchUp's Make Unique: bake a component instance into its OWN mesh
    so edits stop touching the siblings' shared definition."""

    def __init__(self, group) -> None:
        self.group = group
        self._proto = None
        self._xform = None
        self._children = None
        self._axes = None
        self._component = True

    def do(self, scene) -> None:
        self._proto = self.group.mesh
        self._xform = self.group.xform
        self._children = self.group.children
        self._axes = self.group.axes
        self._component = self.group.component
        self.group.make_unique()
        scene.version += 1

    def undo(self, scene) -> None:
        self.group.mesh = self._proto
        self.group.xform = self._xform
        self.group.children = self._children or []
        self.group.axes = self._axes
        self.group.component = self._component
        scene.version += 1


class GroupToComponentCommand(Command):
    """Convert a CLASSIC group into a component instance in place: its mesh
    becomes the shared definition (world frame == local frame) under an
    identity transform. Free — no geometry is copied — and from then on
    Move/Rotate compose the matrix (O(1)) and copies share the definition.
    The reverse road exists too (Make Unique). Exploding a 230k-face group
    to feed Make Component ground the loose-mesh machinery for minutes
    (piscina report); this is the door that was missing."""

    def __init__(self, group, name=None) -> None:
        self.group = group
        self._name = name
        self._old_name = None

    def do(self, scene) -> None:
        from PySide6.QtGui import QMatrix4x4
        self._old_name = self.group.name
        self._old_xform = self.group.xform
        self._old_component = self.group.component
        if self.group.xform is None:
            self.group.xform = QMatrix4x4()
        # A group of groups already carries a matrix: it only changes what
        # it IS — a component from now on (issue #90).
        self.group.component = True
        if self._name:
            self.group.name = self._name
        scene.version += 1

    def undo(self, scene) -> None:
        self.group.xform = self._old_xform
        self.group.component = self._old_component
        self.group.name = self._old_name
        scene.version += 1


class InsertGroupCommand(Command):
    """Insert a ready-made Group (a bundled component, a paste, a future
    collection item) into the scene, selected so the user can Move it into
    place.

    INSIDE an open container it goes into the container — SketchUp's rule
    that whatever you create while editing a group belongs to it. A roof
    pasted while editing the pergola used to land at the top level, beside
    the plaza («se supone que todo lo que edite debería estar dentro del
    grupo», Marco, 2026-09-14). The group arrives in WORLD coordinates and
    is expressed in the container's own space when that one carries a
    matrix (entering usually pushes it down into the children already)."""

    def __init__(self, group) -> None:
        self.group = group
        self._owner: Optional[list] = None

    @staticmethod
    def _target(scene):
        ctx = getattr(scene, "edit_group", None)
        if ctx is not None and getattr(ctx, "children", None) is not None:
            return ctx
        return None

    def do(self, scene) -> None:
        ctx = self._target(scene)
        if ctx is not None:
            owner = ctx.children
            if ctx.xform is not None:
                inv, ok = ctx.xform.inverted()
                if ok:
                    from core.group import transformed_mesh
                    if self.group.xform is not None:
                        self.group.xform = inv * self.group.xform
                    else:
                        self.group.mesh = transformed_mesh(self.group.mesh, inv)
                        from core.group import carry_axes
                        carry_axes(self.group, inv)
        else:
            owner = scene.groups
        owner.append(self.group)
        self._owner = owner
        scene.selection.clear()
        scene.selection.add(self.group)
        scene.version += 1

    def undo(self, scene) -> None:
        owner = self._owner if self._owner is not None else scene.groups
        if self.group in owner:
            owner.remove(self.group)
        scene.selection.discard(self.group)
        scene.version += 1


class EditText3DCommand(Command):
    """Re-edit a 3D text (core/text3d.py): the container keeps its identity,
    pose and own mesh; its letter children are laid out again from the new
    parameters where the old ones stood, and the name follows the text.
    Undo puts the old letters and parameters back."""

    def __init__(self, group, params: dict) -> None:
        self.group = group
        self.params = dict(params)
        self._old: Optional[tuple] = None

    def do(self, scene) -> None:
        from core.text3d import rebuild_text_group, text_state
        g = self.group
        if self._old is None:
            self._old = (g.children, g.text3d, g.name)
        g.children = rebuild_text_group(g, self.params)
        g.text3d = text_state(self.params, g.children)
        g.name = self.params["text"].strip()[:24] or g.name
        scene.version += 1

    def undo(self, scene) -> None:
        g = self.group
        g.children, g.text3d, g.name = self._old
        scene.version += 1


class MakeNestedGroupCommand(Command):
    """SketchUp's Make Group when the selection already holds groups.

    Until 2026-09-11 this was refused: a container baked its children the
    moment you opened it, so nesting would have dissolved the bench and the
    pergola you just grouped. With the edit stack in place (Scene) that is
    gone, and grouping groups is what it says.

    The loose part of the selection, if any, becomes the container's OWN
    mesh — the same thing SketchUp does: inside the new group you find the
    loose faces AND the groups, each still a group. Reusing
    :class:`MakeGroupCommand` for that half keeps one code path for taking
    geometry off the loose mesh.
    """

    def __init__(self, faces: Iterable[Face], edges: Iterable[Edge],
                 groups: Iterable[Group], name: str | None = None) -> None:
        faces, edges, groups = list(faces), list(edges), list(groups)
        self._inner = (MakeGroupCommand(faces, edges, name=name)
                       if (faces or edges) else None)
        self.groups = groups
        self.name = name
        self.container: Optional[Group] = None
        self._indices: list = []
        self._xform0 = None

    def do(self, scene) -> None:
        if self._inner is not None:
            self._inner.do(scene)
            self.container = self._inner.group
        elif self.container is None:
            self.container = Group(Mesh(), name=self.name)
        if self.container not in scene.groups:
            scene.groups.append(self.container)
        self._xform0 = getattr(self.container, "xform", None)
        self._indices = sorted(
            ((scene.groups.index(g), g) for g in self.groups),
            key=lambda pair: pair[0])
        for _i, g in self._indices:
            scene.groups.remove(g)
            scene.selection.discard(g)
        # In document order, not selection order: a selection is a set, and
        # the children of a group are a list somebody will read.
        self.container.adopt([g for _i, g in self._indices])
        # A GROUP of groups: ``adopt`` gives it a matrix, which does not
        # make it a component (issue #90, @fafecm).
        self.container.component = False
        scene.selection.clear()
        scene.selection.add(self.container)
        scene.version += 1

    def undo(self, scene) -> None:
        self.container.children = []
        self.container.xform = self._xform0
        for idx, g in self._indices:
            scene.groups.insert(min(idx, len(scene.groups)), g)
        if self._inner is not None:
            self._inner.undo(scene)        # loose geometry back, group gone
        elif self.container in scene.groups:
            scene.groups.remove(self.container)
        scene.selection.clear()
        scene.version += 1


class MakeComponentOfCommand(Command):
    """Make Component over a selection that holds groups (or groups and
    loose geometry): ONE component containing them, each still a group
    inside — not one component per group (Marco, 24-09, with issue #90).
    It is Make Group's container, made a component."""

    def __init__(self, faces, edges, groups, name=None) -> None:
        self._nest = MakeNestedGroupCommand(faces, edges, groups, name=name)

    @property
    def container(self):
        return self._nest.container

    def do(self, scene) -> None:
        self._nest.do(scene)
        self._nest.container.component = True
        scene.version += 1

    def undo(self, scene) -> None:
        self._nest.undo(scene)


class MergeGroupsCommand(Command):
    """Fuse several groups (component instances included) into ONE new
    group holding their combined world-space geometry — the fix-my-
    grouping path. Explode + regroup routes everything through the loose
    mesh, whose per-face machinery froze on a 100k-leaf import (piscina
    report); this merge goes group-to-group through the bulk-weld API and
    the loose mesh never hears about it. Undo restores the original
    groups at their positions."""

    def __init__(self, groups) -> None:
        self._groups = list(groups)
        self._indices: Optional[list] = None
        self._merged = None

    def do(self, scene) -> None:
        import numpy as np
        from core.group import Group, world_mesh
        from core.mesh import Mesh
        if self._merged is None:
            flat: list = []
            e_flat: list = []
            e_flags: list = []
            ring_sizes: list = []
            ring_counts: list = []
            attrs_list: list = []
            for g in self._groups:
                src = world_mesh(g)      # instances: transformed, UVs refit
                for f in src.faces:
                    holes = f.holes or []
                    ring_counts.append(1 + len(holes))
                    ring_sizes.append(len(f.vertices))
                    flat.extend((v.x(), v.y(), v.z()) for v in f.vertices)
                    for h in holes:
                        ring_sizes.append(len(h))
                        flat.extend((v.x(), v.y(), v.z()) for v in h)
                    attrs_list.append(dict(f.attrs) if f.attrs else None)
                for e in src.edges:
                    e_flat.append((e.a.x(), e.a.y(), e.a.z()))
                    e_flat.append((e.b.x(), e.b.y(), e.b.z()))
                    e_flags.append((bool(getattr(e, "soft", False)),
                                    getattr(e, "curve", None),
                                    getattr(e, "layer", None),
                                    bool(getattr(e, "hidden", False))))
            mesh = Mesh()
            n_edge_pts = len(e_flat)
            if e_flat or flat:
                vobjs, inverse = mesh.bulk_weld(
                    np.array(e_flat + flat, dtype=np.float64))
                emap = None
                if e_flat:
                    emap = mesh.add_edges_welded(
                        vobjs, inverse[0:n_edge_pts:2],
                        inverse[1:n_edge_pts:2], e_flags)
                if ring_counts:
                    mesh.add_faces_welded(
                        vobjs, inverse[n_edge_pts:],
                        np.asarray(ring_sizes, dtype=np.int64),
                        np.asarray(ring_counts, dtype=np.int64),
                        attrs_list, edge_map=emap)
            merged = Group(mesh, name=self._groups[0].name)
            merged.layer = getattr(self._groups[0], "layer", None)
            self._merged = merged
        self._indices = [scene.groups.index(g) for g in self._groups]
        for g in self._groups:
            scene.groups.remove(g)
            scene.selection.discard(g)
        scene.groups.append(self._merged)
        scene.selection.clear()
        scene.selection.add(self._merged)
        scene.version += 1

    def undo(self, scene) -> None:
        if self._merged in scene.groups:
            scene.groups.remove(self._merged)
        scene.selection.discard(self._merged)
        for idx, g in sorted(zip(self._indices or [], self._groups)):
            scene.groups.insert(min(idx, len(scene.groups)), g)
        scene.version += 1


class SetGroupMaterialCommand(Command):
    """Paint a group or component instance as a whole (issue #47): the
    container's ``material`` is set — ``None`` unpaints — and every face
    inside wearing the default material shows it; faces painted themselves
    keep their own. Nothing in the mesh changes, so undo is a plain swap."""

    def __init__(self, group, material) -> None:
        self.group = group
        self.material = dict(material) if material else None
        self._old = None

    def do(self, scene) -> None:
        self._old = getattr(self.group, "material", None)
        self.group.material = self.material
        scene.version += 1

    def undo(self, scene) -> None:
        self.group.material = self._old
        scene.version += 1


class ExplodeGroupCommand(Command):
    """Dissolve ONE level of a group: its own geometry merges back into the
    loose mesh (welding to whatever it touches) and the groups and
    components nested in it come out whole, as top-level objects in its
    place — SketchUp's Explode (@pacaeiro, issue #72: «the inside groups
    explode as well»). Snapshot undo restores the loose mesh, the group and
    each lifted child's placement."""

    def __init__(self, group: Group) -> None:
        self.group = group
        self.snapshot: Optional[dict] = None
        self.index: Optional[int] = None
        self._lifted: list = []   # (child, xform, mesh, material, axes, offset)
        self._selection = None

    def do(self, scene) -> None:
        from core.materials import effective_attrs
        m = scene.mesh
        g = self.group
        self.snapshot = m.capture_state()
        self.index = scene.groups.index(g)
        self._selection = set(scene.selection)
        P = getattr(g, "xform", None)
        paint = getattr(g, "material", None)

        def W(p):
            # Instance prototypes hold LOCAL coords — explode in world.
            return P.map(p) if P is not None else QVector3D(p)

        for f in g.mesh.faces:
            nf = m.add_face([W(v) for v in f.vertices],
                            [[W(v) for v in h] for h in f.holes] or None)
            # What the face showed inside is what it keeps outside: its own
            # paint, or — a default face — the group's on BOTH sides
            # (SketchUp; issue #47: the back used to fall back to default).
            drawn = effective_attrs(dict(f.attrs or {}), paint)
            for key, val in drawn.items():
                nf.attrs[key] = dict(val) if isinstance(val, dict) else val
        for e in g.mesh.edges:
            v0, v1 = m.vertex_at(W(e.a)), m.vertex_at(W(e.b))
            if v0 is None or v1 is None or m.find_edge(v0, v1) is None:
                m.add_edge(W(e.a), W(e.b))
        # Edge flags travel back out of the group (the mirror of
        # MakeGroupCommand): an exploded cylinder must stay smooth, its rims
        # keep selecting as whole curves, and a hidden edge stay hidden.
        for e in g.mesh.edges:
            if edge_is_plain(e):
                continue
            v0, v1 = m.vertex_at(W(e.a)), m.vertex_at(W(e.b))
            k = (m.find_edge(v0, v1)
                 if v0 is not None and v1 is not None else None)
            if k is not None:
                stamp_edge_flags(k, edge_flags(e))
        m.resplit_curves()

        # The nested objects come out one level up, whole: their placement
        # composes with the parent's (a shared prototype is never touched),
        # and an unpainted child takes the parent's paint, as its default
        # faces were already drawn with it.
        kids = list(getattr(g, "children", None) or [])
        self._lifted = [(c, c.xform, c.mesh, c.material, c.axes,
                         c.explode_offset) for c in kids]
        for c in kids:
            # Free of its component, a part keeps where an exploded view put
            # it; there is no longer anything to reassemble it into.
            c.explode_offset = None
            if P is not None:
                if c.xform is not None:
                    c.xform = P * c.xform
                else:
                    from core.group import carry_axes, transformed_mesh
                    c.mesh = transformed_mesh(c.mesh, P)
                    carry_axes(c, P)          # its axes come out with it
            if c.material is None and paint:
                c.material = {k: (dict(v) if isinstance(v, dict) else v)
                              for k, v in paint.items()}
        scene.groups.remove(g)
        scene.groups[self.index:self.index] = kids
        scene.selection.discard(g)
        if kids:
            scene.selection = set(kids)   # SketchUp selects what came out
        scene.version += 1

    def undo(self, scene) -> None:
        for c, xform, mesh, material, axes, offset in self._lifted:
            if c in scene.groups:
                scene.groups.remove(c)
            c.xform, c.mesh, c.material, c.axes = xform, mesh, material, axes
            c.explode_offset = offset
        scene.mesh.restore_state(self.snapshot)
        scene.groups.insert(self.index, self.group)
        if self._selection is not None:
            scene.selection = set(self._selection)
        scene.version += 1


class RenameGroupCommand(Command):
    """Give a group, component or part a new name (the Parts tray's edit)."""

    def __init__(self, group: Group, name: str) -> None:
        self.group = group
        self.name = name
        self.old: Optional[str] = None

    def do(self, scene) -> None:
        self.old = self.group.name
        self.group.name = self.name
        scene.version += 1

    def undo(self, scene) -> None:
        self.group.name = self.old
        scene.version += 1


class ExplodeViewCommand(Command):
    """Pull a component's parts apart to ``factor`` along ``mode`` — or put
    them back with ``factor=0`` (see :mod:`core.explode`)."""

    def __init__(self, container: Group, factor: float,
                 mode: str = "outward") -> None:
        self.container = container
        self.factor = factor
        self.mode = mode
        self.before = None

    def do(self, scene) -> None:
        from core import explode
        self.before = explode.snapshot(self.container)
        explode.apply_explode(self.container, self.factor, self.mode)
        scene.version += 1

    def undo(self, scene) -> None:
        from core import explode
        explode.restore(self.container, self.before)
        scene.version += 1


class SplitIntoPiecesCommand(Command):
    """Replace what ``group`` holds with ``pieces`` (from
    :func:`core.pieces.split_into_pieces`): the same geometry, now one child
    group per physical piece. The group stays the object the user placed —
    same matrix, name, layer and paint — so it moves, copies and exports as
    before, and Explode sets the pieces free. Undo puts the old contents
    back untouched (the split only ever built new meshes)."""

    def __init__(self, group: Group, pieces: list) -> None:
        self.group = group
        self.pieces = list(pieces)
        self.before: Optional[tuple] = None

    def do(self, scene) -> None:
        g = self.group
        self.before = (g.mesh, list(g.children), g.xform, g.exploded)
        from core.mesh import Mesh
        g.mesh = Mesh()
        g.adopt(self.pieces)
        # The pieces are cut from the geometry as it stands, so they ARE
        # assembled in their new arrangement: nothing left to take back.
        g.exploded = None
        scene.version += 1

    def undo(self, scene) -> None:
        g = self.group
        g.mesh, g.children, g.xform, g.exploded = self.before
        scene.version += 1


class MoveGroupCommand(Command):
    """Translate a whole group by ``delta`` (every vertex of its mesh). Because
    the group is isolated, this never drags the rest of the model."""

    def __init__(self, group: Group, delta: QVector3D) -> None:
        self.group = group
        self.delta = QVector3D(delta)

    def _shift(self, scene, delta) -> None:
        if getattr(self.group, "xform", None) is not None:
            # Component instance: compose into the transform — O(1), and the
            # shared prototype mesh (siblings!) is never touched.
            from PySide6.QtGui import QMatrix4x4
            t = QMatrix4x4()
            t.translate(delta)
            self.group.xform = t * self.group.xform
        else:
            from core.group import _remap_uvws
            from PySide6.QtGui import QMatrix4x4
            for v in list(self.group.mesh.vertices):
                self.group.mesh.move_vertex(v, delta)
            t = QMatrix4x4()
            t.translate(delta)
            _remap_uvws(self.group.mesh, t)   # the texture travels along
            from core.group import carry_axes
            carry_axes(self.group, t)         # and its axes (#44)
        scene.version += 1

    def do(self, scene) -> None:
        self._shift(scene, self.delta)

    def undo(self, scene) -> None:
        self._shift(scene, -self.delta)


def placement_is_identity(xform, tol: float = 1e-6) -> bool:
    """True when a placement neither turns nor moves anything (within
    ``tol``) — straightening it would be a silent no-op."""
    if xform is None:
        return True
    from PySide6.QtGui import QMatrix4x4
    ident = QMatrix4x4()
    return all(abs(xform(r, c) - ident(r, c)) <= tol
               for r in range(4) for c in range(4))


def placement_rotation_deg(xform) -> float:
    """Turn about Z (degrees, counter-clockwise seen from above) of a rigid
    placement; raises ``ValueError`` when the placement tilts or scales —
    there is no north angle for those."""
    import math
    c0, c1, c2 = xform.column(0), xform.column(1), xform.column(2)
    if (abs(c2.x()) > 1e-6 or abs(c2.y()) > 1e-6 or abs(c2.z() - 1.0) > 1e-6
            or abs(c0.z()) > 1e-6 or abs(c1.z()) > 1e-6):
        raise ValueError("the model is tilted (its Z axis is not vertical)")
    sx = math.hypot(c0.x(), c0.y())
    sy = math.hypot(c1.x(), c1.y())
    if abs(sx - 1.0) > 1e-4 or abs(sy - 1.0) > 1e-4:
        raise ValueError("the model is scaled")
    return math.degrees(math.atan2(c0.y(), c0.x()))


class StraightenModelCommand(Command):
    """Put a model that was turned and dragged onto its site back on its
    own axes, and turn the MAP under it instead (SketchUp's north angle).

    ``group`` is the placed model: a top-level instance whose ``xform`` is a
    turn about Z plus a translation. The command applies the inverse of that
    placement to EVERYTHING in the scene — every group, loose geometry,
    annotations, guides, section planes, geo data, saved views, sheet
    frames and anchored cotas — so the group's placement becomes identity
    and nothing moves relative to anything else; then it re-anchors the
    datum so the base map, terrain and imports stay where they were under
    the model: the anchor becomes the group's origin and the north angle
    grows by the group's turn. Front/right/top views, axis locks and the
    rectangle tool are square to the model again.

    The vertical part of the placement is dropped: the model returns to
    the heights it was drawn at and the map keeps z = 0 (the reference
    plane) — the only place a flat map can be.
    """

    def __init__(self, group: Group) -> None:
        self.group = group
        self.degrees: float = 0.0
        self._placement = None          # the group's xform before do()
        self._old_datum = None
        self._new_datum = None
        self._snaps: dict = {}          # id(mesh) → (before, after)
        self._terrain = None

    def do(self, scene) -> None:
        if self.group not in scene.groups or self.group.xform is None:
            raise ValueError("pick a placed component at the top level")
        datum = getattr(scene, "georef", None)
        if datum is None:
            raise ValueError("the scene has no location yet")
        if self._placement is None:
            from PySide6.QtGui import QMatrix4x4
            from georef.datum import SceneDatum
            self.degrees = placement_rotation_deg(self.group.xform)
            self._placement = QMatrix4x4(self.group.xform)
            self._old_datum = datum
            t = self._placement.column(3)
            lat, lon, _ = datum.local_to_geodetic(QVector3D(t.x(), t.y(), 0.0))
            self._new_datum = SceneDatum(lat, lon, alt=datum.alt,
                                         north=datum.north + self.degrees)
        w, ok = self._placement.inverted()
        if not ok:
            raise ValueError("the placement is not invertible")
        self._apply(scene, w, -self.degrees, redo=True)
        from PySide6.QtGui import QMatrix4x4
        self.group.xform = QMatrix4x4()     # exactly on its axes, no float dust
        scene.georef = self._new_datum
        self._terrain = getattr(scene, "terrain", None)
        scene.terrain = None            # display-only; rebuilt from the datum

    def undo(self, scene) -> None:
        self._apply(scene, self._placement, self.degrees, redo=False)
        from PySide6.QtGui import QMatrix4x4
        self.group.xform = QMatrix4x4(self._placement)
        scene.georef = self._old_datum
        scene.terrain = self._terrain

    # ---- The rigid transform -----------------------------------------------
    def _apply(self, scene, m, turn_deg: float, redo: bool) -> None:
        """Move everything by the rigid ``m`` (``turn_deg`` is its turn about
        Z, for the cameras)."""
        import math

        def pt(v):
            return m.map(QVector3D(*v) if isinstance(v, (list, tuple))
                         else QVector3D(v))

        def vec(v):
            return m.mapVector(QVector3D(v))

        for g in scene.groups:
            if g.xform is not None:          # instances compose — O(1)
                g.xform = m * g.xform
            else:
                self._transform_mesh(g.mesh, m, redo)
        self._transform_mesh(scene.mesh, m, redo)
        for d in scene.dimensions:
            d.a, d.b, d.offset = pt(d.a), pt(d.b), vec(d.offset)
        for t in scene.text_labels:
            t.anchor, t.offset = pt(t.anchor), vec(t.offset)
        for gd in scene.guides:
            gd.point = pt(gd.point)
            if getattr(gd, "direction", None) is not None:
                gd.direction = vec(gd.direction)
        for sp in scene.section_planes:
            sp.point, sp.normal = pt(sp.point), vec(sp.normal)
        for im in scene.image_planes:
            im.origin, im.u, im.v = pt(im.origin), vec(im.u), vec(im.v)
        for gp in scene.geo_paths:
            gp.points = [pt(q) for q in gp.points]
            if getattr(gp, "_surface_tris", None) is not None:
                gp._surface_tris = None
        for gpt in scene.geo_points:
            gpt.position = pt(gpt.position)
        turn = math.radians(turn_deg)
        for sv in scene.saved_views:
            q = pt(sv.target)
            sv.target = (q.x(), q.y(), q.z())
            sv.yaw = sv.yaw + turn
        for comp in scene.compositions:
            for it in comp.all_items():
                for attr in ("a_world", "b_world"):
                    w = getattr(it, attr, None)
                    if w:
                        q = pt(w)
                        setattr(it, attr, [q.x(), q.y(), q.z()])
                ct = getattr(it, "cam_target", None)
                if ct:
                    q = pt(ct)
                    it.cam_target = [q.x(), q.y(), q.z()]
                    if getattr(it, "cam_yaw", None) is not None:
                        it.cam_yaw = it.cam_yaw + turn
        scene.version += 1

    def _transform_mesh(self, mesh, m, redo: bool) -> None:
        """Classic (world-coordinate) meshes: move the vertices the first
        time, snapshot both states, and replay the snapshots after that so
        undo/redo are exact."""
        from core.group import _remap_uvws
        if not mesh.vertices:
            return
        snap = self._snaps.get(id(mesh))
        if snap is not None:
            mesh.restore_state(snap[1] if redo else snap[0])
            return
        before = mesh.capture_state()
        for v in list(mesh.vertices):
            mesh.move_vertex(v, m.map(v.position) - v.position)
        _remap_uvws(mesh, m)
        self._snaps[id(mesh)] = (before, mesh.capture_state())


def group_owner_list(scene, group):
    """The list ``group`` lives in: ``scene.groups`` at the root, or the
    ``children`` of the container that owns it, however deep. ``None`` when
    the group is not in the scene at all."""
    if group in scene.groups:
        return scene.groups
    from core.group import iter_placements
    for top in scene.groups:
        for pg, _m in iter_placements(top):
            kids = getattr(pg, "children", None)
            if kids and group in kids:
                return kids
    return None


class DeleteGroupCommand(Command):
    """Remove a whole group (and its geometry) from the scene; undo restores it
    at its original position in the list.

    The list may be a container's ``children``: inside a component, Delete
    on one of its parts used to look for it in ``scene.groups`` and fail —
    rolled back, nothing on screen, «quiero eliminar, tampoco puedo»
    (Marco, 2026-09-11, a fountain inside an imported component)."""

    def __init__(self, group: Group) -> None:
        self.group = group
        self.index: Optional[int] = None
        self._owner: Optional[list] = None

    def do(self, scene) -> None:
        owner = group_owner_list(scene, self.group)
        if owner is None:
            raise ValueError("group is not in the scene")
        self._owner = owner
        self.index = owner.index(self.group)
        owner.remove(self.group)
        scene.selection.discard(self.group)
        scene.version += 1

    def undo(self, scene) -> None:
        owner = self._owner if self._owner is not None else scene.groups
        owner.insert(min(self.index or 0, len(owner)), self.group)
        scene.version += 1


class HealOverlapsCommand(Command):
    """Remove redundant 'mother' faces left overlapping their own subdivisions
    (a draw/delete can leave the big enclosing face on top). Snapshot undo."""

    def __init__(self) -> None:
        self.snapshot: Optional[dict] = None
        self.healed = 0

    def do(self, scene) -> None:
        self.snapshot = scene.mesh.capture_state()
        # partial defaults to auto: the aggressive pass runs only on a flat plan.
        removed = heal_overlapping_faces(scene.mesh)
        self.healed = len(removed)
        for f in removed:
            scene.selection.discard(f)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.snapshot is not None:
            scene.mesh.restore_state(self.snapshot)
            scene.version += 1


def _point_in_tri(p: QVector3D, t0: QVector3D, t1: QVector3D,
                  t2: QVector3D) -> bool:
    """Coplanar point-in-triangle via consistent cross-product orientation."""
    n = QVector3D.crossProduct(t1 - t0, t2 - t0)
    if n.length() < 1e-12:
        return False
    for a, b in ((t0, t1), (t1, t2), (t2, t0)):
        c = QVector3D.crossProduct(b - a, p - a)
        if QVector3D.dotProduct(c, n) < -1e-9:
            return False
    return True


class RebuildPlanarFacesCommand(Command):
    """Rebuild the minimal faces of a flat drawing from its edge graph (a planar
    arrangement) — the deterministic, from-scratch replacement for the heuristic
    heal. Splits every crossing/overlap, drops dangling spurs, and recomputes the
    rooms and their holes exactly. Only runs on a single-plane mesh; 3D is left
    untouched (coplanar nesting there is legitimate). Snapshot undo."""

    def __init__(self) -> None:
        self.snapshot: Optional[dict] = None
        self.rebuilt = 0
        self.flat = True

    def do(self, scene) -> None:
        from core.arrangement import coplanar_plane, planar_rebuild
        from core.topology import _point_on_seg_incl

        self.snapshot = scene.mesh.capture_state()
        mesh = scene.mesh
        if not mesh.edges:
            self.flat = False
            return
        # Every edge endpoint must share one plane; 3D models are left alone.
        verts = [v.position for v in mesh.vertices]
        plane = coplanar_plane(verts)
        if plane is None:
            self.flat = False
            return
        origin, normal = plane
        if mesh.faces:  # prefer a real face's normal for a stable orientation
            normal = mesh.faces[0].normal()
            origin = mesh.faces[0].vertices[0]
        segments = [(e.v0.position, e.v1.position) for e in mesh.edges]
        # Remember flagged edges and face attrs so the rebuild preserves them:
        # output edges are sub-segments of input ones (re-stamp by lie-on), and
        # output faces inherit attrs from the old face containing their interior.
        flagged = [(QVector3D(e.a), QVector3D(e.b), edge_flags(e))
                   for e in mesh.edges if not edge_is_plain(e)]
        old_attrs = [([tuple(t) for t in f.triangulate()], dict(f.attrs))
                     for f in mesh.faces if f.attrs]
        edges, faces = planar_rebuild(segments, origin, normal)

        scene.selection.clear()
        mesh.clear()
        for a, b in edges:
            e = mesh.add_edge(a, b)
            for (fa, fb, flags) in flagged:
                if _point_on_seg_incl(e.a, fa, fb) and _point_on_seg_incl(e.b, fa, fb):
                    stamp_edge_flags(e, flags)
                    break
        for outer, holes in faces:
            f = mesh.add_face(outer, holes or None)
            if f is None or not old_attrs:
                continue
            tris = f.triangulate()
            if not tris:
                continue
            probe = (tris[0][0] + tris[0][1] + tris[0][2]) / 3.0
            for old_tris, attrs in old_attrs:
                if any(_point_in_tri(probe, t0, t1, t2)
                       for t0, t1, t2 in old_tris):
                    f.attrs.update(attrs)
                    break
        mesh.resplit_curves()
        self.rebuilt = len(faces)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.snapshot is not None:
            scene.mesh.restore_state(self.snapshot)
            scene.version += 1


class RebuildPlaneFacesCommand(Command):
    """Rebuild the faces of ONE plane of a (possibly 3D) mesh from that plane's
    edge subgraph — the per-plane cousin of :class:`RebuildPlanarFacesCommand`.

    Needed because the whole-mesh flat gate goes dark as soon as ANY 3D
    geometry exists in the scene: two circles drawn on the ground next to a
    solid stacked as full overlapping discs instead of splitting into three
    areas. This command recomputes the arrangement of just the drawing plane
    and leaves the rest of the model untouched.

    Semantics: a minimal region keeps a face only if its interior was covered
    by an existing on-plane face (the freshly drawn loop's face, added by the
    tool before this command, provides coverage for the new regions). Uncovered
    regions stay empty — no resurrecting faces the user deleted. Winding and
    attrs inherit from the covering face; edges are reused (the planner already
    split every crossing), so soft/curve flags survive. Snapshot undo."""

    _TOL = 1e-4

    def __init__(self, origin: QVector3D, normal: QVector3D) -> None:
        self.origin = QVector3D(origin)
        # Normalised by hand: QVector3D.normalized() nulls anything shorter
        # than 1e-5, and a zero normal here means "rebuild the plane of
        # everything", which empties the mesh. See core/mesh.py Face.normal.
        n = QVector3D(normal)
        length = n.length()
        self.normal = n / length if length > 1e-9 else QVector3D()
        self.snapshot: Optional[dict] = None
        self.rebuilt = 0

    def _on_plane(self, p: QVector3D) -> bool:
        return abs(QVector3D.dotProduct(p - self.origin, self.normal)) < self._TOL

    def do(self, scene) -> None:
        from core.arrangement import planar_rebuild
        from core.triangulate import triangulate

        self.snapshot = scene.mesh.capture_state()
        if self.normal.lengthSquared() < 0.5:
            # No plane, nothing to rebuild. _on_plane would otherwise say
            # yes to EVERY point and the arrangement would run over the
            # whole mesh — which is how a 3 mm² sliver erased 447 faces.
            return
        mesh = scene.mesh
        plane_edges = [e for e in mesh.edges
                       if self._on_plane(e.a) and self._on_plane(e.b)]
        if not plane_edges:
            return
        plane_faces = [
            f for f in mesh.faces
            if all(self._on_plane(v.position) for v in f.loop)
            and all(self._on_plane(v.position) for h in f.hole_loops for v in h)
        ]
        old = [([tuple(t) for t in f.triangulate()], f.normal(), dict(f.attrs))
               for f in plane_faces]
        segments = [(QVector3D(e.a), QVector3D(e.b)) for e in plane_edges]
        _, regions = planar_rebuild(segments, self.origin, self.normal)

        def covering(outer, holes):
            tris = triangulate(outer, holes, self.normal)
            if not tris:
                return None
            probe = (tris[0][0] + tris[0][1] + tris[0][2]) / 3.0
            for old_tris, nrm, attrs in old:
                if any(_point_in_tri(probe, t0, t1, t2)
                       for t0, t1, t2 in old_tris):
                    return nrm, attrs
            return None

        keep = []
        for outer, holes in regions:
            cov = covering(outer, holes or [])
            if cov is None:
                continue                      # uncovered region: stays empty
            nrm, attrs = cov
            # Arrangement emits CCW around self.normal; match the old face.
            from core.triangulate import _newell
            if QVector3D.dotProduct(_newell(outer), nrm) < 0:
                outer = list(reversed(outer))
                holes = [list(reversed(h)) for h in (holes or [])]
            keep.append((outer, holes or None, attrs))
        for f in plane_faces:
            mesh.remove_face(f)
        for outer, holes, attrs in keep:
            f = mesh.add_face(outer, holes)
            if attrs:
                f.attrs.update(attrs)
        # AddFaceCommand re-creates a polygon's full-length side even when the
        # planner already split it at a crossing — a border-0 collinear
        # duplicate that fragments the curve contours at resplit (degree-3
        # vertices). The regions above were re-added from the fully noded
        # arrangement, so the duplicates now bound nothing: prune them.
        from core.topology import prune_collinear_orphan_edges

        prune_collinear_orphan_edges(mesh)
        mesh.resplit_curves()
        self.rebuilt = len(keep)
        scene.selection.clear()
        scene.version += 1

    def undo(self, scene) -> None:
        if self.snapshot is not None:
            scene.mesh.restore_state(self.snapshot)
            scene.version += 1


class CompoundCommand(Command):
    """A list of commands executed and reverted as one atomic step."""

    def __init__(self, commands: Iterable[Command]) -> None:
        self.commands: list[Command] = list(commands)

    def do(self, scene) -> None:
        for cmd in self.commands:
            cmd.do(scene)

    def undo(self, scene) -> None:
        for cmd in reversed(self.commands):
            cmd.undo(scene)


class ChangeAxesCommand(Command):
    """SketchUp's Change Axes (issue #44): give ``group`` a new frame —
    origin, red, green, blue as the world matrix ``frame`` — while nothing
    moves in the world.

    A classic group only swaps its ``axes`` (its mesh is in world
    coordinates already). A component instance re-expresses its SHARED
    definition in the new axes: the definition takes ``D = frame⁻¹ · xform``,
    this instance's placement becomes ``frame``, and every other instance of
    the definition takes ``D⁻¹`` on the right — so all of them now carry the
    new axes and none of them moves (SketchUp: «changing one updates the
    others»). Undo runs the inverse."""

    def __init__(self, group, frame) -> None:
        from PySide6.QtGui import QMatrix4x4
        self.group = group
        self.frame = QMatrix4x4(frame)
        self._old_axes = None
        self._d = None
        self._instances: list = []

    def _siblings(self, scene) -> list:
        from core.group import iter_placements
        proto = self.group.mesh
        out, seen = [], set()
        for top in scene.groups:
            for g, _m in iter_placements(top):
                if (g.mesh is proto and getattr(g, "xform", None) is not None
                        and id(g) not in seen):
                    seen.add(id(g))
                    out.append(g)
        if id(self.group) not in seen:
            out.append(self.group)
        return out

    @staticmethod
    def _reexpress(group, d) -> None:
        """Map the definition's geometry (and nested placements) by ``d``."""
        from core.group import transformed_mesh
        proto = group.mesh
        moved = transformed_mesh(proto, d)
        proto.restore_state(moved.capture_state())
        for child in getattr(group, "children", None) or []:
            if child.xform is not None:
                child.xform = d * child.xform

    def do(self, scene) -> None:
        g = self.group
        if getattr(g, "xform", None) is None:
            self._old_axes = g.axes
            g.axes = self._copy(self.frame)
            scene.version += 1
            return
        inv, ok = self.frame.inverted()
        if not ok:
            return
        self._d = inv * g.xform
        d_inv, ok2 = self._d.inverted()
        if not ok2:
            self._d = None
            return
        self._instances = self._siblings(scene)
        self._reexpress(g, self._d)
        for inst in self._instances:
            inst.xform = inst.xform * d_inv
        scene.version += 1

    def undo(self, scene) -> None:
        g = self.group
        if getattr(g, "xform", None) is None and self._d is None:
            g.axes = self._old_axes
            scene.version += 1
            return
        if self._d is None:
            return
        d_inv, _ok = self._d.inverted()
        self._reexpress(g, d_inv)
        for inst in self._instances:
            inst.xform = inst.xform * self._d
        scene.version += 1

    @staticmethod
    def _copy(m):
        from PySide6.QtGui import QMatrix4x4
        return QMatrix4x4(m)
