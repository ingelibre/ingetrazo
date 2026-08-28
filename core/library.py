# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The online component library: an index of models the tray browses, and the
files it downloads when you pick one.

Shipping the whole catalogue inside the app was never an option — the Sweet
Home 3D libraries are ~1500 models and 160 MB, for pieces a given drawing
will never use. So the app carries a handful and reads the rest from
``ingetrazo.com``: a small ``index.json`` describes every model, each has a
128 px thumbnail, and the model itself — its OBJ with the textures and the
licence beside it, zipped — is fetched only when someone clicks it. Browsing
costs kilobytes.

Everything lands in a cache under the app's data folder, so the second time
there is no network at all. And nothing here raises on a network problem:
each call returns what it has (a cached copy) or ``None``, and the tray says
so rather than the app failing because a server is down. Working offline is
one of this program's promises.

``$INGETRAZO_LIBRARY`` overrides the base URL — a ``file://`` URL or a plain
directory path both work, which is how the library is tested and how a
mirror would be pointed at.

Previews are fetched by :func:`prefetch_thumbnails`, several at a time and
off the interface thread: these are 10 KB files whose cost is the round
trip, not the bytes, and one at a time they made browsing take seconds.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from core.version import USER_AGENT

#: Where the published library lives.
DEFAULT_URL = "https://ingetrazo.com/biblioteca"

#: A download that takes longer than this is a server that is not answering.
#: Short, because it is the UI thread waiting.
TIMEOUT = 20


def library_url() -> str:
    """The base URL (or directory) the library is read from."""
    return (os.environ.get("INGETRAZO_LIBRARY") or DEFAULT_URL).rstrip("/")


def library_cache() -> Path:
    """Where downloads are kept. Same home as the texture cache, and just as
    disposable: deleting it costs a re-download, never a drawing."""
    from core.texture import texture_cache_root
    return texture_cache_root().parent / "library"


def _get(rel: str) -> bytes | None:
    """The bytes of ``rel`` under the library base, or ``None``."""
    base = library_url()
    if "://" not in base:                      # a plain path: read it directly
        p = Path(base) / rel
        try:
            return p.read_bytes()
        except OSError:
            return None
    url = base + "/" + urllib.parse.quote(rel)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _cached(rel: str, refresh: bool = False) -> Path | None:
    """``rel`` as a local file, downloading it if it is not cached yet.
    ``None`` when it is neither cached nor reachable."""
    dst = library_cache() / rel
    if dst.is_file() and not refresh:
        return dst
    data = _get(rel)
    if data is None:
        return dst if dst.is_file() else None
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(dst)                       # atomic: no half file is ever read
    except OSError:
        return None
    return dst


def index(refresh: bool = False) -> list:
    """Every model in the library as a list of entries, or ``[]``.

    An entry carries ``id``, ``nombre``, ``categoria``, ``obj``, its real
    size in centimetres (``cm``) and its ``licencia``/``autor`` — the app has
    to be able to say who made a model and under what terms, because the
    collections mix public domain with attribution and copyleft.
    """
    p = _cached("index.json", refresh)
    if p is None:
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("modelos", [])
    except (OSError, ValueError):
        return []


def thumbnail(ident: str) -> Path | None:
    """The 128 px preview of a model, downloading it if need be. Blocks —
    see :func:`prefetch_thumbnails` for the browsing path."""
    return _cached("miniaturas/%s.png" % ident)


def cached_thumbnail(ident: str) -> Path | None:
    """The preview if it is ALREADY on disk, else ``None``. Never touches
    the network, so the tray can paint what it has without waiting."""
    p = library_cache() / ("miniaturas/%s.png" % ident)
    return p if p.is_file() else None


#: Downloads run this many at a time. These are 10 KB files: the cost is
#: not the bandwidth, it is the round trip — ~430 ms each, so one after
#: another a screenful of previews took 21 s. Measured against the live
#: site, a screen of 35 fills in 1.8 s with 8 at a time, 1.1 s with 16 and
#: 0.9 s with 24. Sixteen is where it stops being worth it: the last third
#: buys 0.2 s and costs a poor connection two dozen sockets fighting each
#: other. A browser opens six per host; these are far smaller requests.
_WORKERS = 16

_pool = None
_inflight: set = set()
_lock = threading.Lock()


def prefetch_thumbnails(idents) -> None:
    """Warm the cache for ``idents`` in the background.

    The tray calls this and paints whatever has landed; nothing here blocks
    the interface, and a preview that never arrives costs a blank square,
    not a frozen window. Ids already cached or already being fetched are
    skipped, so calling it every tick with the same screenful is free.
    """
    global _pool
    wanted = []
    with _lock:
        for ident in idents:
            if not ident or ident in _inflight:
                continue
            if cached_thumbnail(ident) is not None:
                continue
            _inflight.add(ident)
            wanted.append(ident)
        if not wanted:
            return
        if _pool is None:
            from concurrent.futures import ThreadPoolExecutor
            _pool = ThreadPoolExecutor(max_workers=_WORKERS,
                                       thread_name_prefix="library")
    for ident in wanted:
        _pool.submit(_fetch_thumb, ident)


def _fetch_thumb(ident: str) -> None:
    try:
        thumbnail(ident)
    except Exception:  # noqa: BLE001 — a preview is never worth a crash
        pass
    finally:
        with _lock:
            _inflight.discard(ident)


def model_dir(ident: str) -> Path | None:
    """The model's folder, downloading and unpacking it the first time.

    The zip holds the OBJ next to the images its MTL names, so unpacking it
    whole is what lets the importer resolve them.
    """
    out = library_cache() / "modelos" / ident
    if out.is_dir() and any(out.iterdir()):
        return out
    z = _cached("modelos/%s.zip" % ident)
    if z is None:
        return None
    try:
        out.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(z) as zf:
            for m in zf.namelist():
                # Flat by construction, but never trust an archive's names.
                name = Path(m).name
                if name:
                    (out / name).write_bytes(zf.read(m))
    except (OSError, zipfile.BadZipFile):
        return None
    return out


def model_matrix(entry: dict, obj: Path) -> tuple:
    """The 3x3 that puts a catalogue model where this app expects it.

    A Sweet Home 3D model is not used as its OBJ stands. The catalogue turns
    it by its own matrix and then stretches it to the width/depth/height it
    declares — a quarter of these files are written in arbitrary units, so a
    handrail whose OBJ is 3 cm across is a 126 cm handrail. Reproducing both
    steps is what makes a piece arrive the size the tray promised, and the
    same way up as its thumbnail.

    So: turn by the catalogue's rotation, fit the result to the declared
    size, and finally stand it up (the file is Y-up, this app is Z-up).
    Returns row-major, ready for :func:`formats.obj.load_obj`.
    """
    from formats.obj import Y_UP_TO_Z_UP

    rot = entry.get("rot") or ()
    try:
        r = [float(v) for v in rot]
    except (TypeError, ValueError):
        r = []
    if len(r) != 9:
        r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]

    # The turned model's size — measured over the vertices the faces
    # actually use. Several of these files carry leftover points no face
    # references (a bed with a stray vertex a metre above it), and sizing to
    # those would land the piece at half the size the catalogue promised.
    verts: list = []
    used: set = set()
    try:
        for line in obj.read_text(errors="replace").splitlines():
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "v" and len(parts) >= 4:
                try:
                    verts.append((float(parts[1]), float(parts[2]),
                                  float(parts[3])))
                except ValueError:
                    verts.append(None)
            elif parts[0] == "f":
                for tok in parts[1:]:
                    try:
                        raw = int(tok.split("/")[0])
                    except ValueError:
                        continue
                    used.add(raw - 1 if raw > 0 else len(verts) + raw)
    except OSError:
        pass
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for i in (used or range(len(verts))):
        p3 = verts[i] if 0 <= i < len(verts) else None
        if p3 is None:
            continue
        x, y, z = p3
        for k in range(3):
            v = r[3 * k] * x + r[3 * k + 1] * y + r[3 * k + 2] * z
            lo[k] = min(lo[k], v)
            hi[k] = max(hi[k], v)

    # The catalogue lists width, depth and height; in the file's Y-up space
    # those are X, Z and Y. Centimetres to the metres the app works in.
    try:
        w, d, h = (float(v) / 100.0 for v in entry.get("cm") or ())
    except (TypeError, ValueError):
        w = d = h = 0.0
    want = (w, h, d)
    sc = [1.0, 1.0, 1.0]
    for k in range(3):
        ext = hi[k] - lo[k]
        if want[k] > 0 and ext > 1e-9:
            sc[k] = want[k] / ext
    # A flat axis (a pane of glass) has no size to fit, so it borrows the
    # scale of the others rather than collapsing or blowing up.
    good = [v for k, v in enumerate(sc) if hi[k] - lo[k] > 1e-9 and want[k] > 0]
    fallback = sum(good) / len(good) if good else 0.01
    for k in range(3):
        if not (hi[k] - lo[k] > 1e-9 and want[k] > 0):
            sc[k] = fallback

    # Z_UP · diag(sc) · rotation, all 3x3 row-major.
    out = []
    for i in range(3):
        for j in range(3):
            out.append(sum(Y_UP_TO_Z_UP[3 * i + k] * sc[k] * r[3 * k + j]
                           for k in range(3)))
    return tuple(out)


def model_file(entry: dict) -> Path | None:
    """The OBJ of ``entry``, ready to import, or ``None``."""
    d = model_dir(entry.get("id", ""))
    if d is None:
        return None
    obj = d / entry.get("obj", "")
    if obj.is_file():
        return obj
    found = sorted(d.glob("*.obj"))
    return found[0] if found else None
