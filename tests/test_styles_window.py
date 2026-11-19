# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Browse existing styles and keep their editor open while modeling."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QToolBar, QToolButton

from core.i18n import tr
from core.scene import Scene
from core.style import BUILTIN_STYLES, FACE_MODES, Style, save_user_style, user_styles


class _Viewport:
    def __init__(self):
        self.scene = Scene()
        self.updates = 0

    def update(self):
        self.updates += 1


class _StatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message, timeout):
        self.messages.append((message, timeout))


class _Window:
    def __init__(self):
        self.viewport = _Viewport()
        self.panel = None
        self.status_bar = _StatusBar()

    def _sync_style_menu(self):
        if self.panel is not None:
            self.panel.refresh()

    def statusBar(self):
        return self.status_bar


@pytest.fixture
def style_library(tmp_path, monkeypatch):
    """Keep saved collections separate from the developer's style library."""
    import core.style as styles

    path = tmp_path / "styles.ini"
    monkeypatch.setattr(styles, "_settings",
                        lambda: QSettings(str(path), QSettings.IniFormat))


@pytest.fixture
def editor(style_library):
    from views.tray import StylesPanel

    window = _Window()
    panel = StylesPanel(window)
    window.panel = panel
    yield window, panel
    panel.close()
    panel.deleteLater()


def _items(panel, kind):
    return [panel._library.item(i) for i in range(panel._library.count())
            if panel._library.item(i).data(Qt.UserRole)
            and panel._library.item(i).data(Qt.UserRole)[0] == kind]


def _find_item(panel, kind, key):
    return next(item for item in _items(panel, kind)
                if item.data(Qt.UserRole)[1] == key)


def _browse(panel, collection):
    index = panel._collection.findData(collection)
    assert index >= 0
    panel._collection.setCurrentIndex(index)


def test_edit_categories_expose_the_existing_controls(editor):
    window, panel = editor
    before = window.viewport.scene.display_style.to_dict()
    assert [panel._tabs.tabText(i) for i in range(panel._tabs.count())] == [
        tr("Select"), tr("Edit"), tr("Mix")]
    panel._tabs.setCurrentIndex(1)
    controls = ((panel._edges, panel._profiles, panel._back_edges, panel._edge_c),
                (panel._mode, panel._front_c, panel._back_c, panel._ao),
                (panel._sky, panel._sky_c, panel._ground_c, panel._bg_c),
                (),
                (panel._fill, panel._fill_c))
    assert len(panel._edit_buttons) == len(controls)
    for index, category_controls in enumerate(controls):
        panel._edit_buttons[index].click()
        assert panel._edit_stack.currentIndex() == index
        assert panel._edit_buttons[index].isChecked()
        assert sum(button.isChecked() for button in panel._edit_buttons) == 1
        assert panel._category_title.text()
        for control in category_controls:
            assert panel._edit_stack.currentWidget().isAncestorOf(control)
    # Looking through categories must not change any display setting.
    assert window.viewport.scene.display_style.to_dict() == before


def test_folders_open_builtin_thumbnails_and_apply_independent_presets(editor):
    window, panel = editor
    assert {item.data(Qt.UserRole)[1] for item in _items(panel, "folder")} == {
        "builtin", "user"}
    panel._open_library_item(_find_item(panel, "folder", "builtin"))
    assert panel._collection.currentData() == "builtin"
    assert {item.data(Qt.UserRole)[1] for item in _items(panel, "style")} == {
        style.name for style in BUILTIN_STYLES}
    hidden = _find_item(panel, "style", "Hidden line")
    assert not hidden.icon().isNull()
    panel._open_library_item(hidden)
    style = window.viewport.scene.display_style
    assert style.face_mode == "hidden_line" and not style.sky
    assert panel._combo.currentData() == "Hidden line"
    assert not panel._del_btn.isEnabled()
    style.edges = False
    assert next(s for s in BUILTIN_STYLES if s.name == "Hidden line").edges
    assert window.viewport.updates > 0
    panel._go_home()
    assert len(_items(panel, "folder")) == 2


def test_saved_collection_applies_the_existing_user_library(editor):
    window, panel = editor
    saved = Style(name="Workshop", face_mode="monochrome", sky=False,
                  edge_color=(0.2, 0.3, 0.4), section_fill=False)
    save_user_style(saved)
    panel.refresh()
    _browse(panel, "user")
    assert [item.data(Qt.UserRole)[1] for item in _items(panel, "style")] == [
        "Workshop"]
    panel._open_library_item(_find_item(panel, "style", "Workshop"))
    assert window.viewport.scene.display_style.to_dict() == saved.to_dict()
    assert panel._del_btn.isEnabled()
    assert panel._collection.currentData() == "user"
    assert panel._tabs.currentIndex() == 0


def test_an_empty_saved_collection_keeps_the_active_style(editor):
    window, panel = editor
    before = window.viewport.scene.display_style.to_dict()
    _browse(panel, "user")
    assert _items(panel, "style") == []
    assert window.viewport.scene.display_style.to_dict() == before
    panel._go_home()
    assert len(_items(panel, "folder")) == 2


def test_save_and_delete_update_the_collection_but_keep_the_active_look(editor, monkeypatch):
    from views import tray

    window, panel = editor
    panel._edges.setChecked(False)
    style = window.viewport.scene.display_style
    monkeypatch.setattr(tray._prompts, "get_text", lambda *a, **k: ("  Workshop  ", True))
    panel._on_save()
    assert style.name == "Workshop"
    assert panel._collection.currentData() == "user"
    saved_item = _find_item(panel, "style", "Workshop")
    assert saved_item.text() == "Workshop" and not saved_item.icon().isNull()
    assert panel._combo.currentText() == "Workshop"
    assert panel._del_btn.isEnabled()
    assert [saved.to_dict() for saved in user_styles()] == [style.to_dict()]
    assert window.status_bar.messages

    before_delete = style.to_dict()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    panel._on_delete()
    assert user_styles() == []
    assert _items(panel, "style") == []
    assert panel._collection.currentData() == "user"
    assert not panel._del_btn.isEnabled()
    assert window.viewport.scene.display_style is style
    assert style.to_dict() == before_delete
    assert panel._combo.currentText() == "Workshop"
    assert tr("Custom style") in panel._style_hint.text()


def test_preview_distinguishes_face_modes_and_updates_existing_colors():
    from views.style_preview import style_preview

    size = QSize(100, 80)
    images = [style_preview(Style(face_mode=mode), size).toImage() for mode in FACE_MODES]
    assert all(not image.isNull() and image.size() == size for image in images)
    assert len({bytes(image.constBits()) for image in images}) == len(FACE_MODES)

    baseline = style_preview(Style(), size).toImage()
    for attr in ("edge_color", "front_color", "back_color", "sky_color", "ground_color"):
        style = Style()
        setattr(style, attr, (0.9, 0.1, 0.2))
        assert style_preview(style, size).toImage() != baseline, attr


def test_refresh_keeps_navigation_and_does_not_rewrite_loaded_values(editor):
    window, panel = editor
    _browse(panel, "user")
    panel._tabs.setCurrentIndex(1)
    panel._edit_buttons[2].click()
    loaded = Style(name="Imported drawing", face_mode="wireframe",
                   back_color=None, ao_distance=0.37, sky=False)
    window.viewport.scene.display_style = loaded
    before = loaded.to_dict()
    panel.refresh()
    assert panel._tabs.currentIndex() == 1
    assert panel._edit_stack.currentIndex() == 2
    assert panel._collection.currentData() == "user"
    assert panel._combo.currentText() == loaded.name
    assert loaded.to_dict() == before
    assert panel._mode.currentData() == "wireframe"
    assert not panel._sky.isChecked()


def test_return_in_editor_does_not_open_unrelated_dialogs(editor, monkeypatch):
    from views import tray
    from views.styles_window import StylesWindow

    _window, panel = editor
    opened = []
    monkeypatch.setattr(panel, "_pick_color", lambda *a: opened.append("color"))

    def save_prompt(*args, **kwargs):
        opened.append("save")
        return "", False

    def delete_prompt(*args, **kwargs):
        opened.append("delete")
        return QMessageBox.No

    monkeypatch.setattr(tray._prompts, "get_text", save_prompt)
    monkeypatch.setattr(QMessageBox, "question", delete_prompt)
    dialog = StylesWindow(None, panel)
    try:
        panel._tabs.setCurrentIndex(1)
        panel._edit_buttons[0].click()
        dialog.show()
        QApplication.processEvents()
        for control in (panel._edit_buttons[0], panel._edges):
            control.setFocus(Qt.OtherFocusReason)
            QTest.keyClick(control, Qt.Key_Return)
            QApplication.processEvents()
            assert opened == []
            assert dialog.isVisible()
    finally:
        panel.setParent(None)
        dialog.close()


def test_toolbar_opens_one_modeless_resizable_styles_window(style_library):
    from views.main_window import MainWindow

    window = MainWindow()
    try:
        toolbar = window.findChild(QToolBar, "panels_toolbar")
        assert toolbar is not None
        button = window.findChild(QToolButton, "styles_button")
        assert button is not None and button.menu() is None
        other_buttons = [widget for action in toolbar.actions()
                         if isinstance(widget := toolbar.widgetForAction(action), QToolButton)
                         and widget is not button]
        assert len(other_buttons) == 2
        assert all(widget.menu() is not None for widget in other_buttons)

        button.click()
        QApplication.processEvents()
        dialog = window._styles_window
        assert isinstance(dialog, QDialog)
        assert dialog.isVisible() and not dialog.isModal()
        assert dialog.isAncestorOf(window.styles_panel)
        original = dialog.size()
        dialog.resize(original.width() + 100, original.height() + 80)
        assert dialog.width() > original.width()
        assert dialog.height() > original.height()

        # The same style controls stay live while the window remains open.
        panel = window.styles_panel
        panel._tabs.setCurrentIndex(1)
        assert window._act_style_edges.isChecked()
        window._act_style_edges.setChecked(False)
        assert not panel._edges.isChecked()
        assert not window.viewport.scene.display_style.edges
        panel._xray.setChecked(True)
        assert window.viewport.scene.display_style.face_mode == "textures"
        assert window.viewport.scene.display_style.xray
        assert not window.viewport.scene.display_style.edges
        assert dialog.isVisible()
        dialog.close()
        assert not dialog.isVisible()
        button.click()
        assert window._styles_window is dialog and dialog.isVisible()
        assert panel._tabs.currentIndex() == 1
        assert not panel._edges.isChecked()
    finally:
        if window._styles_window is not None:
            window._styles_window.close()
        window._saved_version = window.viewport.scene.version
        window.close()
