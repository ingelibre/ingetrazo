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
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

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
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
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
    """The 128 px preview of a model."""
    return _cached("miniaturas/%s.png" % ident)


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
