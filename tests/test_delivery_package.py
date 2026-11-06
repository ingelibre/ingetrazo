# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end delivery and its refusal paths, using real model/sheet exporters."""
import copy
import json
import os
from pathlib import Path
import zipfile

import pytest

from core.composition import Composicion, MarcoVista
from core.delivery_workflow import model_fingerprint
from core.turkiye_delivery import check_scene
from tests.test_delivery_workflow import full_scene


def window_with_project():
    from views.main_window import MainWindow
    win = MainWindow()
    win.viewport.scene = full_scene()
    win.viewport.history.scene = win.viewport.scene
    win.viewport.scene.compositions = [Composicion(name="Software test sheet", frames=[
        MarcoVista(view_key="std:front", style="vectorial")])]
    return win


def close_window(win):
    win._saved_version = win.viewport.scene.version
    win.close()


@pytest.mark.parametrize("language", ["en", "tr"])
def test_workflow_editor_cancel_undo_and_explicit_revision_confirmation(language):
    from views.delivery_workflow import WorkflowDialog
    from core import i18n
    previous = i18n.current_language(); i18n.set_language(language)
    win = window_with_project()
    try:
        before = copy.deepcopy(win.viewport.scene.ifc_project)
        dialog = WorkflowDialog(win)
        dialog.edits[("project", "name")][0].setText("260002")
        dialog.reject()
        assert win.viewport.scene.ifc_project == before
        dialog = WorkflowDialog(win)
        dialog.confirm()
        assert win.viewport.scene.ifc_project["review"]["model_fingerprint"] == model_fingerprint(win.viewport.scene)
        dialog.edits[("project", "description")][0].setText("Changed project")
        assert dialog.apply()
        assert any(r["review"] == "pending" for r in check_scene(win.viewport.scene)["checks"])
        win.viewport.history.undo()
        assert win.viewport.scene.ifc_project["description"] == before["description"]
        dialog = WorkflowDialog(win)
        dialog.quality.item(0, 2).setText("Changed review evidence")
        assert dialog.apply()
        assert "model_fingerprint" not in win.viewport.scene.ifc_project["review"]
        dialog.close()
    finally:
        close_window(win)
        i18n.set_language(previous)


def test_archival_export_requires_persistent_view_without_touching_output(tmp_path):
    from views.composer import ComposerWindow
    win = window_with_project(); composer = None
    try:
        composer = ComposerWindow(win)
        composer.comp = win.viewport.scene.compositions[0]
        composer.comp.frames[0].view_key = "__current__"
        target = tmp_path / "existing.pdf"; target.write_bytes(b"preserve")
        with pytest.raises(ValueError, match="standard or saved"):
            composer.export_pdf(str(target), archival=True)
        assert target.read_bytes() == b"preserve"
    finally:
        if composer: composer.close()
        close_window(win)


def test_archival_sheet_is_independently_pdfa_validated(tmp_path):
    validator = os.environ.get("INGETRAZO_TEST_VERAPDF")
    if not validator:
        pytest.skip("Set INGETRAZO_TEST_VERAPDF to exercise the external PDF/A validator")
    from views.composer import ComposerWindow
    from formats.delivery_package import validate_pdfa
    win = window_with_project(); composer = None
    try:
        composer = ComposerWindow(win)
        composer.comp = win.viewport.scene.compositions[0]
        target = tmp_path / "sheet.pdf"
        composer.export_pdf(str(target), archival=True)
        result = validate_pdfa(target, validator)
        assert result["verified"] and result["profile"] == "PDF/A-1b"
    finally:
        if composer: composer.close()
        close_window(win)


def test_real_verified_delivery_package(tmp_path):
    validator = os.environ.get("INGETRAZO_TEST_VERAPDF")
    if not validator:
        pytest.skip("Set INGETRAZO_TEST_VERAPDF for the full delivery integration test")
    from formats.delivery_package import build_package, digest
    win = window_with_project()
    try:
        scene = win.viewport.scene
        scene.ifc_project["validator"] = validator
        scene.ifc_project["review"]["model_fingerprint"] = model_fingerprint(scene)
        target = tmp_path / "delivery.zip"
        manifest = build_package(win, target)
        with zipfile.ZipFile(target) as archive:
            report = json.loads(archive.read("quality.json"))
            assert report["release_ready"]
            assert len(report["checks"]) == 21
            for name, expected in manifest["files"].items():
                import hashlib
                assert hashlib.sha256(archive.read(name)).hexdigest() == expected
        output = os.environ.get("INGETRAZO_TEST_ARTIFACTS")
        if output:
            import shutil
            Path(output).mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, Path(output) / "fictional-verified-delivery.zip")
        # No stale review can replace an existing good package.
        before = digest(target)
        scene.ifc_project["description"] = "New revision without a new review"
        with pytest.raises(ValueError, match="Delivery blocked"):
            build_package(win, target)
        assert digest(target) == before
        assert target.with_suffix(".checks.json").is_file()
    finally:
        close_window(win)
