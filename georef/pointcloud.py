# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Point clouds: a laser scan or a photogrammetric cloud to model over.

What a terrestrial scanner or a drone flight gives back before anyone turns
it into a mesh: millions of loose points, each with its position and, often,
its colour and the strength of the laser return (intensity). The surveyor of
an existing building, a heritage façade or a site under construction traces
the model on top of them.

Display-only, like the photogrammetric mesh (``georef.photomesh``): a cloud
is **never** part of ``Scene.mesh``. Millions of points are reference data to
trace over, not topology (invariant #4). Everything here is NumPy arrays
ready for one GL upload, and the snap asks this module for the point under
the cursor.

READERS
    LAS 1.0–1.4, uncompressed, point formats 0–10 (the scanner's own
    format); PLY, text or binary (what photogrammetry and most scan tools
    export); and the plain text layouts — XYZ / TXT / CSV / PTS, with or
    without intensity and colour columns. Compressed LAZ and E57 are
    refused with a message that says what to convert to.

THE PRECISION RULE
    A scan in UTM sits millions of metres from the origin, where single
    precision only tells whole metres apart. Coordinates are read in double
    precision and, past ``formats.recenter.RECENTER_BEYOND_M``, one offset in
    whole metres is subtracted before they become float32 — the same rule
    every importer follows. The offset is kept on the cloud so the real
    position is never lost, and a second cloud of the same survey reuses it
    so the two line up.

BIG CLOUDS
    A scanner station gives tens of millions of points. The reader keeps at
    most ``max_points`` of them, spread evenly over the file (a fixed seed:
    the same file always gives the same cloud), and says how many it read
    in total so the user is told the cloud was thinned.
"""
from __future__ import annotations

import io
import re
import struct
from pathlib import Path

import numpy as np

#: Default cap on the points kept from one file. Five million points are
#: 80 MB on the GPU (position + colour) and draw at interactive rates on an
#: integrated graphics chip; a full station is thinned to that.
DEFAULT_MAX_POINTS = 5_000_000

#: File suffixes the importer accepts.
SUFFIXES = (".las", ".ply", ".xyz", ".txt", ".csv", ".pts")

#: Colour modes, in the order the panel lists them.
COLOR_MODES = ("rgb", "elevation", "intensity", "single")

#: Archive member holding a cloud's arrays (``{}`` is its index).
ENTRY = "pointclouds/cloud-{:02d}.npz"


class PointCloudError(ValueError):
    """A file that cannot be read as a point cloud; the message says why
    in words the user can act on.

    ``template`` is the English text with ``{name}`` fields and ``fields``
    their values, so the window can translate it (``tr(template,
    **fields)``); ``str()`` gives the English."""

    def __init__(self, template: str, **fields) -> None:
        self.template = template
        self.fields = fields
        super().__init__(template.format(**fields) if fields else template)


class PointCloud:
    """A point cloud placed in the scene's local frame.

    ``positions`` is ``(N, 3)`` float32 in local metres; ``colors`` is
    ``(N, 3)`` uint8 or ``None``; ``intensity`` is ``(N,)`` float32 in 0..1
    or ``None``. ``offset`` is the ``(x, y, z)`` in metres taken off the
    file's own coordinates (``None`` when it was read as it is)."""

    def __init__(self, positions, colors=None, intensity=None, *,
                 name: str = "", source=None, offset=None,
                 total_points: int | None = None) -> None:
        self.positions = np.ascontiguousarray(positions, dtype=np.float32)
        self.colors = (None if colors is None
                       else np.ascontiguousarray(colors, dtype=np.uint8))
        self.intensity = (None if intensity is None
                          else np.ascontiguousarray(intensity,
                                                    dtype=np.float32))
        self.name = name
        self.source = source            # provenance only, never resolved
        self.offset = None if offset is None else tuple(map(float, offset))
        self.total_points = int(total_points if total_points is not None
                                else len(self.positions))
        self.visible = True
        # A layer, exactly like a Group: hiding the layer hides the cloud
        # (``core.layers.layer_of`` reads this attribute).
        self.layer: str | None = None
        self.color_mode = "rgb" if self.colors is not None else "elevation"
        self.point_size = 2.0           # screen pixels
        #: Bumped whatever changes what the GPU holds (points or colours).
        self.revision = 0

    @property
    def point_count(self) -> int:
        return int(len(self.positions))

    @property
    def thinned(self) -> bool:
        return self.total_points > self.point_count

    def bounds(self):
        """``(lo, hi)`` as NumPy ``(3,)`` arrays, or ``(None, None)``."""
        if not self.point_count:
            return None, None
        return self.positions.min(axis=0), self.positions.max(axis=0)

    def effective_mode(self) -> str:
        """The colour mode actually drawn: a mode the file has no data for
        falls back to elevation rather than painting the cloud one flat
        colour nobody asked for."""
        mode = self.color_mode if self.color_mode in COLOR_MODES else "rgb"
        if mode == "rgb" and self.colors is None:
            return "elevation"
        if mode == "intensity" and self.intensity is None:
            return "elevation"
        return mode

    def display_colors(self) -> np.ndarray:
        """``(N, 3)`` uint8 colours for the current mode."""
        mode = self.effective_mode()
        n = self.point_count
        if mode == "rgb":
            return self.colors
        if mode == "single":
            return np.full((n, 3), (150, 150, 150), dtype=np.uint8)
        if mode == "intensity":
            v = _stretch(self.intensity)
            g = (60 + v * 195).astype(np.uint8)
            return np.stack([g, g, g], axis=1)
        return elevation_ramp(_stretch(self.positions[:, 2]))


# ---- Colour helpers ---------------------------------------------------------

#: Elevation ramp, low → high: deep blue, cyan, green, yellow, red.
_RAMP = np.array([(40, 60, 200), (40, 190, 230), (60, 200, 90),
                  (240, 220, 60), (220, 60, 40)], dtype=np.float32)


def _stretch(values) -> np.ndarray:
    """``values`` mapped onto 0..1 between their 2nd and 98th percentiles —
    a few stray points (a bird, the scanner's tripod) must not squash the
    whole ramp into one colour."""
    v = np.asarray(values, dtype=np.float32)
    if not len(v):
        return v
    lo, hi = np.percentile(v, (2.0, 98.0))
    if not hi > lo:
        return np.zeros(len(v), dtype=np.float32)
    return np.clip((v - lo) / (hi - lo), 0.0, 1.0)


def elevation_ramp(t) -> np.ndarray:
    """``(N,)`` values in 0..1 → ``(N, 3)`` uint8 colours on :data:`_RAMP`."""
    t = np.asarray(t, dtype=np.float32) * (len(_RAMP) - 1)
    i = np.clip(t.astype(np.int64), 0, len(_RAMP) - 2)
    f = (t - i)[:, None]
    rgb = _RAMP[i] * (1.0 - f) + _RAMP[i + 1] * f
    return np.clip(rgb + 0.5, 0, 255).astype(np.uint8)


def _colors_to_u8(rgb) -> np.ndarray | None:
    """Colour channels of any integer or float width → uint8, or ``None``
    when the file carries no colour (all zero)."""
    rgb = np.asarray(rgb)
    if not len(rgb):
        return None
    top = float(rgb.max())
    if top <= 0:
        return None
    if np.issubdtype(rgb.dtype, np.floating):
        scale = 255.0 if top <= 1.0 else (255.0 / 65535.0 if top > 255 else 1.0)
        return np.clip(rgb * scale + 0.5, 0, 255).astype(np.uint8)
    if top > 255:
        return (rgb.astype(np.uint32) >> 8).astype(np.uint8)
    return rgb.astype(np.uint8)


def _pick(total: int, max_points: int | None) -> np.ndarray | None:
    """Sorted indices of the points to keep, or ``None`` to keep all."""
    if not max_points or total <= max_points:
        return None
    rng = np.random.default_rng(0)
    return np.sort(rng.choice(total, size=int(max_points), replace=False))


# ---- LAS --------------------------------------------------------------------

#: Byte offset of the colour channels per LAS point format (``None``: none).
_LAS_RGB_AT = {0: None, 1: None, 2: 20, 3: 28, 4: None, 5: 28,
               6: None, 7: 30, 8: 30, 9: None, 10: 30}
#: Smallest record each point format can have.
_LAS_MIN_RECORD = {0: 20, 1: 28, 2: 26, 3: 34, 4: 57, 5: 63,
                   6: 30, 7: 36, 8: 38, 9: 59, 10: 67}


def read_las(path, max_points: int | None = DEFAULT_MAX_POINTS):
    """``(xyz float64, rgb uint8|None, intensity float32|None, total)``."""
    path = Path(path)
    with open(path, "rb") as f:
        head = f.read(375)
    if len(head) < 227 or head[:4] != b"LASF":
        raise PointCloudError("Not a LAS file.")
    minor = head[25]
    data_at = struct.unpack_from("<I", head, 96)[0]
    fmt_byte = head[104]
    record = struct.unpack_from("<H", head, 105)[0]
    count = struct.unpack_from("<I", head, 107)[0]
    if minor >= 4 and len(head) >= 255:
        count14 = struct.unpack_from("<Q", head, 247)[0]
        if count14:
            count = count14
    scale = np.array(struct.unpack_from("<3d", head, 131))
    offset = np.array(struct.unpack_from("<3d", head, 155))
    if fmt_byte & 0xC0 or path.suffix.lower() == ".laz":
        raise PointCloudError(
            "Compressed LAZ files are not supported yet. Convert it to an "
            "uncompressed LAS first (for example with the free laszip or "
            "PDAL tools).")
    fmt = fmt_byte & 0x3F
    if fmt not in _LAS_RGB_AT:
        raise PointCloudError("LAS point format {fmt} is not supported.",
                              fmt=fmt)
    if record < _LAS_MIN_RECORD[fmt]:
        raise PointCloudError("The LAS file is damaged (point record too "
                              "short).")
    size = path.stat().st_size
    count = int(min(count, max(0, (size - data_at) // record)))
    if count <= 0:
        raise PointCloudError("The file has no points.")
    raw = np.memmap(path, dtype=np.uint8, mode="r", offset=data_at,
                    shape=(count, record))
    keep = _pick(count, max_points)
    rows = raw if keep is None else raw[keep]
    rows = np.ascontiguousarray(rows)
    ints = rows[:, 0:12].copy().view("<i4").reshape(-1, 3)
    xyz = ints.astype(np.float64) * scale + offset
    intensity = rows[:, 12:14].copy().view("<u2").reshape(-1)
    intensity = (intensity.astype(np.float32) / 65535.0
                 if intensity.any() else None)
    rgb = None
    at = _LAS_RGB_AT[fmt]
    if at is not None:
        rgb = _colors_to_u8(
            rows[:, at:at + 6].copy().view("<u2").reshape(-1, 3))
    del raw
    return xyz, rgb, intensity, count


# ---- PLY --------------------------------------------------------------------

_PLY_TYPES = {"char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
              "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
              "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
              "float": "f4", "float32": "f4", "double": "f8",
              "float64": "f8"}
_PLY_RGB = (("red", "green", "blue"), ("r", "g", "b"),
            ("diffuse_red", "diffuse_green", "diffuse_blue"))
_PLY_INTENSITY = ("intensity", "scalar_intensity", "scalar_Intensity",
                  "reflectance")


def _ply_header(f):
    """``(format, [(element, count, [(name, type|('list', ct, it))])])``."""
    if f.readline().strip() != b"ply":
        raise PointCloudError("Not a PLY file.")
    fmt, elements = None, []
    while True:
        line = f.readline()
        if not line:
            raise PointCloudError("The PLY file is cut short.")
        words = line.decode("ascii", "replace").split()
        if not words or words[0] in ("comment", "obj_info"):
            continue
        if words[0] == "end_header":
            return fmt, elements
        if words[0] == "format":
            fmt = words[1]
        elif words[0] == "element":
            elements.append((words[1], int(words[2]), []))
        elif words[0] == "property" and elements:
            if words[1] == "list":
                elements[-1][2].append((words[4], ("list", words[2],
                                                   words[3])))
            else:
                elements[-1][2].append((words[2], words[1]))


def read_ply(path, max_points: int | None = DEFAULT_MAX_POINTS):
    """``(xyz float64, rgb uint8|None, intensity float32|None, total)``."""
    with open(path, "rb") as f:
        fmt, elements = _ply_header(f)
        vertex = next((e for e in elements if e[0] == "vertex"), None)
        if vertex is None or not vertex[1]:
            raise PointCloudError("The file has no points.")
        names = [p[0] for p in vertex[2]]
        if not all(c in names for c in "xyz"):
            raise PointCloudError("The PLY points have no x, y, z.")
        before = elements[:elements.index(vertex)]
        if fmt == "ascii":
            for _name, n, _props in before:
                for _ in range(n):
                    f.readline()
            text = b"".join(f.readline() for _ in range(vertex[1]))
            table = np.loadtxt(io.BytesIO(text), dtype=np.float64, ndmin=2)
            cols = {nm: table[:, i] for i, nm in enumerate(names)
                    if i < table.shape[1]}
        elif fmt in ("binary_little_endian", "binary_big_endian"):
            end = "<" if fmt == "binary_little_endian" else ">"
            if any(isinstance(t, tuple) for _, _, ps in before
                   for _, t in ps):
                raise PointCloudError(
                    "This PLY layout is not supported: save it with only "
                    "the points (x, y, z and colour).")
            for _name, n, props in before:
                f.seek(n * sum(np.dtype(_PLY_TYPES[t]).itemsize
                               for _, t in props), 1)
            if any(isinstance(t, tuple) for _, t in vertex[2]):
                raise PointCloudError(
                    "This PLY layout is not supported: save it with only "
                    "the points (x, y, z and colour).")
            dtype = np.dtype([(nm, end + _PLY_TYPES[t])
                              for nm, t in vertex[2]])
            data = np.fromfile(f, dtype=dtype, count=vertex[1])
            if len(data) < vertex[1]:
                raise PointCloudError("The PLY file is cut short.")
            cols = {nm: data[nm] for nm in names}
        else:
            raise PointCloudError("Unknown PLY format «{fmt}».", fmt=fmt)
    total = len(cols["x"])
    keep = _pick(total, max_points)

    def col(name):
        c = cols[name]
        return c if keep is None else c[keep]

    xyz = np.stack([col("x"), col("y"), col("z")], axis=1).astype(np.float64)
    rgb = None
    for trio in _PLY_RGB:
        if all(c in cols for c in trio):
            rgb = _colors_to_u8(np.stack([col(c) for c in trio], axis=1))
            break
    intensity = None
    for name in _PLY_INTENSITY:
        if name in cols:
            intensity = _stretch(col(name))
            break
    return xyz, rgb, intensity, total


# ---- Plain text: XYZ / TXT / CSV / PTS ---------------------------------------

def read_text(path, max_points: int | None = DEFAULT_MAX_POINTS):
    """``(xyz float64, rgb uint8|None, intensity float32|None, total)``.

    Columns: ``x y z``, ``x y z i``, ``x y z r g b`` or ``x y z i r g b``
    (the PTS layout), separated by spaces, tabs, commas or semicolons. A
    PTS file's leading point count and any header line are skipped."""
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", "replace")
    lines = text.splitlines()
    start = 0
    while start < len(lines):
        words = _split(lines[start])
        if len(words) >= 3 and all(_is_number(w) for w in words[:3]):
            break
        start += 1
    if start >= len(lines):
        raise PointCloudError("No x y z rows found in the file.")
    first = lines[start]
    semicolon = ";" in first
    body = "\n".join(lines[start:])
    if semicolon:
        body = body.replace(",", ".").replace(";", " ")
    else:
        body = body.replace(",", " ")
    width = len(body.split("\n", 1)[0].split())
    try:
        table = np.loadtxt(io.StringIO(body), dtype=np.float64, ndmin=2,
                           usecols=range(min(width, 7)))
    except ValueError as exc:
        raise PointCloudError("A row could not be read: {error}",
                              error=str(exc)) from exc
    total = len(table)
    keep = _pick(total, max_points)
    if keep is not None:
        table = table[keep]
    xyz = table[:, :3]
    rgb = intensity = None
    w = table.shape[1]
    if w >= 7:
        intensity = _stretch(table[:, 3])
        rgb = _colors_to_u8(table[:, 4:7])
    elif w == 6:
        rgb = _colors_to_u8(table[:, 3:6])
    elif w in (4, 5):
        intensity = _stretch(table[:, 3])
    return xyz, rgb, intensity, total


def _split(line: str) -> list[str]:
    return [w for w in re.split(r"[\s,;]+", line.strip()) if w]


def _is_number(word: str) -> bool:
    try:
        float(word)
    except ValueError:
        return False
    return True


# ---- Loading and placing ----------------------------------------------------

def read_file(path, max_points: int | None = DEFAULT_MAX_POINTS):
    """Dispatch on the suffix; ``(xyz, rgb, intensity, total)``."""
    suffix = Path(path).suffix.lower()
    if suffix in (".las", ".laz"):
        return read_las(path, max_points)
    if suffix == ".ply":
        return read_ply(path, max_points)
    if suffix in (".xyz", ".txt", ".csv", ".pts"):
        return read_text(path, max_points)
    if suffix == ".e57":
        raise PointCloudError(
            "E57 files are not supported yet. Export the scan as LAS, PLY "
            "or PTS from the scanner's software.")
    raise PointCloudError("«{suffix}» is not a point cloud format.",
                          suffix=suffix)


def load_point_cloud(path, max_points: int | None = DEFAULT_MAX_POINTS,
                     offset=None) -> PointCloud:
    """Read ``path`` and place it in local metres.

    ``offset``: the one another cloud of the document already uses — a
    second scan of the same survey is moved by the same amount so the two
    line up. Without one, the file decides (:func:`formats.recenter.
    survey_offset`)."""
    from formats.recenter import survey_offset

    xyz, rgb, intensity, total = read_file(path, max_points)
    finite = np.isfinite(xyz).all(axis=1)
    if not finite.all():
        xyz = xyz[finite]
        rgb = None if rgb is None else rgb[finite]
        intensity = None if intensity is None else intensity[finite]
    if not len(xyz):
        raise PointCloudError("The file has no points.")
    lo, hi = xyz.min(axis=0), xyz.max(axis=0)
    own = survey_offset(tuple(map(float, lo)), tuple(map(float, hi)))
    if offset is None or own is None:
        offset = own
    if offset is not None:
        xyz = xyz - np.asarray(offset, dtype=np.float64)
    return PointCloud(xyz, rgb, intensity, name=Path(path).stem,
                      source=str(path), offset=offset, total_points=total)


# ---- Snapping ---------------------------------------------------------------

def nearest_screen_point(positions, mvp, width: float, height: float,
                         px: float, py: float, radius: float = 8.0,
                         keep=None):
    """Index of the cloud point under the cursor, or ``None``.

    ``mvp`` is the ``(4, 4)`` row-major projection·view. Of the points
    within ``radius`` pixels, the ones nearest the eye win (the scanned
    surface in front, not the wall behind it seen through the gaps), and
    of those the one closest to the cursor. ``keep(points) → bool mask``
    drops points a section cut hides."""
    pts = np.asarray(positions, dtype=np.float32)
    if not len(pts):
        return None
    m = np.asarray(mvp, dtype=np.float64)
    # A cheap screen box first: only rows near the cursor pay the divide.
    clip = pts @ m[:, :3].T.astype(np.float32) + m[:, 3].astype(np.float32)
    w = clip[:, 3]
    front = w > 1e-6
    with np.errstate(divide="ignore", invalid="ignore"):
        sx = (clip[:, 0] / w * 0.5 + 0.5) * width
        sy = (1.0 - (clip[:, 1] / w * 0.5 + 0.5)) * height
    near = (front & (np.abs(sx - px) <= radius)
            & (np.abs(sy - py) <= radius))
    idx = np.nonzero(near)[0]
    if not len(idx):
        return None
    d2 = (sx[idx] - px) ** 2 + (sy[idx] - py) ** 2
    inside = d2 <= radius * radius
    idx, d2 = idx[inside], d2[inside]
    if keep is not None and len(idx):
        ok = np.asarray(keep(pts[idx]), dtype=bool)
        idx, d2 = idx[ok], d2[ok]
    if not len(idx):
        return None
    depth = w[idx]
    nearest = float(depth.min())
    front_layer = depth <= nearest * 1.03 + 0.02
    idx, d2 = idx[front_layer], d2[front_layer]
    return int(idx[int(np.argmin(d2))])


# ---- Storing in the document ------------------------------------------------

def pack_clouds(clouds) -> tuple[list, dict]:
    """``(json_metadata, blobs)`` for storing ``clouds`` in an ``.igz``."""
    meta, blobs = [], {}
    for i, cloud in enumerate(clouds):
        if not cloud.point_count:
            continue
        member = ENTRY.format(i)
        arrays = {"positions": cloud.positions}
        if cloud.colors is not None:
            arrays["colors"] = cloud.colors
        if cloud.intensity is not None:
            arrays["intensity"] = cloud.intensity
        buffer = io.BytesIO()
        np.savez_compressed(buffer, **arrays)
        blobs[member] = buffer.getvalue()
        entry = {"data": member, "name": cloud.name,
                 "visible": bool(cloud.visible), "layer": cloud.layer,
                 "color_mode": cloud.color_mode,
                 "point_size": float(cloud.point_size),
                 "total_points": int(cloud.total_points)}
        if cloud.offset is not None:
            entry["offset"] = list(cloud.offset)
        if cloud.source:
            entry["source"] = str(cloud.source)
        meta.append(entry)
    return meta, blobs


def unpack_clouds(meta, read_blob) -> list:
    """Rebuild the stored clouds from ``meta`` plus ``read_blob(member)``.

    A damaged block is left out, never a reason to refuse the document."""
    clouds = []
    for entry in meta or ():
        try:
            raw = read_blob(entry.get("data", ""))
            if not raw:
                continue
            with np.load(io.BytesIO(raw)) as data:
                positions = data["positions"]
                colors = data["colors"] if "colors" in data else None
                intensity = (data["intensity"] if "intensity" in data
                             else None)
            if positions.ndim != 2 or positions.shape[1] != 3:
                continue
            cloud = PointCloud(positions, colors, intensity,
                               name=str(entry.get("name", "")),
                               source=entry.get("source"),
                               offset=entry.get("offset"),
                               total_points=entry.get("total_points"))
        except Exception:  # noqa: BLE001 — a broken block is not a broken document
            continue
        cloud.visible = bool(entry.get("visible", True))
        cloud.layer = entry.get("layer")
        mode = entry.get("color_mode")
        if mode in COLOR_MODES:
            cloud.color_mode = mode
        try:
            cloud.point_size = min(12.0, max(1.0, float(
                entry.get("point_size", 2.0))))
        except (TypeError, ValueError):
            pass
        clouds.append(cloud)
    return clouds
