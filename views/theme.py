"""Light / dark UI chrome that follows the desktop, or a fixed choice.

Window ▸ Preferences ▸ Theme stores the General setting ``theme``: ``dark`` (the
default — IngeTrazo's look, Marco 2026-09-22: the user opts into the rest),
``light``, ``slate`` (see below), or ``system``, which follows the OS colour
scheme and flips live when the user switches it — GNOME/KDE portals, Windows
10/11 and macOS all report it to Qt through ``QStyleHints.colorScheme``.
Only the chrome changes: the 3D viewport keeps the model's display style,
and the composer's paper stays paper.

The palettes are complete on purpose (Light/Midlight/Mid/Dark/Shadow too):
stylesheets reference ``palette(mid)`` and ``palette(midlight)``, and a role
left unset falls back to whatever the platform theme hands Qt, which is how
a dark window ends up with light hover strips.

Secondary text in stylesheets is written with ``{muted}`` through
:func:`style`, which re-applies the rule on every theme change — a literal
grey is always too dark on one of the two backgrounds.

Dark is a blue-grey near black, Light a soft light grey. Slate is an
opt-in neutral mid-dark grey with one application-wide stylesheet
(:data:`SLATE_SHEET`) for the chrome Qt draws on its own — toolbars, menus,
docks, the status bar, buttons, fields and scroll bars; being app-wide, the
panels, toolbars and docks added later or by extensions get the same look.
Tabs keep IngeTrazo's own. Dark and Light keep no app stylesheet at all: on
Windows any one makes Qt paint the checked tool in the desktop's accent.

What every theme shares is drawn by :class:`ChromeStyle`: the toolbars' grip
and separators as one thin grey line, and the active tool as a thin outline
with nothing inside. The icons' grey and stroke live in views/icons.py.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPalette, QPen
from PySide6.QtWidgets import QProxyStyle, QStyle

SYSTEM, LIGHT, DARK, SLATE = "system", "light", "dark", "slate"
# The themes after the colour schemes Linux users keep in their terminals:
# each is a table of shades on Slate's pattern (see SHEET_THEMES).
SOLARIZED, CAMPBELL, SAND = "solarized", "campbell", "sand"
# And one after the 3D suites' neutral studio grey.
STUDIO = "studio"
THEMES = (SYSTEM, LIGHT, DARK, SLATE, SOLARIZED, CAMPBELL, SAND, STUDIO)
_KEY = "theme"          # a General setting: core.general_settings (#266)

# The one accent both themes share — selection and the IngeTrazo blue.
_HIGHLIGHT = QColor(42, 93, 143)

# ---- accent colour of the icons and toolbars --------------------------------
# Preferences ▸ General ▸ Accent colour (#393, Peter Mican by e-mail; Marco
# 12-10: «the orange suits Ubuntu, maybe not other systems»). It paints the
# icons' dots and handles, the hover of the toolbar buttons and the
# docking hints. The 3D view's selection stays orange: it is how a user
# recognises what is selected. Orange stays the default, so nobody sees a
# change until they choose one.
ORANGE, SYSTEM_ACCENT = "orange", "system"
ACCENTS = (
    (ORANGE, "IngeTrazo orange", (243, 115, 41)),
    ("blue", "Blue", (53, 132, 228)),
    ("green", "Green", (46, 160, 67)),
    ("red", "Red", (224, 27, 36)),
    ("purple", "Purple", (145, 65, 172)),
    ("yellow", "Yellow", (229, 165, 10)),
    # Neutral accents, for a sober chrome (the user's request, 0.6.1).
    ("white", "White", (245, 245, 245)),
    ("light_grey", "Light grey", (184, 188, 194)),
    (SYSTEM_ACCENT, "Same as the system", None),
)
_ACCENT_KEY = "accent"  # a General setting, like the theme
# The desktop's accent, read before apply_theme replaces the palette with
# IngeTrazo's own (Windows 11, macOS and the portals hand it to Qt there).
_system_accent: QColor | None = None


def saved_accent() -> str:
    from core import general_settings
    name = str(general_settings.value(_ACCENT_KEY, ORANGE) or ORANGE)
    return name if any(name == key for key, _l, _c in ACCENTS) else ORANGE


def save_accent(name: str) -> None:
    from core import general_settings
    general_settings.set_value(
        _ACCENT_KEY,
        name if any(name == key for key, _l, _c in ACCENTS) else ORANGE)


def accent_color(name: str | None = None) -> QColor:
    """The accent in force (or ``name``'s)."""
    name = saved_accent() if name is None else name
    if name == SYSTEM_ACCENT:
        if _system_accent is not None and _system_accent.isValid():
            return QColor(_system_accent)
        return QColor(_HIGHLIGHT)
    for key, _label, rgb in ACCENTS:
        if key == name and rgb is not None:
            return QColor(*rgb)
    return QColor(*ACCENTS[0][2])


def _remember_system_accent(app) -> None:
    global _system_accent
    if _system_accent is None:
        role = getattr(QPalette.ColorRole, "Accent", QPalette.Highlight)
        _system_accent = QColor(app.palette().color(role))


def saved_theme() -> str:
    from core import general_settings
    mode = str(general_settings.value(_KEY, DARK) or DARK)
    return mode if mode in THEMES else DARK


def save_theme(mode: str) -> None:
    from core import general_settings
    general_settings.set_value(_KEY, mode if mode in THEMES else DARK)


def is_dark(mode: str, system_scheme: Qt.ColorScheme) -> bool:
    """Which palette a mode resolves to. The system saying nothing (an old
    desktop, a bare X session) keeps the dark chrome IngeTrazo always had."""
    if mode == LIGHT:
        return False
    if mode == DARK:
        return True
    if mode in SHEET_THEMES:
        return mode not in LIGHT_SHEET_THEMES
    return system_scheme != Qt.ColorScheme.Light


def dark_palette() -> QPalette:
    # Blue-grey, near black: the first Slate's shades, moved here when Slate
    # took the neutral grey of the user's reference (0.6.1). Dark stays the
    # darkest theme.
    window = QColor(0x22, 0x29, 0x33)
    text = QColor(0xdd, 0xe2, 0xe8)
    disabled = QColor(0x6c, 0x75, 0x81)
    p = QPalette()
    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, QColor(0x1b, 0x20, 0x28))
    p.setColor(QPalette.AlternateBase, window)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.PlaceholderText, disabled)
    p.setColor(QPalette.Button, QColor(0x29, 0x30, 0x3a))
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor(255, 104, 104))
    p.setColor(QPalette.ToolTipBase, QColor(0x33, 0x3a, 0x45))
    p.setColor(QPalette.ToolTipText, QColor(0xf0, 0xf3, 0xf7))
    p.setColor(QPalette.Highlight, _HIGHLIGHT)
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.Link, QColor(96, 166, 226))
    # The shades Fusion draws bevels and frames with — pinned so the look
    # does not move with the platform theme.
    p.setColor(QPalette.Light, QColor(0x34, 0x3a, 0x44))
    p.setColor(QPalette.Midlight, QColor(0x29, 0x30, 0x3a))
    p.setColor(QPalette.Mid, QColor(0x29, 0x30, 0x3a))
    p.setColor(QPalette.Dark, QColor(0x1b, 0x20, 0x28))
    p.setColor(QPalette.Shadow, QColor(0x0a, 0x0c, 0x0f))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText,
                 QPalette.HighlightedText):
        p.setColor(QPalette.Disabled, role, disabled)
    return p


def light_palette() -> QPalette:
    # A bright, faintly cool light grey instead of Fusion's white and grey:
    # fields almost white, frames and lines a quiet light grey, text a very
    # dark grey (0.6.1, after a light ribbon the user showed).
    window = QColor(0xed, 0xee, 0xf0)
    # The text keeps IngeTrazo's own near black: the rows' eye, padlock and
    # target are drawn in it, and a lighter grey washed them out at 16 px
    # (the Browser, the Layers drop-down).
    text = QColor(20, 22, 26)
    disabled = QColor(0xa0, 0xa3, 0xa8)
    p = QPalette()
    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, QColor(0xfb, 0xfb, 0xfc))
    p.setColor(QPalette.AlternateBase, QColor(0xf4, 0xf5, 0xf6))
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.PlaceholderText, QColor(0x80, 0x84, 0x8a))
    p.setColor(QPalette.Button, QColor(0xe5, 0xe7, 0xea))
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor(200, 30, 30))
    p.setColor(QPalette.ToolTipBase, QColor(0xf8, 0xf8, 0xf9))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Highlight, _HIGHLIGHT)
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.Link, QColor(26, 110, 190))
    p.setColor(QPalette.Light, QColor(0xf8, 0xf8, 0xf9))
    p.setColor(QPalette.Midlight, QColor(0xda, 0xdc, 0xe0))
    p.setColor(QPalette.Mid, QColor(0xcc, 0xcf, 0xd4))
    p.setColor(QPalette.Dark, QColor(0xb2, 0xb6, 0xbc))
    p.setColor(QPalette.Shadow, QColor(0x7a, 0x7e, 0x85))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText,
                 QPalette.HighlightedText):
        p.setColor(QPalette.Disabled, role, disabled)
    return p


# ---- Slate ------------------------------------------------------------------
# One set of shades, used by both the palette and the stylesheet so the two
# never drift apart: a neutral mid-dark grey with the faintest cool cast,
# hairlines darker than the panels (as in image editors' tool columns), and
# a muted steel blue for the active tool only.
SLATE_COLOURS = {
    "deep": "#2a2b2d",      # fields, lists, the status and menu bars
    "window": "#323335",    # the window and the panels
    "raised": "#38393b",    # toolbars, menus, dock titles
    "button": "#444548",    # push buttons
    "border": "#262728",    # hairlines between areas: darker, not lighter
    "edge": "#4d4f53",      # the outline of buttons and fields
    "thumb": "#55575b",     # scroll-bar handles
    "grip": "#5a5c60",      # the toolbars' grip line: grey, never bright
    "active": "#6a6e76",    # the active tool's thin outline
    "text": "#d6d7d9",
    "bright": "#eeeff1",    # the brightest text
    "muted": "#9a9ca1",
    "disabled": "#707276",
}


# ---- the themes drawn on Slate's pattern ------------------------------------
# Each is the same table of shades (the roles of SLATE_COLOURS) with the
# extras a theme of its own colour wants (SHEET_EXTRAS): the icons' ink, the
# selection and the links. They take their shades from the colour schemes
# Linux users keep in their terminals — Solarized's dark blue-green and its
# light warm sand (Sand), the classic console's Campbell — so the window
# can go with the terminal beside it — and Studio, the 3D suites' look.
# Nothing else differs from Slate: the same
# stylesheet, the same grip and outline drawn by ChromeStyle.
SOLARIZED_COLOURS = {
    # Solarized's dark: its deep blue-green ground, the text a step
    # brighter than the scheme's own soft grey — a window is read in
    # small type, not a terminal's.
    "deep": "#002730", "window": "#002b36", "raised": "#073642",
    "button": "#0d4452", "border": "#00202a", "edge": "#2a5561",
    "thumb": "#2f5f6b", "grip": "#3d6b76", "active": "#4f7f8c",
    "text": "#b4c0c0", "bright": "#eee8d5", "muted": "#839496",
    "disabled": "#586e75",
}
CAMPBELL_COLOURS = {
    # The classic console's near black and light grey, with its bright
    # blue for the selection.
    "deep": "#0c0c0c", "window": "#161616", "raised": "#1f1f1f",
    "button": "#2d2d2d", "border": "#000000", "edge": "#3a3a3a",
    "thumb": "#3c3c3c", "grip": "#444444", "active": "#4a6fb5",
    "text": "#cccccc", "bright": "#f2f2f2", "muted": "#8a8a8a",
    "disabled": "#5a5a5a",
}
STUDIO_COLOURS = {
    # The 3D suites' studio look, the other way round from Slate: the
    # bars (menus, toolbars, dock titles, status) near black above lighter
    # mid-grey panels, fields as dark as the bars, buttons a clearly
    # lighter grey, and a soft blue for the active tool and the selection.
    "deep": "#1b1b1b", "window": "#404040", "raised": "#1f1f1f",
    "button": "#5c5c5c", "border": "#121212", "edge": "#585858",
    "thumb": "#646464", "grip": "#5a5a5a", "active": "#5a7fb8",
    "text": "#e6e6e6", "bright": "#ffffff", "muted": "#a0a0a0",
    "disabled": "#7a7a7a",
}
SAND_COLOURS = {
    # A light theme: the fields are the lightest, the hairlines a step
    # darker than the panels, the text a deep blue-black, not the soft
    # grey such schemes print with (the rows' icons drawn in it washed out
    # at 16 px on Light, see light_palette).
    "deep": "#fdf6e3", "window": "#eee8d5", "raised": "#e6dfca",
    "button": "#f6f0dd", "border": "#d3cbb4", "edge": "#c5bda5",
    "thumb": "#c9c1a9", "grip": "#bdb59c", "active": "#93a1a1",
    "text": "#1f3138", "bright": "#073642", "muted": "#657b83",
    "disabled": "#a3a89a",
}

#: Every theme drawn with :data:`SLATE_SHEET`, by its shades.
SHEET_THEMES = {SLATE: SLATE_COLOURS,
                SOLARIZED: SOLARIZED_COLOURS, CAMPBELL: CAMPBELL_COLOURS,
                SAND: SAND_COLOURS, STUDIO: STUDIO_COLOURS}
#: Those of them that are light.
LIGHT_SHEET_THEMES = frozenset({SAND})
#: What a theme of its own colour adds: the icons' ink, the selection, its
#: text and the links. Slate keeps IngeTrazo's blue.
SHEET_EXTRAS = {
    SLATE: {"ink": "#c3c4c7"},
    SOLARIZED: {"ink": "#93a1a1", "highlight": "#268bd2", "link": "#2aa198"},
    CAMPBELL: {"ink": "#c0c0c0", "highlight": "#3b78ff", "link": "#61d6d6"},
    STUDIO: {"ink": "#d0d0d0", "highlight": "#4772b3", "link": "#71a8ff"},
    SAND: {"ink": "#586e75", "highlight": "#268bd2", "link": "#1d6fa5",
           "shadow": "#8a8470"},
}


def sheet_palette(mode: str) -> QPalette:
    """The palette of a theme on Slate's pattern (:data:`SHEET_THEMES`)."""
    c = {k: QColor(v) for k, v in SHEET_THEMES[mode].items()}
    extra = SHEET_EXTRAS.get(mode, {})
    light = mode in LIGHT_SHEET_THEMES
    p = QPalette()
    p.setColor(QPalette.Window, c["window"])
    p.setColor(QPalette.WindowText, c["text"])
    p.setColor(QPalette.Base, c["deep"])
    p.setColor(QPalette.AlternateBase, c["window"])
    p.setColor(QPalette.Text, c["text"])
    p.setColor(QPalette.PlaceholderText, c["disabled"])
    p.setColor(QPalette.Button, c["raised"])
    p.setColor(QPalette.ButtonText, c["text"])
    p.setColor(QPalette.BrightText, QColor(200, 30, 30) if light
               else QColor(255, 104, 104))
    p.setColor(QPalette.ToolTipBase, c["button"])
    p.setColor(QPalette.ToolTipText, c["bright"])
    p.setColor(QPalette.Highlight, QColor(extra.get("highlight", _HIGHLIGHT)))
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.Link, QColor(extra.get("link", "#60a6e2")))
    p.setColor(QPalette.Light, c["border"])
    p.setColor(QPalette.Midlight, c["border"])
    p.setColor(QPalette.Mid, c["raised"])
    p.setColor(QPalette.Dark, c["deep"])
    p.setColor(QPalette.Shadow, QColor(extra.get("shadow", "#0a0c0f")))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText,
                 QPalette.HighlightedText):
        p.setColor(QPalette.Disabled, role, c["disabled"])
    return p


def slate_palette() -> QPalette:
    return sheet_palette(SLATE)


#: The Slate chrome. Only type selectors and sub-controls: a widget that
#: sets its own stylesheet (the colour swatches, the measurements box…)
#: still wins. The grip is not here: :class:`ChromeStyle` draws it.
#: ``{accent_rgb}`` is Preferences ▸ Accent colour; the doubled braces are
#: literal ones for :meth:`str.format`.
SLATE_SHEET = """
QMainWindow::separator {{ background: {deep}; width: 3px; height: 3px; }}
QMenuBar {{ background: {deep}; }}
QMenuBar::item {{ background: transparent; padding: 3px 8px 2px 8px;
    border-radius: 3px; }}
QMenuBar::item:selected {{ background: rgba({accent_rgb}, 46);
    color: {bright}; }}
QMenu {{ background: {raised}; border: 1px solid {edge}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}
QMenu::item:selected {{ background: rgba({accent_rgb}, 70); color: {bright}; }}
QToolBar {{ background: {raised}; border: none; padding: 4px;
    spacing: 0; }}
QToolBar::separator {{ background: {border}; width: 1px; height: 1px;
    margin: 5px 4px; }}
QToolBar QToolButton {{ background: transparent;
    border: 1px solid transparent; border-radius: 4px;
    padding: 1px 1px 1px 2px; }}
QToolBar QToolButton:hover {{ background: rgba({accent_rgb}, 38);
    border-color: rgba({accent_rgb}, 110); }}
QToolBar QToolButton:checked, QToolBar QToolButton:pressed {{
    background: transparent; border-color: {active}; border-radius: 3px; }}
QToolBar QToolButton[popupMode="1"] {{ padding-right: 13px; }}
QToolBar QToolButton::menu-button {{ border: none; width: 12px; }}
QToolBar QToolButton#qt_toolbar_ext_button {{ padding: 0; border: none;
    border-radius: 3px; }}
QDockWidget::title {{ background: {raised}; padding: 5px 8px;
    border-bottom: 1px solid {border}; }}
QStatusBar {{ background: {deep}; border-top: 1px solid {border}; }}
QStatusBar::item {{ border: none; }}
QPushButton {{ background: {button}; border: 1px solid {edge};
    border-radius: 4px; padding: 4px 12px; }}
QPushButton:hover {{ border-color: rgba({accent_rgb}, 190); }}
QPushButton:pressed, QPushButton:checked {{
    background: rgba({accent_rgb}, 70); }}
QPushButton:disabled {{ color: {disabled}; border-color: {border}; }}
QLineEdit {{ background: {deep}; border: 1px solid {edge};
    border-radius: 4px; padding: 3px 6px; }}
QLineEdit:focus {{ border-color: rgb({accent_rgb}); }}
QToolTip {{ background: {button}; color: {bright};
    border: 1px solid {edge}; padding: 4px 6px; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle {{ background: {thumb}; border-radius: 4px; margin: 2px; }}
QScrollBar::handle:vertical {{ min-height: 28px; }}
QScrollBar::handle:horizontal {{ min-width: 28px; }}
QScrollBar::handle:hover {{ background: {edge}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""


#: The grip's grey on each theme's toolbar: a step off the background,
#: like the dots it replaces.
GRIP_COLOURS = {DARK: "#485462", LIGHT: "#c8cbd0",
                **{k: c["grip"] for k, c in SHEET_THEMES.items()}}


def sheet_for(mode: str) -> str:
    """:data:`SLATE_SHEET` with ``mode``'s shades and the accent in force."""
    accent = accent_color()
    return SLATE_SHEET.format(
        accent_rgb=f"{accent.red()}, {accent.green()}, {accent.blue()}",
        **SHEET_THEMES[mode])


def slate_sheet() -> str:
    """:data:`SLATE_SHEET` with the shades and the accent in force."""
    return sheet_for(SLATE)


def app_sheet(mode: str) -> str:
    """The app-wide stylesheet for a theme: Slate's chrome, and nothing at
    all for the others. Any app sheet, even one rule, makes Qt paint the
    checked tool buttons in the desktop's accent on Windows (light blue in
    Dark, blue in Light), so Dark and Light must keep none."""
    return sheet_for(mode) if mode in SHEET_THEMES else ""


#: The active tool's outline on each theme: a thin, quiet grey border and
#: nothing inside, as IngeTrazo always had it — Fusion's bright edge read
#: too heavy, a fill too loud (the user, 0.6.1).
ACTIVE_COLOURS = {DARK: "#5b6676", LIGHT: "#a7aeb8",
                  **{k: c["active"] for k, c in SHEET_THEMES.items()}}


def active_tool_colour() -> QColor:
    """The active tool's outline for the theme in force."""
    return QColor(ACTIVE_COLOURS.get(_grip_key, ACTIVE_COLOURS[DARK]))


#: The icons' ink on each theme: a very light or very dark grey, softer
#: than the text — pure white or black lines glared (the user, 0.6.1).
ICON_INKS = {DARK: "#d9dce1", LIGHT: "#55595f",
             **{k: e["ink"] for k, e in SHEET_EXTRAS.items()}}


def icon_ink() -> QColor:
    """The icons' ink for the theme in force."""
    return QColor(ICON_INKS.get(_grip_key, ICON_INKS[DARK]))


def grip_colour() -> QColor:
    """The grip's grey for the theme in force."""
    return QColor(GRIP_COLOURS.get(_grip_key, GRIP_COLOURS[DARK]))


def _in_toolbar(widget) -> bool:
    from PySide6.QtWidgets import QToolBar, QToolButton
    return (isinstance(widget, QToolButton)
            and isinstance(widget.parentWidget(), QToolBar))


class ChromeStyle(QProxyStyle):
    """Fusion, with the toolbars' grip drawn as one thin grey line instead
    of two columns of dots — narrower and quieter, in every theme (the
    user's choice). Drawn by the style, not a stylesheet: see
    :func:`app_sheet`. views/floating_toolbar.py builds on it."""

    #: Room the grip takes along the bar (Fusion's dots take 9 px).
    GRIP_EXTENT = 7
    #: Gap between the line's ends and the bar's edges.
    GRIP_INSET = 6

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PM_ToolBarHandleExtent:
            return self.GRIP_EXTENT
        return super().pixelMetric(metric, option, widget)

    #: Corner radius of the active tool's outline.
    ACTIVE_RADIUS = 3

    def drawPrimitive(self, element, option, painter, widget=None):
        if (element == QStyle.PE_PanelButtonTool
                and option.state & QStyle.State_On
                and _in_toolbar(widget)):
            # The active (checked) tool: a thin outline, nothing inside.
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(QPen(active_tool_colour(), 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(option.rect).adjusted(
                0.5, 0.5, -0.5, -0.5), self.ACTIVE_RADIUS, self.ACTIVE_RADIUS)
            painter.restore()
            return
        if element == QStyle.PE_IndicatorToolBarSeparator:
            # Between groups of tools: the grip's thin grey line, so every
            # line on a bar is one and the same.
            r, inset = option.rect, self.GRIP_INSET
            if option.state & QStyle.State_Horizontal:
                line = QRect(r.center().x(), r.top() + inset,
                             1, max(1, r.height() - 2 * inset))
            else:
                line = QRect(r.left() + inset, r.center().y(),
                             max(1, r.width() - 2 * inset), 1)
            painter.fillRect(line, grip_colour())
            return
        if element != QStyle.PE_IndicatorToolBarHandle:
            super().drawPrimitive(element, option, painter, widget)
            return
        r, inset = option.rect, self.GRIP_INSET
        if option.state & QStyle.State_Horizontal:   # a horizontal bar
            line = QRect(r.center().x(), r.top() + inset,
                         1, max(1, r.height() - 2 * inset))
        else:
            line = QRect(r.left() + inset, r.center().y(),
                         max(1, r.width() - 2 * inset), 1)
        painter.fillRect(line, grip_colour())


def tokens() -> dict[str, str]:
    """Colours a stylesheet template may name, for the palette in force."""
    app = QGuiApplication.instance()
    dark = (app is None
            or app.palette().color(QPalette.Window).lightness() < 128)
    accent = accent_color()
    return {"muted": "#8a94a0" if dark else "#5a6472",
            "accent_rgb": f"{accent.red()}, {accent.green()}, "
                          f"{accent.blue()}"}


# ---- stylesheet templates that follow the theme ----------------------------

_styled: dict[int, tuple[object, str]] = {}


def style(widget, template: str) -> None:
    """``widget.setStyleSheet(template.format(**tokens()))``, and again on
    every theme change for as long as the widget lives."""
    widget.setStyleSheet(template.format(**tokens()))
    key = id(widget)
    if key not in _styled:
        widget.destroyed.connect(lambda *_a, k=key: _styled.pop(k, None))
    _styled[key] = (widget, template)


def _restyle() -> None:
    t = tokens()
    for widget, template in list(_styled.values()):
        try:
            widget.setStyleSheet(template.format(**t))
        except RuntimeError:            # C++ side already gone
            pass


def _repolish(app) -> None:
    """Qt resolves a stylesheet's ``palette(mid)`` — and the text colour of
    any widget that has a stylesheet — once, at polish time; a later
    ``setPalette`` does not reach them (the tray headers stayed light grey on
    the light theme). Re-setting the sheet re-polishes the widget and its
    children with the palette now in force."""
    from PySide6.QtWidgets import QWidget
    for top in app.topLevelWidgets():
        # Walk the live tree, not allWidgets(): that flat set can still list
        # a widget whose C++ half is gone (the test suite managed it with
        # dialogs whose parent was collected), and wrapping it segfaults.
        for w in [top, *top.findChildren(QWidget)]:
            sheet = w.styleSheet()
            if sheet:
                w.setStyleSheet(sheet)


def _reinherit_palettes(app) -> None:
    """Make every widget take the palette in force again. Once Slate's sheet
    had come and gone, Qt left hundreds of widgets — the Properties and
    Layers tabs among them — holding the palette of that moment and deaf
    to every later theme change: Slate → Dark → Light kept Dark's panels
    (and at times the menu bar) in Light. Parents before children, so each
    inherits the corrected one; a widget with a palette or a stylesheet of
    its own (a colour swatch, the search list) is left as it is."""
    from PySide6.QtWidgets import QWidget
    blank = QPalette()

    def walk(w) -> None:
        if (not w.testAttribute(Qt.WA_SetPalette) and not w.styleSheet()):
            w.setPalette(blank)
        for child in w.children():
            if isinstance(child, QWidget):
                walk(child)

    for top in app.topLevelWidgets():
        walk(top)


def _redraw_icons(app) -> None:
    """The programmatic icons are painted in the palette's ink when built;
    anything tagged with an ``icon_key`` property gets repainted. (The main
    window keeps its own list — see MainWindow._refresh_toolbar_icons.)

    A menu is a top-level widget of its own, and with PySide 6.11.1 asking
    one for its QActions leaves the wrappers of OTHER widgets dead: after an
    accent change the next Open failed in the Styles/Shadows panels («C++
    object already deleted») or F3's menu walk segfaulted (extension bench,
    15-10). Its actions are reached anyway from the window that owns it."""
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QAbstractButton, QMenu
    from views.icons import tool_icon
    for top in app.topLevelWidgets():
        actions = [] if isinstance(top, QMenu) else top.findChildren(QAction)
        for obj in actions + top.findChildren(QAbstractButton):
            key = obj.property("icon_key")
            if key:
                obj.setIcon(tool_icon(str(key)))


# ---- applying ---------------------------------------------------------------

class _Follower(QObject):
    """Re-applies the saved mode when the desktop scheme flips."""

    def on_scheme(self, _scheme) -> None:
        app = QGuiApplication.instance()
        if app is not None and saved_theme() == SYSTEM:
            apply_theme(app)


_follower: _Follower | None = None


def apply_accent(app) -> None:
    """Repaint what wears the accent after Preferences changed it."""
    from views import icons
    icons.clear_cursor_cache()
    if _applied in SHEET_THEMES:        # its hovers wear the accent
        _set_app_sheet(app, app_sheet(_applied))
    _restyle()
    _redraw_icons(app)
    for top in app.topLevelWidgets():
        refresh = getattr(top, "_refresh_toolbar_icons", None)
        if callable(refresh):
            refresh()
        top.update()


# The app-wide sheet this module last set. Another one (an extension's) is
# never replaced or cleared: only ours is ours to change.
_app_sheet = ""
_app_style = None                       # the app's ChromeStyle, kept alive
_applied = ""                           # the mode apply_theme last set
_grip_key = DARK                        # whose grip grey is in force


def _set_app_sheet(app, sheet: str) -> None:
    global _app_sheet
    current = app.styleSheet()
    if current not in ("", _app_sheet) or current == sheet:
        return
    app.setStyleSheet(sheet)
    _app_sheet = sheet


def _system_scheme(app) -> Qt.ColorScheme:
    # With the override cleared (see apply_theme) styleHints reports the
    # desktop's own scheme.
    return app.styleHints().colorScheme()


def apply_theme(app, mode: str | None = None) -> bool:
    """Set the palette for ``mode`` (default: the saved one). Returns True
    when the dark palette was applied."""
    global _follower
    mode = saved_theme() if mode is None else mode
    _remember_system_accent(app)
    hints = app.styleHints()
    # Clear any earlier override first so the desktop's answer is readable,
    # then pin the resolved scheme: it drives the platform pieces the
    # palette cannot reach (Wayland client-side title bar, native menus).
    hints.unsetColorScheme()
    dark = is_dark(mode, _system_scheme(app))
    if mode != SYSTEM:
        hints.setColorScheme(Qt.ColorScheme.Dark if dark
                             else Qt.ColorScheme.Light)
    global _app_style, _grip_key
    _grip_key = mode if mode in SHEET_THEMES else (DARK if dark else LIGHT)
    if not isinstance(app.style(), ChromeStyle):
        _app_style = ChromeStyle("Fusion")
        app.setStyle(_app_style)
    app.setPalette(sheet_palette(mode) if mode in SHEET_THEMES
                   else dark_palette() if dark else light_palette())
    _set_app_sheet(app, app_sheet(mode))
    _reinherit_palettes(app)
    global _applied
    _applied = mode
    _restyle()
    _repolish(app)
    _redraw_icons(app)
    if _follower is None:
        _follower = _Follower(app)
        hints.colorSchemeChanged.connect(_follower.on_scheme)
    return dark
