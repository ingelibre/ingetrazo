#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Bring a Sweet Home 3D texture library (``.sh3t``) into the bundled one.

A ``.sh3t`` is a ZIP: a ``PluginTexturesCatalog*.properties`` catalogue plus
the images. What makes it worth importing is not the pictures — it is that
the catalogue declares **how big each one is in the real world**. A brick
image tiled at an arbitrary size reads as a mosaic; tiled at 1.00 x 0.60 m it
reads as brick. Our own procedural set already carries that, and this keeps
it true for the imported ones.

Writes ``resources/textures/library/<category>/<slug>.<ext>`` and rewrites
``resources/textures/library.json``, preserving the categories already there
and merging the new textures into them where the taxonomies meet.

The English name goes in the manifest and the tray translates it; the
Spanish the catalogue ships is appended to ``i18n/es.json`` so nothing has
to be typed twice.

Usage:  scripts/import_sh3t.py <biblioteca.sh3t> [<biblioteca.sh3t> …]
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEX = ROOT / "resources" / "textures"

#: Sweet Home 3D's categories mapped onto ours. Floor, Wood and Roof already
#: exist here and the imports join them; the rest arrive as their own
#: sections rather than being forced into a bucket they do not belong in.
CATEGORIES = {
    "Wall": "wall",
    "Floor": "floor",
    "Wood": "wood",
    "Roof": "roof",
    "Wallpaper": "wallpaper",
    "Fabric": "fabric",
    "Rug": "rug",
    "Sky": "sky",
    "Miscellaneous": "misc",
}

#: Order the tray shows them in: what a building is made of first, what goes
#: inside it after.
ORDER = ["brick", "concrete", "stone", "wall", "wood", "roof", "floor",
         "wallpaper", "fabric", "rug", "metal", "ground", "glass", "water",
         "sky", "misc"]


def _fields(text: str, tag: str) -> dict:
    return {int(i): v.strip()
            for i, v in re.findall(r"^%s#(\d+)=(.+)$" % tag, text, re.M)}


def _read(zf: zipfile.ZipFile, name: str) -> str:
    try:
        return zf.read(name).decode("iso-8859-1")
    except KeyError:
        return ""


def _slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore")
    out = re.sub(r"[^a-z0-9]+", "_", plain.decode().lower()).strip("_")
    return out or "textura"


def convert(sh3t: Path, cats: dict, names_es: dict) -> int:
    """Add every texture of ``sh3t`` to ``cats``; returns how many."""
    with zipfile.ZipFile(sh3t) as zf:
        base = _read(zf, "PluginTexturesCatalog.properties")
        es = _read(zf, "PluginTexturesCatalog_es.properties")
        names, es_names = _fields(base, "name"), _fields(es, "name")
        cat, image = _fields(base, "category"), _fields(base, "image")
        width, height = _fields(base, "width"), _fields(base, "height")
        creator = _fields(base, "creator")
        members = set(zf.namelist())
        added = 0
        for i in sorted(image):
            rel = image[i].lstrip("/")
            if rel not in members:
                continue
            cid = CATEGORIES.get(cat.get(i, ""), "misc")
            name = names.get(i) or _slug(rel)
            slug = _slug(name)
            ext = Path(rel).suffix.lower() or ".png"
            folder = TEX / "library" / cid
            folder.mkdir(parents=True, exist_ok=True)
            dst = folder / (slug + ext)
            n = 2
            # Names repeat across (and within) these catalogues — "Beige
            # fabric" twice, "Grass" in two libraries. Whatever is already
            # taken gets a number; without this the second one overwrites
            # the first and the manifest points two entries at one image.
            while dst.name in _written:
                dst = folder / ("%s_%d%s" % (slug, n, ext))
                n += 1
            dst.write_bytes(zf.read(rel))
            _written.add(dst.name)
            try:
                # The catalogue says centimetres; the app works in metres.
                sw = round(float(width[i]) / 100.0, 4)
                sh = round(float(height[i]) / 100.0, 4)
            except (KeyError, ValueError):
                sw = sh = 1.0
            cats.setdefault(cid, []).append({
                "file": "%s/%s" % (cid, dst.name),
                "name": name,
                "sw": sw,
                "sh": sh,
                "author": creator.get(i, ""),
                "src": "sh3t",          # so a re-import can replace its own
            })
            if i in es_names:
                names_es[name] = es_names[i]
            added += 1
    return added


_written: set = set()


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[-1])
        return 2
    manifest = TEX / "library.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    # Run it twice and you must get the same library, not a second copy of
    # it: everything a previous import wrote is dropped and its files with
    # it. Our own procedural set carries no "src" and is left alone.
    cats: dict = {}
    dropped = 0
    for c in data["categories"]:
        keep = []
        for it in c.get("items", []):
            if it.get("src") == "sh3t":
                (TEX / "library" / it["file"]).unlink(missing_ok=True)
                dropped += 1
                continue
            keep.append(it)
            _written.add(Path(it["file"]).name)
        cats[c["id"]] = keep
    if dropped:
        print("  (reemplazando %d texturas de una importación anterior)"
              % dropped)

    names_es: dict = {}
    for src in argv[1:]:
        p = Path(src)
        print("  %-28s %3d texturas" % (p.name, convert(p, cats, names_es)))

    order = {cid: n for n, cid in enumerate(ORDER)}
    data["categories"] = [
        {"id": cid, "items": cats[cid]}
        for cid in sorted(cats, key=lambda c: (order.get(c, 99), c))
    ]
    manifest.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    # The Spanish the catalogue already ships, straight into our own file —
    # never overwriting a translation that is already there.
    es_path = ROOT / "i18n" / "es.json"
    es = json.loads(es_path.read_text(encoding="utf-8"))
    clash = {k: (es[k], v) for k, v in names_es.items()
             if k in es and es[k] != v}
    new = {k: v for k, v in names_es.items() if k not in es}
    es.update(new)
    es_path.write_text(
        json.dumps(es, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")

    total = sum(len(v) for v in cats.values())
    mb = sum(f.stat().st_size for f in (TEX / "library").rglob("*")
             if f.is_file()) / 1e6
    print("total: %d texturas en %d categorías, %.1f MB"
          % (total, len(cats), mb))
    print("es.json: %d nombres nuevos%s"
          % (len(new), "" if not clash else
             ", %d ya traducidos distinto (respetados): %s"
             % (len(clash), list(clash)[:4])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
