# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The AI bridge's named tools — an agent works without ``run_python``.

Marco, 19-11 (Xavi Montero's idea, IngeTrazo as a platform for agents):
an MCP client that does not allow arbitrary code must still be able to
look at the document, move the camera, select, paint, open, save, import
and export. Each ``_tool_<name>`` below is one order of the bridge
(``plugins/ai_bridge.py`` dispatches to it on the Qt main thread, through
the same request check as ``run_python``), and each one goes through what
the menus already use — the same importers, writers, scene panel, camera
and composer — instead of a second copy of that logic.

The rules every tool keeps:

- What changes the document is ONE undo step (an import, a paint, a
  layer shown or hidden), like ``run_python``. The view — camera,
  selection, the scene shown — stays outside the history, as in the app.
- Paths are absolute; a relative one is refused, not resolved against
  whatever folder the app was started in.
- Nobody is at the screen to answer a dialog: the bridge cancels any that
  opens, and a tool whose step failed with one says what it said.
- Opening never loses unsaved work: it refuses unless
  ``discard_changes=true``.
- Without OpenGL (a server on the offscreen platform) the renders answer
  with an error that says why, at once — never a hang.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

# ``quiet`` lives with the window-less bootstrap since PR #1494: one copy.
from views.headless import quiet  # noqa: F401 — re-exported

#: The standard views ``set_camera`` takes (``OrbitCamera.set_view``).
STANDARD_VIEWS = ("top", "bottom", "front", "back", "left", "right", "iso")
#: The projections ``set_camera`` takes (``OrbitCamera.set_projection``).
PROJECTIONS = ("perspective", "parallel", "two_point")
#: Units of the formats that record none (OBJ, STL, DXF): metres per unit.
UNITS = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "ft": 0.3048}
#: What ``import_file`` reads, by suffix.
IMPORT_SUFFIXES = (".igz", ".dae", ".glb", ".gltf", ".skp", ".obj", ".stl",
                   ".dxf", ".dwg")
#: What ``export_file`` writes, by suffix.
EXPORT_SUFFIXES = (".ifc", ".glb", ".dae", ".stl", ".obj", ".dxf")

NO_GL = ("no OpenGL context: this IngeTrazo has nothing to render with "
         "(a server started on the offscreen platform, or a machine without "
         "OpenGL 3.3). Start the server under a display — Xvfb, or a real "
         "one with the window minimised — to take screenshots and render "
         "sheets; everything else works without it.")


def out_dir() -> Path:
    """Where the renders go when the agent names no file: the bridge's own
    folder in the system's temporary one, as ``screenshot`` always did."""
    folder = Path(tempfile.gettempdir()) / "ingetrazo-ai"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def absolute(path, must_exist: bool = False) -> Path:
    """``path`` as a ``Path``, refused unless absolute (and existing, with
    ``must_exist``): a relative path would land wherever the app was
    started, which the agent cannot know."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("a path is required (an absolute file path)")
    p = Path(path)
    if not p.is_absolute():
        raise ValueError(f"the path must be absolute: {path!r}")
    if must_exist and not p.is_file():
        raise FileNotFoundError(f"no such file: {p}")
    return p


def can_render(viewport) -> bool:
    """Whether ``viewport`` has the GL context ``render_image`` needs."""
    return (getattr(viewport, "_gl", None) is not None
            and getattr(viewport, "_program", None) is not None)


def _writable(path: Path) -> Path:
    if not path.parent.is_dir():
        raise FileNotFoundError(f"the folder does not exist: {path.parent}")
    return path


def _vec(p) -> list:
    return [float(p.x()), float(p.y()), float(p.z())]


def _triple(value, name: str) -> tuple:
    try:
        x, y, z = (float(v) for v in value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be [x, y, z] in metres") from None
    return x, y, z


# The sheet number and THE sheet resolver live in core.sheets_api (#1505).
from core.sheets_api import SheetError, find_sheet  # noqa: E402
from core.sheets_api import sheet_number as _sheet_number  # noqa: E402


def _material_dict(mat) -> dict:
    """A scene material as the paint a container wears (the Paint tool's
    ``_current_as_material``): no texture map, a container has no plane."""
    paint = mat.face_attrs()
    if "texture" in paint:
        paint["texture"].pop("uvw", None)
    if "color" in paint:
        paint["color"] = list(paint["color"])
    return paint


class BridgeTools:
    """The named tools, mixed into the bridge. Needs ``self._viewport``
    (the project in front) and ``self._guard`` (the dialogs cancelled
    during this call, set by the bridge)."""

    _guard = None

    # ---- Helpers -----------------------------------------------------------
    def _window(self):
        return self._viewport.window()

    def _cancelled(self, since: int = 0) -> list:
        guard = self._guard
        return list(guard.refused[since:]) if guard is not None else []

    def _mark(self) -> int:
        return len(self._guard.refused) if self._guard is not None else 0

    def _failed(self, what: str, since: int) -> RuntimeError:
        said = self._cancelled(since)
        return RuntimeError(what + (": " + " | ".join(said) if said else ""))

    def _groups(self, names=None, ids=None) -> list:
        """The groups and components named, by name or by uid, in the
        order asked; an unknown one is an error that says which."""
        from core.purge import iter_groups
        scene = self._viewport.scene
        every = list(iter_groups(scene.groups))
        found, missing = [], []
        for n in names or []:
            hit = [g for g in every if g.name == n]
            if not hit:
                missing.append(f"name {n!r}")
            found += [g for g in hit if g not in found]
        for i in ids or []:
            hit = [g for g in every if g.uid == i]
            if not hit:
                missing.append(f"id {i!r}")
            found += [g for g in hit if g not in found]
        if missing:
            raise KeyError("no object with " + ", ".join(missing))
        return found

    def _scene_view(self, name: str):
        views = self._viewport.scene.saved_views
        for v in views:
            if v.name == name:
                return v
        raise KeyError(f"no scene called {name!r}; the scenes are: "
                       + ", ".join(repr(v.name) for v in views))

    def _sheet(self, sheet):
        """A sheet by its name, its title-block number (``L-02``) or its
        place (1 = the first, as the sheet tabs count): see
        :func:`core.sheets_api.find_sheet`, the one resolver. Its
        :class:`~core.sheets_api.SheetError` is a ``ValueError``."""
        return find_sheet(self._viewport.scene.compositions, sheet)

    def _has_gl(self) -> bool:
        return can_render(self._viewport)

    def _render_aimed(self, width: int, height: int, view, fit: bool):
        """The view rendered ``width`` × ``height``, the camera aimed at
        ``view``/``fit`` for it and given back after, even when the render
        fails (PR #463). render_image leaves the aspect of an explicit
        height to the caller, so it is set to the picture's: a 1024×768
        shot of a wide window came out squashed. The overlay painters
        follow the live widget, so they join in only when the shot has the
        widget's shape."""
        from PySide6.QtGui import QVector3D
        if not self._has_gl():
            raise RuntimeError(NO_GL)
        vp = self._viewport
        cam = vp.camera
        saved = (QVector3D(cam.target), cam.distance, cam.yaw, cam.pitch,
                 cam.perspective, cam.two_point, cam.aspect)
        live = max(vp.width(), 1) / max(vp.height(), 1)
        overlays = view is None and not fit \
            and abs(width / height - live) < 0.01
        try:
            cam.aspect = width / height
            if view is not None:
                cam.set_view(view)
                if view != "iso":           # elevations read best parallel
                    cam.perspective, cam.two_point = False, False
            if fit:
                lo, hi = vp.scene.bounds()
                if lo is not None:
                    cam.fit_box(lo, hi)
            image = vp.render_image(width, height, overlays=overlays)
        finally:
            (cam.target, cam.distance, cam.yaw, cam.pitch,
             cam.perspective, cam.two_point, cam.aspect) = saved
        if image is None or image.isNull():
            raise RuntimeError("the view did not render (" + NO_GL + ")")
        return image

    def _render_view(self, width: int, height: int | None):
        if not self._has_gl():
            raise RuntimeError(NO_GL)
        image = self._viewport.render_image(width, height)
        if image is None or image.isNull():
            raise RuntimeError("the view did not render (" + NO_GL + ")")
        return image

    def _composer_for(self, comps):
        """The project's composer (created hidden if it never opened),
        after checking that ``comps`` can be drawn: a view that is not a
        vector drawing needs GL."""
        composer = self._window()._ensure_composer()
        if not self._has_gl() and any(
                not (f.style == "vectorial"
                     and not composer.frame_is_perspective(f))
                for c in comps for f in c.frames):
            raise RuntimeError(NO_GL)
        return composer

    # ---- Looking ------------------------------------------------------------
    def _tool_get_scene_info(self) -> dict:
        """``query_model`` and what an agent needs to find its way: the
        file, the scenes, the sheets, the layers with their visibility,
        the georeference."""
        win = self._window()
        scene = self._viewport.scene
        info = self._tool_query_model()
        # What is open and what is allowed, under document_info's keys.
        doc = (self._tool_document_info()
               if hasattr(self, "_tool_document_info") else {})
        info.update({k: v for k, v in doc.items() if k not in ("sheets",
                                                                "views")})
        path = getattr(win, "_current_path", None)
        shown = getattr(getattr(getattr(win, "tray", None), "scenes", None),
                        "shown", None)
        georef = getattr(scene, "georef", None)
        info.update({
            "path": str(path) if path else None,
            "modified": bool(win._is_dirty()),
            "scenes": [v.name for v in scene.saved_views],
            "scene_shown": getattr(shown, "name", None),
            "sheets": [{"index": i + 1, "name": c.name,
                        "number": _sheet_number(c), "paper": c.paper,
                        "landscape": bool(c.landscape),
                        "views": len(c.frames)}
                       for i, c in enumerate(scene.compositions)],
            "layers": self._tool_list_layers()["layers"],
            "georef": georef.to_dict() if georef is not None else None,
            "can_render": self._has_gl(),
        })
        return info

    def _tool_get_object_info(self, name: str | None = None,
                              id: str | None = None) -> dict:  # noqa: A002
        """One group or component: its box, layer, material, children and
        BIM tag. With several of that name, the first, and how many."""
        from core.layers import layer_of
        from core.outliner import world_bounds
        from formats.igz import _ifc_json
        if not name and not id:
            raise ValueError("give the object's name or id")
        groups = self._groups([name] if name else None, [id] if id else None)
        g = groups[0]
        scene = self._viewport.scene
        box = world_bounds(scene.groups, g)
        mat = getattr(g, "material", None) or None
        return {
            "name": g.name, "id": g.uid,
            "kind": ("component" if g.is_instance() else "group"),
            "same_name": len(groups),
            "layer": layer_of(g),
            "hidden": bool(g.hidden), "locked": bool(g.locked),
            "material": (mat.get("mat") or "(colour)") if mat else None,
            "bounds": (None if box is None else
                       {"min": list(box[0]), "max": list(box[1]),
                        "size": [b - a for a, b in zip(*box)]}),
            "faces": len(g.mesh.faces), "edges": len(g.mesh.edges),
            "children": [{"name": c.name, "id": c.uid}
                         for c in getattr(g, "children", None) or []][:200],
            "bim": _ifc_json(g.ifc, g.name) if getattr(g, "ifc", None)
            else None,
        }

    def _tool_list_layers(self) -> dict:
        from core.layers import active_layer
        scene = self._viewport.scene
        return {"active": active_layer(scene), "layers": [
            {"name": ly.name, "visible": bool(ly.visible),
             "locked": bool(ly.locked), "folder": ly.folder}
            for ly in scene.layers]}

    def _tool_list_scenes(self) -> dict:
        """The scenes as the Scenes tab lists them, the one shown, and the
        sheets that show each (``used_by``)."""
        win = self._window()
        shown = getattr(getattr(getattr(win, "tray", None), "scenes", None),
                        "shown", None)
        return {"shown": getattr(shown, "name", None),
                "scenes": self._sheets_api().list_scenes()}

    def _tool_list_materials(self) -> dict:
        mats = getattr(self._viewport.scene, "materials", {}) or {}
        out = []
        for name in sorted(mats):
            m = mats[name]
            out.append({"name": name,
                        "color": list(m.color) if m.color else None,
                        "texture": bool(m.texture),
                        "opacity": m.opacity, "finish": m.finish})
        return {"materials": out}

    def _camera(self) -> dict:
        cam = self._viewport.camera
        return {"eye": _vec(cam.eye()), "target": _vec(cam.target),
                "projection": cam.projection_mode(),
                "fov": float(cam.fov_deg)}

    def _tool_screenshot(self, width: int = 1024, height: int = 768,
                         path: str | None = None,
                         view: str | None = None, fit: bool = False) -> dict:
        """The view as a PNG (or JPG, by ``path``'s suffix). A saved scene
        is ``export_view`` (PR #1494) — one tool for that, not two.

        ``view`` (a standard view: top, front, iso…) and ``fit`` (zoom
        extents) aim the camera for this one picture only (PR #463): the
        agent looks from anywhere without moving the user's view."""
        width = max(64, min(int(width), 4096))
        height = max(64, min(int(height), 4096))
        if view is not None and view not in STANDARD_VIEWS:
            raise ValueError(f"unknown view {view!r}; one of "
                             + ", ".join(STANDARD_VIEWS))
        out = (_writable(absolute(path)) if path
               else out_dir() / "viewport.png")
        image = self._render_aimed(width, height, view, bool(fit))
        if not image.save(str(out)):
            raise OSError(f"could not write {out}")
        return {"path": str(out), "width": image.width(),
                "height": image.height()}

    def _tool_render_sheet(self, sheet, width: int = 1600,
                           dpi: float | None = None,
                           path: str | None = None,
                           sheet_set: str | None = None) -> dict:
        """A sheet as a PNG, painted by the composer as its PDF and image
        exports do (``ComposerWindow.render_sheet_image``): the window is
        never shown, and it stays on the sheet it was on. ``sheet_set``
        (#1519): as that set prints it, its page number, count and sheet
        index within the set."""
        comp = self._sheet(sheet)
        if sheet_set:
            self._sheets_api().sheet_set(sheet_set)   # unknown: a clear error
        out = (_writable(absolute(path)) if path
               else out_dir() / "sheet.png")
        if dpi is None:
            page_w = comp.page_size_mm()[0]
            dpi = max(20.0, min(600.0, int(width) * 25.4 / page_w))
        dpi = max(20.0, min(600.0, float(dpi)))
        composer = self._composer_for([comp])
        if sheet_set:
            comps, name = composer._sheets_to_export(None, sheet_set)
            with composer.export_scope(comps, name):
                image, blank = composer.render_sheet_image(comp, dpi)
        else:
            image, blank = composer.render_sheet_image(comp, dpi)
        if not image.save(str(out)):
            raise OSError(f"could not write {out}")
        from core.sheets_api import SheetsAPI
        reply = {"path": str(out), "sheet": comp.name,
                 "width": image.width(), "height": image.height(),
                 "dpi": dpi,
                 "warnings": SheetsAPI(self._viewport.scene).warnings(comp)}
        if blank:
            reply["views_not_rendered"] = blank
        return reply

    # ---- The view (not undo steps, as in the app) ------------------------------
    def _tool_set_camera(self, view: str | None = None, eye=None,
                         target=None, up=None,
                         projection: str | None = None,
                         fov: float | None = None,
                         zoom_extents: bool = False) -> dict:
        from core.saved_views import from_lookat
        win = self._window()
        cam = self._viewport.camera
        if view is not None:
            if view not in STANDARD_VIEWS:
                raise ValueError(f"unknown view {view!r}; one of "
                                 + ", ".join(STANDARD_VIEWS))
            cam.set_view(view)
        if (eye is None) != (target is None):
            raise ValueError("eye and target go together")
        if eye is not None:
            if view is not None:
                raise ValueError("give a standard view or eye/target, "
                                 "not both")
            e, t = _triple(eye, "eye"), _triple(target, "target")
            if e == t:
                raise ValueError("eye and target are the same point")
            u = _triple(up, "up") if up is not None else (0.0, 0.0, 1.0)
            pose = from_lookat("", e, t, u, cam.fov_deg)
            from PySide6.QtGui import QVector3D
            cam.target = QVector3D(*pose.target)
            cam.distance, cam.yaw, cam.pitch = (pose.distance, pose.yaw,
                                                pose.pitch)
        if projection is not None:
            if projection not in PROJECTIONS:
                raise ValueError(f"unknown projection {projection!r}; one "
                                 "of " + ", ".join(PROJECTIONS))
            cam.set_projection(projection)
        if fov is not None:
            fov = float(fov)
            if not 1.0 <= fov <= 170.0:
                raise ValueError("fov is in degrees, between 1 and 170")
            cam.fov_deg = fov
        if zoom_extents:
            win._on_zoom_extents()
        sync = getattr(win, "_sync_projection_buttons", None)
        if sync is not None:
            sync(cam.projection_mode())
        self._viewport.update()
        return self._camera()

    def _tool_select(self, names=None, ids=None, clear: bool = False,
                     mode: str = "replace") -> dict:
        """Select groups and components by name or uid (``mode`` as the
        click modifiers: replace, add, remove, toggle), or empty the
        selection."""
        scene = self._viewport.scene
        if clear:
            scene.clear_selection()
        else:
            if not names and not ids:
                raise ValueError("give names or ids, or clear=true")
            if mode not in ("replace", "add", "remove", "toggle"):
                raise ValueError("mode is replace, add, remove or toggle")
            scene.select(self._groups(names, ids), mode=mode)
        self._viewport.notify_scene_changed()
        picked = [e for e in scene.selection if hasattr(e, "uid")]
        return {"selected": len(scene.selection),
                "objects": [{"name": g.name, "id": g.uid}
                            for g in picked][:200]}

    def _tool_show_scene(self, name: str) -> dict:
        """Show a saved scene as a click on its row does (no glide)."""
        view = self._scene_view(name)
        self._window().tray.scenes.show_view(view, animate=False)
        return {"shown": view.name, "camera": self._camera()}

    # ---- Changes to the document: one undo step each -------------------------
    def _tool_set_layer_visibility(self, layers, visible: bool) -> dict:
        from core.history import SetLayersVisibleCommand
        scene = self._viewport.scene
        if isinstance(layers, str):
            layers = [layers]
        missing = [n for n in layers or [] if scene.layer(n) is None]
        if not layers or missing:
            raise KeyError("no layer called " + ", ".join(
                repr(n) for n in missing or ["(none given)"])
                + "; the layers are: "
                + ", ".join(repr(ly.name) for ly in scene.layers))
        history = self._viewport.history
        history.execute(SetLayersVisibleCommand(layers, bool(visible)))
        if history.last_error is not None:
            raise RuntimeError(str(history.last_error))
        self._viewport.notify_scene_changed()
        return self._tool_list_layers()

    def _tool_apply_material(self, material: str, names=None,
                             ids=None) -> dict:
        """Paint with a material of the document: the objects named as a
        whole (as painting them from outside, or from the Outliner), or
        else the selection — its faces face by face, its objects whole."""
        from core.history import (CompoundCommand, SetFaceColorCommand,
                                  SetFaceMaterialTagCommand,
                                  SetFaceOpacityCommand,
                                  SetFaceTextureCommand,
                                  SetGroupMaterialCommand)
        from core.mesh import Face
        scene = self._viewport.scene
        mats = getattr(scene, "materials", {}) or {}
        mat = mats.get(material)
        if mat is None:
            raise KeyError(f"no material called {material!r}; the document "
                           "has: " + ", ".join(repr(n) for n in sorted(mats)))
        if names or ids:
            groups, faces = self._groups(names, ids), []
        else:
            groups = [e for e in scene.selection if hasattr(e, "children")]
            faces = [e for e in scene.selection if isinstance(e, Face)]
            if not groups and not faces:
                raise ValueError("nothing to paint: give names or ids, or "
                                 "select something first")
        cmds = [SetGroupMaterialCommand(g, _material_dict(mat))
                for g in groups]
        if faces:
            tag = SetFaceMaterialTagCommand(faces, mat.name, mat)
            opacity = SetFaceOpacityCommand(faces, mat.opacity)
            if mat.texture is not None:
                from tools.paint import _texture_commands
                cmds += _texture_commands(faces, dict(mat.texture), None)
                cmds += [opacity, tag]
            else:
                cmds += [SetFaceColorCommand(faces, tuple(mat.color)
                                             if mat.color else None),
                         SetFaceTextureCommand(faces, None), opacity, tag]
        history = self._viewport.history
        history.execute(CompoundCommand(cmds))
        if history.last_error is not None:
            raise RuntimeError(str(history.last_error))
        self._viewport.notify_scene_changed()
        return {"material": mat.name, "objects": len(groups),
                "faces": len(faces)}

    def _tool_import_file(self, path: str, unit: str | None = None,
                          make_faces: bool = False) -> dict:
        """File ▸ Import, by the file's suffix, as one undo step. ``unit``
        answers what OBJ, STL and DXF files do not record (OBJ: the
        importer's guess, STL: millimetres, DXF: the drawing's own)."""
        src = absolute(path, must_exist=True)
        suffix = src.suffix.lower()
        if suffix not in IMPORT_SUFFIXES:
            raise ValueError(f"unknown import format {suffix!r}; one of "
                             + ", ".join(IMPORT_SUFFIXES))
        if unit is not None and unit not in UNITS:
            raise ValueError("unit is one of " + ", ".join(UNITS))
        win = self._window()
        depth = len(self._viewport.history.undo_stack)
        mark = self._mark()
        win.viewport.end_group_edit()
        with quiet(win):
            if suffix == ".igz":
                try:
                    ok = win.import_igz_path(src, at=(0.0, 0.0, 0.0)) \
                        is not None
                except Exception as exc:  # noqa: BLE001 — said to the agent
                    raise RuntimeError(f"could not read {src}: {exc}") \
                        from None
                if not ok:
                    raise RuntimeError(f"{src.name} has no geometry")
            elif suffix == ".dae":
                ok = win._import_dae_path(src)
            elif suffix in (".glb", ".gltf"):
                ok = win._import_glb_path(src)
            elif suffix == ".skp":
                ok = win.import_skp_path(src)
            elif suffix == ".obj":
                from formats.obj import suggest_unit
                ok = win._import_obj_path(
                    src, UNITS[unit or suggest_unit(src) or "m"])
            elif suffix == ".stl":
                ok = win._import_stl_path(src, UNITS[unit or "mm"])
            else:
                options = (UNITS[unit] if unit else None, bool(make_faces))
                ok = (win._import_dxf_path(src, options=options)
                      if suffix == ".dxf"
                      else win._import_dwg_path(src, options=options))
        if not ok:
            raise self._failed(f"could not import {src}", mark)
        self._viewport.notify_scene_changed()
        return {"imported": str(src),
                "undo_steps": len(self._viewport.history.undo_stack) - depth,
                "model": self._tool_query_model()}

    # ---- Files ------------------------------------------------------------------
    def _tool_export_file(self, path: str, unit: str = "mm",
                          selection_only: bool = False) -> dict:
        """File ▸ Export, by the suffix: IFC (the BIM-tagged objects),
        glTF binary, COLLADA, STL, OBJ and DXF (the view's lines). The
        sheets are ``export_pdf`` and the pictures ``screenshot`` /
        ``export_view`` / ``render_sheet`` (PR #1494's names): one tool for
        each job."""
        from formats import dae as dae_format
        from formats import gltf as gltf_format
        from formats import ifc as ifc_format
        from formats import obj as obj_format
        from formats import stl as stl_format
        out = _writable(absolute(path))
        suffix = out.suffix.lower()
        win = self._window()
        scene = self._viewport.scene
        mark = self._mark()
        win.viewport.end_group_edit()
        reply: dict = {"exported": str(out)}
        if suffix == ".gltf":
            raise ValueError("glTF is written as one binary file: use .glb")
        if suffix in (".pdf", ".png", ".jpg"):
            raise ValueError(f"{suffix} is not a model format: export_pdf "
                             "writes the sheets, screenshot the view, "
                             "export_view a saved scene")
        if suffix not in EXPORT_SUFFIXES:
            raise ValueError(f"unknown export format {suffix!r}; one of "
                             + ", ".join(EXPORT_SUFFIXES))
        if suffix == ".ifc":
            from core.bim import collect_objects
            if not collect_objects(scene):
                raise ValueError("nothing to export to IFC: only objects "
                                 "tagged in the BIM panel go there")
            count: dict = {}

            def writer(s, p):
                count["n"] = ifc_format.save_ifc(s, str(p))
            ok = win._write_export("IFC", out, writer)
            reply["elements"] = count.get("n")
        elif suffix == ".glb":
            only = set(scene.selection) if selection_only else None
            if selection_only and not only:
                raise ValueError("selection_only, and nothing is selected")
            ok = win._write_export("GLB", out, lambda s, p:
                                   gltf_format.save_glb(s, p, only=only))
        elif suffix == ".dae":
            ok = win._write_export("COLLADA", out, dae_format.save_dae)
        elif suffix == ".stl":
            if unit not in stl_format.STL_UNITS:
                raise ValueError("unit is one of "
                                 + ", ".join(stl_format.STL_UNITS))
            ok = win._write_export("STL", out, lambda s, p:
                                   stl_format.save_stl(s, p, unit))
        elif suffix == ".obj":
            ok = win._write_export("OBJ", out, obj_format.save_obj)
        elif suffix == ".dxf":
            from core.i18n import tr
            from formats.dxf_out import save_dxf_layers
            before = out.stat().st_mtime_ns if out.exists() else None
            win._export_view_lines(str(out), save_dxf_layers,
                                   tr("Export DXF failed"))
            ok = (out.is_file() and not self._cancelled(mark)
                  and out.stat().st_mtime_ns != before)
        if not ok:
            raise self._failed(f"could not export {out}", mark)
        return reply

    # ---- Sheets and scenes (#1505) --------------------------------------------
    # One tool per operation of core.sheets_api.SheetsAPI. A writing tool is
    # ONE undo step (core.ai.run_step: rolled back whole when it fails, no
    # step when it changes nothing), takes an optional ``expected_revision``
    # (the document's ``revision`` as list_documents gives it) and answers
    # with ``changed`` and the new ``document_revision``. None needs the
    # composer window shown.
    def _sheets_api(self):
        from core.sheets_api import SheetsAPI
        vp = self._viewport
        return SheetsAPI(vp.scene, getattr(vp, "camera", None))

    def _revision(self) -> int:
        return int(self._viewport.scene.content_version)

    def _sheet_read(self, key: str, value) -> dict:
        return {key: value, "document_revision": self._revision()}

    def _sheet_step(self, expected_revision, method: str, **kw) -> dict:
        """``SheetsAPI.<method>(**kw)`` as one undoable step."""
        from core.ai import run_step
        if (expected_revision is not None
                and int(expected_revision) != self._revision()):
            raise RuntimeError(
                f"the document changed since revision {expected_revision} "
                f"(now {self._revision()}): read it again before editing")
        api = self._sheets_api()
        step = run_step(self._viewport,
                        lambda _scene: getattr(api, method)(**kw))
        if step["error"] is not None:
            raise RuntimeError("rolled back, the document is unchanged: "
                               + str(step["error"]).replace(
                                   "SnapshotImport: ", ""))
        if step["changed"]:
            self._sync_sheets()
        return {"result": step["result"], "changed": step["changed"],
                "document_revision": self._revision()}

    def _sync_sheets(self) -> None:
        """The composer (open or hidden) and the sheet strip catch up with
        sheets added, removed or renamed. Content edits reach the composer
        by themselves (core.history.SHEET_CONTENT_LISTENERS)."""
        win = self._window()
        composer = getattr(win, "_composer", None)
        if composer is not None:
            composer.sync_with_document()
        tabs = getattr(win, "_refresh_sheet_tabs", None)
        if tabs is not None:
            tabs()

    def _tool_list_sheets(self) -> dict:
        return self._sheet_read("sheets", self._sheets_api().list())

    def _tool_get_sheet(self, sheet, dimensions: bool = False) -> dict:
        out = self._sheets_api().get(sheet, cotas=bool(dimensions))
        out["document_revision"] = self._revision()
        return out

    def _tool_list_sheet_folders(self) -> dict:
        return self._sheet_read("folders", self._sheets_api().list_folders())

    def _tool_create_sheet(self, name, template=None, after=None,
                           paper: str = "A3", landscape: bool = True,
                           frame: bool = True, title_block: bool = False,
                           folder=None, expected_revision=None) -> dict:
        return self._sheet_step(
            expected_revision, "create", name=name, template=template,
            after=after, paper=paper, landscape=landscape, frame=frame,
            title_block=title_block, folder=folder)

    def _tool_update_sheet(self, sheet, name=None, paper=None,
                           landscape=None, index=None, margin_mm=None,
                           folder=None, print_in_all=None,
                           expected_revision=None) -> dict:
        return self._sheet_step(
            expected_revision, "update", ref=sheet, name=name, paper=paper,
            landscape=landscape, index=index, margin_mm=margin_mm,
            folder=folder, print_in_all=print_in_all)

    def _tool_delete_sheet(self, sheet, confirm: bool = False,
                           expected_revision=None) -> dict:
        return self._sheet_step(expected_revision, "delete", ref=sheet,
                                confirm=confirm)

    def _tool_add_frame(self, sheet, view=None, scale=None, x_mm=None,
                        y_mm=None, w_mm=None, h_mm=None, fit=None,
                        fields=None, expected_revision=None) -> dict:
        return self._sheet_step(
            expected_revision, "add_frame", sheet=sheet, view=view,
            scale=scale, x_mm=x_mm, y_mm=y_mm, w_mm=w_mm, h_mm=h_mm,
            fit=fit, **dict(fields or {}))

    def _tool_update_frame(self, sheet, frame, view=None, scale=None,
                           x_mm=None, y_mm=None, w_mm=None, h_mm=None,
                           fit=None, fields=None,
                           expected_revision=None) -> dict:
        return self._sheet_step(
            expected_revision, "update_frame", sheet=sheet, frame=frame,
            view=view, scale=scale, x_mm=x_mm, y_mm=y_mm, w_mm=w_mm,
            h_mm=h_mm, fit=fit, **dict(fields or {}))

    def _tool_remove_frame(self, sheet, frame,
                           expected_revision=None) -> dict:
        return self._sheet_step(expected_revision, "remove_frame",
                                sheet=sheet, frame=frame)

    def _tool_fit_frame(self, sheet, frame, mode: str = "content",
                        expected_revision=None) -> dict:
        return self._sheet_step(expected_revision, "fit", sheet=sheet,
                                frame=frame, mode=mode)

    def _tool_set_title_block(self, sheet="all", fields=None, columns=None,
                              x_mm=None, y_mm=None, w_mm=None, h_mm=None,
                              replace: bool = False,
                              expected_revision=None) -> dict:
        return self._sheet_step(
            expected_revision, "set_title_block", sheet=sheet,
            fields=fields, columns=columns, x_mm=x_mm, y_mm=y_mm,
            w_mm=w_mm, h_mm=h_mm, replace=replace)

    def _tool_add_text(self, sheet, text, x_mm: float = 20.0,
                       y_mm: float = 20.0, fields=None,
                       expected_revision=None) -> dict:
        return self._sheet_step(expected_revision, "add_text", sheet=sheet,
                                text=text, x_mm=x_mm, y_mm=y_mm,
                                **dict(fields or {}))

    def _tool_update_text(self, sheet, text, fields=None,
                          expected_revision=None) -> dict:
        return self._sheet_step(expected_revision, "update_text",
                                sheet=sheet, index=text,
                                **dict(fields or {}))

    def _tool_create_scene(self, name, from_scene=None, folder=None,
                           hidden_layers=None, target=None,
                           expected_revision=None) -> dict:
        return self._sheet_step(
            expected_revision, "create_scene", name=name,
            from_scene=from_scene, folder=folder,
            hidden_layers=hidden_layers, target=target)

    def _tool_update_scene(self, scene, name=None, folder=None,
                           hidden_layers=None, target=None,
                           expected_revision=None) -> dict:
        return self._sheet_step(
            expected_revision, "update_scene", ref=scene, name=name,
            folder=folder, hidden_layers=hidden_layers, target=target)

    def _tool_delete_scene(self, scene, confirm: bool = False,
                           expected_revision=None) -> dict:
        return self._sheet_step(expected_revision, "delete_scene",
                                ref=scene, confirm=confirm)

    # ---- Sheet sets (plan sets, #1519) ----------------------------------------
    def _tool_list_sheet_sets(self) -> dict:
        return self._sheet_read("sets", self._sheets_api().list_sets())

    def _tool_get_sheet_set(self, set) -> dict:  # noqa: A002 — the tool's name
        out = self._sheets_api().get_set(set)
        out["document_revision"] = self._revision()
        return out

    def _tool_create_sheet_set(self, name, sheets=None, cover=None,
                               description: str = "",
                               expected_revision=None) -> dict:
        return self._sheet_step(expected_revision, "create_set", name=name,
                                sheets=sheets, cover=cover,
                                description=description)

    def _tool_update_sheet_set(self, set, name=None, sheets=None,  # noqa: A002
                               add=None, remove=None, cover=None,
                               description=None,
                               expected_revision=None) -> dict:
        return self._sheet_step(expected_revision, "update_set", ref=set,
                                name=name, sheets=sheets, add=add,
                                remove=remove, cover=cover,
                                description=description)

    def _tool_delete_sheet_set(self, set, confirm: bool = False,  # noqa: A002
                               expected_revision=None) -> dict:
        return self._sheet_step(expected_revision, "delete_set", ref=set,
                                confirm=confirm)

