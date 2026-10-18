"""Light / dark UI chrome that follows the desktop, or a fixed choice.

Window ▸ Preferences ▸ Theme stores the General setting ``theme``: ``dark`` (the
default — IngeTrazo's look, Marco 2026-09-22: the user opts into the rest),
``light``, or ``system``, which follows the OS colour scheme and flips live
when the user switches it — GNOME/KDE portals, Windows 10/11 and macOS all
report it to Qt through ``QStyleHints.colorScheme``. Only the
chrome changes: the 3D viewport keeps the model's display style, and the
composer's paper stays paper.

The palettes are complete on purpose (Light/Midlight/Mid/Dark/Shadow too):
stylesheets reference ``palette(mid)`` and ``palette(midlight)``, and a role
left unset falls back to whatever the platform theme hands Qt, which is how
a dark window ends up with light hover strips.

Secondary text in stylesheets is written with ``{muted}`` through
:func:`style`, which re-applies the rule on every theme change — a literal
grey is always too dark on one of the two backgrounds.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

SYSTEM, LIGHT, DARK = "system", "light", "dark"
THEMES = (SYSTEM, LIGHT, DARK)
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
    return system_scheme != Qt.ColorScheme.Light


def dark_palette() -> QPalette:
    window = QColor(45, 45, 48)
    text = QColor(224, 224, 224)
    disabled = QColor(128, 128, 128)
    p = QPalette()
    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, QColor(37, 37, 40))
    p.setColor(QPalette.AlternateBase, window)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.PlaceholderText, disabled)
    p.setColor(QPalette.Button, window)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor(255, 96, 96))
    p.setColor(QPalette.ToolTipBase, QColor(58, 58, 61))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Highlight, _HIGHLIGHT)
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.Link, QColor(74, 163, 224))
    # The shades Fusion derived here when the scheme was forced dark —
    # pinned so the dark look does not move with the platform theme.
    p.setColor(QPalette.Light, QColor(0x34, 0x34, 0x34))
    p.setColor(QPalette.Midlight, QColor(0x2F, 0x2F, 0x2F))
    p.setColor(QPalette.Mid, QColor(0x2F, 0x2F, 0x2F))
    p.setColor(QPalette.Dark, QColor(0x25, 0x25, 0x25))
    p.setColor(QPalette.Shadow, QColor(0x02, 0x02, 0x02))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText,
                 QPalette.HighlightedText):
        p.setColor(QPalette.Disabled, role, disabled)
    return p


def light_palette() -> QPalette:
    # Fusion's own light shades, with IngeTrazo's accent.
    window = QColor(239, 239, 239)
    text = QColor(20, 22, 26)
    disabled = QColor(160, 160, 160)
    p = QPalette()
    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, QColor(255, 255, 255))
    p.setColor(QPalette.AlternateBase, QColor(247, 247, 247))
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.PlaceholderText, QColor(120, 124, 130))
    p.setColor(QPalette.Button, window)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor(200, 30, 30))
    p.setColor(QPalette.ToolTipBase, QColor(255, 255, 225))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Highlight, _HIGHLIGHT)
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.Link, QColor(26, 110, 190))
    p.setColor(QPalette.Light, QColor(255, 255, 255))
    p.setColor(QPalette.Midlight, QColor(0xCA, 0xCA, 0xCA))
    p.setColor(QPalette.Mid, QColor(0xB8, 0xB8, 0xB8))
    p.setColor(QPalette.Dark, QColor(0x9F, 0x9F, 0x9F))
    p.setColor(QPalette.Shadow, QColor(0x76, 0x76, 0x76))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText,
                 QPalette.HighlightedText):
        p.setColor(QPalette.Disabled, role, disabled)
    return p


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
    _restyle()
    _redraw_icons(app)
    for top in app.topLevelWidgets():
        refresh = getattr(top, "_refresh_toolbar_icons", None)
        if callable(refresh):
            refresh()
        top.update()


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
    if app.style().name().lower() != "fusion":
        app.setStyle("Fusion")
    app.setPalette(dark_palette() if dark else light_palette())
    _restyle()
    _repolish(app)
    _redraw_icons(app)
    if _follower is None:
        _follower = _Follower(app)
        hints.colorSchemeChanged.connect(_follower.on_scheme)
    return dark
