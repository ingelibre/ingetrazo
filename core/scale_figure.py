# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The scale figure a new document starts with (#655).

Preferences ▸ General choose it: none, any person of
``resources/components/people.json`` (the Engineer by default), or the
user's own picture — a PNG cut out on a transparent background and the
height that person stands. The picture is copied into the user's data
folder first, so moving or deleting the original never breaks the next
new document.

The group the app places carries ``ext["scale_figure"]``: that, not the
picture's file name, is how «insert a document into another» knows to
leave it out (``core.insert.is_scale_figure``).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from core.paths import app_root

#: Where the choice lives (QSettings). ``scale_figure`` is the old on/off
#: switch of #221 and keeps its meaning.
KEY_ON = "new_document/scale_figure"
KEY_PICK = "new_document/scale_figure_pick"      # a people.json key / CUSTOM
KEY_IMAGE = "new_document/scale_figure_image"    # CUSTOM: the stored copy
KEY_HEIGHT = "new_document/scale_figure_height"  # CUSTOM: metres
KEY_NAME = "new_document/scale_figure_name"      # CUSTOM: the group's name

DEFAULT_PICK = "ingeniero"
CUSTOM = "custom"
#: The mark in ``Group.ext`` (the slot extensions use, saved in the .igz).
MARK = "scale_figure"
#: The pictures of the figures the app placed before the mark existed:
#: Sumari until 26-09, then the Engineer.
LEGACY_IMAGES = ("sumari.png", "ingeniero.png")

MIN_HEIGHT, MAX_HEIGHT = 0.30, 3.00


@dataclass(frozen=True)
class Figure:
    image: Path
    height: float
    name: str


def people_dir() -> Path:
    return app_root() / "resources" / "components"


def people() -> list[dict]:
    """``[{"key", "name", "tip", "height"}…]`` — the bundled cutouts."""
    path = people_dir() / "people.json"
    try:
        return [p for p in json.loads(path.read_text(encoding="utf-8"))
                if (people_dir() / f"{p['key']}.png").is_file()]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def figures_dir() -> Path:
    """The user's own pictures, beside the rest of the app's data."""
    from PySide6.QtCore import QStandardPaths
    base = (QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
            or str(Path.home() / ".ingetrazo"))
    return Path(base) / "figures"


def store_picture(source: str | Path) -> Path:
    """Copy ``source`` into :func:`figures_dir` under a name made from its
    bytes (the same picture chosen twice is one file). Raises ``OSError``
    or ``ValueError`` when it cannot be read as an image."""
    from PySide6.QtGui import QImage
    data = Path(source).read_bytes()
    img = QImage()
    if not img.loadFromData(data) or img.isNull() or img.height() == 0:
        raise ValueError("not an image")
    folder = figures_dir()
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(source).suffix.lower() or ".png"
    target = folder / f"{hashlib.sha256(data).hexdigest()[:16]}{suffix}"
    if not target.exists():
        tmp = target.with_suffix(target.suffix + ".part")
        shutil.copyfile(source, tmp)
        tmp.replace(target)
    return target


def _height(value, default: float) -> float:
    try:
        h = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(h, MIN_HEIGHT), MAX_HEIGHT)


def chosen(settings=None) -> Figure | None:
    """The figure for the next new document, or ``None`` for an empty
    sheet. A choice that no longer resolves (a deleted picture, a person
    gone from people.json) falls back to the Engineer rather than to
    nothing: the user asked for a figure."""
    from PySide6.QtCore import QSettings
    from core.i18n import tr
    st = settings if settings is not None else QSettings()
    if str(st.value(KEY_ON, "1")) == "0":
        return None
    pick = str(st.value(KEY_PICK, DEFAULT_PICK) or DEFAULT_PICK)
    if pick == CUSTOM:
        image = Path(str(st.value(KEY_IMAGE, "") or ""))
        if image.is_file():
            name = str(st.value(KEY_NAME, "") or "").strip() or tr("Person")
            return Figure(image, _height(st.value(KEY_HEIGHT), 1.70), name)
        pick = DEFAULT_PICK
    known = {p["key"]: p for p in people()}
    entry = known.get(pick) or known.get(DEFAULT_PICK)
    if entry is None:
        return None
    return Figure(people_dir() / f"{entry['key']}.png",
                  _height(entry.get("height"), 1.70), tr(entry["name"]))


def mark(group) -> None:
    group.ext = dict(group.ext or {})
    group.ext[MARK] = True


def is_marked(group) -> bool:
    return bool((getattr(group, "ext", None) or {}).get(MARK))
