# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The style editor: the user style library (core) and the tray panel (UI).

The library lives in QSettings ("styles/user", a JSON list) like the custom
basemap sources; ``style_by_name`` resolves built-ins first, then the
library — that is what lets a composer frame reference a saved style by
``"style:<name>"``. The panel edits ``scene.display_style`` in place, live.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

import core.style as style_mod  # noqa: E402
from core.scene import Scene  # noqa: E402
from core.style import (  # noqa: E402
    Style,
    delete_user_style,
    save_user_style,
    style_by_name,
    user_styles,
)


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Point the style library at a throwaway INI file."""
    path = tmp_path / "styles.ini"
    monkeypatch.setattr(style_mod, "_settings",
                        lambda: QSettings(str(path), QSettings.IniFormat))
    return path


def test_save_load_round_trip(settings_file):
    st = Style(name="Obra", face_mode="hidden_line",
               edge_color=(0.1, 0.2, 0.3), sky=False)
    save_user_style(st)
    loaded = user_styles()
    assert [s.name for s in loaded] == ["Obra"]
    assert loaded[0].face_mode == "hidden_line"
    assert loaded[0].edge_color == (0.1, 0.2, 0.3)
    assert loaded[0].sky is False


def test_save_replaces_by_name_and_delete(settings_file):
    save_user_style(Style(name="Obra", face_mode="shaded"))
    save_user_style(Style(name="Obra", face_mode="wireframe"))
    save_user_style(Style(name="Croquis"))
    assert [s.name for s in user_styles()] == ["Obra", "Croquis"]
    assert user_styles()[0].face_mode == "wireframe"   # replaced, not doubled

    assert delete_user_style("Obra") is True
    assert delete_user_style("Obra") is False          # already gone
    assert [s.name for s in user_styles()] == ["Croquis"]


def test_builtin_name_is_refused(settings_file):
    with pytest.raises(ValueError):
        save_user_style(Style(name="Hidden line"))
    assert user_styles() == []


def test_style_by_name_resolves_user_styles_as_copies(settings_file):
    save_user_style(Style(name="Obra", face_mode="monochrome"))
    got = style_by_name("Obra")
    assert got is not None and got.face_mode == "monochrome"
    got.face_mode = "xray"                             # a COPY: no write-back
    assert style_by_name("Obra").face_mode == "monochrome"
    # Built-ins still win and still resolve.
    assert style_by_name("Wireframe").face_mode == "wireframe"
    assert style_by_name("no existe") is None


def test_broken_settings_entry_is_dropped(settings_file):
    s = QSettings(str(settings_file), QSettings.IniFormat)
    s.setValue("styles/user", "{esto no es json")
    s.sync()
    assert user_styles() == []


# ---- The tray panel ----------------------------------------------------------

class _Win:
    """Just enough main window for the panel."""

    def __init__(self):
        class _VP:
            def __init__(self):
                self.scene = Scene()

            def update(self):
                pass

        self.viewport = _VP()

    def _sync_style_menu(self):
        # The real one refreshes menu + panel; tests drive refresh directly.
        pass


def test_panel_pick_applies_a_preset(settings_file):
    from views.tray import StylesPanel
    win = _Win()
    panel = StylesPanel(win)
    idx = panel._combo.findData("Hidden line")
    assert idx >= 0
    panel._on_pick(idx)
    assert win.viewport.scene.display_style.face_mode == "hidden_line"
    assert win.viewport.scene.display_style.sky is False


def test_panel_edits_the_active_style_live(settings_file):
    from views.tray import StylesPanel
    win = _Win()
    panel = StylesPanel(win)
    panel._edges.setChecked(False)
    panel._mode.setCurrentIndex(panel._mode.findData("xray"))
    style = win.viewport.scene.display_style
    assert style.edges is False
    assert style.face_mode == "xray"


def test_every_swatch_stays_editable_and_hints_when_invisible(settings_file):
    """Every colour is editable in every mode — you build a look, then see
    each piece where it applies (disabling them read as "can't change the
    sky/front color", live, 2026-08-31). What changes with the mode is the
    HINT: edits that can't show right now say why; edits that show say
    nothing."""
    from views.tray import StylesPanel
    win = _Win()
    panel = StylesPanel(win)
    style = win.viewport.scene.display_style

    # Default style: textures + sky + edges + section fill.
    for sw in (panel._edge_c, panel._front_c, panel._sky_c,
               panel._ground_c, panel._bg_c, panel._fill_c):
        assert sw.isEnabled()
    assert panel._color_hint("front_color")        # textures: can't show
    assert panel._color_hint("background")         # sky covers it
    assert panel._color_hint("sky_color") is None  # sky is on: visible
    assert panel._color_hint("edge_color") is None

    style.face_mode = "hidden_line"
    style.sky = False
    style.edges = False
    style.section_fill = False
    assert panel._color_hint("front_color") is None
    assert panel._color_hint("background") is None
    assert panel._color_hint("sky_color")          # sky off now
    assert panel._color_hint("edge_color")         # edges off
    assert panel._color_hint("section_fill_color")

    style.face_mode = "wireframe"
    assert panel._color_hint("edge_color") is None  # wireframe always draws


def test_sky_gradient_ramps_from_haze_to_the_picked_tones():
    """The backdrop gradient: the user's sky colour rules the zenith and the
    ground colour rules the foreground, both hazing toward white at the
    horizon. Pure math (no GL) — the quads only colour their corners, so
    these ARE the rendered colours."""
    from pytest import approx
    from views.viewport import Viewport
    sky = (0.2, 0.4, 0.9)                       # a deep blue
    gnd = (0.4, 0.3, 0.2)
    s0, s1, g0, g1, line = Viewport._sky_gradient(sky, gnd, 0.0)
    # Near the horizon both halves are pulled toward white (haze)…
    assert s0[0] > sky[0] and g0[0] > gnd[0]
    # …and away from it they approach the picked tones (blue: red channel
    # falls toward 0.2 going up; ground darkens going down).
    assert s1[0] < s0[0] and g1[0] < g0[0]
    assert all(0.0 <= v <= 1.0 for c in (s0, s1, g0, g1, line) for v in c)

    # Camera pitched up: the whole visible sky is zenith colour.
    s0, s1, _g0, _g1, _l = Viewport._sky_gradient(sky, gnd, -3.0)
    assert s0 == approx(sky) and s1 == approx(sky)
    # Pitched down: the visible ground is fully the ground colour.
    _s0, _s1, g0, g1, _l = Viewport._sky_gradient(sky, gnd, 3.0)
    assert g0 == approx(gnd) and g1 == approx(gnd)


def test_sky_and_ground_colors_are_style_data(settings_file):
    """The backdrop tones live in the Style (serialised, library-saved) and
    the viewport reads them per frame — Marco asked for the sky colour and
    it was a hardcoded constant."""
    st = Style(name="Tarde", sky_color=(0.9, 0.7, 0.5),
               ground_color=(0.4, 0.3, 0.2))
    save_user_style(st)
    got = style_by_name("Tarde")
    assert got.sky_color == (0.9, 0.7, 0.5)
    assert got.ground_color == (0.4, 0.3, 0.2)
    # An old style dict without the fields gets the historical defaults —
    # which are the viewport's former constants, so old documents render
    # identically.
    from views.viewport import Viewport
    legacy = Style.from_dict({"name": "vieja"})
    assert legacy.sky_color == Viewport._SKY_RGB
    assert legacy.ground_color == Viewport._GROUND_RGB


def test_panel_combo_lists_saved_styles_and_arms_delete(settings_file):
    from views.tray import StylesPanel
    save_user_style(Style(name="Obra", face_mode="hidden_line"))
    win = _Win()
    panel = StylesPanel(win)
    idx = panel._combo.findData("Obra")
    assert idx >= 0
    panel._on_pick(idx)
    panel.refresh()
    assert win.viewport.scene.display_style.name == "Obra"
    assert panel._del_btn.isEnabled()                  # a user style: deletable
    panel._on_pick(panel._combo.findData("Default"))
    panel.refresh()
    assert not panel._del_btn.isEnabled()              # a built-in: not


# ---- Back color (the usual Front/Back color pair) ----------------------------

def test_back_color_is_style_data_and_round_trips(settings_file):
    """The back-face tint lives in the Style next to the front colour:
    serialised, library-saved, copied. Unset (``None``) stays automatic."""
    from core.style import DEFAULT_BACK_COLOR, effective_back_color
    assert Style().back_color is None
    assert effective_back_color(Style()) == DEFAULT_BACK_COLOR

    st = Style(name="Interior", back_color=(0.9, 0.2, 0.1))
    again = Style.from_dict(st.to_dict())
    assert again.back_color == (0.9, 0.2, 0.1)
    assert Style.from_dict(Style().to_dict()).back_color is None
    save_user_style(st)
    assert style_by_name("Interior").back_color == (0.9, 0.2, 0.1)
    # Old documents (no key) and junk values fall back to automatic.
    assert Style.from_dict({}).back_color is None
    assert Style.from_dict({"back_color": "rojo"}).back_color is None
    assert Style.from_dict({"back_color": [1, 2]}).back_color is None


def test_back_color_precedence_style_then_document_then_default():
    """A picked Back color wins over the tint adopted from an imported .skp
    (``scene.back_face_color``); with none picked the adopted tint still
    shows, exactly as before this option existed."""
    from core.style import DEFAULT_BACK_COLOR, effective_back_color
    scene = Scene()
    style = scene.display_style
    assert effective_back_color(style, scene) == DEFAULT_BACK_COLOR
    scene.back_face_color = (0.5, 0.5, 0.5)
    assert effective_back_color(style, scene) == (0.5, 0.5, 0.5)
    style.back_color = (0.1, 0.8, 0.3)
    assert effective_back_color(style, scene) == (0.1, 0.8, 0.3)


def test_panel_back_swatch_shows_the_tint_that_draws(settings_file,
                                                     monkeypatch):
    from PySide6.QtGui import QColor
    from views import tray
    from views.tray import StylesPanel
    win = _Win()
    panel = StylesPanel(win)
    style = win.viewport.scene.display_style
    # Automatic: the swatch shows the default blue-grey (158,178,199).
    assert "rgb(158,178,199)" in panel._back_c.styleSheet()

    import views.color_dialog as color_dialog
    monkeypatch.setattr(color_dialog.QColorDialog, "getColor",
                        staticmethod(lambda *a, **k: QColor(255, 0, 0)))
    panel._pick_color("Back color", "back_color")
    assert style.back_color == (1.0, 0.0, 0.0)
    assert "rgb(255,0,0)" in panel._back_c.styleSheet()
    assert style.front_color == (1.0, 1.0, 1.0)     # front untouched


def test_a_swatch_tooltip_keeps_the_tooltip_colours(settings_file):
    """A swatch's colour is ITS background only: a bare «background: …»
    sheet reached the tooltip over it too — light text on the white front
    colour, unreadable."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QToolTip
    from views.tray import StylesPanel
    win = _Win()
    panel = StylesPanel(win)
    swatch = panel._front_c                          # white (255,255,255)
    swatch.show()
    QToolTip.showText(QPoint(10, 10), "tip", swatch)
    QApplication.processEvents()
    labels = [w for w in QApplication.topLevelWidgets()
              if w.objectName() == "qtooltip_label" and w.isVisible()]
    try:
        assert labels
        assert labels[0].palette().color(QPalette.Window).name() != "#ffffff"
    finally:
        QToolTip.hideText()
        swatch.close()


def test_back_color_hint_only_where_back_faces_cannot_show(settings_file):
    from views.tray import StylesPanel
    win = _Win()
    panel = StylesPanel(win)
    style = win.viewport.scene.display_style
    for mode in ("textures", "shaded", "monochrome", "xray"):
        style.face_mode = mode
        assert panel._color_hint("back_color") is None, mode
    for mode in ("hidden_line", "wireframe"):
        style.face_mode = mode
        assert panel._color_hint("back_color"), mode
