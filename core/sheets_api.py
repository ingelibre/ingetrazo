# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A small, public API over the document's sheets and scenes (#1505).

An agent working over MCP could reach the Sheet Composer only through
``run_python`` and private methods of an OPEN ``ComposerWindow``
(``_reload_comp_combo``, ``_refresh_sheet_tabs``…): the window had to be
open, every task took trial and error, and the names could change with any
release. This module is the stable door instead:

- It works on the MODEL (``scene.compositions`` and ``scene.saved_views``),
  with no window at all. Rendering and export, which need the composer's
  painters, are the bridge's ``render_sheet`` and ``export_pdf``
  (:meth:`views.composer.ComposerWindow.render_sheet_image`).
- Every answer is plain JSON-able data, so the same calls serve the MCP
  tools (``list_sheets``, ``get_sheet``…) and the ``sheets`` object in the
  ``run_python`` scope.
- It never touches the undo history itself: the caller runs the mutating
  calls inside one step (``core.history.SnapshotImport``, which tracks the
  CONTENT of sheets and scenes, not only which ones exist).

Every place counts from 1, as the sheet tabs and the Scenes tab do: sheets
by place, name or title-block number (:func:`find_sheet`, the one resolver
the bridge uses too); frames by place, uid or Items-list name; texts and
scenes by place, or scenes by name.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import asdict, fields
from typing import Any, Iterable, Optional

from core.composition import (COMMON_SCALES, FIELD_NAMES, PAPER_SIZES_MM,
                              Cajetin, Composicion, MarcoVista, TextoItem,
                              format_scale, parse_scale)

#: The frame attributes ``add_frame`` / ``update_frame`` accept besides the
#: geometry ones (x/y/w/h, scale, view, fit) handled by name.
_FRAME_EXTRA = ("style", "perspective", "cam_target", "cam_yaw", "cam_pitch",
                "cam_distance", "cam_fov", "rot_deg", "show_title",
                "title_text", "title_subtitle", "title_number",
                "title_style", "show_scale", "scale_text", "border",
                "paper_bg", "hidden", "list_name", "locked", "section_marks",
                "hidden_lines")

_TEXT_KEYS = ("text", "x_mm", "y_mm", "w_mm", "size_pt", "bold", "italic",
              "underline", "family", "color", "align", "bg_color",
              "frame_uid", "hidden", "list_name", "locked")

#: Placeholders the sheet expands that ``FIELD_NAMES`` does not list: the
#: scale label's ``{n}``.
_OTHER_FIELDS = {"n"}

_PLACEHOLDER_RE = re.compile(r"\{([^{}\s]+)\}")


class SheetError(ValueError):
    """A request the API refuses (unknown sheet, bad paper, …). The bridge
    reports its message to the agent; the step is rolled back."""


def _norm(name: Any) -> str:
    return unicodedata.normalize("NFC", str(name or "")).strip().casefold()


def sheet_number(comp) -> Optional[str]:
    """The sheet's number as its title block shows it (``L-02``)."""
    rows = getattr(getattr(comp, "cajetin", None), "campos", None) or []
    # «N.º» first: in plaza-final3 «LÁMINA» holds the sheet's title and
    # «N.º» its number; Renumber writes the number into «LÁMINA».
    for labels in (("N.º", "Nº", "N°", "NO.", "NUMBER"),
                   ("LÁMINA", "LAMINA", "SHEET")):
        for row in rows:
            if str(row[0]).strip().upper() in labels and str(row[1]).strip():
                return str(row[1]).strip()
    return None


def find_sheet(comps, ref) -> Composicion:
    """THE sheet resolver: the AI bridge's tools, the sheets API and
    ``export_pdf`` all name sheets through it.

    ``ref`` is the sheet itself; its place (1 = the first, as the sheet
    tabs count; an int, or digits no sheet is named); its name; its
    title-block number (``L-02``); or the number a name begins with
    («L-02 Ubicación»), when only one sheet begins so. Names and numbers
    are compared after Unicode NFC normalisation and case folding, so
    «Küche» typed one way finds «Küche» stored the other."""
    comps = list(comps)
    if not comps:
        raise SheetError("the document has no sheets")
    if isinstance(ref, Composicion):
        if any(c is ref for c in comps):
            return ref
        raise SheetError("that sheet is not in this document")
    if isinstance(ref, bool) or ref is None:
        raise SheetError(f"no sheet {ref!r}")
    if isinstance(ref, int):
        if 1 <= ref <= len(comps):
            return comps[ref - 1]
        raise SheetError(f"no sheet at place {ref} (1…{len(comps)})")
    key = str(ref).strip()
    want = _norm(key)
    for c in comps:                       # the exact name first
        if c.name == key:
            return c
    for c in comps:
        if _norm(c.name) == want:
            return c
    numbered = [c for c in comps if _norm(sheet_number(c)) == want]
    if len(numbered) == 1:
        return numbered[0]
    if key.isdigit() and 1 <= int(key) <= len(comps):
        return comps[int(key) - 1]
    starts = [c for c in comps if _norm(c.name).startswith(want + " ")]
    if len(starts) == 1 and not numbered:
        return starts[0]
    starts = numbered or starts
    if starts:
        raise SheetError(f"{key!r} begins several sheets: " + ", ".join(
            repr(c.name) for c in starts) + "; give the full name")
    raise SheetError(f"no sheet {ref!r}; the sheets are: " + ", ".join(
        repr(c.name) for c in comps))


def placeholder_names() -> dict:
    """``{canonical: [aliases…]}`` — every ``{field}`` a sheet text, frame
    title or title-block value may use (DE/EN/ES spellings). What the MCP
    tool descriptions quote, so nobody has to read ``FIELD_NAMES``."""
    return {es: [es, *names] for es, names in FIELD_NAMES.items()}


def _known_placeholders() -> set:
    out = set(_OTHER_FIELDS)
    for es, names in FIELD_NAMES.items():
        out.add(es)
        out.update(names)
    return out


def unresolved_placeholders(text: str) -> list:
    """The ``{…}`` in ``text`` the sheet will print literally —
    ``{contents:20:1}``, a typo like ``{projet}``…"""
    known = _known_placeholders()
    return sorted({m.group(1) for m in _PLACEHOLDER_RE.finditer(text or "")
                   if m.group(1).lower() not in known})


def is_standard_scale(n: float, extra: Iterable[float] = ()) -> bool:
    """Whether ``1:n`` is one of the scales a drawing is printed at."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return False
    return any(math.isclose(n, s, rel_tol=1e-6)
               for s in (*COMMON_SCALES, 75, 150, 300, 400, 5000, *extra))


def snap_scale(n: float) -> float:
    """The standard scale nearest ``n`` (on a log scale: 1:90.9 → 1:100)."""
    n = max(float(n), 1e-9)
    return min(COMMON_SCALES, key=lambda s: abs(math.log(s) - math.log(n)))


class SheetsAPI:
    """The document's sheets and scenes — see the module docstring.

    ``scene`` is the live scene (kept as ``doc``: ``scene()`` finds a
    scene of it); ``camera`` (optional) is the viewport's,
    used only for frames that show the live view (``__current__``)."""

    def __init__(self, scene, camera=None) -> None:
        self.doc = scene
        self.camera = camera

    # ---- lookup ---------------------------------------------------------------
    @property
    def _comps(self) -> list:
        comps = getattr(self.doc, "compositions", None)
        if comps is None:
            raise SheetError("this document has no sheets list")
        return comps

    @property
    def _views(self) -> list:
        return getattr(self.doc, "saved_views", None) or []

    def sheet(self, ref) -> Composicion:
        """The sheet ``ref`` names (see :func:`find_sheet`)."""
        return find_sheet(self._comps, ref)

    def scene(self, ref):
        """The scene (saved view) ``ref`` names: its place (1 = the first,
        as the Scenes tab lists them) or its name."""
        views = self._views
        if isinstance(ref, int) and not isinstance(ref, bool):
            if 1 <= ref <= len(views):
                return views[ref - 1]
            raise SheetError(f"no scene at place {ref} (1…{len(views)})")
        name = str(ref or "")
        if name.startswith("scene:"):
            name = name[6:]
        want = _norm(name)
        for v in views:
            if _norm(v.name) == want:
                return v
        raise SheetError(f"no scene named {ref!r}; scenes: "
                         + ", ".join(repr(v.name) for v in views))

    @staticmethod
    def _frame(comp: Composicion, ref) -> MarcoVista:
        frames = comp.frames
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            i = int(ref)
            if 1 <= i <= len(frames):
                return frames[i - 1]
            raise SheetError(f"sheet {comp.name!r} has no frame {i} "
                             f"(frames 1…{len(frames)})")
        for f in frames:
            if ref and (f.uid == ref or _norm(f.list_name) == _norm(ref)):
                return f
        raise SheetError(f"sheet {comp.name!r} has no frame {ref!r}")

    @staticmethod
    def _text(comp: Composicion, ref) -> TextoItem:
        try:
            i = int(ref)
        except (ValueError, TypeError):
            i = 0
        if 1 <= i <= len(comp.texts):
            return comp.texts[i - 1]
        raise SheetError(f"sheet {comp.name!r} has no text {ref!r} "
                         f"(texts 1…{len(comp.texts)})")

    def _view_key(self, view) -> str:
        """``view`` as a frame stores it: a scene's name becomes
        ``scene:<name>`` (and must exist); ``std:top``… and ``__current__``
        pass through."""
        if view is None:
            return "__current__"
        key = str(view)
        if key == "__current__" or key.startswith("std:"):
            return key
        return f"scene:{self.scene(key).name}"

    # ---- reading ----------------------------------------------------------------
    def list(self) -> list:
        """Every sheet, in document order, with its warnings. ``index`` is
        the sheet's place, 1 = the first, as everywhere in the bridge."""
        out = []
        for i, c in enumerate(self._comps, 1):
            out.append({
                "index": i, "name": c.name, "number": sheet_number(c), "paper": c.paper,
                "landscape": c.landscape, "frames": len(c.frames),
                "texts": len(c.texts), "title_block": c.cajetin is not None,
                **self._tree_info(c),
                "warnings": self.warnings(c),
            })
        return out

    # ---- the sheet explorer's folders and Print flag ---------------------------
    def _tree_info(self, c: Composicion) -> dict:
        """Where ``c`` sits in the sheet explorer: its folder path ("" at
        the top), its own Print flag, and whether Print all takes it (its
        flag and every folder around it on)."""
        from core import sheet_folders as sf
        return {"folder": "/".join(sf.folder_path(
                    self.doc, getattr(c, "folder_id", None))),
                "print_in_all": bool(getattr(c, "print_in_all", True)),
                "printed": sf.sheet_printed(self.doc, c)}

    def folder(self, ref):
        """The sheet folder ``ref`` names: its id or its path ("A/B");
        ``None`` or "" is the top (returns ``None``)."""
        from core import sheet_folders as sf
        if ref is None or str(ref).strip("/ ") == "":
            return None
        f = sf.folder_by_id(self.doc, ref)
        if f is not None:
            return f
        want = tuple(_norm(p) for p in str(ref).replace("\\", "/").split("/")
                     if p.strip())
        for f in sf.folders_of(self.doc):
            if tuple(_norm(n) for n in sf.folder_path(self.doc, f.id)) == want:
                return f
        raise SheetError(f"no sheet folder {ref!r}; folders: " + (", ".join(
            repr("/".join(sf.folder_path(self.doc, f.id)))
            for f in sf.folders_of(self.doc)) or "none"))

    def list_folders(self) -> list:
        """Every sheet folder, top to bottom: id, path, Print flag, whether
        it prints (it and every folder around it on), and its own sheets."""
        from core import sheet_folders as sf
        out = []

        def walk(parent_id) -> None:
            for f in sf.subfolders(self.doc, parent_id):
                out.append({
                    "id": f.id, "name": f.name,
                    "path": "/".join(sf.folder_path(self.doc, f.id)),
                    "print_in_all": bool(f.print_in_all),
                    "printed": sf.folder_printed(self.doc, f.id),
                    "sheets": [c.name for c in sf.sheets_in(self.doc, f.id)]})
                walk(f.id)
        walk(None)
        return out

    def _place(self, c: Composicion, folder) -> None:
        """Put ``c`` at the end of ``folder`` (id or path; "" the top); the
        sheet order follows the tree, as the explorer keeps it."""
        from core import sheet_folders as sf
        target = self.folder(folder)
        sf.move_items(self.doc, [c], [],
                      None if target is None else target.id)

    def get(self, ref, cotas: bool = False) -> dict:
        """One sheet as JSON. Dimensions only as a count unless ``cotas``."""
        c = self.sheet(ref)
        comps = self._comps
        d = {
            "index": comps.index(c) + 1, "name": c.name,
            "number": sheet_number(c), "paper": c.paper,
            "landscape": c.landscape, "page_mm": list(c.page_size_mm()),
            "margin_mm": c.margin_mm, **self._tree_info(c),
            "frames": [self.frame_info(c, f, i)
                       for i, f in enumerate(c.frames, 1)],
            "texts": [dict(index=i, **{k: getattr(t, k) for k in _TEXT_KEYS})
                      for i, t in enumerate(c.texts, 1)],
            "labels": len(c.etiquetas), "images": len(c.images),
            "title_block": (None if c.cajetin is None else {
                "x_mm": c.cajetin.x_mm, "y_mm": c.cajetin.y_mm,
                "w_mm": c.cajetin.w_mm, "h_mm": c.cajetin.h_mm,
                "columns": c.cajetin.columns,
                "fields": [list(r) for r in c.cajetin.campos]}),
            "dimensions": (len(c.cotas) + len(c.cotas_ang)
                           + len(c.cotas_rad)),
            "warnings": self.warnings(c),
        }
        if cotas:
            d["cotas"] = [asdict(ct) for ct in c.cotas]
        return d

    def frame_info(self, comp: Composicion, f: MarcoVista,
                   index: Optional[int] = None) -> dict:
        info = {
            "index": comp.frames.index(f) + 1 if index is None else index,
            "uid": f.uid, "view": f.view_key,
            "scale": format_scale(f.scale_n), "scale_n": f.scale_n,
            "x_mm": f.x_mm, "y_mm": f.y_mm, "w_mm": f.w_mm, "h_mm": f.h_mm,
            "style": f.style, "perspective": bool(f.perspective),
            "cam_target": f.cam_target, "hidden": f.hidden,
            "list_name": f.list_name, "show_title": f.show_title,
            "title_text": f.title_text,
        }
        ext = self.content_extent(f)
        if ext is not None:
            info["content_mm"] = ext
        return info

    # ---- validation -------------------------------------------------------------
    def warnings(self, comp: Composicion) -> list:
        """What would print wrong: frames on a missing view, clipped or at a
        non-standard scale, and placeholders the sheet cannot expand."""
        out = []
        for i, f in enumerate(comp.frames, 1):
            if f.view_key.startswith("scene:"):
                name = f.view_key[6:]
                if not any(v.name == name for v in self._views):
                    out.append({"kind": "missing_scene", "frame": i,
                                "scene": name,
                                "message": f"frame {i} shows the scene "
                                           f"{name!r}, which no longer "
                                           f"exists"})
                    continue
            if not f.perspective and not is_standard_scale(f.scale_n):
                out.append({"kind": "nonstandard_scale", "frame": i,
                            "scale": format_scale(f.scale_n),
                            "suggested": format_scale(snap_scale(f.scale_n)),
                            "message": f"frame {i} is at "
                                       f"{format_scale(f.scale_n)}"})
            ext = self.content_extent(f)
            if ext is not None and ext.get("clipped"):
                out.append({"kind": "clipped", "frame": i, "content": ext,
                            "message": f"frame {i}: the drawing "
                                       f"({ext['w_mm']:.0f}×{ext['h_mm']:.0f}"
                                       f" mm at {format_scale(f.scale_n)}) "
                                       f"does not fit the frame "
                                       f"({f.w_mm:.0f}×{f.h_mm:.0f} mm)"})
        texts = [(f"text {i}", t.text)
                 for i, t in enumerate(comp.texts, 1)]
        texts += [(f"frame {i} title", " ".join(
            (f.title_text, f.title_subtitle)))
            for i, f in enumerate(comp.frames, 1)]
        if comp.cajetin is not None:
            texts += [(f"title block «{r[0]}»", str(r[1]))
                      for r in comp.cajetin.campos]
        for where, text in texts:
            bad = unresolved_placeholders(text)
            if bad:
                out.append({"kind": "unresolved_placeholder", "where": where,
                            "placeholders": bad,
                            "message": f"{where} prints "
                                       + ", ".join("{%s}" % b for b in bad)
                                       + " literally"})
        return out

    # ---- framing (fit to content) ----------------------------------------------
    def _camera_for(self, f: MarcoVista):
        """A throw-away camera pointed like the frame — WITHOUT applying the
        saved view to the scene (that changes layer visibility)."""
        from core.camera import OrbitCamera
        from core.composition import apply_frame_camera
        cam = OrbitCamera()
        sv = None
        if f.view_key.startswith("scene:"):
            try:
                sv = self.scene(f.view_key)
            except SheetError:
                return None, None
            cam.yaw, cam.pitch = sv.yaw, sv.pitch
            from PySide6.QtGui import QVector3D
            cam.target = QVector3D(*sv.target)
        elif f.view_key == "__current__" and self.camera is not None:
            live = self.camera
            cam.yaw, cam.pitch = live.yaw, live.pitch
            cam.target = live.target
        elif not f.view_key.startswith("std:"):
            return None, None
        apply_frame_camera(cam, f, saved_view=None, scene=self.doc)
        return cam, sv

    def _bounds_for(self, sv):
        """The box of what the view shows: the model's visible geometry with
        the view's hidden layers off. (Hidden objects and the section cut
        are not taken into account — the box can only be larger.)"""
        scene = self.doc
        hidden = set(getattr(sv, "hidden_layers", None) or ())
        layers = [ly for ly in getattr(scene, "layers", None) or ()
                  if ly.name in hidden and ly.visible]
        if not layers:
            return scene.bounds()
        # Measured with those layers off, then everything put back as it
        # was — the cache too, and WITHOUT a version bump: a bump would mark
        # every frame of the open composer stale, for a read.
        cache = scene.__dict__.get("_bounds_cache")
        for ly in layers:
            ly.visible = False
        scene._bounds_cache = None
        try:
            return scene.bounds()
        finally:
            for ly in layers:
                ly.visible = True
            scene._bounds_cache = cache

    def content_extent(self, f: MarcoVista) -> Optional[dict]:
        """Where the view's content lands on the paper, in mm relative to
        the frame's centre, at the frame's scale: ``{w_mm, h_mm, dx_mm,
        dy_mm, clipped}``. None for perspective frames (they have no
        scale) and when there is nothing to measure."""
        if f.perspective or f.scale_n <= 0:
            return None
        try:
            cam, sv = self._camera_for(f)
            if cam is None:
                return None
            lo, hi = self._bounds_for(sv)
        except Exception:  # noqa: BLE001 — a stub scene, a broken view
            return None
        if lo is None:
            return None
        from PySide6.QtGui import QVector3D
        fwd = cam.forward()
        up = cam.up_vector()
        right = QVector3D.crossProduct(fwd, up).normalized()
        up = QVector3D.crossProduct(right, fwd).normalized()
        xs, ys = [], []
        for x in (lo.x(), hi.x()):
            for y in (lo.y(), hi.y()):
                for z in (lo.z(), hi.z()):
                    p = QVector3D(x, y, z) - cam.target
                    xs.append(QVector3D.dotProduct(p, right))
                    ys.append(QVector3D.dotProduct(p, up))
        k = 1000.0 / f.scale_n                       # metres → paper mm
        w, h = (max(xs) - min(xs)) * k, (max(ys) - min(ys)) * k
        dx = (max(xs) + min(xs)) / 2.0 * k
        dy = -(max(ys) + min(ys)) / 2.0 * k            # page y grows down
        tol = 0.5
        clipped = (abs(dx) + w / 2.0 > f.w_mm / 2.0 + tol
                   or abs(dy) + h / 2.0 > f.h_mm / 2.0 + tol)
        return {"w_mm": round(w, 2), "h_mm": round(h, 2),
                "dx_mm": round(dx, 2), "dy_mm": round(dy, 2),
                "clipped": bool(clipped)}

    def fit(self, sheet, frame, mode: str = "content") -> dict:
        """Frame the view: ``content`` centres it on the box of what the
        view shows; ``view`` drops the frame's own target and takes the
        saved view's (or, for a standard view, the model's centre)."""
        c = self.sheet(sheet)
        f = self._frame(c, frame)
        self._fit(f, mode)
        return self.frame_info(c, f)

    def _fit(self, f: MarcoVista, mode: str) -> None:
        if mode == "view":
            f.cam_target = None
            return
        if mode != "content":
            raise SheetError(f"fit must be 'content' or 'view', not {mode!r}")
        sv = None
        if f.view_key.startswith("scene:"):
            sv = self.scene(f.view_key)
        lo, hi = self._bounds_for(sv)
        if lo is None:
            raise SheetError("nothing visible to fit the frame on")
        mid = (lo + hi) * 0.5
        f.cam_target = [mid.x(), mid.y(), mid.z()]

    # ---- sheets -------------------------------------------------------------------
    def create(self, name: str, template=None, after=None, paper: str = "A3",
               landscape: bool = True, frame: bool = True,
               title_block: bool = False, folder=None) -> dict:
        """A new sheet: empty (one frame filling the page unless
        ``frame=False``), or a copy of the sheet ``template`` names. It goes
        after the sheet ``after`` names (into that sheet's folder), else
        last; ``folder`` (id or path, "" the top) puts it at that folder's
        end instead."""
        import uuid
        comps = self._comps
        name = str(name or "").strip()
        if not name:
            raise SheetError("a sheet needs a name")
        if any(_norm(c.name) == _norm(name) for c in comps):
            raise SheetError(f"there is already a sheet named {name!r}")
        if template is not None:
            src = self.sheet(template)
            c = Composicion.from_dict(src.to_dict())
            c.uid = ""                            # fresh identities
            for f in c.frames:
                f.uid = uuid.uuid4().hex if f.uid else ""
            for ct in c.cotas:
                ct.anchor_uid, ct.a_world, ct.b_world = "", None, None
        else:
            self._check_paper(paper)
            c = Composicion(name=name, paper=paper, landscape=bool(landscape))
            if frame:
                c.frames.append(c.default_frame())
            if title_block:
                c.cajetin = c.default_cajetin()
        c.name = name
        if folder is not None:
            self.folder(folder)                   # an unknown one: refused
        if after is None:
            c.folder_id = None
            comps.append(c)
        else:
            prev = self.sheet(after)
            c.folder_id = getattr(prev, "folder_id", None)
            comps.insert(comps.index(prev) + 1, c)
        if folder is not None:
            self._place(c, folder)
        else:
            from core.sheet_folders import sync_order
            sync_order(self.doc)
        return self.get(c)

    @staticmethod
    def _check_paper(paper) -> None:
        if paper not in PAPER_SIZES_MM:
            raise SheetError(f"paper must be one of "
                             f"{', '.join(PAPER_SIZES_MM)}, not {paper!r}")

    def update(self, ref, name=None, paper=None, landscape=None,
               index=None, margin_mm=None, folder=None,
               print_in_all=None) -> dict:
        """Rename, change the paper, move the sheet to place ``index``
        (1 = the first; within the tree: sheets stay with their folders), into ``folder`` (id or
        path, "" the top), or switch its Print flag."""
        c = self.sheet(ref)
        comps = self._comps
        if name is not None:
            name = str(name).strip()
            if not name:
                raise SheetError("a sheet needs a name")
            if any(o is not c and _norm(o.name) == _norm(name)
                   for o in comps):
                raise SheetError(f"there is already a sheet named {name!r}")
            c.name = name
        if paper is not None:
            self._check_paper(paper)
            c.paper = paper
        if landscape is not None:
            c.landscape = bool(landscape)
        if margin_mm is not None:
            c.margin_mm = float(margin_mm)
        if index is not None:
            i = int(index)
            if not 1 <= i <= len(comps):
                raise SheetError(f"index must be 1…{len(comps)}")
            comps.remove(c)
            comps.insert(i - 1, c)
        if folder is not None:
            self._place(c, folder)
        elif index is not None:
            from core.sheet_folders import sync_order
            sync_order(self.doc)
        if print_in_all is not None:
            c.print_in_all = bool(print_in_all)
        return self.get(c)

    def delete(self, ref, confirm: bool = False) -> dict:
        """Delete the sheet; refused without ``confirm=True``, and a
        document keeps at least one sheet (as in the composer)."""
        c = self.sheet(ref)
        comps = self._comps
        if not confirm:
            raise SheetError(f"deleting {c.name!r} needs confirm=true")
        if len(comps) <= 1:
            raise SheetError("a document keeps at least one sheet")
        comps.remove(c)
        from core.sheet_sets import prune
        prune(self.doc)                   # it leaves every sheet set
        return {"deleted": c.name, "sheets": len(comps)}

    # ---- frames -------------------------------------------------------------------
    def add_frame(self, sheet, view=None, scale=None, x_mm=None, y_mm=None,
                  w_mm=None, h_mm=None, fit=None, **extra) -> dict:
        """A view frame. Without a position it fills the page inside the
        margins; ``fit`` = ``content`` | ``view`` frames it (see
        :meth:`fit`)."""
        c = self.sheet(sheet)
        f = c.default_frame()
        c.frames.append(f)
        self._apply_frame(c, f, view, scale, x_mm, y_mm, w_mm, h_mm, fit,
                          extra)
        return self.frame_info(c, f)

    def update_frame(self, sheet, frame, view=None, scale=None, x_mm=None,
                     y_mm=None, w_mm=None, h_mm=None, fit=None,
                     **extra) -> dict:
        c = self.sheet(sheet)
        f = self._frame(c, frame)
        self._apply_frame(c, f, view, scale, x_mm, y_mm, w_mm, h_mm, fit,
                          extra)
        return self.frame_info(c, f)

    def remove_frame(self, sheet, frame) -> dict:
        c = self.sheet(sheet)
        f = self._frame(c, frame)
        c.frames.remove(f)
        return {"sheet": c.name, "frames": len(c.frames)}

    def _apply_frame(self, c, f, view, scale, x_mm, y_mm, w_mm, h_mm, fit,
                     extra) -> None:
        if view is not None:
            f.view_key = self._view_key(view)
        if scale is not None:
            n = parse_scale(str(scale), default=-1.0) \
                if isinstance(scale, str) else float(scale)
            if n <= 0:
                raise SheetError(f"bad scale {scale!r} (use 50 or '1:50')")
            f.scale_n = n
        for attr, value in (("x_mm", x_mm), ("y_mm", y_mm),
                            ("w_mm", w_mm), ("h_mm", h_mm)):
            if value is not None:
                setattr(f, attr, float(value))
        if f.w_mm <= 0 or f.h_mm <= 0:
            raise SheetError("a frame needs a positive width and height")
        unknown = set(extra) - set(_FRAME_EXTRA)
        if unknown:
            raise SheetError(f"unknown frame field(s): {sorted(unknown)}; "
                             f"accepted: {list(_FRAME_EXTRA)}")
        for k, v in extra.items():
            setattr(f, k, v)
        if fit:
            self._fit(f, fit)

    # ---- title blocks and texts ---------------------------------------------------
    def set_title_block(self, sheet="all", fields=None, columns=None,
                        x_mm=None, y_mm=None, w_mm=None, h_mm=None,
                        replace: bool = False) -> list:
        """Set the title block of one sheet, or of every sheet with
        ``sheet="all"``. ``fields`` is ``[[label, value], …]``: each row is
        set (added if missing) unless ``replace``, which makes them THE
        rows. A sheet without a title block gets the default one."""
        targets = (list(self._comps) if sheet == "all"
                   else [self.sheet(sheet)])
        rows = [[str(a), str(b)] for a, b in (fields or [])]
        for c in targets:
            if c.cajetin is None:
                c.cajetin = c.default_cajetin()
            caj: Cajetin = c.cajetin
            if replace:
                caj.campos = [list(r) for r in rows]
            else:
                for label, value in rows:
                    caj.set_field(label, value)
            if columns is not None:
                caj.columns = max(1, int(columns))
            for attr, value in (("x_mm", x_mm), ("y_mm", y_mm),
                                ("w_mm", w_mm), ("h_mm", h_mm)):
                if value is not None:
                    setattr(caj, attr, float(value))
        return [c.name for c in targets]

    def add_text(self, sheet, text: str, x_mm: float = 20.0,
                 y_mm: float = 20.0, **extra) -> dict:
        c = self.sheet(sheet)
        t = TextoItem(x_mm=float(x_mm), y_mm=float(y_mm), text=str(text))
        self._apply_text(t, extra)
        c.texts.append(t)
        return dict(index=len(c.texts),
                    **{k: getattr(t, k) for k in _TEXT_KEYS})

    def update_text(self, sheet, index, **changes) -> dict:
        c = self.sheet(sheet)
        t = self._text(c, index)
        self._apply_text(t, changes)
        return dict(index=c.texts.index(t) + 1,
                    **{k: getattr(t, k) for k in _TEXT_KEYS})

    @staticmethod
    def _apply_text(t: TextoItem, changes: dict) -> None:
        unknown = set(changes) - set(_TEXT_KEYS)
        if unknown:
            raise SheetError(f"unknown text field(s): {sorted(unknown)}; "
                             f"accepted: {list(_TEXT_KEYS)}")
        for k, v in changes.items():
            setattr(t, k, v)

    # ---- scenes (saved views) -------------------------------------------------
    def list_scenes(self) -> list:
        """Every scene, as the Scenes tab lists them, with the sheets that
        show it (``used_by``)."""
        from core.outliner import frames_showing
        out = []
        for i, v in enumerate(self._views, 1):
            used = []
            for comp, _frame in frames_showing(self.doc, v.name):
                if comp.name not in used:
                    used.append(comp.name)
            out.append({"index": i, "name": v.name, "folder": v.folder,
                        "projection": ("parallel" if not v.perspective else
                                       "two_point" if v.two_point
                                       else "perspective"),
                        "section": (v.section or {}).get("active"),
                        "hidden_layers": list(v.hidden_layers),
                        "target": list(v.target), "used_by": used})
        return out

    def create_scene(self, name: str, from_scene=None, folder=None,
                     hidden_layers=None, target=None) -> dict:
        """A scene: a copy of ``from_scene``, else of what the live camera
        shows (when this API has one)."""
        from core.saved_views import SavedView
        name = str(name or "").strip()
        if not name:
            raise SheetError("a scene needs a name")
        if any(_norm(v.name) == _norm(name) for v in self._views):
            raise SheetError(f"there is already a scene named {name!r}")
        if from_scene is not None:
            v = SavedView.from_dict(self.scene(from_scene).to_dict())
            v.name = name
        elif self.camera is not None:
            v = SavedView.capture(name, self.doc, self.camera)
        else:
            raise SheetError("give from_scene: there is no live camera")
        self._edit_scene(v, folder, hidden_layers, target)
        self.doc.saved_views.append(v)
        return self.list_scenes()[-1]

    def update_scene(self, ref, name=None, folder=None, hidden_layers=None,
                     target=None) -> dict:
        """Change a scene. Renaming it renames every frame that shows it
        (``core.outliner.rename_scene``), so no sheet is orphaned."""
        from core.outliner import rename_scene
        v = self.scene(ref)
        if name is not None and str(name).strip() != v.name:
            if not rename_scene(self.doc, v, str(name)):
                raise SheetError(f"cannot rename {v.name!r} to {name!r} "
                                 f"(empty, or another scene has that name)")
        self._edit_scene(v, folder, hidden_layers, target)
        return next(d for d in self.list_scenes() if d["name"] == v.name)

    @staticmethod
    def _edit_scene(v, folder, hidden_layers, target) -> None:
        if folder is not None:
            v.folder = folder or None
        if hidden_layers is not None:
            v.hidden_layers = [str(n) for n in hidden_layers]
        if target is not None:
            if len(target) != 3:
                raise SheetError("target is [x, y, z] in metres")
            v.target = tuple(float(t) for t in target)

    def delete_scene(self, ref, confirm: bool = False) -> dict:
        """Delete a scene. Refused while frames show it unless
        ``confirm=True``, and the reply names those sheets either way."""
        from core.outliner import frames_showing
        v = self.scene(ref)
        users = sorted({c.name for c, _f in frames_showing(self.doc,
                                                             v.name)})
        if not confirm:
            raise SheetError(
                f"deleting scene {v.name!r} needs confirm=true"
                + (f"; it is shown on: {', '.join(users)}" if users else ""))
        self.doc.saved_views.remove(v)
        return {"deleted": v.name, "orphaned_on": users}

    # ---- documentation ------------------------------------------------------------
    @staticmethod
    def placeholders() -> dict:
        return placeholder_names()


def frame_fields() -> list:
    """Every attribute a frame has (for documentation and tests)."""
    return [f.name for f in fields(MarcoVista)]
