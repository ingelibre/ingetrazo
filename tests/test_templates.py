# SPDX-License-Identifier: GPL-3.0-or-later
"""Document templates (File > Save As Template / New from Template)."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from core import templates  # noqa: E402

NEW_MESSAGES = [
    "Save As Template\u2026",
    "Save As Template",
    "Name:",
    "Description:",
    "File:",
    "Set as default template",
    "Save",
    "Cancel",
    "A template with that name already exists. Replace it?",
    "Template saved: {name}",
    "Keep this document's settings (units, layers, materials, styles, camera) as a template for new documents.",
    "New from Template",
    "Start a new project from one of your saved templates.",
    "No templates yet",
    "Blank document",
    "Start a new project without any template.",
    "Default template",
    "None (blank document)",
    "The template that File \u25b8 New starts from. Save one with File \u25b8 Save As Template\u2026"
]


def test_safe_name_drops_forbidden_characters():
    assert templates._safe_name('a/b\\c:d*e?"f<g>h|i') == "a_b_c_d_e_f_g_h_i"
    assert templates._safe_name("  ..  ") == "Plantilla"


def test_read_info_without_json_uses_the_file_name(tmp_path):
    p = tmp_path / "Civil.igz"
    p.write_bytes(b"")
    assert templates.read_info(p) == {"name": "Civil", "description": ""}


def test_read_info_reads_name_and_description(tmp_path):
    p = tmp_path / "civil.igz"
    p.write_bytes(b"")
    templates.info_path(p).write_text(
        json.dumps({"name": "Civil", "description": "Metros"}),
        encoding="utf-8")
    assert templates.read_info(p) == {"name": "Civil",
                                      "description": "Metros"}


def test_list_templates_is_sorted_and_only_igz(tmp_path, monkeypatch):
    monkeypatch.setattr(templates, "templates_dir", lambda: tmp_path)
    for n in ("b.igz", "A.igz", "c.json", "d.txt"):
        (tmp_path / n).write_bytes(b"")
    assert [p.name for p in templates.list_templates()] == ["A.igz", "b.igz"]


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_save_waits_for_a_name():
    _app()
    from views.template_dialog import SaveTemplateDialog
    d = SaveTemplateDialog()
    assert not d._ok.isEnabled()
    d._name.setText("Civil")
    assert d._ok.isEnabled()
    d._name.setText("  ")
    assert not d._ok.isEnabled()


def test_dialog_file_follows_the_name_until_edited():
    _app()
    from views.template_dialog import SaveTemplateDialog
    d = SaveTemplateDialog()
    d._name.setText("Civil")
    assert d._file.text() == "Civil"
    d._file.textEdited.emit("x")
    d._file.setText("mine")
    d._name.setText("Other")
    assert d._file.text() == "mine"
    assert d.file_stem() == "mine" and d.name() == "Other"


def test_every_new_message_is_in_every_catalog():
    from core.i18n import _I18N_DIR
    for path in sorted(_I18N_DIR.glob("*.json")):
        if path.stem == "en":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in NEW_MESSAGES if k not in data]
        assert not missing, f"{path.stem}: {missing[:2]}"
