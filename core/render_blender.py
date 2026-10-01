# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Render with Blender (issue #181): everything but the dialog.

IngeTrazo does not render photorealistic images itself; the user's own
Blender does, in the background (``blender -b``), with Cycles or EEVEE.
This module finds that Blender, writes the job (the model as GLB, the
current camera, the sun of the Shadows panel, engine and quality), builds
the command and the environment to run it in, and reads its progress. The
dialog is ``plugins/render_blender.py``; the Blender side is
``resources/blender/render_scene.py``.

Where Blender can be reached:

- **Windows, macOS, AppImage, .tar.gz**: directly. The packaged builds
  (PyInstaller) set ``LD_LIBRARY_PATH`` to their own libraries; Blender must
  not inherit it (:func:`clean_env`).
- **Flatpak**: the sandbox cannot see the host's programs. With the user's
  permission (``flatpak override --user --talk-name=org.freedesktop.Flatpak
  com.ingetrazo.IngeTrazo``) Blender runs through ``flatpak-spawn --host``,
  a system install or Blender's own Flatpak alike. The permission is NOT in
  the manifest: it lets the app run host commands, so it stays opt-in.
- **Snap**: strict confinement cannot run host programs at all.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: QSettings key for a Blender the user picked by hand.
SETTINGS_KEY = "render/blender_path"

BLENDER_FLATPAK_ID = "org.blender.Blender"
ENGINES = ("eevee", "cycles")
#: Samples per quality, per engine: (draft, medium, high).
SAMPLES = {"eevee": (16, 64, 128), "cycles": (32, 128, 512)}


def in_flatpak() -> bool:
    return Path("/.flatpak-info").exists()


def in_snap() -> bool:
    return bool(os.environ.get("SNAP"))


def render_script() -> Path:
    from core.paths import app_root
    return app_root() / "resources" / "blender" / "render_scene.py"


@dataclass
class BlenderFound:
    """How to start Blender: ``command`` is the argv prefix (the program,
    or ``flatpak-spawn --host …``); ``where`` is what the dialog shows."""
    command: list
    where: str


# ---- Finding Blender ----------------------------------------------------------

def _platform_candidates() -> list:
    """Usual install locations, newest version first."""
    out: list = []
    if sys.platform == "win32":
        roots = [os.environ.get(k) for k in
                 ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        for root in filter(None, roots):
            out += sorted(glob.glob(os.path.join(
                root, "Blender Foundation", "Blender*", "blender.exe")),
                reverse=True)
            out.append(os.path.join(root, "Steam", "steamapps", "common",
                                    "Blender", "blender.exe"))
    elif sys.platform == "darwin":
        for base in ("/Applications", os.path.expanduser("~/Applications")):
            out += sorted(glob.glob(os.path.join(
                base, "Blender*.app", "Contents", "MacOS", "Blender")),
                reverse=True)
    else:
        out += ["/usr/bin/blender", "/usr/local/bin/blender",
                "/snap/bin/blender", os.path.expanduser("~/.local/bin/blender")]
        out += sorted(glob.glob("/opt/blender*/blender"), reverse=True)
    return out


def _host(args: list, timeout: float = 10.0) -> Optional[str]:
    """Run ``args`` on the Flatpak host; stdout, or None if not allowed."""
    try:
        r = subprocess.run(["flatpak-spawn", "--host", *args],
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def find_blender(saved: str | None = None) -> Optional[BlenderFound]:
    """The Blender to render with, or None. A path the user chose wins."""
    if in_flatpak():
        if saved:
            return BlenderFound(["flatpak-spawn", "--host", saved], saved)
        path = (_host(["sh", "-c", "command -v blender"]) or "").strip()
        if path:
            return BlenderFound(["flatpak-spawn", "--host", path], path)
        if _host(["flatpak", "info", BLENDER_FLATPAK_ID]) is not None:
            return BlenderFound(
                ["flatpak-spawn", "--host", "flatpak", "run",
                 "--filesystem=home", BLENDER_FLATPAK_ID],
                f"Flatpak {BLENDER_FLATPAK_ID}")
        return None
    if saved and Path(saved).is_file():
        return BlenderFound([saved], saved)
    which = shutil.which("blender")
    if which:
        return BlenderFound([which], which)
    for cand in _platform_candidates():
        if Path(cand).is_file():
            return BlenderFound([cand], cand)
    # Blender installed from Flathub, on a system where IngeTrazo itself is
    # not a Flatpak (the AppImage, the tarball): `flatpak run` it.
    flatpak = shutil.which("flatpak")
    if flatpak and sys.platform.startswith("linux"):
        try:
            r = subprocess.run([flatpak, "info", BLENDER_FLATPAK_ID],
                               capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            r = None
        if r is not None and r.returncode == 0:
            return BlenderFound([flatpak, "run", "--filesystem=home",
                                 BLENDER_FLATPAK_ID],
                                f"Flatpak {BLENDER_FLATPAK_ID}")
    return None


# ---- How to install it, for the package the user has ---------------------------

DOWNLOAD_URL = "https://www.blender.org/download/"
FLATPAK_PERMISSION = ("flatpak override --user "
                      "--talk-name=org.freedesktop.Flatpak "
                      "com.ingetrazo.IngeTrazo")


def package_kind() -> str:
    """Which IngeTrazo this is: snap, flatpak, windows, macos, or linux
    (AppImage, tarball or source — all can run a system Blender)."""
    if in_snap():
        return "snap"
    if in_flatpak():
        return "flatpak"
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def install_steps(kind: str | None = None,
                  host_allowed: bool | None = None) -> list:
    """What to do when no Blender is found, for this package: a list of
    ``(English text, command or None)``, commands ready to copy."""
    kind = kind or package_kind()
    if kind == "windows":
        return [("Download Blender from blender.org and install it, or run "
                 "in a terminal:", "winget install --id BlenderFoundation.Blender -e")]
    if kind == "macos":
        return [("Download Blender from blender.org, open the .dmg and drag "
                 "Blender to Applications.", None)]
    if kind == "flatpak":
        if host_allowed is None:
            host_allowed = flatpak_host_allowed()
        steps = [("Install Blender from Flathub (skip it if you already have "
                  "Blender):", f"flatpak install flathub {BLENDER_FLATPAK_ID}")]
        if not host_allowed:
            steps.append(("Let IngeTrazo start it (the Flatpak cannot see "
                          "other programs on its own), once:",
                          FLATPAK_PERMISSION))
        return steps
    if kind == "snap":
        return [("The Snap package cannot start other programs. To render "
                 "with Blender, use IngeTrazo's AppImage or Flatpak.", None)]
    return [("Install Blender, for example with Snap (current version):",
             "sudo snap install blender --classic"),
            ("or with Flatpak:", f"flatpak install flathub {BLENDER_FLATPAK_ID}")]


def flatpak_host_allowed() -> bool:
    """Whether this Flatpak may run host commands (the opt-in permission)."""
    return _host(["true"], timeout=5.0) is not None


# ---- The environment Blender runs in ----------------------------------------

#: Variables a frozen IngeTrazo sets for ITSELF that would break Blender.
_OURS = ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH",
         "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH", "QT_QPA_PLATFORM")


def clean_env(environ: dict | None = None) -> dict:
    """The environment for the Blender child: PyInstaller's
    ``LD_LIBRARY_PATH`` points at IngeTrazo's bundled libraries, and a
    Blender that inherits it loads our Qt/Python libs and dies. PyInstaller
    keeps the original in ``LD_LIBRARY_PATH_ORIG``; restore it."""
    env = dict(os.environ if environ is None else environ)
    for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        orig = env.pop(var + "_ORIG", None)
        if orig is not None:
            env[var] = orig
        elif getattr(sys, "frozen", False):
            env.pop(var, None)
    for var in _OURS:
        env.pop(var, None)
    return env


# ---- The job ------------------------------------------------------------------

def sun_toward(scene) -> Optional[tuple]:
    """Unit vector toward the sun for the date and time of the Shadows
    panel — whether or not shadows are on in the viewport: a render always
    has a sun. None at night. Same site, zone and north as the viewport."""
    import datetime as _dt
    from core import sun
    sh = getattr(scene, "shadows", None) or sun.ShadowSettings()
    datum = getattr(scene, "georef", None)
    lat = getattr(datum, "lat", None)
    lon = getattr(datum, "lon", None)
    if lat is None or lon is None:
        lat, lon = sun.DEFAULT_LAT, sun.DEFAULT_LON
    try:
        when = sh.when_utc(lon, year=_dt.date.today().year)
    except ValueError:
        return None
    d = sun.sun_direction(lat, lon, when)
    if d is None:
        return None
    if datum is not None and getattr(datum, "north", 0.0):
        x, y = datum.grid_to_local_xy(d[0], d[1])
        d = (x, y, d[2])
    return tuple(float(v) for v in d)


def camera_dict(camera) -> dict:
    """The viewport camera, in the terms the Blender script uses."""
    eye, target, up = camera.eye(), camera.target, camera.up_vector()
    half_h = camera.distance * math.tan(math.radians(camera.fov_deg) / 2.0)
    return {
        "eye": [eye.x(), eye.y(), eye.z()],
        "target": [target.x(), target.y(), target.z()],
        "up": [up.x(), up.y(), up.z()],
        "perspective": bool(camera.perspective),
        "fov_deg": float(camera.fov_deg),
        "half_height": float(half_h),
        "near": float(min(getattr(camera, "znear", 0.1),
                          max(camera.distance * 0.02, 1e-4))),
        "far": float(getattr(camera, "zfar", 1e5)),
    }


def ground_dict(scene) -> Optional[dict]:
    """A matte ground under the model to catch its shadow, as the viewport
    does: at the model's foot (or z = 0), a few times the model's size."""
    lo, hi = scene.bounds()
    if lo is None:
        return None
    size = max(hi.x() - lo.x(), hi.y() - lo.y(), 1.0)
    # Big enough that its edge sits past the horizon, not across the view.
    return {"z": min(lo.z(), 0.0) - 0.002, "size": max(size * 200.0, 4000.0),
            "color": [0.42, 0.42, 0.40]}


# ---- Ambience and lights --------------------------------------------------------

#: Day = the sun of the Shadows panel; night = no sun, a dark sky and the
#: user's lights; overcast = no sun, a bright even sky, soft shadows.
AMBIENCES = ("day", "night", "overcast")
#: Exposure per ambience: a daylit scene washes out under AgX at 0, a night
#: lit by lamps does not.
EXPOSURE = {"day": -0.6, "night": 0.0, "overcast": -0.3}

LIGHT_KINDS = ("point", "spot")
#: A light's colour is its temperature, from a candle to a blue sky.
MIN_KELVIN, MAX_KELVIN = 1800, 10000
#: The three names the first version stored (and still reads): warm ≈ a
#: street or house lamp, neutral, cool ≈ a daylight LED.
NAMED_KELVIN = {"warm": 2700, "neutral": 4000, "cool": 6500}
DEFAULT_KELVIN = 2700
#: Watts in Blender's terms, a sensible start for each kind.
DEFAULT_POWER = {"point": 400.0, "spot": 1500.0}


def kelvin_to_rgb(kelvin: float) -> tuple:
    """The colour of a light at ``kelvin`` (black-body, Tanner Helland's
    fit), scaled so its brightest channel is 1 — the power sets how much."""
    t = max(1000.0, min(40000.0, float(kelvin))) / 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * (t - 60) ** -0.1332047592
        g = 288.1221695283 * (t - 60) ** -0.0755148492
        b = 255.0
    rgb = [max(0.0, min(255.0, c)) / 255.0 for c in (r, g, b)]
    top = max(rgb) or 1.0
    return tuple(round(c / top, 4) for c in rgb)


#: Light colours by name, kept for the first version's files and tests.
LIGHT_COLORS = {k: kelvin_to_rgb(v) for k, v in NAMED_KELVIN.items()}


def aim_from_angles(heading_deg: float, tilt_deg: float) -> list:
    """A spot's direction from its heading (0° = north, +Y, clockwise, like
    a compass) and its tilt below the horizon (90° = straight down)."""
    h, t = math.radians(heading_deg), math.radians(tilt_deg)
    return [math.cos(t) * math.sin(h), math.cos(t) * math.cos(h),
            -math.sin(t)]


def angles_from_aim(d) -> tuple:
    """``(heading, tilt)`` in degrees for a direction — the inverse of
    :func:`aim_from_angles`; a spot aiming straight down keeps heading 0."""
    x, y, z = (float(v) for v in d)
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    tilt = math.degrees(math.asin(max(-1.0, min(1.0, -z / n))))
    heading = (math.degrees(math.atan2(x, y)) % 360.0
               if math.hypot(x, y) > 1e-9 else 0.0)
    return round(heading, 1), round(tilt, 1)


def clean_lights(raw) -> list:
    """The document's lights, validated: whatever a hand-edited or older
    file holds, only well-formed entries reach the job."""
    out = []
    for lt in raw if isinstance(raw, list) else []:
        try:
            kind = lt.get("kind", "point")
            if kind not in LIGHT_KINDS:
                continue
            pos = [float(v) for v in lt["pos"]][:3]
            d = [float(v) for v in lt.get("dir", (0.0, 0.0, -1.0))][:3]
            power = float(lt.get("power", DEFAULT_POWER[kind]))
            angle = float(lt.get("angle", 60.0))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if len(pos) != 3 or not all(math.isfinite(v) for v in pos + d):
            continue
        if math.hypot(*d) < 1e-9:
            d = [0.0, 0.0, -1.0]
        # The temperature is what the panel sets; a colour name (the first
        # version) maps to one, and a plain RGB from a hand-edited file is
        # kept as it is.
        kelvin = lt.get("kelvin")
        color = lt.get("color")
        rgb = None
        try:
            if kelvin is not None:
                kelvin = int(max(MIN_KELVIN, min(MAX_KELVIN, float(kelvin))))
            elif isinstance(color, str) or color is None:
                kelvin = NAMED_KELVIN.get(color or "warm", DEFAULT_KELVIN)
            else:
                rgb = tuple(max(0.0, min(1.0, float(c))) for c in color[:3])
                if len(rgb) != 3:
                    rgb, kelvin = None, DEFAULT_KELVIN
        except (TypeError, ValueError):
            rgb, kelvin = None, DEFAULT_KELVIN
        if rgb is None:
            rgb = kelvin_to_rgb(kelvin)
        out.append({
            "kind": kind, "pos": pos, "dir": d, "kelvin": kelvin,
            "color": list(rgb),
            "power": max(0.0, min(power, 1e6)),
            "angle": max(1.0, min(angle, 179.0)),
            "on": bool(lt.get("on", True)),
            "name": str(lt.get("name", "")),
        })
    return out


def write_job(scene, camera, work: Path, *, engine: str = "eevee",
              quality: int = 1, width: int = 1600, height: int = 900,
              ground: bool = True, keep_blend: bool = False,
              ambience: str = "day", lights=(),
              sun_scale: float = 1.0, serve: bool = False) -> Path:
    """Export the model and write ``job.json`` in ``work``; returns its path.
    ``lights`` are the document's (:func:`clean_lights`); the ones switched
    off stay out. ``sun_scale`` brightens or dims the day's sun (1 = as
    measured for a clear day). ``serve`` = Blender builds the scene and
    waits for cameras (:func:`sync_request`) instead of rendering once."""
    from formats.gltf import save_glb
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}")
    if ambience not in AMBIENCES:
        raise ValueError(f"unknown ambience {ambience!r}")
    work.mkdir(parents=True, exist_ok=True)
    glb = work / "model.glb"

    def toward(anchor):
        # As the viewport turns them (views.viewport._faceme_dir): to the
        # eye in perspective, along the view in a parallel projection.
        if camera.perspective:
            return camera.eye() - anchor
        return camera.eye() - camera.target

    save_glb(scene, glb, face_me=toward)
    job = {
        "glb": str(glb),
        "output": str(work / "render.png"),
        "blend": str(work / "render.blend") if keep_blend else None,
        "width": int(width), "height": int(height),
        "engine": engine,
        "samples": SAMPLES[engine][max(0, min(2, int(quality)))],
        "camera": camera_dict(camera),
        "ambience": ambience,
        "exposure": EXPOSURE[ambience],
        "sun": sun_toward(scene) if ambience == "day" else None,
        "sun_strength": 3.0 * max(0.0, min(float(sun_scale), 4.0)),
        "lights": [lt for lt in clean_lights(list(lights)) if lt["on"]],
        "ground": ground_dict(scene) if ground else None,
    }
    if serve:
        job["serve"] = True
        job["blend"] = None
    path = work / "job.json"
    path.write_text(json.dumps(job, indent=2), encoding="utf-8")
    return path


def work_base() -> Path:
    """Where each render's folder goes. Blender runs OUTSIDE the Flatpak
    sandbox, so there it must be a folder the host sees at the same path:
    the real ``~/.cache`` (the sandbox's own cache lives under
    ``~/.var/app``, which Blender's own Flatpak cannot read)."""
    if in_flatpak():
        return Path.home() / ".cache" / "IngeTrazo" / "render"
    from PySide6.QtCore import QStandardPaths
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericCacheLocation)
    return Path(base) / "IngeTrazo" / "render"


def command(found: BlenderFound, job: Path) -> list:
    """The full argv: Blender in the background, without the user's startup
    file or add-ons, running our script on the job.

    The script always travels next to the job, a folder Blender is sure to
    see. Its own path may exist only for IngeTrazo: inside our Flatpak
    (``/app/ingetrazo/…``, «Python file … could not be opened»), or under
    the AppImage's ``/tmp/.mount_…`` when Blender is the Flathub one, whose
    sandbox sees the home folder but not our /tmp."""
    import shutil
    script = job.parent / render_script().name
    shutil.copyfile(render_script(), script)
    return [*found.command, "-b", "--factory-startup",
            "--python", str(script), "--", str(job)]


# ---- Sync with the view ----------------------------------------------------------

#: A synced image is a draft: small and few samples, so it is back within a
#: second or two of the camera stopping. Render gives the final one.
SYNC_WIDTH = 960
SYNC_SAMPLES = {"eevee": 8, "cycles": 16}
#: How long the camera must rest before a synced render starts (ms).
SYNC_REST_MS = 700


def sync_request(camera, output, width: int, height: int,
                 engine: str = "eevee") -> str:
    """One line for a serving Blender: render this camera to ``output``."""
    return json.dumps({"camera": camera_dict(camera), "output": str(output),
                       "width": int(width), "height": int(height),
                       "samples": SYNC_SAMPLES.get(engine, 8)}) + "\n"


def camera_key(camera) -> tuple:
    """What a synced image depends on in the camera, rounded so that a
    redraw with the camera untouched never asks for a new one."""
    d = camera_dict(camera)
    return (tuple(round(v, 3) for v in d["eye"] + d["target"] + d["up"]),
            d["perspective"], round(d["fov_deg"], 2),
            round(d["half_height"], 3))


# ---- Progress -----------------------------------------------------------------

_SAMPLES_RE = (re.compile(r"Sample (\d+)\s*/\s*(\d+)"),          # Cycles
               re.compile(r"Rendering (\d+)\s*/\s*(\d+) samples"))  # EEVEE


def progress_of(line: str) -> Optional[float]:
    """0..1 from a line of Blender's output, when it says how far it is."""
    for rx in _SAMPLES_RE:
        m = rx.search(line)
        if m:
            done, total = int(m.group(1)), int(m.group(2))
            if total > 0:
                return max(0.0, min(1.0, done / total))
    return None
