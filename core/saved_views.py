# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Saved views — "Scenes": a named snapshot of the camera and of
the layer-visibility state, re-applied with one click.

A saved view never owns geometry; it is pure presentation state. Together
with layers it completes the '2D that emerges' workflow: "Plan view" =
top camera + parallel projection + only the plan layers on, stored as a
view and recalled instantly.

The camera snapshot is stored in the orbit camera's own terms (target /
distance / yaw / pitch), so capture → apply round-trips exactly. Importers
that carry eye/target/up cameras (e.g. .skp) convert once at import time.
"""
from __future__ import annotations


class SavedView:
    """A named camera + layer-visibility snapshot."""

    def __init__(self, name: str, target=(0.0, 0.0, 0.0), distance: float = 20.0,
                 yaw: float = -0.7853981633974483, pitch: float = 0.5235987755982988,
                 fov_deg: float = 45.0, perspective: bool = True,
                 two_point: bool = False, hidden_layers=None, style=None, section=None,
                 georef=None, shadows=None, hidden_objects=None,
                 hidden_shown=None, folder_id=None, position=0, hidden_layer_folders=None) -> None:
        self.name = name
        self.folder_id = folder_id
        self.position = int(position)
        self.target = tuple(target)
        self.distance = float(distance)
        self.yaw = float(yaw)
        self.pitch = float(pitch)
        self.fov_deg = float(fov_deg)
        self.perspective = bool(perspective)
        #: Two-point perspective (verticals kept vertical).
        self.two_point = bool(two_point)
        #: Layer NAMES hidden in this view. Every other layer shows — a layer
        #: created after the view was saved defaults to visible.
        self.hidden_layers = list(hidden_layers or [])
        self.hidden_layer_folders = list(hidden_layer_folders or [])
        #: Display-style snapshot (core.style.Style.to_dict()) or ``None`` —
        #: a scene remembers the style it was saved with.
        self.style = dict(style) if style else None
        #: Section state (scenes remember it): the ACTIVE plane's
        #: uid (or None = no cut) + the two visibility toggles. ``None``
        #: entirely = a view loaded from a document older than sections,
        #: which is left alone on recall. A view captured with NO planes in
        #: the model still records {"active": None}: "Active Section
        #: Planes" is saved per scene by default, so a plan or
        #: elevation scene made BEFORE any cut switches the cut OFF when
        #: recalled — every scene stands on its own (Marco, 2026-09-02).
        self.section = dict(section) if section else None
        #: Geographic reference layers shown in this view: the flat base
        #: map, the 3D terrain and the photogrammetric survey. In a .skp
        #: those are groups on their own layers, so a scene hides or shows
        #: them like anything else; here they hang off the scene as display
        #: objects, so the view records their visibility explicitly — a
        #: plan scene taken WITH the map and a detail scene taken WITHOUT it
        #: must each come back (and render on a sheet) as they were made
        #: (Marco, 2026-09-14). ``None`` = a view from a document older than
        #: this field, left alone on recall.
        self.georef = dict(georef) if georef else None
        #: Shadow settings snapshot (core.sun.ShadowSettings.to_dict()):
        #: on/off, date, time, darkness. Scenes save "Shadow Settings"
        #: too — a 3D captured with shadows renders its sheet
        #: frame with shadows, one captured without renders without (Marco,
        #: 2026-09-14). ``None`` = a view from before this field, hands-off.
        self.shadows = dict(shadows) if shadows else None
        #: The objects (group uids) hidden when the scene was saved —
        #: scenes remember "Hidden Objects" (Rafael, 2026-09-16:
        #: «una escena en donde esto esté oculto»). ``None`` = a view from
        #: before this field, hands-off; a list, even empty, is applied.
        self.hidden_objects = (list(hidden_objects)
                               if hidden_objects is not None else None)
        #: View ▸ Hidden Objects / Hidden Geometry as the scene was saved
        #: (``{"objects": bool, "geometry": bool}``); scenes keep
        #: both. ``None`` = hands-off.
        self.hidden_shown = dict(hidden_shown) if hidden_shown else None

    # ---- Snapshot / recall ---------------------------------------------------
    @classmethod
    def capture(cls, name: str, scene, camera) -> "SavedView":
        """Snapshot the live camera and the current layer visibility."""
        t = camera.target
        return cls(name, target=(t.x(), t.y(), t.z()),
                   distance=camera.distance, yaw=camera.yaw,
                   pitch=camera.pitch, fov_deg=camera.fov_deg,
                   perspective=camera.perspective,
                   two_point=bool(getattr(camera, "two_point", False)),
                   hidden_layers=[ly.name for ly in scene.layers
                                  if not ly.visible],
                   hidden_layer_folders=[f.uid for f in scene.layer_folders
                                         if not f.visible],
                   style=(scene.display_style.to_dict()
                          if getattr(scene, "display_style", None) else None),
                   section={
                       "active": (scene.active_section().uid
                                  if scene.active_section() else None),
                       "planes_shown": getattr(scene, "show_section_planes",
                                               True),
                       "cuts_shown": getattr(scene, "show_section_cuts",
                                             True),
                   },
                   georef=georef_state(scene),
                   shadows=(scene.shadows.to_dict()
                            if getattr(scene, "shadows", None) is not None
                            else None),
                   hidden_objects=[uid for uid, g in
                                   scene.groups_by_uid().items() if g.hidden],
                   hidden_shown={
                       "objects": bool(getattr(scene, "show_hidden_objects",
                                               False)),
                       "geometry": bool(getattr(scene, "show_hidden_geometry",
                                                False))})

    def recapture(self, scene, camera) -> None:
        """Update this view in place from the live state (keeps the name)."""
        fresh = SavedView.capture(self.name, scene, camera)
        fresh.folder_id = self.folder_id
        fresh.position = self.position
        self.__dict__.update(fresh.__dict__)

    def apply(self, scene, camera) -> None:
        """Recall the view: camera first, then the layer-visibility state.
        The caller bumps ``scene.version`` / repaints (tray convention)."""
        from PySide6.QtGui import QVector3D
        camera.target = QVector3D(*self.target)
        camera.distance = self.distance
        camera.yaw = self.yaw
        camera.pitch = self.pitch
        camera.fov_deg = self.fov_deg
        camera.perspective = self.perspective
        camera.two_point = self.two_point
        hidden = set(self.hidden_layers)
        for ly in scene.layers:
            ly.visible = ly.name not in hidden
        for folder in scene.layer_folders:
            folder.visible = folder.uid not in self.hidden_layer_folders
        if self.style:
            from core.style import Style
            scene.display_style = Style.from_dict(self.style)
        if self.section is not None:
            uid = self.section.get("active")
            target = None
            for sp in getattr(scene, "section_planes", []):
                if sp.uid == uid:
                    target = sp
                    break
            scene.set_active_section(target)
            scene.show_section_planes = bool(
                self.section.get("planes_shown", True))
            scene.show_section_cuts = bool(
                self.section.get("cuts_shown", True))
        if self.georef is not None:
            for key, obj in georef_objects(scene):
                if obj is not None and key in self.georef:
                    obj.visible = bool(self.georef[key])
        if self.shadows is not None and getattr(scene, "shadows", None) is not None:
            apply_shadow_state(scene, self.shadows)
        if self.hidden_objects is not None:
            hidden = set(self.hidden_objects)
            for uid, g in scene.groups_by_uid().items():
                g.hidden = uid in hidden
        if self.hidden_shown is not None:
            scene.show_hidden_objects = bool(self.hidden_shown.get("objects"))
            scene.show_hidden_geometry = bool(self.hidden_shown.get("geometry"))

    # ---- Serialisation (.igz) ------------------------------------------------
    def to_dict(self) -> dict:
        entry: dict = {
            "name": self.name,
            "target": [self.target[0], self.target[1], self.target[2]],
            "distance": self.distance,
            "yaw": self.yaw,
            "pitch": self.pitch,
        }
        if self.folder_id is not None:
            entry["folder_id"] = self.folder_id
        entry["position"] = self.position
        if self.fov_deg != 45.0:
            entry["fov"] = self.fov_deg
        if not self.perspective:
            entry["parallel"] = True
        if self.two_point:
            entry["two_point"] = True
        if self.hidden_layers:
            entry["hidden_layers"] = list(self.hidden_layers)
        if self.hidden_layer_folders:
            entry["hidden_layer_folders"] = list(self.hidden_layer_folders)
        if self.style:
            entry["style"] = dict(self.style)
        if self.section is not None:
            entry["section"] = dict(self.section)
        if self.georef is not None:
            entry["georef"] = dict(self.georef)
        if self.shadows is not None:
            entry["shadows"] = dict(self.shadows)
        if self.hidden_objects is not None:
            entry["hidden_objects"] = list(self.hidden_objects)
        if self.hidden_shown is not None:
            entry["hidden_shown"] = dict(self.hidden_shown)
        return entry

    @classmethod
    def from_dict(cls, raw: dict) -> "SavedView":
        t = raw.get("target") or [0.0, 0.0, 0.0]
        return cls(raw.get("name", "Scene"),
                   target=(t[0], t[1], t[2]),
                   distance=raw.get("distance", 20.0),
                   yaw=raw.get("yaw", -0.7853981633974483),
                   pitch=raw.get("pitch", 0.5235987755982988),
                   fov_deg=raw.get("fov", 45.0),
                   perspective=not raw.get("parallel", False),
                   two_point=bool(raw.get("two_point", False)),
                   hidden_layers=raw.get("hidden_layers"),
                   hidden_layer_folders=raw.get("hidden_layer_folders"),
                   style=raw.get("style"),
                   section=raw.get("section"),
                   georef=raw.get("georef"),
                   shadows=raw.get("shadows"),
                   hidden_objects=raw.get("hidden_objects"),
                   hidden_shown=raw.get("hidden_shown"),
                   folder_id=raw.get("folder_id"),
                   position=raw.get("position", 0))


def apply_shadow_state(scene, raw: dict) -> None:
    """Put a shadow snapshot back onto ``scene.shadows`` IN PLACE — the
    panel, the menu and the viewport all hold that one object."""
    from core.sun import ShadowSettings
    fresh = ShadowSettings.from_dict(raw)
    scene.shadows.__dict__.update(fresh.__dict__)


def georef_objects(scene) -> list[tuple[str, object]]:
    """The scene's geographic display objects as ``(key, obj_or_None)``:
    the flat base map (``"map"``), the 3D terrain and the survey mesh."""
    return [("map", getattr(scene, "tile_layer", None)),
            ("terrain", getattr(scene, "terrain", None)),
            ("survey", getattr(scene, "photo_mesh", None))]


def georef_state(scene) -> dict:
    """Visibility of the geographic layers right now — a missing object
    counts as hidden, so a scene made before any base map existed recalls
    with the map OFF (every scene stands on its own, like sections)."""
    return {key: bool(obj is not None and getattr(obj, "visible", False))
            for key, obj in georef_objects(scene)}


def from_lookat(name: str, eye, target, up, fov_deg: float = 45.0,
                perspective: bool = True, ortho_height: float | None = None,
                hidden_layers=None) -> SavedView:
    """A :class:`SavedView` from an eye/target/up camera (importer entry).

    ``eye``/``target``/``up`` are (x, y, z) metres, Z-up. The orbit camera
    derives its screen-up from the world Z axis, so only the LOOK direction
    survives the conversion exactly; for a straight-down view (plan), the
    stored ``up`` becomes the yaw (screen rotation) instead — that keeps
    "north up" plans north-up. For a parallel view, ``ortho_height``
    (visible height in metres) sets the framing distance.
    """
    import math
    dx = eye[0] - target[0]
    dy = eye[1] - target[1]
    dz = eye[2] - target[2]
    distance = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    pitch = math.asin(max(-1.0, min(1.0, dz / distance)))
    limit = math.radians(89.0)
    if abs(pitch) < limit - 1e-6:
        yaw = math.atan2(dy, dx)
    else:
        # Looking straight up/down: the horizontal direction is degenerate —
        # recover the screen rotation from the stored up vector (at the pole
        # the orbit camera's screen-up is −(cos yaw, sin yaw)).
        yaw = math.atan2(-up[1], -up[0]) if (up[0] or up[1]) \
            else math.radians(-90.0)
    pitch = max(-limit, min(limit, pitch))
    if not perspective and ortho_height and ortho_height > 0:
        # The orbit camera sizes its parallel frustum from distance·tan(fov/2):
        # pick the distance that reproduces the stored visible height.
        distance = (ortho_height / 2.0) / math.tan(math.radians(fov_deg) / 2.0)
    return SavedView(name, target=tuple(target), distance=distance, yaw=yaw,
                     pitch=pitch, fov_deg=fov_deg, perspective=perspective,
                     hidden_layers=hidden_layers)


class SceneFolder:
    """Document-owned folder; parent IDs allow arbitrary nested folders."""

    def __init__(self, name, uid=None, parent_id=None, position=0, expanded=True):
        from uuid import uuid4
        self.name = name
        self.uid = uid or str(uuid4())
        self.parent_id = parent_id
        self.position = int(position)
        self.expanded = bool(expanded)

    def to_dict(self) -> dict:
        """Serialize the folder hierarchy and state for a document."""
        return dict(name=self.name, uid=self.uid, parent_id=self.parent_id,
                    position=self.position, expanded=self.expanded)

    @classmethod
    def from_dict(cls, raw: dict) -> "SceneFolder":
        """Restore a folder, using defaults for omitted document fields."""
        return cls(raw.get("name", "Folder"), uid=raw.get("uid"),
                   parent_id=raw.get("parent_id"),
                   position=raw.get("position", 0),
                   expanded=raw.get("expanded", True))
