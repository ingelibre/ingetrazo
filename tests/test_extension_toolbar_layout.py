# SPDX-License-Identifier: GPL-3.0-or-later
"""A worker's late toolbars join the same saved layout as synchronous ones."""
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QMainWindow, QToolBar
from views.extension_api import ExtensionApp


def _bar(win, key, area=Qt.TopToolBarArea):
    bar = QToolBar(key, win)
    bar.setObjectName('extension_test_' + key)
    bar.addAction(key)
    win.addToolBar(area, bar)
    return bar


def test_ready_restores_late_toolbar_area_break_order_and_visibility():
    settings = QSettings()
    old = settings.value('ui/window_state')
    seed = QMainWindow()
    win = QMainWindow()
    try:
        _bar(seed, 'native')
        _bar(seed, 'a', Qt.BottomToolBarArea)
        seed.addToolBarBreak(Qt.BottomToolBarArea)
        _bar(seed, 'b', Qt.BottomToolBarArea)
        c = _bar(seed, 'c', Qt.LeftToolBarArea)
        c.hide()
        state = seed.saveState()
        settings.setValue('ui/window_state', state)
        _bar(win, 'native')
        assert win.restoreState(state)
        # The Ruby/worker messages arrive after normal startup restoration.
        late_a, late_b, late_c = (_bar(win, k) for k in ('a', 'b', 'c'))
        assert win.toolBarArea(late_a) == Qt.TopToolBarArea
        app = ExtensionApp(win, 'test')
        assert app.restore_toolbar_layout()
        assert win.toolBarArea(late_a) == Qt.BottomToolBarArea
        assert win.toolBarArea(late_b) == Qt.BottomToolBarArea
        assert win.toolBarBreak(late_b)
        assert win.toolBarArea(late_c) == Qt.LeftToolBarArea
        assert late_c.isHidden()
        # A repeated ready must not override a move made after startup.
        win.addToolBar(Qt.RightToolBarArea, late_a)
        assert not app.restore_toolbar_layout()
        assert win.toolBarArea(late_a) == Qt.RightToolBarArea
    finally:
        if old is None:
            settings.remove('ui/window_state')
        else:
            settings.setValue('ui/window_state', old)
        seed.close()
        win.close()


def test_fresh_profile_retains_default_toolbar_positions():
    settings = QSettings()
    old = settings.value('ui/window_state')
    settings.remove('ui/window_state')
    win = QMainWindow()
    try:
        bar = _bar(win, 'fresh')
        assert not ExtensionApp(win, 'fresh').restore_toolbar_layout()
        assert win.toolBarArea(bar) == Qt.TopToolBarArea
    finally:
        if old is None:
            settings.remove('ui/window_state')
        else:
            settings.setValue('ui/window_state', old)
        win.close()


def test_ingetrazo_window_places_and_packs_a_late_bar():
    """In IngeTrazo's own window the hook takes the setup() path: saved
    place restored, and the bar re-seated to its own length (a bare
    restoreState would bring back the stored length and its gap)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from views.main_window import MainWindow
    app_ = QApplication.instance() or QApplication([])
    settings = QSettings()
    old = settings.value('ui/window_state')
    first = MainWindow()
    try:
        first.show()
        app_.processEvents()
        bar = _bar(first, 'late_left', Qt.LeftToolBarArea)
        for k in range(5):                     # stored long: 6 actions
            bar.addAction(f'x{k}')
        settings.setValue('ui/window_state', first.saveState())
    finally:
        first._saved_version = first.viewport.scene.version
        first.close()
    win = MainWindow()
    try:
        win.show()
        app_.processEvents()
        late = _bar(win, 'late_left')          # arrives on top, 1 action
        assert win.toolBarArea(late) == Qt.TopToolBarArea
        assert ExtensionApp(win, 'late').restore_toolbar_layout()
        app_.processEvents()
        assert win.toolBarArea(late) == Qt.LeftToolBarArea
        assert late.height() <= late.sizeHint().height() + 2
    finally:
        if old is None:
            settings.remove('ui/window_state')
        else:
            settings.setValue('ui/window_state', old)
        win._saved_version = win.viewport.scene.version
        win.close()
