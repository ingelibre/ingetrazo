"""Right-click on a component says "Component", not "Group" (#1412).

The entries act the same; only their names follow what is selected: a
component reads Edit Component / Explode Component, a classic group keeps
Edit Group / Explode Group, and a mix of both keeps "Explode Group"."""
from __future__ import annotations

from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group, edit_label, explode_label
from core.mesh import Mesh


def _quad(x=0.0, size=1.0):
    m = Mesh()
    m.add_face([V(x, 0, 0), V(x + size, 0, 0), V(x + size, size, 0),
                V(x, size, 0)])
    return m


def _plain(name, x=0.0):
    return Group(_quad(x), name=name)


def _component(name, x=0.0):
    g = Group(_quad(), name=name)
    xf = QMatrix4x4()
    xf.translate(x, 0.0, 0.0)
    g.xform = xf
    g.component = True
    return g


def test_the_labels_follow_what_is_selected():
    plain, comp = _plain("Losa"), _component("Silla", 3.0)
    assert edit_label(plain) == "Edit Group"
    assert edit_label(comp) == "Edit Component"
    assert explode_label([plain]) == "Explode Group"
    assert explode_label([comp]) == "Explode Component"
    assert explode_label([comp, _component("Mesa", 6.0)]) == \
        "Explode Component"
    assert explode_label([comp, plain]) == "Explode Group"   # a mix
    assert explode_label([]) == "Explode Group"


def test_a_group_with_a_matrix_is_still_a_group():
    # A placed group that is not a component (``component`` False) is
    # not called one.
    g = _plain("Pieza")
    g.xform = QMatrix4x4()
    g.component = False
    assert edit_label(g) == "Edit Group"
    assert explode_label([g]) == "Explode Group"


def test_every_language_translates_the_new_entries():
    import glob
    import json
    import os
    here = os.path.join(os.path.dirname(__file__), os.pardir, "i18n")
    for path in glob.glob(os.path.join(here, "*.json")):
        with open(path, encoding="utf8") as fh:
            table = json.load(fh)
        if "Edit Group" not in table:      # en.json: English is the key
            continue
        for key in ("Edit Component", "Explode Component"):
            assert table.get(key), (os.path.basename(path), key)


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.viewport.scene.groups.clear()
    win.viewport.scene.version += 1
    return win


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_the_view_right_click_names_a_component(monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu
    import views.main_window as mw

    class _Menu(QMenu):
        opened: list = []

        def exec(self, *a, **k):
            _Menu.opened.append(self)
            return None

    monkeypatch.setattr(mw, "QMenu", _Menu)
    win = _window()
    try:
        sc = win.viewport.scene
        plain, comp = _plain("Losa"), _component("Silla", 3.0)
        sc.groups.extend([plain, comp])
        sc.version += 1

        def entries(sel):
            _Menu.opened.clear()
            sc.select(sel)
            win.show_viewport_context_menu(QPoint(0, 0))
            return [a.text() for a in _Menu.opened[0].actions()]

        on_comp = entries([comp])
        assert "Edit Component" in on_comp
        assert "Explode Component" in on_comp
        assert "Edit Group" not in on_comp
        assert "Explode Group" not in on_comp

        on_plain = entries([plain])
        assert "Edit Group" in on_plain
        assert "Explode Group" in on_plain
        assert "Edit Component" not in on_plain

        on_both = entries([plain, comp])
        assert "Explode Group" in on_both
        assert "Explode Component" not in on_both
    finally:
        _close(win)


def _row_menu_texts(panel, item):
    """The Browser row menu's entries, read while it is open."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    found = []

    def read():
        menu = QApplication.activePopupWidget()
        if menu is None:
            QTimer.singleShot(10, read)
            return
        found.extend(a.text() for a in menu.actions())
        menu.close()
    QTimer.singleShot(0, read)
    panel._on_context_menu(panel.tree.visualItemRect(item).center())
    return found


def test_the_browser_row_menu_names_a_component():
    win = _window()
    try:
        sc = win.viewport.scene
        plain, comp = _plain("Losa"), _component("Silla", 3.0)
        sc.groups.extend([plain, comp])
        sc.version += 1
        panel = win.project_browser.outliner
        panel.refresh()
        on_comp = _row_menu_texts(panel, panel._items[id(comp)])
        assert "Explode Component" in on_comp
        assert "Explode Group" not in on_comp
        on_plain = _row_menu_texts(panel, panel._items[id(plain)])
        assert "Explode Group" in on_plain
        assert "Explode Component" not in on_plain
    finally:
        _close(win)
