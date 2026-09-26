# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Which Qt platform plugin to start on.

Measured on Marco's laptop (2026-09-14, Radeon 780M, GNOME Wayland with the
display at 125 %): under the native Wayland plugin the viewport's frames ran
p90 149 ms with the same model that gave p90 30 ms under ``xcb`` (XWayland) —
Qt composes a QOpenGLWidget window through a slow path when the output scale
is fractional. So a Wayland session whose configured monitor scale is not a
whole number starts under ``xcb`` unless the user says otherwise
(Preferences ▸ General ▸ Graphics server, or ``QT_QPA_PLATFORM`` set by hand,
which always wins). ``xwayland-native-scaling`` keeps it crisp on GNOME 46+.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

#: Preference values (QSettings ``general/platform``).
AUTO, WAYLAND, XCB = "auto", "wayland", "xcb"


DRM_SYSFS = Path("/sys/class/drm")


def _connector_name(drm: str) -> str:
    """``card1-HDMI-A-1`` (the kernel) → ``HDMI-1`` (what GNOME writes)."""
    name = drm.split("-", 1)[1] if drm.startswith("card") and "-" in drm else drm
    return re.sub(r"^(HDMI|DP|DVI)-[A-Z]-", r"\1-", name)


def connected_outputs(sysfs: Path | None = None) -> set[str]:
    """Connector names of the outputs the kernel reports as connected —
    the monitors plugged in RIGHT NOW, which is what the choice must
    follow (a laptop alone vs the laptop beside a desktop screen)."""
    sysfs = sysfs or DRM_SYSFS
    out: set[str] = set()
    try:
        entries = list(sysfs.iterdir())
    except OSError:
        return out
    for entry in entries:
        try:
            status = (entry / "status").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if status == "connected" and "Writeback" not in entry.name:
            out.add(_connector_name(entry.name))
    return out


def parse_gnome_configurations(text: str) -> list[dict]:
    """GNOME's ``monitors.xml`` keeps one ``<configuration>`` per set of
    monitors it has seen: ``[{"connectors": {...}, "scales": [...]}, …]``."""
    configs = []
    for block in re.findall(r"<configuration>(.*?)</configuration>", text, re.S):
        configs.append({
            "connectors": set(re.findall(r"<connector>\s*([^<\s]+)\s*</connector>", block)),
            "scales": [float(v) for v in re.findall(r"<scale>\s*([0-9.]+)\s*</scale>", block)],
        })
    return configs


def _monitors_xml_scales(home: Path, connected: set[str] | None = None) -> list[float]:
    """The ``<scale>`` values of the GNOME configuration in force: the one
    whose connectors are exactly the monitors connected now; every stored
    configuration's when none matches (or nothing is known about them)."""
    path = home / ".config" / "monitors.xml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    configs = parse_gnome_configurations(text)
    if connected:
        for cfg in configs:
            if cfg["connectors"] == connected:
                return cfg["scales"]
    return [s for cfg in configs for s in cfg["scales"]]


def _kwin_scales(home: Path) -> list[float]:
    """The ``scale`` values KDE writes in ``~/.config/kwinoutputconfig.json``."""
    path = home / ".config" / "kwinoutputconfig.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[float] = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "scale" and isinstance(v, (int, float)):
                    out.append(float(v))
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(data)
    return out


def fractional_scale_configured(home: Path | None = None,
                                connected: set[str] | None = None) -> bool:
    """Whether a configured monitor (of the configuration in force, when
    ``connected`` is known) uses a non-integer scale (125 %, 150 %…)."""
    home = home or Path.home()
    scales = _monitors_xml_scales(home, connected) + _kwin_scales(home)
    return any(abs(s - round(s)) > 1e-6 for s in scales)


def choose_platform(preference: str, env: dict | None = None,
                    home: Path | None = None,
                    sysfs: Path | None = None) -> str | None:
    """The plugin to force through ``QT_QPA_PLATFORM``, or ``None`` to leave
    Qt's own choice. An explicit ``QT_QPA_PLATFORM`` in the environment is
    never overridden.

    Automatic: xcb on KDE Plasma (its Wayland session breaks Qt's popup
    menus, issue #136), and elsewhere only for a SINGLE connected monitor
    at a fractional scale. With two or more monitors Wayland stays — under XWayland an app
    is scaled for the primary output and merely rescaled on the others,
    while Wayland keeps each screen crisp at its own scale (Marco,
    2026-09-14: the laptop at 125 % beside a desktop monitor at 100 %)."""
    env = os.environ if env is None else env
    if env.get("QT_QPA_PLATFORM"):
        return None
    pref = (preference or AUTO).lower()
    if pref == XCB:
        return XCB if env.get("DISPLAY") else None
    if pref == WAYLAND:
        return None
    if env.get("XDG_SESSION_TYPE", "").lower() != "wayland":
        return None
    if not env.get("DISPLAY"):
        return None                      # no XWayland to fall back to
    if "KDE" in env.get("XDG_CURRENT_DESKTOP", "").upper():
        # KDE Plasma under Wayland draws Qt's floating menus broken — torn,
        # misplaced, flickering (issue #136, @leo-smi; Anki shows the same
        # on the same desktop). XWayland draws them right, and broken menus
        # cost more than the crispness Wayland keeps on a second screen.
        return XCB
    connected = connected_outputs(sysfs)
    if len(connected) >= 2:
        return None                      # two screens: crisp on both wins
    return XCB if fractional_scale_configured(home, connected or None) else None


def apply_platform_preference() -> str | None:
    """Called BEFORE the QApplication exists: reads the preference and sets
    ``QT_QPA_PLATFORM`` when the choice says so. Returns what was set."""
    from PySide6.QtCore import QCoreApplication, QSettings
    QCoreApplication.setOrganizationName("IngeTrazo")
    QCoreApplication.setApplicationName("IngeTrazo")
    pref = str(QSettings().value("general/platform", AUTO) or AUTO)
    chosen = choose_platform(pref)
    if chosen:
        os.environ["QT_QPA_PLATFORM"] = chosen
    return chosen
