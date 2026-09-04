# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What is actually drawing the viewport.

A "terribly slow on Windows" report has one question behind it: is the
viewport on the GPU driver, or on Qt's bundled software rasterizer
(``opengl32sw.dll``, which Qt falls back to when the driver cannot give a
3.3 core context — old drivers, Remote Desktop, a VM)? The strings the GL
context reports answer it, so the viewport records them here, the About
box shows them, and ``ingetrazo-gl.txt`` in the log folder keeps them for a
user who cannot read a dialog over WhatsApp."""
from __future__ import annotations

from pathlib import Path

GL_VENDOR = 0x1F00
GL_RENDERER = 0x1F01
GL_VERSION = 0x1F02

# Renderer strings that mean "no GPU is drawing this".
SOFTWARE_MARKERS = ("gdi generic", "llvmpipe", "softpipe", "swiftshader",
                    "microsoft basic render", "mesa offscreen", "software")


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")
    return str(value)


def read_gl_info(gl) -> dict:
    """Vendor / renderer / version of the live context behind ``gl`` (a
    ``QOpenGLFunctions``), plus ``software``: whether the renderer string
    says the frames are rasterised on the CPU. Never raises — a driver that
    answers nothing yields empty strings."""
    info = {}
    for key, enum in (("vendor", GL_VENDOR), ("renderer", GL_RENDERER),
                      ("version", GL_VERSION)):
        try:
            info[key] = _text(gl.glGetString(enum)).strip()
        except Exception:
            info[key] = ""
    info["software"] = is_software_renderer(info["renderer"], info["vendor"])
    return info


def is_software_renderer(renderer: str, vendor: str = "") -> bool:
    text = f"{renderer} {vendor}".lower()
    return any(marker in text for marker in SOFTWARE_MARKERS)


def describe(info: dict) -> str:
    """One line for the About box: ``renderer (vendor) — OpenGL version``."""
    if not info or not info.get("renderer"):
        return ""
    parts = [info["renderer"]]
    if info.get("vendor"):
        parts.append(f"({info['vendor']})")
    if info.get("version"):
        parts.append(f"— OpenGL {info['version']}")
    return " ".join(parts)


def write_gl_report(info: dict, path: Path | None = None) -> Path | None:
    """Overwrite ``ingetrazo-gl.txt`` in the log folder with the context
    strings; returns the path, or None when nothing is writable."""
    if path is None:
        from core.paths import user_log_dir
        path = user_log_dir() / "ingetrazo-gl.txt"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"vendor   : {info.get('vendor', '')}\n"
            f"renderer : {info.get('renderer', '')}\n"
            f"version  : {info.get('version', '')}\n"
            f"software : {'yes' if info.get('software') else 'no'}\n",
            encoding="utf-8")
        return path
    except OSError:
        return None
