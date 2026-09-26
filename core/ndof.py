# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""3D mouse (3Dconnexion SpaceMouse) navigation — issue #108.

A 3D mouse is a cap that can be pushed, pulled, lifted, tilted and twisted:
six axes at once. This module is the device-free half: it turns one reading
of the six axes into a camera move. The drivers that deliver the readings
live in ``views/ndof_input.py`` (spacenavd on Linux, Raw Input on Windows).

The mapping is SketchUp's and FreeCAD's default, «object mode»: you hold the
MODEL. Move the cap right and the model goes right; lift it and the model
rises; push it away and the model goes away (zoom out); tilt it forward and
the model tips its top toward you; twist it and the model turns on its
vertical axis. The camera has no roll, so rolling the cap does nothing.

Every backend normalises its device's raw numbers into :class:`NdofSample`
first, in ONE frame — the user's — so the mapping here never cares which
driver spoke:

* ``right``   cap pushed right          (+) / left  (−)
* ``up``      cap lifted                (+) / pressed down (−)
* ``forward`` cap pushed away from you  (+) / pulled toward you (−)
* ``tilt``    cap tipped away from you  (+) (its top goes forward)
* ``spin``    cap twisted anticlockwise seen from above (+)
* ``roll``    cap tipped to the right   (+)

each in [−1, 1] at full deflection.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: What the devices report at full deflection. spacenavd and the HID
#: reports of every current 3Dconnexion model sit around ±350; a little
#: headroom keeps a hard push from clipping below full speed.
FULL_SCALE = 350.0

#: Full-deflection speeds, at sensitivity 1.
ORBIT_RAD_PER_S = 2.0          # about 115°/s
PAN_VIEWS_PER_S = 1.0          # one viewport height per second
ZOOM_STEPS_PER_S = 8.0         # eight wheel notches per second

#: Readings older than this (a device that stopped reporting, a machine
#: that stalled) move the camera as if only this much time had passed.
MAX_DT = 0.1


@dataclass
class NdofSample:
    right: float = 0.0
    up: float = 0.0
    forward: float = 0.0
    tilt: float = 0.0
    spin: float = 0.0
    roll: float = 0.0

    @classmethod
    def from_raw(cls, right, up, forward, tilt, spin, roll,
                 full_scale: float = FULL_SCALE) -> "NdofSample":
        def n(v):
            return max(-1.0, min(1.0, float(v) / full_scale))
        return cls(n(right), n(up), n(forward), n(tilt), n(spin), n(roll))

    def is_idle(self) -> bool:
        return not any((self.right, self.up, self.forward,
                        self.tilt, self.spin, self.roll))


@dataclass
class NdofSettings:
    enabled: bool = True
    sensitivity: float = 1.0       # 0.25 … 4
    deadzone: float = 0.05         # a cap at rest never reads exactly zero
    invert_pan: bool = False       # both pan axes (the first settings)
    invert_zoom: bool = False
    invert_rotate: bool = False    # both orbit axes (the first settings)
    #: One box per axis (issue #108, a user with a SpaceMouse: «a checkbox
    #: for each axis for panning and rotation»). Each flips on top of the
    #: pair switch above, which older settings may still carry.
    invert_pan_x: bool = False     # right / left
    invert_pan_y: bool = False     # up / down
    invert_tilt: bool = False      # orbit up / down (cap tipped)
    invert_spin: bool = False      # orbit around (cap twisted)
    #: Only translations (pan + zoom) — for plan drawing, where an accidental
    #: twist that tips the view out of Top is the last thing wanted.
    lock_rotation: bool = False


def shape(v: float, deadzone: float) -> float:
    """Dead zone, then a gentle curve: fine control near the centre, full
    speed at the stop — the same feel the 3Dconnexion driver gives."""
    a = abs(v)
    if a <= deadzone:
        return 0.0
    t = (a - deadzone) / (1.0 - deadzone)
    return math.copysign(t * t * 0.6 + t * 0.4, v)


def apply_ndof(camera, sample: NdofSample, dt: float, viewport_h: int,
               settings: NdofSettings | None = None) -> bool:
    """Move *camera* (an :class:`core.camera.OrbitCamera`) by one reading
    held for *dt* seconds. Returns True when the camera changed."""
    st = settings or NdofSettings()
    if not st.enabled:
        return False
    dt = max(0.0, min(dt, MAX_DT))
    if dt == 0.0:
        return False
    k = st.sensitivity * dt
    h = max(int(viewport_h), 1)
    right = shape(sample.right, st.deadzone)
    up = shape(sample.up, st.deadzone)
    forward = shape(sample.forward, st.deadzone)
    tilt = spin = 0.0
    if not st.lock_rotation:
        tilt = shape(sample.tilt, st.deadzone)
        spin = shape(sample.spin, st.deadzone)
    if st.invert_pan != st.invert_pan_x:
        right = -right
    if st.invert_pan != st.invert_pan_y:
        up = -up
    if st.invert_zoom:
        forward = -forward
    if st.invert_rotate != st.invert_tilt:
        tilt = -tilt
    if st.invert_rotate != st.invert_spin:
        spin = -spin
    moved = False
    if right or up:
        # camera.pan GRABS the model like a mouse drag: +dx carries it right,
        # +dy (screen down) carries it down — so lifting the cap is −dy.
        px = PAN_VIEWS_PER_S * h * k
        camera.pan(right * px, -up * px, h)
        moved = True
    if forward:
        # Pushing the model away = zooming out (negative wheel steps).
        camera.zoom(-forward * ZOOM_STEPS_PER_S * k)
        moved = True
    if tilt or spin:
        # camera.orbit takes pixels at π radians per viewport height and,
        # like a drag, grabs the model: +dx swings it right (a twist
        # anticlockwise from above brings its near side to the right),
        # +dy tips its top toward you (a cap tipped away).
        px = ORBIT_RAD_PER_S * k * h / math.pi
        camera.orbit(spin * px, tilt * px, h)
        moved = True
    return moved


# ---- Device frames → the user's frame ----------------------------------------
# Both conversions are ONE place each, so a sign found wrong on a real device
# is a one-character fix with a test beside it.

def from_spacenavd(x, y, z, rx, ry, rz) -> NdofSample:
    """spacenavd's frame: right-handed, Y up, Z toward the user — so +rx
    brings the cap's top toward the user, +ry turns it anticlockwise seen
    from above and +rz tips it to the left."""
    return NdofSample.from_raw(right=x, up=y, forward=-z,
                               tilt=-rx, spin=ry, roll=-rz)


def from_hid(x, y, z, rx, ry, rz) -> NdofSample:
    """The raw USB HID frame every 3Dconnexion device reports (what Windows
    Raw Input hands over): X right, Y toward the user, Z DOWN."""
    # Right-hand rotations about those axes: +rx brings the cap's top toward
    # the user, +rz turns it clockwise seen from above (Z points down), +ry
    # tips it to the left.
    return NdofSample.from_raw(right=x, up=-z, forward=-y,
                               tilt=-rx, spin=-rz, roll=-ry)
