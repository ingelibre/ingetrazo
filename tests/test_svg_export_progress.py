# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Working out a big model's visible faces for the SVG export shows a bar
with Cancel, and Cancel stops it.

Seen on a 1 035-object plaza: exporting the view as SVG, or only
previewing «Faces in colour», froze the window for minutes, with nothing
to say it was working and no way to give up but killing the program.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

pytest.importorskip("manifold3d")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt                 # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402

from core import progress as P                         # noqa: E402
from core import vista_caras as VC                      # noqa: E402
from core.vista_caras import FaceFill                   # noqa: E402
from tests.test_view_faces_cost import _scene           # noqa: E402
from views import export_svg_dialog as D                # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _faces(n=300):
    return [FaceFill(**vars(f)) for f in _scene(np.random.default_rng(5), n)]


# ---- The visible faces say how far they have come --------------------------

def test_the_visible_faces_tell_how_far_they_have_come(monkeypatch):
    monkeypatch.setattr(P, "REPORT_EVERY", 0.0)
    told = []
    plain = VC._visible_parts(_faces())
    with P.reporting(told.append):
        reported = VC._visible_parts(_faces())
    assert P._report is None
    assert len(set(told)) > 100
    assert told == sorted(told)
    assert 0.0 <= told[0] and told[-1] < 1.0
    # Reporting changes nothing of what comes out.
    assert ([(f.depth, [r.tolist() for r in f.rings]) for f in reported]
            == [(f.depth, [r.tolist() for r in f.rings]) for f in plain])


def test_a_report_that_raises_stops_the_work_there(monkeypatch):
    monkeypatch.setattr(P, "REPORT_EVERY", 0.0)
    done = []
    real = VC._take_away

    def counted(visible, covers):
        done.append(1)
        return real(visible, covers)

    monkeypatch.setattr(VC, "_take_away", counted)
    VC._visible_parts(_faces())
    whole = len(done)
    done.clear()

    class Enough(Exception):
        pass

    def stop(at):
        if at > 0.25:
            raise Enough()

    with pytest.raises(Enough):
        with P.reporting(stop):
            VC._visible_parts(_faces())
    assert P._report is None
    assert 0 < len(done) < 0.5 * whole


def test_every_stretch_of_the_work_is_heard(monkeypatch):
    """Gathering the faces, filing them, cutting them down and their
    shadows: a stretch that said nothing was a window Windows marked as
    not responding before the bar came (14 s of a plaza's preview)."""
    from core.scene import Scene
    from tests.test_export_view_svg import _box, _camera, _sunny
    scene = Scene()
    from core.group import Group
    from core.mesh import Mesh
    for k in range(40):
        g = Group(Mesh(), name=f"c{k}")
        _box(g.mesh, x0=1.5 * (k % 8), y0=1.5 * (k // 8))
        scene.groups.append(g)
    scene.version += 1
    cam = _camera(scene)
    heard = []
    real_tick = P.tick

    def where(done=None):
        import sys
        heard.append(sys._getframe(1).f_code.co_name)
        real_tick(done)

    monkeypatch.setattr(P, "tick", where)
    _sunny(scene)
    with P.reporting(lambda done: None):
        VC.view_faces(scene, cam, shadows=True)
    assert {"view_faces", "__init__", "_visible_parts",
            "_cast_shadows"} <= set(heard)
    # And the hidden lines drawn over them (8.7 s of the plaza's export
    # after the faces, with nothing said).
    from core.hlr import hlr_drawing
    heard.clear()
    with P.reporting(lambda done: None):
        hlr_drawing(scene, cam)
    assert {"eat_mesh", "_merge_collinear"} <= set(heard)


# ---- The bar ----------------------------------------------------------------

def _bars(monkeypatch, cancel_after=None, watch=None):
    """Bars that record what they were told; Cancel pressed once they have
    shown ``cancel_after`` values (``None``: never)."""
    made = []

    class Bar(D.QProgressDialog):
        def __init__(self, *a):
            super().__init__(*a)
            self.values = []
            self.held = []
            made.append(self)

        def setValue(self, v):
            self.values.append(v)
            super().setValue(v)

        def wasCanceled(self):
            if watch is not None:
                self.held.append(watch.updatesEnabled())
            return cancel_after is not None and len(self.values) > cancel_after

    monkeypatch.setattr(D, "QProgressDialog", Bar)
    return made


def test_a_small_model_never_sees_the_bar(monkeypatch):
    _app()
    made = _bars(monkeypatch)
    monkeypatch.setattr(P, "REPORT_EVERY", 0.0)
    with D.faces_progress(None):
        VC._visible_parts(_faces(20))
    assert made == []


def test_cancel_on_the_bar_raises_and_puts_everything_back(monkeypatch):
    from PySide6.QtWidgets import QWidget
    _app()
    view = QWidget()
    made = _bars(monkeypatch, cancel_after=3, watch=view)
    monkeypatch.setattr(P, "REPORT_EVERY", 0.0)
    monkeypatch.setattr(D, "PROGRESS_AFTER", 0.0)
    QApplication.setOverrideCursor(Qt.WaitCursor)        # the export's own
    try:
        with pytest.raises(D.SvgCancelled):
            with D.faces_progress(None, view):
                VC._visible_parts(_faces())
        # The arrow over Cancel is gone, the work's wait cursor is back.
        assert QApplication.overrideCursor().shape() == Qt.WaitCursor
    finally:
        QApplication.restoreOverrideCursor()
    assert QApplication.overrideCursor() is None
    assert len(made) == 1
    bar = made[0]
    assert bar.windowModality() == Qt.WindowModal
    assert len(bar.values) == 4 and bar.values == sorted(bar.values)
    # The view painted nothing meanwhile, and paints again after.
    assert bar.held and not any(bar.held)
    assert view.updatesEnabled()
    assert not bar.isVisible()
    assert P._report is None


def _window_with_faces():
    from tests.test_export_view_svg import _two_layer_scene
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    vp.resize(800, 600)
    vp.camera.set_aspect(800, 600)
    _two_layer_scene(vp.scene)
    vp.notify_scene_changed()
    lo, hi = vp.scene.bounds()
    vp.camera.fit_to(lo, hi, 1.2)
    vp.camera.perspective = False
    return win


def _export(win, monkeypatch, path):
    from views import main_window as mw
    monkeypatch.setattr(D, "ask_svg_options", lambda parent, *a, **k: (
        True, {"materials": True, "textures": True, "as_view": True}, None))
    monkeypatch.setattr(mw.file_dialogs, "getSaveFileName",
                        lambda *a, **k: (str(path), ""))
    win._on_export_view_svg()


def test_cancel_stops_the_export_and_writes_nothing(tmp_path, monkeypatch):
    _app()
    win = _window_with_faces()
    try:
        made = _bars(monkeypatch, cancel_after=0, watch=win.viewport)
        monkeypatch.setattr(P, "REPORT_EVERY", 0.0)
        monkeypatch.setattr(D, "PROGRESS_AFTER", 0.0)
        _export(win, monkeypatch, tmp_path / "vista.svg")
        assert not (tmp_path / "vista.svg").exists()
        assert len(made) == 1 and made[0].held == [False]
        assert win.statusBar().currentMessage() == "SVG export cancelled"
        assert win.viewport.updatesEnabled()
        assert QApplication.overrideCursor() is None
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_bar_left_alone_writes_the_svg_as_before(tmp_path, monkeypatch):
    _app()
    win = _window_with_faces()
    try:
        _export(win, monkeypatch, tmp_path / "antes.svg")
        made = _bars(monkeypatch)
        monkeypatch.setattr(P, "REPORT_EVERY", 0.0)
        monkeypatch.setattr(D, "PROGRESS_AFTER", 0.0)
        win2 = _window_with_faces()
        try:
            _export(win2, monkeypatch, tmp_path / "con-barra.svg")
        finally:
            win2._saved_version = win2.viewport.scene.version
            win2.close()
        assert len(made) == 1 and made[0].values
        before = (tmp_path / "antes.svg").read_text(encoding="utf-8")
        after = (tmp_path / "con-barra.svg").read_text(encoding="utf-8")
        assert "<path" in before and before == after
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_cancel_on_a_slow_preview_turns_the_preview_off(tmp_path,
                                                        monkeypatch):
    _app()
    settings = QSettings(str(tmp_path / "svg.ini"), QSettings.IniFormat)
    built = []

    def build(options, paper=None, preview=False):
        built.append(preview)
        VC._visible_parts(_faces())
        return "<svg/>", 0

    dlg = D.ExportSvgDialog(None, build, settings=settings, advanced=True)
    try:
        dlg.preview_box.setChecked(True)
        made = _bars(monkeypatch, cancel_after=1)
        monkeypatch.setattr(P, "REPORT_EVERY", 0.0)
        monkeypatch.setattr(D, "PROGRESS_AFTER", 0.0)
        built.clear()
        dlg._refresh_preview()
        assert built == [True] and len(made) == 1
        assert not dlg.preview_box.isChecked()
        assert dlg.preview.text() == "Preview off"
        assert QApplication.overrideCursor() is None
    finally:
        dlg.deleteLater()


def test_a_preview_does_not_start_inside_another(tmp_path, monkeypatch):
    """The bar lets the events through while a preview works: the preview
    timer, firing then, started a second one inside the first."""
    _app()
    settings = QSettings(str(tmp_path / "svg.ini"), QSettings.IniFormat)
    built, inside = [], []

    def build(options, paper=None, preview=False):
        built.append(preview)
        if len(built) == 1:
            dlg._refresh_preview()             # the timer, meanwhile
            inside.append(len(built))
        return "<svg/>", 0

    dlg = D.ExportSvgDialog(None, build, settings=settings, advanced=True)
    try:
        dlg.preview_box.setChecked(True)
        dlg._timer.stop()
        built.clear()
        dlg._refresh_preview()
        assert inside == [1] and built == [True]
        # The one asked for meanwhile comes after.
        assert dlg._timer.isActive()
        dlg._timer.stop()
        dlg._refresh_preview()
        assert built == [True, True]
    finally:
        dlg.deleteLater()


def test_cancel_stops_the_composer_frame_export(tmp_path, monkeypatch):
    from core.composition import MarcoVista
    from tests.test_export_view_svg import _two_layer_scene
    from views import composer as C
    from views.main_window import MainWindow
    _app()
    monkeypatch.setattr(C.ComposerWindow, "render_frame",
                        lambda self, f: None)
    win = MainWindow()
    comp = C.ComposerWindow(win)
    try:
        _two_layer_scene(win.viewport.scene)
        win.viewport.notify_scene_changed()
        frame = MarcoVista(view_key="std:top", scale_n=100.0,
                           w_mm=100.0, h_mm=100.0)

        class Item:
            model = frame

        monkeypatch.setattr(C, "FrameItem", Item)
        monkeypatch.setattr(comp, "_selected_item", lambda: Item())
        monkeypatch.setattr(D, "ask_svg_options", lambda parent, *a, **k: (
            True, {"materials": True, "textures": True, "as_view": True},
            None))
        monkeypatch.setattr(C.file_dialogs, "getSaveFileName",
                            lambda *a, **k: (str(tmp_path / "marco"), ""))
        made = _bars(monkeypatch, cancel_after=0, watch=win.viewport)
        monkeypatch.setattr(P, "REPORT_EVERY", 0.0)
        monkeypatch.setattr(D, "PROGRESS_AFTER", 0.0)
        comp._on_export_svg()
        assert len(made) == 1 and made[0].held == [False]
        assert not (tmp_path / "marco.svg").exists()
        assert comp.statusBar().currentMessage() == "SVG export cancelled"
        assert win.viewport.updatesEnabled()
        assert QApplication.overrideCursor() is None
        # Left alone, the bar lets it write the frame.
        made = _bars(monkeypatch)
        comp._on_export_svg()
        assert len(made) == 1 and (tmp_path / "marco.svg").exists()
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
