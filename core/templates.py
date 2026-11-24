# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Document templates, like SketchUp's *Save As Template*.

A template is an ordinary ``.igz`` kept in the user's templates folder, with
a ``.json`` beside it holding its name and description. File > New starts
from the default template, and File > New from Template from any of them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths

SUFFIX = ".igz"
DEFAULT_KEY = "templates/default"


def templates_dir() -> Path:
    """The folder the user's templates live in (created on first use)."""
    base = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation))
    d = base / "templates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    """``name`` as a file name: no path separators or characters Windows
    refuses."""
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .")
    return name or "Plantilla"


def template_path(file_stem: str) -> Path:
    return templates_dir() / (_safe_name(file_stem) + SUFFIX)


def info_path(path) -> Path:
    """The ``.json`` that sits beside a template."""
    return Path(path).with_suffix(".json")


def read_info(path) -> dict:
    """``{"name", "description"}`` of a template; the file name and an empty
    description when it has no (readable) ``.json``."""
    p = Path(path)
    info = {"name": p.stem, "description": ""}
    try:
        data = json.loads(info_path(p).read_text(encoding="utf-8"))
        info["name"] = str(data.get("name") or p.stem)
        info["description"] = str(data.get("description") or "")
    except (OSError, ValueError):
        pass
    return info


def list_templates() -> list:
    """Every saved template, by name."""
    return sorted(templates_dir().glob("*" + SUFFIX),
                  key=lambda p: p.stem.lower())


def default_template():
    """The template File > New starts from, or ``None`` (none chosen, or its
    file is gone)."""
    raw = QSettings().value(DEFAULT_KEY)
    if not raw:
        return None
    p = Path(str(raw))
    return p if p.is_file() else None


def set_default_template(path) -> None:
    """Choose the template File > New starts from; ``None`` for none."""
    st = QSettings()
    if path is None:
        st.remove(DEFAULT_KEY)
    else:
        st.setValue(DEFAULT_KEY, str(path))
    st.sync()


def save_as_template(scene, name: str, *, description: str = "",
                     file_stem=None, thumbnail=None,
                     make_default: bool = False) -> Path:
    """Save ``scene`` as a template and return its path."""
    from formats import igz
    path = template_path(file_stem or name)
    igz.save_scene(scene, path, thumbnail=thumbnail)
    try:
        info_path(path).write_text(
            json.dumps({"name": name, "description": description},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError:
        pass
    if make_default:
        set_default_template(path)
    return path


def apply_template(scene, path) -> None:
    """Load a template into an empty ``scene``."""
    from formats import igz
    igz.load_into(scene, Path(path))
