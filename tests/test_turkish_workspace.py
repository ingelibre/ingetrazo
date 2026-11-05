# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ibrahim Halim Gokbulut (h-skycloud).
"""Turkish display metadata must never become model/schema identifiers."""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from core import i18n, string_search, units
from core.bim import IFC_CLASSES
from core.scene import Scene
from formats import ifc, igz
from views import command_search
from views.main_window import MainWindow
from views.workspace_profiles import offer_intro, show_intro


@pytest.fixture
def window(tmp_path, monkeypatch):
    import core.extensions
    monkeypatch.setattr(core.extensions, "plugin_dirs", lambda: [tmp_path])
    st = QSettings()
    before = {k: st.value(k) for k in st.allKeys()}
    st.clear()
    lang = i18n.current_language()
    i18n.set_language("tr")
    win = MainWindow()
    win.show()
    QApplication.processEvents()
    yield win
    win._saved_version = win.viewport.scene.version
    win.close()
    st.clear()
    for k, v in before.items():
        st.setValue(k, v)
    i18n.set_language(lang)


def test_turkish_system_language_and_persistence(window, monkeypatch):
    assert i18n.language_for_locales(["tr-TR"]) == "tr"
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    window._on_set_language("tr")
    assert QSettings().value("language") == "tr"
    assert i18n.resolve_language(QSettings().value("language")) == "tr"
    assert i18n.tr("File") == "Dosya"
    assert i18n.tr("not-a-catalog-key") == "not-a-catalog-key"


def test_ifc_picker_stores_codes_and_exports_them(window, tmp_path):
    panel = window.bim_tray.bim
    assert [panel.class_box.itemData(i) for i in range(panel.class_box.count())] == IFC_CLASSES
    index = panel.class_box.findData("IfcSlab")
    assert panel.class_box.itemText(index) == "IfcSlab — Döşeme"
    panel.class_box.setCurrentIndex(index)
    scene = window.viewport.scene
    face = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0),
                               QVector3D(2, 3, 0), QVector3D(0, 3, 0)])
    scene.selection.add(face)
    scene.units = {"length": "m", "precision": 2, "decimal": ","}
    panel._on_tag()
    assert face.attrs["ifc"]["class"] == "IfcSlab"
    assert "6,00" in panel.tree.topLevelItem(0).text(2)
    panel.active_check.setChecked(True)
    assert scene.active_ifc["class"] == "IfcSlab"
    saved = tmp_path / "turkish.igz"
    igz.save_scene(scene, saved)
    restored = Scene()
    igz.load_into(restored, saved)
    assert restored.mesh.faces[0].attrs["ifc"]["class"] == "IfcSlab"
    exported = tmp_path / "turkish.ifc"
    assert ifc.save_ifc(restored, exported) == 1
    data = exported.read_text(encoding="utf-8")
    assert "IFCSLAB(" in data
    assert "Döşeme" not in data
    assert "IfcDöşeme" not in data


def test_all_profiles_restore_original_and_keep_shortcuts(window):
    from views.shortcuts import collect_actions, action_key
    controller = window.workspace_profiles
    before = {b.objectName(): b.isHidden() for b in window.toolbars.values()}
    docks = {d.objectName(): d.isHidden() for d in window._sidebar_docks()}
    shortcuts = {action_key(a): a.shortcuts() for a in collect_actions(window)}
    for profile in ("cad", "bim", "simple"):
        controller.apply(profile)
        assert controller.current == profile
        assert str(QSettings().value("workspace_profiles/current")) == profile
        assert not window.toolbars["draw"].isHidden()
        if profile == "bim":
            assert not window.bim_tray.isHidden()
            assert not window.project_browser.isHidden()
    controller.apply("original")
    assert {b.objectName(): b.isHidden() for b in window.toolbars.values()} == before
    assert {d.objectName(): d.isHidden() for d in window._sidebar_docks()} == docks
    assert {action_key(a): a.shortcuts() for a in collect_actions(window)} == shortcuts


def test_profile_customization_is_restored(window):
    c = window.workspace_profiles
    c.apply("cad")
    window.toolbars["sections"].hide()
    c.apply("bim")
    c.apply("cad")
    assert window.toolbars["sections"].isHidden()
    window._saved_version = window.viewport.scene.version
    window.close()
    other = MainWindow()
    try:
        assert other.workspace_profiles.current == "cad"
        assert other.toolbars["sections"].isHidden()
    finally:
        other.close()


def test_unused_profiles_do_not_change_upstream_persistence(window):
    st = QSettings()
    hidden_before = st.value("ui/hidden_trays")
    assert not window.workspace_profiles.enabled
    window.close()
    assert not any(k.startswith("workspace_profiles/") for k in st.allKeys())
    assert st.value("ui/hidden_trays") == hidden_before


def test_original_folded_sidebar_returns_and_unfolds(window):
    original_open = {d.objectName() for d in window._sidebar_docks() if not d.isHidden()}
    window._act_sidebar.setChecked(False)
    c = window.workspace_profiles
    c.apply("bim")
    assert window._act_sidebar.isChecked()
    c.apply("original")
    assert not window._act_sidebar.isChecked()
    window._act_sidebar.setChecked(True)
    assert {d.objectName() for d in window._sidebar_docks() if not d.isHidden()} == original_open


def test_skipping_intro_changes_no_layout_or_units(window, monkeypatch):
    before = bytes(window.saveState())
    defaults = QSettings().value(units.NEW_DOCUMENT_KEY)
    monkeypatch.setattr(QDialog, "exec", lambda _: QDialog.Rejected)
    show_intro(window)
    assert bytes(window.saveState()) == before
    assert QSettings().value(units.NEW_DOCUMENT_KEY) == defaults
    assert not offer_intro(window)


def test_intro_metric_option_affects_only_new_documents(window, monkeypatch):
    from PySide6.QtWidgets import QCheckBox, QComboBox
    def accept(dialog):
        dialog.findChild(QCheckBox).setChecked(True)
        picker = dialog.findChild(QComboBox)
        picker.setCurrentIndex(picker.findData("bim"))
        return QDialog.Accepted
    monkeypatch.setattr(QDialog, "exec", accept)
    original_units = dict(window.viewport.scene.units)
    show_intro(window)
    assert window.workspace_profiles.current == "bim"
    assert units.new_document_units()["decimal"] == ","
    assert window.viewport.scene.units == original_units
    assert abs(units.parse("1,25m").value - 1.25) < 1e-9
    assert abs(units.parse("125cm").value - 1.25) < 1e-9


@pytest.mark.parametrize("query, tool", [("öteleme", "offset"), ("offset", "offset"),
                                       ("katılaştırma", "pushpull"), ("push pull", "pushpull")])
def test_bilingual_command_discovery(window, query, tool):
    assert window._tool_actions[tool] in [c.action for c in command_search.search(window, query)]


def test_turkish_search_handles_dotted_and_dotless_i():
    assert string_search.fold("İT IŞIK ıslak") == "it isik islak"
