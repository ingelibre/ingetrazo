# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Slate theme: a blue-grey palette plus one app-wide stylesheet for the
chrome (views/theme.py). The other themes must keep no app stylesheet, and a
sheet somebody else set is never touched.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMainWindow, QToolBar

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from views import theme  # noqa: E402


@pytest.fixture
def app():
    a = QApplication.instance()
    before_theme, before_accent = theme.saved_theme(), theme.saved_accent()
    a.setStyleSheet("")
    theme._app_sheet = ""
    yield a
    theme.save_theme(before_theme)
    theme.save_accent(before_accent)
    a.setStyleSheet("")
    theme._app_sheet = ""
    theme.apply_theme(a, theme.DARK)


def test_slate_is_a_dark_theme_that_can_be_saved(app):
    assert theme.SLATE in theme.THEMES
    for scheme in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark,
                   Qt.ColorScheme.Unknown):
        assert theme.is_dark(theme.SLATE, scheme) is True
    theme.save_theme(theme.SLATE)
    assert theme.saved_theme() == theme.SLATE


def test_slate_sets_its_palette_and_sheet(app):
    assert theme.apply_theme(app, theme.SLATE) is True
    window = app.palette().color(QPalette.Window)
    assert window == QColor(theme.SLATE_COLOURS["window"])
    # A neutral grey with the faintest cool cast.
    assert 0 <= window.blue() - window.red() <= 6
    sheet = app.styleSheet()
    for selector in ("QToolBar", "QMenuBar", "QStatusBar",
                     "QDockWidget::title", "QScrollBar"):
        assert selector in sheet


@pytest.mark.parametrize("mode", [theme.DARK, theme.LIGHT])
def test_leaving_slate_clears_the_sheet(app, mode):
    theme.apply_theme(app, theme.SLATE)
    assert "QPushButton" in app.styleSheet()
    theme.apply_theme(app, mode)
    assert app.styleSheet() == ""


@pytest.mark.parametrize("mode", [theme.DARK, theme.LIGHT])
def test_dark_and_light_keep_no_app_sheet(app, mode):
    """Round 6: with any app stylesheet — even only the grip — Qt on
    Windows painted the active tool in the desktop's accent (light blue in
    Dark, blue in Light). The grip is drawn by the style instead."""
    theme.apply_theme(app, mode)
    assert app.styleSheet() == ""
    assert isinstance(app.style(), theme.ChromeStyle)


def _grip_pixels(app, mode, vertical=False):
    theme.apply_theme(app, mode)
    win = QMainWindow()
    tb = QToolBar(win)
    tb.setMovable(True)
    win.addToolBar(Qt.LeftToolBarArea if vertical else Qt.TopToolBarArea, tb)
    tb.addAction("a")
    win.resize(300, 300)
    win.show()
    app.processEvents()
    img = tb.grab().toImage()
    win.close()
    w, h = (img.width(), 12) if vertical else (12, img.height())
    return [img.pixelColor(x, y) for x in range(w) for y in range(h)]


@pytest.mark.parametrize("mode", [theme.DARK, theme.LIGHT, theme.SLATE])
@pytest.mark.parametrize("vertical", [False, True])
def test_every_theme_has_the_grey_grip_line(app, mode, vertical):
    # Round 5: the one-line grip in every theme, its grey matched to each.
    grip = QColor(theme.GRIP_COLOURS[mode])
    px = _grip_pixels(app, mode, vertical)
    line = [c for c in px if c == grip]
    assert len(line) >= 8           # a line, not a dot
    # ... and only one: the line is 1 px across.
    assert len(line) <= max(len(px) // 12 + 2, 40)


def test_the_floating_title_style_draws_the_same_grip():
    from views.floating_toolbar import _GripStyle
    assert issubclass(_GripStyle, theme.ChromeStyle)


def test_system_resolves_its_grip(app):
    theme.apply_theme(app, theme.SYSTEM)
    dark = app.palette().color(QPalette.Window).lightness() < 128
    assert theme.grip_colour() == QColor(
        theme.GRIP_COLOURS[theme.DARK if dark else theme.LIGHT])


def test_grips_are_a_quiet_step_off_their_toolbar():
    for mode, pal in ((theme.DARK, theme.dark_palette()),
                      (theme.LIGHT, theme.light_palette()),
                      (theme.SLATE, theme.slate_palette())):
        grip = QColor(theme.GRIP_COLOURS[mode]).lightness()
        window = pal.color(QPalette.Window).lightness()
        assert 10 <= abs(grip - window) <= 80, mode


def _chrome_sizes(app, mode):
    from PySide6.QtWidgets import QToolButton
    from views.icons import tool_icon
    theme.apply_theme(app, mode)
    win = QMainWindow()
    win.menuBar().addMenu("File")
    tb = QToolBar(win)
    tb.setIconSize(QSize(24, 24))
    win.addToolBar(tb)
    act = tb.addAction(tool_icon("select"), "")
    act.setCheckable(True)
    win.resize(400, 300)
    win.show()
    app.processEvents()
    btn = tb.widgetForAction(act)
    assert isinstance(btn, QToolButton)
    sizes = (win.menuBar().height(), tb.height(), btn.size().toTuple())
    win.close()
    return sizes


def test_slate_takes_no_more_room_than_dark(app):
    """Round 5: Slate's menu bar, toolbars and buttons were taller, which
    took height from the 3D view."""
    assert _chrome_sizes(app, theme.SLATE) == _chrome_sizes(app, theme.DARK)


def test_a_sheet_set_by_someone_else_is_left_alone(app):
    foreign = "QLabel { color: red; }"
    app.setStyleSheet(foreign)
    theme.apply_theme(app, theme.SLATE)
    assert app.styleSheet() == foreign
    theme.apply_theme(app, theme.DARK)
    assert app.styleSheet() == foreign


def test_the_sheet_follows_the_accent(app):
    theme.save_accent("blue")
    theme.apply_theme(app, theme.SLATE)
    assert "53, 132, 228" in app.styleSheet()
    theme.save_accent("green")
    theme.apply_accent(app)
    assert "46, 160, 67" in app.styleSheet()
    assert "53, 132, 228" not in app.styleSheet()


def test_the_sheet_template_is_fully_filled():
    sheet = theme.slate_sheet()
    # Every placeholder resolved; only the rules' own braces remain.
    assert "{accent_rgb}" not in sheet
    assert sheet.count("{") == sheet.count("}")
    for name in theme.SLATE_COLOURS:
        assert "{" + name + "}" not in sheet


def test_slate_palette_defines_the_shades_stylesheets_use():
    pal = theme.slate_palette()
    for role in (QPalette.Light, QPalette.Midlight, QPalette.Mid,
                 QPalette.Dark, QPalette.Shadow):
        assert pal.isBrushSet(QPalette.Active, role)
    # Readable: light text on the dark window.
    assert (pal.color(QPalette.WindowText).lightness()
            - pal.color(QPalette.Window).lightness()) > 120


def test_the_overflow_chevron_still_shows(app):
    """The toolbar's «more tools» button is narrow: the buttons' padding
    and border once left its chevron no room at all."""
    from views.icons import style_overflow_button
    theme.apply_theme(app, theme.SLATE)
    win = QMainWindow()
    tb = QToolBar(win)
    tb.setIconSize(QSize(24, 24))
    win.addToolBar(tb)
    for i in range(30):
        tb.addAction(f"a{i}")
    style_overflow_button(tb)
    win.resize(220, 120)
    win.show()
    app.processEvents()
    from PySide6.QtWidgets import QToolButton
    ext = tb.findChild(QToolButton, "qt_toolbar_ext_button")
    assert ext is not None and ext.isVisible()
    img = ext.grab().toImage()
    # The chevron's ink: bright, opaque pixels (the button itself is
    # transparent). Squeezed by the padding, only a sliver of it is left.
    ink = sum(
        1 for x in range(img.width()) for y in range(img.height())
        if img.pixelColor(x, y).alpha() > 128
        and img.pixelColor(x, y).lightness() > 100)
    win.close()
    assert ink >= 15


def _rule(sheet: str, selector: str) -> str:
    """The body of the first rule whose selector list starts with
    ``selector``."""
    at = sheet.index(selector + " ") if selector + " " in sheet \
        else sheet.index(selector)
    return sheet[sheet.index("{", at):sheet.index("}", at) + 1]


def test_the_active_tool_is_not_painted_in_the_accent():
    # Round 2 of the user's test: the active tool keeps Dark's quiet box.
    theme.save_accent("blue")
    sheet = theme.slate_sheet()
    body = _rule(sheet, "QToolBar QToolButton:checked")
    assert "53, 132, 228" not in body
    assert "border-color: " + theme.SLATE_COLOURS["active"] in body
    assert "background: transparent" in body


def test_panel_tabs_keep_ingetrazo_s_own_look():
    # Rounds 2-4: flat names read as one tab, boxes looked too far apart;
    # the user chose IngeTrazo's original tabs, only recoloured.
    assert "QTabBar" not in theme.slate_sheet()


def test_the_toolbar_grips_are_quiet_grey(app):
    """Round 2: under a stylesheet Fusion drew the grip dots in translucent
    white, far brighter than Dark's grey ones."""
    theme.apply_theme(app, theme.SLATE)
    win = QMainWindow()
    tb = QToolBar(win)
    tb.setMovable(True)
    win.addToolBar(tb)
    tb.addAction("a")
    win.resize(300, 100)
    win.show()
    app.processEvents()
    img = tb.grab().toImage()
    win.close()
    # The grip sits at the toolbar's start, before the first button.
    lightest = max(img.pixelColor(x, y).lightness()
                   for x in range(0, 10) for y in range(img.height()))
    assert lightest <= QColor(theme.SLATE_COLOURS["grip"]).lightness() + 4


def test_the_grip_is_one_thin_line():
    # Round 3: one grey line instead of two columns of dots, to save width.
    from PySide6.QtWidgets import QStyle
    style = theme.ChromeStyle("Fusion")
    assert style.pixelMetric(QStyle.PM_ToolBarHandleExtent)         == theme.ChromeStyle.GRIP_EXTENT < 9
    assert "QToolBar::handle" not in theme.app_sheet(theme.SLATE)


def test_neutral_accents_are_offered():
    # Round 6: white and light grey, for a sober chrome.
    keys = [k for k, _l, _c in theme.ACCENTS]
    assert "white" in keys and "light_grey" in keys
    assert theme.accent_color("white").lightness() > 230
    grey = theme.accent_color("light_grey")
    assert 160 < grey.lightness() < 215
    assert abs(grey.red() - grey.blue()) < 16      # a grey, not a tint


@pytest.mark.parametrize("mode", [theme.DARK, theme.LIGHT, theme.SLATE])
def test_the_active_tool_is_only_a_thin_outline(app, mode):
    """Round 12: the active tool is a thin quiet outline with nothing
    inside, as IngeTrazo always had it (a fill, round 7, was too loud)."""
    from views.icons import tool_icon
    theme.apply_theme(app, mode)
    win = QMainWindow()
    tb = QToolBar(win)
    tb.setIconSize(QSize(24, 24))
    win.addToolBar(tb)
    act = tb.addAction(tool_icon("select"), "")
    act.setCheckable(True)
    act.setChecked(True)
    win.resize(300, 120)
    win.show()
    app.processEvents()
    btn = tb.widgetForAction(act)
    img = btn.grab().toImage()
    bar = tb.grab().toImage()
    win.close()
    outline = QColor(theme.ACTIVE_COLOURS[mode])
    mid_y = img.height() // 2
    edge = img.pixelColor(0, mid_y)
    assert abs(edge.lightness() - outline.lightness()) <= 12, (mode,
                                                               edge.name())
    # Inside, clear of the icon: the bar's own background, no fill.
    inside = img.pixelColor(3, mid_y)
    background = bar.pixelColor(bar.width() - 2, bar.height() // 2)
    # (Transparent where the stylesheet leaves the bar to show through;
    # the bar's gradient where Fusion paints it.)
    assert inside.alpha() < 10 or abs(
        inside.lightness() - background.lightness()) <= 8, (
        mode, inside.name(), background.name())


@pytest.mark.parametrize("mode", [theme.DARK, theme.LIGHT, theme.SLATE])
def test_icons_are_inked_in_a_soft_grey(app, mode):
    """Round 7: the icons' lines were the text colour, near white or near
    black; now a very light or very dark grey, a step softer."""
    from views.icons import _ink
    theme.apply_theme(app, mode)
    ink = _ink()
    assert ink == QColor(theme.ICON_INKS[mode])
    text = app.palette().color(QPalette.WindowText)
    window = app.palette().color(QPalette.Window)
    # Softer than the text, still far from the background.
    assert abs(ink.lightness() - window.lightness()) \
        < abs(text.lightness() - window.lightness())
    assert abs(ink.lightness() - window.lightness()) > 100
    assert 25 < ink.lightness() < 230


def test_cursors_keep_the_full_contrast_ink(app):
    from views.icons import _text_ink
    theme.apply_theme(app, theme.DARK)
    assert _text_ink() == app.palette().color(QPalette.WindowText)


def test_dark_is_darker_than_slate():
    """Round 8: «Dark» read lighter than Slate. Slate took the neutral grey
    of the user's reference and Dark the first Slate's blue-grey: Dark is
    the darkest theme."""
    dark = theme.dark_palette()
    slate = theme.slate_palette()
    for role in (QPalette.Window, QPalette.Base):
        assert dark.color(role).lightness() < slate.color(role).lightness()
    # Blue-grey, and not black.
    window = dark.color(QPalette.Window)
    assert window.blue() > window.red()
    assert window.lightness() > 15


def test_light_is_a_soft_grey_not_white():
    """Round 9: Light gets the same care: a soft light grey with quiet
    frames, fields almost white, text and icons a very dark grey."""
    pal = theme.light_palette()
    window = pal.color(QPalette.Window)
    assert 215 < window.lightness() < 240           # light, not white
    assert pal.color(QPalette.Base).lightness() > window.lightness()
    text = pal.color(QPalette.WindowText)
    assert 20 < text.lightness() < 60               # very dark, not black
    # The active tool's outline: a quiet grey, darker than the window.
    active = QColor(theme.ACTIVE_COLOURS[theme.LIGHT])
    assert active.lightness() < window.lightness() - 30


@pytest.mark.parametrize("mode", [theme.DARK, theme.LIGHT])
def test_separators_are_the_grip_s_grey_line(app, mode):
    """Round 10: the separators between groups of tools are the same thin
    grey line as the grip (Fusion drew a two-tone groove)."""
    theme.apply_theme(app, mode)
    win = QMainWindow()
    tb = QToolBar(win)
    tb.setMovable(False)
    win.addToolBar(tb)
    tb.addAction("a")
    sep = tb.addSeparator()
    tb.addAction("b")
    win.resize(300, 100)
    win.show()
    app.processEvents()
    geo = tb.actionGeometry(sep)
    img = tb.grab(geo).toImage()
    win.close()
    grip = QColor(theme.GRIP_COLOURS[mode])
    # The bar's background is a vertical gradient: a column that differs
    # from the first one is a line. Exactly one, in the grip's grey.
    def column(x):
        return [img.pixelColor(x, y).rgb() for y in range(img.height())]
    lines = [x for x in range(img.width()) if column(x) != column(0)]
    assert len(lines) == 1
    assert grip.rgb() in column(lines[0])


def test_light_icons_are_a_mid_dark_grey():
    # Round 10: grey lines in Light, as in the user's reference.
    ink = QColor(theme.ICON_INKS[theme.LIGHT])
    assert 70 < ink.lightness() < 110


def _contrast(a: QColor, b: QColor) -> float:
    def lum(c):
        def f(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(c.red()) + 0.7152 * f(c.green()) + 0.0722 * f(c.blue())
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_dark_icons_have_a_reference_contrast():
    """Round 11: Dark's icons read dull (8.7:1) next to the user's
    reference toolbar (about 10.4:1); they are brighter now, still short
    of white."""
    window = theme.dark_palette().color(QPalette.Window)
    ink = QColor(theme.ICON_INKS[theme.DARK])
    assert _contrast(ink, window) >= 10
    assert ink.lightness() < 240
    # Separators and the grip: visible but quiet, as in the reference.
    grip = QColor(theme.GRIP_COLOURS[theme.DARK])
    assert 1.6 <= _contrast(grip, window) <= 2.4


def _ink_pixels(icon, size=48) -> int:
    img = icon.pixmap(size, size).toImage()
    return sum(1 for x in range(img.width()) for y in range(img.height())
               if img.pixelColor(x, y).alpha() > 128)


def test_toolbar_icons_are_drawn_with_fine_lines(app, monkeypatch):
    """Round 14: the icons' lines read heavy (1.5-2 px at 24 px); they are
    drawn at 65 % of their written width now."""
    from views import icons
    assert icons.ICON_STROKE == pytest.approx(0.65)
    thin = [_ink_pixels(icons.tool_icon(k)) for k in ("line", "move", "zoom")]
    monkeypatch.setattr(icons, "ICON_STROKE", 1.0)
    full = [_ink_pixels(icons.tool_icon(k)) for k in ("line", "move", "zoom")]
    for a, b in zip(thin, full):
        assert a < b * 0.8


def test_the_overflow_chevron_keeps_its_weight(app):
    # Thinned, the 16 px chevron faded to a grey blank again.
    from views import icons
    assert {"overflow_h", "overflow_v"} <= icons.FULL_WEIGHT


def test_cursors_keep_their_full_weight(app):
    from views import icons
    icons.tool_icon("move")                  # a toolbar icon in between
    assert icons._stroke == 1.0              # ... leaves no factor behind
    pen = icons._Pen(QColor("black"), 3.0)
    assert pen.widthF() == pytest.approx(3.0)
    with icons._weighted(icons.ICON_STROKE):
        assert icons._Pen(QColor("black"), 3.0).widthF() \
            == pytest.approx(3.0 * icons.ICON_STROKE)


@pytest.mark.parametrize("mode", [theme.DARK, theme.LIGHT, theme.SLATE])
def test_row_marks_keep_ingetrazo_s_original_look(app, mode):
    """Rounds 13-16: re-inking the eye and the padlock read worse than the
    original, in Light and in Dark; they keep the palette's text ink."""
    from views.outliner import _ink
    theme.apply_theme(app, mode)
    assert _ink() == app.palette().color(QPalette.Text)


def test_light_text_keeps_the_original_ink():
    """Round 17: the Browser's and the Layers drop-down's eye and padlock
    are drawn in the text colour; a lighter text washed them out."""
    pal = theme.light_palette()
    assert pal.color(QPalette.Text) == QColor(20, 22, 26)
    assert pal.color(QPalette.WindowText) == QColor(20, 22, 26)
