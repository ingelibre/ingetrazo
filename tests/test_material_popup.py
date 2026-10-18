# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Browser's floating material panel (#565, @fafecm): a click on a
row's Material cell opens it under the cell — the document's materials and
the recent paints as swatches, a search field, «No material», «New color…»
and «More materials…» — and the choice paints the row, or every selected
row when it is one of them, as one undo step."""
from __future__ import annotations

from PySide6.QtGui import QColor, QVector3D as V
from PySide6.QtWidgets import QApplication, QPushButton

from core.group import Group
from core.i18n import tr
from core.materials import Material
from core.mesh import Mesh
from views.outliner import COL_MATERIAL, COL_NAME, MaterialPopup


def _quad(x=0.0):
    m = Mesh()
    m.add_face([V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0)])
    return m


def _setup():
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    scene.groups.clear()
    groups = [Group(_quad(i * 2.0), name=n)
              for i, n in enumerate(("Muro", "Losa", "Mesa"))]
    scene.groups.extend(groups)
    scene.materials["Ladrillo"] = Material("Ladrillo", color=(0.7, 0.3, 0.2))
    scene.materials["Hormigón"] = Material("Hormigón", color=(0.6, 0.6, 0.6))
    scene.version += 1
    panel = win.project_browser.outliner
    panel.set_column_shown(COL_MATERIAL, True)
    panel.refresh()
    return win, scene, panel, groups


def _close(win, panel):
    panel.set_column_shown(COL_MATERIAL, False)
    win._saved_version = win.viewport.scene.version
    win.close()


def _row(panel, group):
    root = panel.tree.topLevelItem(0)
    for i in range(root.childCount()):
        if root.child(i).data(COL_NAME, 0x0100) is group:
            return root.child(i)
    raise AssertionError(group.name)


def _popups():
    return [w for w in QApplication.topLevelWidgets()
            if isinstance(w, MaterialPopup) and w.isVisible()]


def _swatch(popup, label):
    for name, b in popup._swatches:
        if name == label.casefold():
            return b
    raise AssertionError(label)


def _button(popup, text):
    for b in popup.findChildren(QPushButton):
        if b.text() == text:
            return b
    raise AssertionError(text)


def _press(panel, item, on_arrow=True):
    """A left press on ``item``'s Material cell: on its ▾, or on the rest
    of the cell."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import Qt
    from views.outliner import _MaterialCellDelegate
    tree = panel.tree
    head = tree.header()
    cell = tree.visualItemRect(item)
    cell.setLeft(head.sectionViewportPosition(COL_MATERIAL))
    cell.setWidth(head.sectionSize(COL_MATERIAL))
    arrow = _MaterialCellDelegate.arrow_rect(cell)
    pt = arrow.center() if on_arrow else cell.topLeft() +         (cell.center() - cell.topLeft()) / 4
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(pt),
                     QPointF(tree.viewport().mapToGlobal(pt)), Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(tree.viewport(), ev)
    rel = QMouseEvent(QEvent.MouseButtonRelease, QPointF(pt),
                      QPointF(tree.viewport().mapToGlobal(pt)), Qt.LeftButton,
                      Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(tree.viewport(), rel)


def test_the_cells_arrow_opens_the_panel_and_leaves_the_selection():
    """The ▾ opens the panel without selecting its row; the rest of the
    Material cell selects the row, as anywhere in it, and opens nothing."""
    win, scene, panel, (muro, losa, mesa) = _setup()
    try:
        win.project_browser.show()
        win.project_browser.raise_()
        panel.tree.resize(900, 300)
        panel.tree.setCurrentItem(_row(panel, muro))
        _press(panel, _row(panel, losa))
        pops = _popups()
        assert len(pops) == 1
        assert [i.text(0) for i in panel.tree.selectedItems()] == ["Muro"]
        labels = [n for n, _b in pops[0]._swatches]
        assert "ladrillo" in labels and "hormigón" in labels
        pops[0].close()
        _press(panel, _row(panel, losa), on_arrow=False)
        assert not _popups()
        assert [i.text(0) for i in panel.tree.selectedItems()] == ["Losa"]
    finally:
        _close(win, panel)


def test_a_plain_click_on_the_cell_opens_nothing():
    win, scene, panel, (muro, losa, mesa) = _setup()
    try:
        panel._on_item_clicked(_row(panel, losa), COL_MATERIAL)
        assert not _popups()
    finally:
        _close(win, panel)


def test_a_swatch_paints_the_row_in_one_undo_step():
    win, scene, panel, (muro, losa, mesa) = _setup()
    try:
        steps = len(win.viewport.history.undo_stack)
        pop = panel.material_popup(_row(panel, losa))
        _swatch(pop, "Ladrillo").click()
        assert losa.material["mat"] == "Ladrillo"
        assert muro.material is None and mesa.material is None
        assert not pop.isVisible()                     # gone on a choice
        assert len(win.viewport.history.undo_stack) == steps + 1
        assert _row(panel, losa).text(COL_MATERIAL) == "Ladrillo"
        win.viewport.history.undo()
        assert losa.material is None
    finally:
        _close(win, panel)


def test_on_a_selected_row_it_paints_every_selected_row():
    win, scene, panel, (muro, losa, mesa) = _setup()
    try:
        _row(panel, muro).setSelected(True)
        _row(panel, mesa).setSelected(True)
        pop = panel.material_popup(_row(panel, mesa))
        _swatch(pop, "Hormigón").click()
        assert muro.material["mat"] == mesa.material["mat"] == "Hormigón"
        assert losa.material is None                  # not selected
    finally:
        _close(win, panel)


def test_the_current_material_is_framed_and_no_material_takes_it_off():
    win, scene, panel, (muro, losa, mesa) = _setup()
    try:
        muro.material = {"color": [0.7, 0.3, 0.2], "mat": "Ladrillo"}
        scene.version += 1
        pop = panel.material_popup(_row(panel, muro))
        assert _swatch(pop, "Ladrillo").isChecked()
        assert not _swatch(pop, "Hormigón").isChecked()
        _button(pop, tr("No material")).click()
        assert muro.material is None
    finally:
        _close(win, panel)


def test_the_search_narrows_the_swatches():
    win, scene, panel, (muro, losa, mesa) = _setup()
    try:
        pop = panel.material_popup(_row(panel, muro))
        pop.search.setText("lad")
        assert not _swatch(pop, "Ladrillo").isHidden()
        assert _swatch(pop, "Hormigón").isHidden()
        pop.close()
    finally:
        _close(win, panel)


def test_a_new_color_with_a_name_becomes_a_material(monkeypatch):
    from views import color_dialog, prompts
    win, scene, panel, (muro, losa, mesa) = _setup()
    try:
        monkeypatch.setattr(color_dialog, "get_color",
                            lambda *a, **k: QColor(0, 128, 255))
        monkeypatch.setattr(prompts, "get_text",
                            lambda *a, **k: ("Azul fachada", True))
        pop = panel.material_popup(_row(panel, mesa))
        _button(pop, tr("New color…")).click()
        assert mesa.material["mat"] == "Azul fachada"
        assert "Azul fachada" in scene.materials
        assert scene.materials["Azul fachada"].color[2] == 1.0
    finally:
        _close(win, panel)


def test_a_new_color_without_a_name_is_a_plain_color(monkeypatch):
    from views import color_dialog, prompts
    win, scene, panel, (muro, losa, mesa) = _setup()
    try:
        monkeypatch.setattr(color_dialog, "get_color",
                            lambda *a, **k: QColor(255, 0, 0))
        monkeypatch.setattr(prompts, "get_text", lambda *a, **k: ("", True))
        pop = panel.material_popup(_row(panel, mesa))
        _button(pop, tr("New color…")).click()
        assert mesa.material == {"color": [1.0, 0.0, 0.0]}
    finally:
        _close(win, panel)


def test_more_materials_opens_the_library_and_paints_with_its_choice(
        monkeypatch):
    """«More materials…» opens the library in a window of its own, as «New
    color…» opens the colour dialog; what is picked there paints the row."""
    from views.outliner import MaterialLibraryDialog
    win, scene, panel, (muro, losa, mesa) = _setup()
    try:
        brick = {"texture": {"path": "brick.png", "sw": 1.0, "sh": 0.6,
                             "rot": 0.0}, "mat": "brick_red"}
        opened = []

        def choose(parent=None):
            opened.append(parent)
            return brick
        monkeypatch.setattr(MaterialLibraryDialog, "choose", choose)
        pop = panel.material_popup(_row(panel, muro))
        _button(pop, tr("More materials…")).click()
        assert opened
        assert muro.material["texture"]["path"] == "brick.png"
        assert "brick_red" in scene.materials          # registered with it
        assert not pop.isVisible()
    finally:
        _close(win, panel)


def test_closing_the_library_without_a_choice_paints_nothing(monkeypatch):
    from views.outliner import MaterialLibraryDialog
    win, scene, panel, (muro, losa, mesa) = _setup()
    try:
        monkeypatch.setattr(MaterialLibraryDialog, "choose",
                            lambda parent=None: None)
        pop = panel.material_popup(_row(panel, muro))
        _button(pop, tr("More materials…")).click()
        assert muro.material is None
    finally:
        _close(win, panel)


def test_the_library_holds_the_ral_colours_and_the_textures():
    from views.outliner import library_catalog
    cat = dict(library_catalog())
    colours = cat[tr("Colors")]
    assert len(colours) > 200
    label, paint, swatch = colours[0]
    assert paint["mat"].startswith("RAL ") and len(paint["color"]) == 3
    textures = [e for t, es in cat.items() if t != tr("Colors") for e in es]
    assert textures
    label, paint, swatch = textures[0]
    assert paint["texture"]["path"].endswith(".png")
    assert paint["texture"]["sw"] > 0 and paint["mat"] == label
    assert swatch() is not None                  # the image reads


def test_the_library_dialog_shows_a_category_searches_and_chooses():
    from views.outliner import MaterialLibraryDialog
    dlg = MaterialLibraryDialog()
    try:
        assert dlg.categories.count() >= 2
        first = len(dlg.buttons)
        assert first > 0                              # the colours, shown
        dlg.categories.setCurrentRow(1)
        assert 0 < len(dlg.buttons)
        dlg.search.setText("ral 9010")
        assert [label for label, _b in dlg.buttons][0].startswith("RAL 9010")
        dlg.buttons[0][1].click()
        assert dlg.chosen["mat"].startswith("RAL 9010")
        from PySide6.QtWidgets import QDialog
        assert dlg.result() == QDialog.DialogCode.Accepted
    finally:
        dlg.close()


def test_the_material_cell_shows_a_swatch():
    win, scene, panel, (muro, losa, mesa) = _setup()
    try:
        muro.material = {"color": [0.7, 0.3, 0.2], "mat": "Ladrillo"}
        scene.version += 1
        panel.refresh()
        assert not _row(panel, muro).icon(COL_MATERIAL).isNull()
        assert _row(panel, losa).icon(COL_MATERIAL).isNull()
    finally:
        _close(win, panel)


def test_the_library_opens_in_the_middle_of_the_screen():
    """Centred on the screen the program is on, and wholly on it — placed
    once shown, when its frame is known."""
    from views.outliner import MaterialLibraryDialog
    win, scene, panel, (muro, losa, mesa) = _setup()
    try:
        win.resize(1000, 700)
        win.show()
        QApplication.processEvents()
        dlg = MaterialLibraryDialog(panel)
        dlg.show()
        QApplication.processEvents()
        room = win.screen().availableGeometry()
        frame = dlg.frameGeometry()
        assert room.contains(frame)
        if frame.width() < room.width() and frame.height() < room.height():
            assert abs(frame.center().x() - room.center().x()) <= 2
            assert abs(frame.center().y() - room.center().y()) <= 2
        dlg.close()
    finally:
        _close(win, panel)
