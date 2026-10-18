# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Long tooltips wrap into a box (Marco, 2026-09-20: some hints came out
as one long strip, others as a neat block — Qt only wraps rich text)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QToolTip, QWidget

_app = QApplication.instance() or QApplication([])


def test_plain_text_becomes_rich_text_escaped_and_rich_text_is_left_alone():
    from views.tooltips import wrapped
    assert wrapped("") == ""
    assert wrapped("<b>bold</b>") == "<b>bold</b>"            # already rich
    out = wrapped("Text (<> = measured value) & more\nnext line")
    assert out.startswith("<p style='white-space:normal'>")
    assert "&lt;&gt;" in out and "&amp;" in out and "<br>" in out
    assert "<>" not in out


def test_the_filter_shows_the_wrapped_text_for_a_widgets_tooltip():
    from views.tooltips import WrappingToolTips
    shown = []
    orig = QToolTip.showText
    QToolTip.showText = staticmethod(lambda pos, text, *a: shown.append(text))
    try:
        w = QWidget()
        w.setToolTip("Zoom: drag up to zoom in (Ctrl+wheel does the same)")
        f = WrappingToolTips()
        ev = QHelpEvent(QEvent.ToolTip, QPoint(1, 1), QPoint(10, 10))
        assert f.eventFilter(w, ev) is True
        assert shown and shown[-1].startswith("<p style='white-space:normal'>")
        assert "Ctrl+wheel" in shown[-1]
        rich = QWidget()
        rich.setToolTip("<b>already</b> rich")
        assert f.eventFilter(rich, ev) is False           # Qt's own path
        bare = QWidget()
        assert f.eventFilter(bare, ev) is False           # nothing to show
    finally:
        QToolTip.showText = orig


# A toolbar button's tooltip is a name over a description: the name reads
# in bold, the keys after it and the sentence under it do not.

def test_titled_puts_the_name_alone_in_bold_and_escapes_every_part():
    from views.tooltips import wrapped
    cases = [(f"Tool {i} <&>", f"Ctrl+{k}", f"Does thing {i} & <more>")
             for i, k in enumerate("ABCDEFGH")]
    for name, keys, desc in cases:
        out = wrapped(f"{name}  ({keys})\n{desc}", titled=True)
        esc = name.replace("&", "&amp;").replace("<", "&lt;") \
            .replace(">", "&gt;")
        assert f"<b>{esc}</b>  ({keys})<br>" in out
        assert out.count("<b>") == 1 and "<>" not in out
        assert "Does thing" in out and "&amp; &lt;more&gt;" in out
        # no keys: the whole first line is the name
        assert wrapped(f"{name}\n{desc}", titled=True) \
            .startswith(f"<p style='white-space:normal'><b>{esc}</b><br>")
    # one line, or not titled, or already rich: no bold added
    assert "<b>" not in wrapped("Line  (L)", titled=True)
    assert "<b>" not in wrapped("Line  (L)\nDraws edges.")
    assert wrapped("<i>x</i>\ny", titled=True) == "<i>x</i>\ny"


def test_only_a_toolbar_buttons_tooltip_shows_the_name_in_bold():
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtWidgets import QToolBar, QToolButton
    from views.shortcuts import set_tooltip
    from views.tooltips import WrappingToolTips
    shown = []
    orig = QToolTip.showText
    QToolTip.showText = staticmethod(lambda pos, text, *a: shown.append(text))
    try:
        tb = QToolBar()
        act = QAction("Offset", tb)
        act.setShortcut(QKeySequence("F"))
        act.setStatusTip("Copy edges at a distance.")
        set_tooltip(act, "Offset")
        tb.addAction(act)
        btn = tb.widgetForAction(act)
        assert isinstance(btn, QToolButton)
        # the stored tooltip stays plain: F3 and the shortcuts read it
        assert act.toolTip() == "Offset  (F)\nCopy edges at a distance."
        f = WrappingToolTips()
        ev = QHelpEvent(QEvent.ToolTip, QPoint(1, 1), QPoint(10, 10))
        assert f.eventFilter(btn, ev) is True
        assert "<b>Offset</b>  (F)<br>Copy edges at a distance." in shown[-1]
        # the same text on a widget outside a toolbar: no bold
        other = QToolButton()
        other.setToolTip(act.toolTip())
        assert f.eventFilter(other, ev) is True
        assert "<b>" not in shown[-1]
    finally:
        QToolTip.showText = orig


def test_every_toolbar_button_of_the_window_shows_its_name_in_bold(
        tmp_path, monkeypatch):
    """Orbit, Pan, Zoom, Zoom Window and Sample material used to carry
    their keys and sentence on ONE line («Orbit (O) — left-drag…»), so
    nothing set the name apart (Marco, 2026-10-16: «orbita desplazar zoom
    muestra de materia entre otros no quedo»)."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QToolBar, QToolButton
    import PySide6.QtCore as qc
    import views.main_window as mw
    from views.tooltips import wrapped, _titled, _toolbar_tip
    path = tmp_path / "prefs.ini"
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory)
    win = mw.MainWindow()
    try:
        flat = []
        for tb in win.findChildren(QToolBar):
            for btn in tb.findChildren(QToolButton):
                act = btn.defaultAction()
                if btn.parentWidget() is tb and act is not None \
                        and btn.toolTip():
                    assert _titled(btn)
                    if "<b>" not in wrapped(_toolbar_tip(btn), True):
                        flat.append(btn.toolTip())
        assert not flat, flat
        nav = win._nav_actions
        assert nav["orbit"].toolTip().startswith("Orbit  (O)\n")
        assert nav["zoom_window"].toolTip().startswith("Zoom Window\n")
        assert win._act_eyedropper.toolTip().startswith("Sample material\n")
    finally:
        win.close()


# Buttons that do not write «name  (keys)\nsentence» themselves — an
# extension's, or one added later — come out the same on screen.

def test_any_tooltip_shape_comes_out_as_name_over_sentence():
    from views.tooltips import titled_text
    names = [f"Tool{i}" for i in range(6)] + ["Unir sólidos", "Summon + Extruder"]
    for name in names:
        for keys in ("", "Ctrl+K"):
            k = f"  ({keys})" if keys else ""
            want = f"{name}{k}\nDoes the thing."
            # one line, every separator people write
            for sep in (" — ", " – ", ": ", " - ", "—"):
                assert titled_text(f"{name}{sep}does the thing.", name,
                                   keys) == want
            # keys written in the tooltip win over the action's
            assert titled_text(f"{name} (Q) — does the thing.", name, keys) \
                == f"{name}  (Q)\nDoes the thing."
            # the name alone: the sentence comes from the status tip
            assert titled_text(name, name, keys, "Does the thing.") == want
            assert titled_text(f"{name}{k}", name, keys,
                               "Does the thing.") == want
            # only the sentence: the action's name goes over it
            assert titled_text("Does the thing.", name, keys) == want
            # mnemonic and ellipsis in the action's text
            assert titled_text(f"{name} — does the thing.", f"&{name}…",
                               keys) == want
    # nothing to say under the name, or a status tip that only repeats it
    assert titled_text("Line", "Line") == "Line"
    assert titled_text("Line  (L)", "Line", "L", "Line") == "Line  (L)"
    # already shaped, rich text, or no name: left alone
    assert titled_text("Line  (L)\nDraws.", "Line", "L") == "Line  (L)\nDraws."
    assert titled_text("<b>x</b>", "x") == "<b>x</b>"
    assert titled_text("Draws.", "") == "Draws."
    # a hyphen inside a word is not a separator
    assert titled_text("Pan-and-zoom the view", "Pan") == \
        "Pan\nPan-and-zoom the view"


def test_an_extensions_toolbar_added_after_start_up_shows_names_in_bold(
        tmp_path, monkeypatch):
    """As the extensions build theirs: a toolbar of their own, added once
    the window is up, with «Name — sentence» tooltips or a status tip."""
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QKeySequence
    import PySide6.QtCore as qc
    import views.main_window as mw
    from views.tooltips import WrappingToolTips
    path = tmp_path / "prefs.ini"
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory)
    shown = []
    orig = QToolTip.showText
    QToolTip.showText = staticmethod(lambda pos, text, *a: shown.append(text))
    win = mw.MainWindow()
    try:
        tb = win.addToolBar("Plugin bar")
        one_line = tb.addAction("Extruder")
        one_line.setToolTip("Extruder — extruye cada cara a su propio grupo")
        status_only = tb.addAction("Summon Faces")
        status_only.setStatusTip("Crea caras a partir de las aristas.")
        status_only.setShortcut(QKeySequence("Ctrl+Shift+J"))
        also_main = win.toolbars["main"].addAction("Late tool")
        also_main.setToolTip("Late tool: added by an update")
        f = WrappingToolTips()
        ev = QHelpEvent(QEvent.ToolTip, QPoint(1, 1), QPoint(10, 10))
        for bar, act, bold, under in (
                (tb, one_line, "<b>Extruder</b><br>",
                 "Extruye cada cara a su propio grupo"),
                (tb, status_only, "<b>Summon Faces</b>  (Ctrl+Shift+J)<br>",
                 "Crea caras a partir de las aristas."),
                (win.toolbars["main"], also_main, "<b>Late tool</b><br>",
                 "Added by an update")):
            btn = bar.widgetForAction(act)
            assert f.eventFilter(btn, ev) is True
            assert bold in shown[-1] and under in shown[-1], shown[-1]
        # the stored tooltips are untouched
        assert one_line.toolTip().startswith("Extruder — ")
    finally:
        QToolTip.showText = orig
        win.close()
