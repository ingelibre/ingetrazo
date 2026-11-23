# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""360° panoramas: six square views from one eye, the faces of a cube,
joined into one equirectangular picture — twice as wide as tall, the
longitude across and the latitude down — which panorama viewers turn
around the eye.

No Qt here: the faces come in as numpy arrays with the rotation of the
camera that took each one, so the joining is tested with synthetic faces.
``views.panorama_export`` renders them and writes the file.
"""
from __future__ import annotations

import math
import struct
import zlib

import numpy as np

#: The widths offered (the height is half), from the lowest a panorama
#: viewer shows without blur on a phone; ``DEFAULT_WIDTH`` is chosen first.
QUALITIES = ((2048, "2K"), (4096, "4K"), (6144, "6K"), (8192, "8K"))
MIN_WIDTH = QUALITIES[0][0]
DEFAULT_WIDTH = 4096

#: A face's border beyond its 90°, as a share of its side: the joining
#: reads pixels a little past each edge, and a screen-space effect (the
#: ambient occlusion) has room there to fade out of view.
FACE_MARGIN = 0.03

#: Rows of the panorama worked out at a time (keeps an 8K picture to a few
#: hundred megabytes of temporaries).
_CHUNK_ROWS = 128


def panorama_size(width: int) -> tuple[int, int]:
    """``(width, height)`` of a panorama about ``width`` wide: never under
    :data:`MIN_WIDTH`, even, and twice as wide as tall."""
    w = max(int(width), MIN_WIDTH)
    w += w % 2
    return w, w // 2


def face_size(width: int) -> int:
    """The side in pixels of the 90° part of each face for a panorama
    ``width`` wide: at the middle of a face, as many pixels per degree as
    the panorama has (``width / π``), rounded up to a multiple of 8."""
    return int(math.ceil(width / math.pi / 8.0)) * 8


def face_render(side: int) -> tuple[int, float]:
    """The size each face is rendered at and its field of view in degrees:
    ``side`` pixels for the 90° plus :data:`FACE_MARGIN` on every edge."""
    margin = max(4, int(math.ceil(side * FACE_MARGIN)))
    full = side + 2 * margin
    return full, math.degrees(2.0 * math.atan(full / side))


def heading_basis(forward) -> np.ndarray:
    """The panorama's frame for a camera looking along ``forward``: columns
    front, right and up in the world. The middle of the picture is the
    level heading of ``forward``, the up is the world's Z."""
    f = np.array([float(forward[0]), float(forward[1]), 0.0])
    n = float(np.hypot(f[0], f[1]))
    f = f / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])
    up = np.array([0.0, 0.0, 1.0])
    right = np.cross(f, up)
    return np.stack([f, right, up], axis=1)


def face_directions(basis: np.ndarray) -> list:
    """The six view directions (world) — front, right, back, left, up and
    down — of the panorama frame ``basis``."""
    f, r, u = basis[:, 0], basis[:, 1], basis[:, 2]
    return [f, r, -f, -r, u, -u]


def directions(width: int, height: int, rows: slice,
               basis: np.ndarray) -> np.ndarray:
    """The world direction (unit) through the middle of each pixel of the
    panorama rows ``rows``, shape ``(n_rows, width, 3)``. Longitude goes
    from -180° at the left edge to +180° at the right, 0 in the middle
    (the front, turning right); latitude from +90° at the top."""
    ys = np.arange(height, dtype=np.float64)[rows]
    lat = math.pi / 2.0 - (ys + 0.5) / height * math.pi
    lon = (np.arange(width, dtype=np.float64) + 0.5) / width * 2.0 * math.pi \
        - math.pi
    cl = np.cos(lat)[:, None]
    local = np.stack(np.broadcast_arrays(cl * np.cos(lon)[None, :],
                                         cl * np.sin(lon)[None, :],
                                         np.sin(lat)[:, None]), axis=-1)
    return local @ basis.T


def _bilinear(img: np.ndarray, px: np.ndarray, py: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    px = np.clip(px, 0.0, w - 1.0)
    py = np.clip(py, 0.0, h - 1.0)
    x0 = np.minimum(px.astype(np.int64), w - 2)
    y0 = np.minimum(py.astype(np.int64), h - 2)
    fx = (px - x0)[:, None]
    fy = (py - y0)[:, None]
    a = img[y0, x0].astype(np.float32)
    b = img[y0, x0 + 1].astype(np.float32)
    c = img[y0 + 1, x0].astype(np.float32)
    d = img[y0 + 1, x0 + 1].astype(np.float32)
    top = a + (b - a) * fx
    bottom = c + (d - c) * fx
    return top + (bottom - top) * fy


def equirectangular(faces, width: int, basis: np.ndarray,
                    side: int) -> np.ndarray:
    """Join ``faces`` into a panorama ``width`` × ``width / 2``.

    ``faces`` is a list of ``(rotation, image)``: ``rotation`` the 3×3
    world-to-camera rotation of the view that took it (rows: the camera's
    right, up and back — OpenGL's eye space, looking down -Z) and ``image``
    an ``(n, n, channels)`` uint8 array, row 0 at the top, whose middle
    ``side`` pixels span exactly 90° (:func:`face_render`). Each pixel of
    the panorama takes the face its direction is deepest in, sampled
    bilinearly. ``basis`` is the panorama's frame (:func:`heading_basis`)."""
    width, height = panorama_size(width)
    rots = np.stack([np.asarray(r, dtype=np.float64) for r, _ in faces])
    images = [np.asarray(img) for _, img in faces]
    channels = images[0].shape[2]
    out = np.empty((height, width, channels), dtype=np.uint8)
    for start in range(0, height, _CHUNK_ROWS):
        rows = slice(start, min(start + _CHUNK_ROWS, height))
        d = directions(width, height, rows, basis).reshape(-1, 3)
        cam = np.einsum("fij,nj->fni", rots, d)          # (faces, n, 3)
        depth = -cam[:, :, 2]
        which = np.argmax(depth, axis=0)
        chunk = np.empty((d.shape[0], channels), dtype=np.float32)
        for k, img in enumerate(images):
            sel = np.nonzero(which == k)[0]
            if sel.size == 0:
                continue
            c = cam[k, sel]
            z = depth[k, sel]
            full = img.shape[0]
            scale = side / full            # tangent ±1 is the 90° edge
            u = c[:, 0] / z * scale
            v = c[:, 1] / z * scale
            px = (u + 1.0) * 0.5 * full - 0.5
            py = (1.0 - v) * 0.5 * full - 0.5
            chunk[sel] = _bilinear(img, px, py)
        out[rows] = np.clip(np.rint(chunk), 0, 255).astype(np.uint8).reshape(
            rows.stop - rows.start, width, channels)
    return out


# ---- The mark panorama viewers look for -------------------------------------

def xmp_packet(width: int, height: int) -> bytes:
    """The XMP that tells a viewer the picture is a full 360° × 180°
    equirectangular panorama (the open "GPano" photo-sphere properties)."""
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" '
        'xmlns:GPano="http://ns.google.com/photos/1.0/panorama/" '
        'GPano:UsePanoramaViewer="True" '
        'GPano:ProjectionType="equirectangular" '
        f'GPano:FullPanoWidthPixels="{width}" '
        f'GPano:FullPanoHeightPixels="{height}" '
        f'GPano:CroppedAreaImageWidthPixels="{width}" '
        f'GPano:CroppedAreaImageHeightPixels="{height}" '
        'GPano:CroppedAreaLeftPixels="0" '
        'GPano:CroppedAreaTopPixels="0"/>'
        '</rdf:RDF></x:xmpmeta>'
        '<?xpacket end="w"?>').encode("utf-8")


_XMP_JPEG_NS = b"http://ns.adobe.com/xap/1.0/\x00"


def jpeg_with_xmp(data: bytes, xmp: bytes) -> bytes:
    """``data`` (a JPEG file) with ``xmp`` in an APP1 segment, put after
    the JFIF header where readers look for it."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG file")
    payload = _XMP_JPEG_NS + xmp
    if len(payload) + 2 > 0xFFFF:
        raise ValueError("XMP too large for one JPEG segment")
    segment = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    at = 2
    if data[2:4] == b"\xff\xe0":                    # JFIF APP0 first
        at = 4 + struct.unpack(">H", data[4:6])[0]
    return data[:at] + segment + data[at:]


def png_with_xmp(data: bytes, xmp: bytes) -> bytes:
    """``data`` (a PNG file) with ``xmp`` in an ``iTXt`` chunk under the
    keyword XMP readers know, right after the header chunk."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    ihdr_len = struct.unpack(">I", data[8:12])[0]
    at = 8 + 12 + ihdr_len
    body = b"XML:com.adobe.xmp\x00\x00\x00\x00\x00" + xmp
    chunk = (struct.pack(">I", len(body)) + b"iTXt" + body
             + struct.pack(">I", zlib.crc32(b"iTXt" + body) & 0xFFFFFFFF))
    return data[:at] + chunk + data[at:]
