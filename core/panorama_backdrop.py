# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A 360° panorama as the viewport's backdrop.

A style can carry an equirectangular picture (2:1, the whole sphere around
the camera): an ordinary JPG/PNG or a Radiance ``.hdr`` high dynamic range
image. The viewport looks it up per pixel by the direction of sight
(``resources/shaders/panorama.frag``), so it turns with the camera like a
real sky and stays put on zoom and pan — it lies at infinity.

Conventions, shared with the shader (:func:`direction_uv` is its mirror for
the tests):

* Z is up. The middle of the picture (``u = 0.5``) faces +Y — the green
  axis — and the picture runs left to right as the view turns clockwise
  seen from above, the way a panorama reads from inside.
* ``rotation`` (degrees) turns the picture counter-clockwise seen from above.
* ``v = 1`` is the zenith, the picture's top row.

A ``.hdr`` holds light values beyond white. It is brought to the screen
once, on load: ``exposure`` stops of gain, a filmic curve that rolls the
highlights off instead of clipping them, and the sRGB transfer. The result
is an 8-bit picture like any other; changing the exposure redoes only the
cheap last step (the decoded light values stay cached).
"""
from __future__ import annotations

import math
from collections import OrderedDict
from pathlib import Path

import numpy as np

#: The extensions the file dialog offers.
PANORAMA_SUFFIXES = (".hdr", ".jpg", ".jpeg", ".png")
#: The widest picture kept in memory and on the GPU: a 4K panorama shows a
#: 60° view at about 680 pixels, sharp on any common screen.
MAX_WIDTH = 4096
#: The exposure control's range, in stops.
EXPOSURE_RANGE = (-10.0, 10.0)

_RADIANCE_MAGIC = (b"#?RADIANCE", b"#?RGBE")


def panorama_label(path: str, limit: int = 24) -> str:
    """The picture's name as the user knows it: without the content-hash
    prefix the document cache adds (``9b6af3…-cielo.hdr`` → ``cielo.hdr``)
    and shortened in the middle when long, so the extension stays."""
    from core.texture import texture_file_name
    name = texture_file_name(Path(path).name)
    if len(name) <= limit:
        return name
    keep = limit - 1
    return name[:keep - keep // 2] + "…" + name[-(keep // 2):]


def is_hdr_bytes(head: bytes) -> bool:
    return bytes(head[:10]).startswith(_RADIANCE_MAGIC)


def is_hdr_file(path) -> bool:
    try:
        with open(path, "rb") as fh:
            return is_hdr_bytes(fh.read(10))
    except OSError:
        return False


# --- Radiance RGBE ---------------------------------------------------------

def read_hdr(data: bytes) -> np.ndarray:
    """Decode a Radiance ``.hdr`` file into float32 RGB, shape (H, W, 3),
    first row at the top. Reads the run-length scanlines every writer uses
    and the flat ones of the oldest files; only the standard ``-Y H +X W``
    orientation (the one panoramas come in)."""
    if not is_hdr_bytes(data):
        raise ValueError("not a Radiance HDR file")
    pos = 0
    fmt = None
    while True:                               # header: lines up to a blank
        end = data.find(b"\n", pos)
        if end < 0:
            raise ValueError("HDR header has no end")
        line = data[pos:end].strip()
        pos = end + 1
        if not line:
            break
        if line.startswith(b"FORMAT="):
            fmt = line[7:].strip()
    if fmt not in (None, b"32-bit_rle_rgbe"):
        raise ValueError("only RGBE HDR files are supported")
    end = data.find(b"\n", pos)
    parts = data[pos:end].split()
    pos = end + 1
    if len(parts) != 4 or parts[0] != b"-Y" or parts[2] != b"+X":
        raise ValueError("unsupported HDR orientation")
    height, width = int(parts[1]), int(parts[3])
    if not (0 < width <= 65536 and 0 < height <= 65536):
        raise ValueError("bad HDR size")
    rgbe = np.empty((height, width, 4), dtype=np.uint8)
    view = memoryview(data)
    for y in range(height):
        pos = _read_scanline(view, pos, width, rgbe[y])
    return _rgbe_to_float(rgbe)


def _read_scanline(view, pos: int, width: int, out: np.ndarray) -> int:
    """One scanline into ``out`` (W, 4); returns the position after it."""
    head = bytes(view[pos:pos + 4])
    if len(head) < 4:
        raise ValueError("HDR data ends early")
    rle = (8 <= width < 32768 and head[0] == 2 and head[1] == 2
           and not head[2] & 0x80)
    if not rle:
        # Flat pixels (the oldest files, or very narrow pictures).
        need = width * 4
        chunk = bytes(view[pos:pos + need])
        if len(chunk) < need:
            raise ValueError("HDR data ends early")
        out[:] = np.frombuffer(chunk, dtype=np.uint8).reshape(width, 4)
        return pos + need
    if (head[2] << 8 | head[3]) != width:
        raise ValueError("HDR scanline width mismatch")
    pos += 4
    line = bytearray(width)
    size = len(view)
    for channel in range(4):
        x = 0
        while x < width:
            if pos >= size:
                raise ValueError("HDR data ends early")
            count = view[pos]
            pos += 1
            if count > 128:                   # a run of one value
                count -= 128
                if x + count > width or pos >= size:
                    raise ValueError("bad HDR run")
                line[x:x + count] = bytes((view[pos],)) * count
                pos += 1
            else:                             # literal values
                if count == 0 or x + count > width or pos + count > size:
                    raise ValueError("bad HDR run")
                line[x:x + count] = view[pos:pos + count]
                pos += count
            x += count
        out[:, channel] = np.frombuffer(bytes(line), dtype=np.uint8)
    return pos


def _rgbe_to_float(rgbe: np.ndarray) -> np.ndarray:
    exponent = rgbe[..., 3].astype(np.int32)
    scale = np.where(exponent > 0,
                     np.ldexp(np.float32(1.0), exponent - (128 + 8)),
                     0.0).astype(np.float32)
    return rgbe[..., :3].astype(np.float32) * scale[..., None]


def write_hdr(rgb: np.ndarray) -> bytes:
    """Encode float RGB (H, W, 3) as a flat Radiance file — for the tests'
    synthetic panoramas and the sample model; the reader takes it back."""
    rgb = np.asarray(rgb, dtype=np.float32)
    height, width = rgb.shape[:2]
    peak = rgb.max(axis=2)
    mantissa, exponent = np.frexp(peak)
    scale = np.where(peak > 1e-32, mantissa * 256.0 / np.maximum(peak, 1e-32),
                     0.0)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    out[..., :3] = np.clip(rgb * scale[..., None], 0, 255).astype(np.uint8)
    out[..., 3] = np.where(peak > 1e-32, exponent + 128, 0).astype(np.uint8)
    header = (b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n"
              + f"-Y {height} +X {width}\n".encode("ascii"))
    return header + out.tobytes()


# --- To the screen ---------------------------------------------------------

def tone_map(rgb: np.ndarray, exposure: float = 0.0) -> np.ndarray:
    """Light values → 8-bit sRGB (H, W, 3): ``exposure`` stops of gain, then
    a filmic curve (a published fit of the common film response: values
    near 0.18 barely move, highlights roll off towards white)."""
    x = np.asarray(rgb, dtype=np.float32) * np.float32(2.0 ** float(exposure))
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    x = np.clip((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0)
    srgb = np.where(x <= 0.0031308, x * 12.92,
                    1.055 * np.power(x, 1.0 / 2.4) - 0.055)
    return (srgb * 255.0 + 0.5).astype(np.uint8)


def _shrink(pixels: np.ndarray, max_width: int) -> np.ndarray:
    """Halve by 2×2 averages until the picture is at most ``max_width``."""
    while pixels.shape[1] > max_width and pixels.shape[0] >= 2:
        h, w = pixels.shape[0] // 2 * 2, pixels.shape[1] // 2 * 2
        p = pixels[:h, :w].astype(np.float32)
        p = (p[0::2, 0::2] + p[1::2, 0::2] + p[0::2, 1::2] + p[1::2, 1::2]) / 4
        pixels = p
    return pixels


def _read_ldr(path: str, max_width: int) -> np.ndarray:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    image = QImage(path)
    if image.isNull():
        raise ValueError(f"cannot read the picture {Path(path).name}")
    if image.width() > max_width:
        image = image.scaledToWidth(max_width, Qt.SmoothTransformation)
    image = image.convertToFormat(QImage.Format_RGB888)
    w, h, stride = image.width(), image.height(), image.bytesPerLine()
    raw = np.frombuffer(image.constBits(), dtype=np.uint8,
                        count=stride * h).reshape(h, stride)
    return raw[:, :w * 3].reshape(h, w, 3).copy()


#: Decoded light values (HDR) or pixels (LDR) per file, the few most recent.
_DECODED: "OrderedDict[tuple, np.ndarray]" = OrderedDict()
_DECODED_KEEP = 2


def _file_key(path: str) -> tuple:
    p = Path(path)
    st = p.stat()
    return (str(p), st.st_mtime_ns, st.st_size)


def load_pixels(path: str, exposure: float = 0.0,
                max_width: int = MAX_WIDTH) -> np.ndarray:
    """The panorama ready for the GPU: uint8 RGB (H, W, 3), top row up.
    Raises ``OSError`` / ``ValueError`` for a file that cannot be read."""
    key = _file_key(path) + (max_width,)
    decoded = _DECODED.get(key)
    hdr = is_hdr_file(path)
    if decoded is None:
        if hdr:
            decoded = _shrink(read_hdr(Path(path).read_bytes()), max_width)
            decoded = decoded.astype(np.float32)
        else:
            decoded = _read_ldr(path, max_width)
        _DECODED[key] = decoded
        while len(_DECODED) > _DECODED_KEEP:
            _DECODED.popitem(last=False)
    else:
        _DECODED.move_to_end(key)
    if hdr:
        return tone_map(decoded, exposure)
    return decoded


# --- Directions ------------------------------------------------------------

def direction_uv(direction, rotation: float = 0.0) -> tuple[float, float]:
    """Where a direction of sight lands on the panorama, ``(u, v)`` in
    [0, 1) × [0, 1] — the shader's lookup, in Python for the tests."""
    x, y, z = (float(c) for c in direction)
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    x, y, z = x / n, y / n, z / n
    azimuth = math.atan2(y, x)
    centre = math.radians(90.0 + float(rotation))
    u = (0.5 - (azimuth - centre) / (2.0 * math.pi)) % 1.0
    v = 0.5 + math.asin(max(-1.0, min(1.0, z))) / math.pi
    return u, v
