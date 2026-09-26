# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Wayland + fractional display scale starts under xcb (measured: frames p90
149 ms vs 30 ms on the same model, Marco's laptop, 2026-09-14) — unless the
user or the environment says otherwise."""
from core.platform_choice import (AUTO, WAYLAND, XCB, choose_platform, connected_outputs,
                                  fractional_scale_configured)


def _gnome_home(tmp_path, scale):
    (tmp_path / ".config").mkdir(parents=True)
    (tmp_path / ".config" / "monitors.xml").write_text(
        f"<monitors version=\"2\"><configuration><logicalmonitor>"
        f"<scale>{scale}</scale></logicalmonitor></configuration></monitors>")
    return tmp_path


def test_fractional_scale_is_read_from_gnome_and_kde(tmp_path):
    assert fractional_scale_configured(_gnome_home(tmp_path, "1.25"))
    assert not fractional_scale_configured(_gnome_home(tmp_path / "b", "2"))
    kde = tmp_path / "kde"
    (kde / ".config").mkdir(parents=True)
    (kde / ".config" / "kwinoutputconfig.json").write_text(
        '[{"data": [{"name": "eDP-1", "scale": 1.5}]}]')
    assert fractional_scale_configured(kde)
    assert not fractional_scale_configured(tmp_path / "nothing")


def test_auto_picks_xcb_only_on_wayland_with_fractional_scale_and_x11_available(tmp_path):
    home = _gnome_home(tmp_path, "1.25")
    wl = {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}
    # A fake sysfs with ONE monitor: the rule reads the machine's outputs,
    # and this test failed on Marco's laptop the day a second screen was
    # plugged in (2026-09-15).
    one = _sysfs(tmp_path / "s", ["card1-eDP-1"])
    assert choose_platform(AUTO, wl, home, one) == XCB
    assert choose_platform(AUTO, {"XDG_SESSION_TYPE": "wayland"}, home, one) is None      # no XWayland
    assert choose_platform(AUTO, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}, home, one) is None
    assert choose_platform(AUTO, wl, _gnome_home(tmp_path / "int", "2"), one) is None    # whole scale
    assert choose_platform(AUTO, {**wl, "QT_QPA_PLATFORM": "wayland"}, home, one) is None  # the env wins


def test_the_explicit_choices(tmp_path):
    home = _gnome_home(tmp_path, "1")
    wl = {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}
    assert choose_platform(XCB, wl, home) == XCB
    assert choose_platform(XCB, {"XDG_SESSION_TYPE": "wayland"}, home) is None
    assert choose_platform(WAYLAND, wl, _gnome_home(tmp_path / "f", "1.25")) is None


def _sysfs(tmp_path, connected, others=()):
    root = tmp_path / "drm"
    for name in connected:
        (root / name).mkdir(parents=True)
        (root / name / "status").write_text("connected\n")
    for name in others:
        (root / name).mkdir(parents=True)
        (root / name / "status").write_text("disconnected\n")
    return root


MARCOS_XML = """<monitors version="2">
  <configuration>
    <logicalmonitor><scale>1</scale><monitor><monitorspec><connector>HDMI-1</connector></monitorspec></monitor></logicalmonitor>
    <logicalmonitor><scale>1.25</scale><monitor><monitorspec><connector>eDP-1</connector></monitorspec></monitor></logicalmonitor>
  </configuration>
  <configuration>
    <logicalmonitor><scale>1.25</scale><monitor><monitorspec><connector>eDP-1</connector></monitorspec></monitor></logicalmonitor>
  </configuration>
</monitors>"""


def test_the_kernels_connector_names_match_gnomes(tmp_path):
    root = _sysfs(tmp_path, ["card1-eDP-1", "card1-HDMI-A-1"], ["card1-DP-1", "card1-Writeback-1"])
    assert connected_outputs(root) == {"eDP-1", "HDMI-1"}


def test_two_monitors_stay_on_wayland_one_fractional_one_goes_xcb(tmp_path):
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    (home / ".config" / "monitors.xml").write_text(MARCOS_XML)
    wl = {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}
    alone = _sysfs(tmp_path / "a", ["card1-eDP-1"], ["card1-HDMI-A-1"])
    assert choose_platform(AUTO, wl, home, alone) == XCB              # the laptop alone, 125 %
    both = _sysfs(tmp_path / "b", ["card1-eDP-1", "card1-HDMI-A-1"])
    assert choose_platform(AUTO, wl, home, both) is None              # beside the monitor: Wayland
    # A single monitor whose configuration in force is whole-scaled.
    xml_int = MARCOS_XML.replace("<scale>1.25</scale><monitor><monitorspec><connector>eDP-1</connector></monitorspec></monitor></logicalmonitor>\n  </configuration>\n</monitors>",
                                 "<scale>2</scale><monitor><monitorspec><connector>eDP-1</connector></monitorspec></monitor></logicalmonitor>\n  </configuration>\n</monitors>")
    home2 = tmp_path / "home2"
    (home2 / ".config").mkdir(parents=True)
    (home2 / ".config" / "monitors.xml").write_text(xml_int)
    assert choose_platform(AUTO, wl, home2, alone) is None


def test_kde_plasma_on_wayland_starts_under_xcb(tmp_path):
    """Issue #136 (@leo-smi): KDE Plasma's Wayland session draws Qt's
    floating menus broken; XWayland draws them right — whatever the scale
    and however many screens. The user's explicit choice still wins."""
    home = _gnome_home(tmp_path, "1")                 # whole scale
    both = _sysfs(tmp_path / "s", ["card1-eDP-1", "card1-HDMI-A-1"])
    kde = {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0",
           "XDG_CURRENT_DESKTOP": "KDE"}
    assert choose_platform(AUTO, kde, home, both) == XCB
    assert choose_platform(WAYLAND, kde, home, both) is None
    assert choose_platform(AUTO, {**kde, "QT_QPA_PLATFORM": "wayland"}, home,
                           both) is None
    assert choose_platform(AUTO, {**kde, "DISPLAY": ""}, home, both) is None
    gnome = {**kde, "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}
    assert choose_platform(AUTO, gnome, home, both) is None
