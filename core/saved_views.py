# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Saved views — SketchUp's "Scenes": a named snapshot of the camera and of
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
                 hidden_layers=None, style=None, section=None) -> None:
        self.name = name
        self.target = tuple(target)
        self.distance = float(distance)
        self.yaw = float(yaw)
        self.pitch = float(pitch)
        self.fov_deg = float(fov_deg)
        self.perspective = bool(perspective)
        #: Layer NAMES hidden in this view. Every other layer shows — a layer
        #: created after the view was saved defaults to visible, like SketchUp.
        self.hidden_layers = list(hidden_layers or [])
        #: Display-style snapshot (core.style.Style.to_dict()) or ``None`` —
        #: SketchUp scenes remember the style they were saved with.
        self.style = dict(style) if style else None
        #: Section state (SketchUp scenes remember it): the ACTIVE plane's
        #: uid (or None = no cut) + the two visibility toggles. ``None``
        #: entirely = a view loaded from a document older than sections,
        #: which is left alone on recall. A view captured with NO planes in
        #: the model still records {"active": None}: SketchUp's "Active
        #: Section Planes" is saved per scene by default, so a plan or
        #: elevation scene made BEFORE any cut switches the cut OFF when
        #: recalled — every scene stands on its own (Marco, 2026-09-02).
        self.section = dict(section) if section else None

    # ---- Snapshot / recall ---------------------------------------------------
    @classmethod
    def capture(cls, name: str, scene, camera) -> "SavedView":
        """Snapshot the live camera and the current layer visibility."""
        t = camera.target
        return cls(name, target=(t.x(), t.y(), t.z()),
                   distance=camera.distance, yaw=camera.yaw,
                   pitch=camera.pitch, fov_deg=camera.fov_deg,
                   perspective=camera.perspective,
                   hidden_layers=[ly.name for ly in scene.layers
                                  if not ly.visible],
                   style=(scene.display_style.to_dict()
                          if getattr(scene, "display_style", None) else None),
                   section={
                       "active": (scene.active_section().uid
                                  if scene.active_section() else None),
                       "planes_shown": getattr(scene, "show_section_planes",
                                               True),
                       "cuts_shown": getattr(scene, "show_section_cuts",
                                             True),
                   })

    def recapture(self, scene, camera) -> None:
        """Update this view in place from the live state (keeps the name)."""
        fresh = SavedView.capture(self.name, scene, camera)
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
        hidden = set(self.hidden_layers)
        for ly in scene.layers:
            ly.visible = ly.name not in hidden
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

    # ---- Serialisation (.igz) ------------------------------------------------
    def to_dict(self) -> dict:
        entry: dict = {
            "name": self.name,
            "target": [self.target[0], self.target[1], self.target[2]],
            "distance": self.distance,
            "yaw": self.yaw,
            "pitch": self.pitch,
        }
        if self.fov_deg != 45.0:
            entry["fov"] = self.fov_deg
        if not self.perspective:
            entry["parallel"] = True
        if self.hidden_layers:
            entry["hidden_layers"] = list(self.hidden_layers)
        if self.style:
            entry["style"] = dict(self.style)
        if self.section is not None:
            entry["section"] = dict(self.section)
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
                   hidden_layers=raw.get("hidden_layers"),
                   style=raw.get("style"),
                   section=raw.get("section"))


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
