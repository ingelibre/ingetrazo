# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Scene transitions — the camera glides from one scene to the next.

Pure maths, no Qt widgets: what the camera looks like at any instant
between two scenes, and along a whole run through every scene (glide,
pause, glide…). The viewport's player (``views/scene_player.py``) asks it
for the pose of the moment and paints it; an export of the run as a video
can ask it for the pose of every frame the same way.

Only the camera moves. The rest of what a scene recalls — layers, style,
section, shadows, hidden objects — changes once, when the camera arrives:
it is the destination's, and changing it on every frame would rebuild the
model's caches sixty times a second.

The glide, per term of the orbit camera:

- the target travels in a straight line;
- the distance changes in proportion (log scale), so coming in from far
  away does not crawl at first and then rush at the end;
- the yaw turns the short way round, never the long one;
- pitch and field of view go from one value to the other;
- it starts and stops gently (``ease``).

A parallel view stays parallel only while both ends are: a glide from or
to perspective runs in perspective, and the projection snaps where the
parallel end is — at the arrival, or at once on leaving. Parallel framing
is the perspective's at the target plane, so the snap barely shows there.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: The defaults: two seconds to glide, one to stay on each scene in a run.
DEFAULT_TRANSITION = 2.0
DEFAULT_PAUSE = 1.0
#: The longest either may be (seconds) — a typo of 2000 is not a setting.
MAX_SECONDS = 60.0


@dataclass
class SceneAnimation:
    """A document's scene-transition settings (saved in the .igz)."""

    #: Whether showing a scene glides there (off: it jumps, as before).
    enabled: bool = True
    #: Seconds the camera takes from one scene to the next.
    transition: float = DEFAULT_TRANSITION
    #: Seconds a run through every scene stays on each.
    pause: float = DEFAULT_PAUSE

    def __post_init__(self) -> None:
        self.enabled = bool(self.enabled)
        self.transition = _seconds(self.transition, DEFAULT_TRANSITION)
        self.pause = _seconds(self.pause, DEFAULT_PAUSE)

    def glide_seconds(self) -> float:
        """How long showing a scene takes: 0 = a jump."""
        return self.transition if self.enabled else 0.0

    def to_dict(self) -> dict:
        """Only what differs from the defaults (terse files)."""
        out: dict = {}
        if not self.enabled:
            out["enabled"] = False
        if self.transition != DEFAULT_TRANSITION:
            out["transition"] = self.transition
        if self.pause != DEFAULT_PAUSE:
            out["pause"] = self.pause
        return out

    @classmethod
    def from_dict(cls, raw) -> "SceneAnimation":
        raw = raw if isinstance(raw, dict) else {}
        return cls(enabled=raw.get("enabled", True),
                   transition=raw.get("transition", DEFAULT_TRANSITION),
                   pause=raw.get("pause", DEFAULT_PAUSE))


def _seconds(value, default: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return max(0.0, min(MAX_SECONDS, value))


@dataclass(frozen=True)
class Pose:
    """The orbit camera's terms, as plain numbers."""

    target: tuple
    distance: float
    yaw: float
    pitch: float
    fov_deg: float = 45.0
    perspective: bool = True
    two_point: bool = False

    @classmethod
    def of_camera(cls, camera) -> "Pose":
        t = camera.target
        return cls((t.x(), t.y(), t.z()), float(camera.distance),
                   float(camera.yaw), float(camera.pitch),
                   float(camera.fov_deg), bool(camera.perspective),
                   bool(getattr(camera, "two_point", False)))

    @classmethod
    def of_view(cls, view) -> "Pose":
        return cls(tuple(view.target), float(view.distance), float(view.yaw),
                   float(view.pitch), float(view.fov_deg),
                   bool(view.perspective), bool(view.two_point))

    def put_on(self, camera) -> None:
        """Set ``camera`` to this pose."""
        from PySide6.QtGui import QVector3D
        camera.target = QVector3D(*self.target)
        camera.distance = self.distance
        camera.yaw = self.yaw
        camera.pitch = self.pitch
        camera.fov_deg = self.fov_deg
        camera.perspective = self.perspective
        camera.two_point = self.two_point

    def close_to(self, other: "Pose", tol: float = 1e-6) -> bool:
        """The same view, give or take rounding (a glide there is idle)."""
        return (all(abs(a - b) <= tol * max(1.0, abs(a), abs(b))
                    for a, b in zip(self.target, other.target))
                and abs(self.distance - other.distance)
                <= tol * max(1.0, self.distance)
                and abs(turn(self.yaw, other.yaw)) <= tol
                and abs(self.pitch - other.pitch) <= tol
                and abs(self.fov_deg - other.fov_deg) <= tol
                and self.perspective == other.perspective
                and self.two_point == other.two_point)


def ease(u: float) -> float:
    """Gentle start and stop: 0 → 0, 1 → 1, flat at both ends."""
    u = max(0.0, min(1.0, u))
    return 0.5 - 0.5 * math.cos(math.pi * u)


def turn(a: float, b: float) -> float:
    """The short way from angle ``a`` to angle ``b`` (radians, −π…π]."""
    d = math.fmod(b - a, 2.0 * math.pi)
    if d > math.pi:
        d -= 2.0 * math.pi
    elif d <= -math.pi:
        d += 2.0 * math.pi
    return d


def between(a: Pose, b: Pose, u: float) -> Pose:
    """The pose a fraction ``u`` (0…1, already eased or not) of the way
    from ``a`` to ``b``. ``u`` = 1 is exactly ``b``."""
    if u >= 1.0:
        return b
    if u <= 0.0:
        return a
    lerp = lambda x, y: x + (y - x) * u           # noqa: E731
    target = tuple(lerp(x, y) for x, y in zip(a.target, b.target))
    da, db = max(a.distance, 1e-9), max(b.distance, 1e-9)
    distance = math.exp(lerp(math.log(da), math.log(db)))
    yaw = a.yaw + turn(a.yaw, b.yaw) * u
    # On the way: parallel only between two parallel scenes, two-point
    # only between two two-point ones.
    perspective = a.perspective or b.perspective
    two_point = a.two_point and b.two_point
    return Pose(target, distance, yaw, lerp(a.pitch, b.pitch),
                lerp(a.fov_deg, b.fov_deg), perspective, two_point)


def glide(a: Pose, b: Pose, seconds: float, t: float) -> Pose:
    """The pose ``t`` seconds into a glide of ``seconds`` from a to b."""
    if seconds <= 0.0 or t >= seconds:
        return b
    return between(a, b, ease(t / seconds))


class Run:
    """A run through scenes: glide to the first, stay, glide to the next…
    round and round. Built from the camera's pose when it starts and the
    poses of the scenes in order, starting with the one it goes to first.

    ``at(t)`` gives the pose at ``t`` seconds and the index (into
    ``poses``) of the scene last arrived at, or −1 before the first."""

    def __init__(self, start: Pose, poses: list, transition: float,
                 pause: float, loop: bool = True) -> None:
        self.start = start
        self.poses = list(poses)
        self.transition = max(0.0, float(transition))
        self.pause = max(0.0, float(pause))
        self.loop = bool(loop)

    @property
    def leg(self) -> float:
        """One scene's share: its glide and its pause."""
        return self.transition + self.pause

    def duration(self) -> float:
        """One time through every scene (``loop`` repeats it)."""
        return self.leg * len(self.poses)

    def at(self, t: float) -> tuple:
        n = len(self.poses)
        if n == 0:
            return self.start, -1
        t = max(0.0, t)
        leg = self.leg
        if leg <= 0.0:                       # nothing to wait for: the first
            return self.poses[0], 0
        k = int(t // leg)
        if not self.loop and k >= n:
            return self.poses[-1], n - 1
        into = t - k * leg
        i = k % n
        if into >= self.transition:          # arrived: staying on scene i
            return self.poses[i], i
        if k == 0:                           # the first glide, from start
            return glide(self.start, self.poses[0], self.transition,
                         into), -1
        last = (i - 1) % n                   # on the way from the last one
        return glide(self.poses[last], self.poses[i], self.transition,
                     into), last


# ---- A video of the run ------------------------------------------------------
# The same glide and pause, once through the scenes and no round: the
# first scene stands for its pause, the camera glides to the next, stands,
# and so on, and the video ends on the last scene's pause.

#: Frames per second a video may have.
VIDEO_FPS = (24, 25, 30, 60)


def video_seconds(count: int, transition: float, pause: float) -> float:
    """How long a video of ``count`` scenes lasts."""
    if count <= 0:
        return 0.0
    return max(0.0, pause) + (count - 1) * (max(0.0, transition)
                                            + max(0.0, pause))


def video_frame_count(count: int, transition: float, pause: float,
                      fps: int) -> int:
    """Frames in that video — at least one, the first scene."""
    if count <= 0:
        return 0
    return max(1, int(round(video_seconds(count, transition, pause)
                            * fps)) + 1)


def video_at(poses: list, transition: float, pause: float, t: float) -> tuple:
    """The pose ``t`` seconds into the video and the index of the scene
    whose layers and style show then (the last one reached)."""
    if not poses:
        raise ValueError("a video needs at least one scene")
    pause = max(0.0, pause)
    if t < pause or len(poses) == 1:
        return poses[0], 0
    run = Run(poses[0], poses[1:], transition, pause, loop=False)
    pose, reached = run.at(t - pause)
    return pose, reached + 1
