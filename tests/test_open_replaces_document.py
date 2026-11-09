# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #602 (ArchXQ IT): File ▸ Open of another document kept the
previous document's section planes. The writer leaves a block out when it
holds the default (no planes, nothing hidden…), so the loader must reset
what the file does not bring — otherwise it leaks from the document that
was open before. One fixture that sets every such field, one plain file,
and the scene must end exactly as if the plain file were the only one
ever opened.

Issue #765 is the same leak for dimensions: ``load_into()`` appended the
file's dimensions without clearing the previous ones, so they doubled on
every open/save cycle. The rich fixture carries dimensions too."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.dimension import Dimension  # noqa: E402
from core.layers import Layer  # noqa: E402
from core.scene import Scene  # noqa: E402
from core.section import SectionPlane  # noqa: E402
from formats import igz  # noqa: E402

_app = QApplication.instance() or QApplication([])

#: Runtime-only or identity fields: not document state, or compared apart.
_SKIP = {"mesh", "version", "view_version", "selection"}


def _square(scene, z=0.0):
    scene.mesh.add_face([QVector3D(0, 0, z), QVector3D(1, 0, z),
                         QVector3D(1, 1, z), QVector3D(0, 1, z)])


def _rich(tmp_path):
    s = Scene()
    _square(s)
    s.section_planes = [
        SectionPlane(QVector3D(0, 0, 1), QVector3D(0, 0, 1), "Plan", "P",
                     active=True),
        SectionPlane(QVector3D(0.5, 0, 0), QVector3D(1, 0, 0), "A", "A")]
    s.show_section_planes = False
    s.show_section_cuts = False
    s.show_hidden_objects = True
    s.show_hidden_geometry = True
    s.show_axes = False
    s.back_face_color = (0.1, 0.2, 0.3)
    s.custom_scales = [33.0]
    s.layers.append(Layer("Walls"))
    s.dimension_style = dict(s.dimension_style, extra_key=1)
    s.dimensions.append(Dimension(QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                                  QVector3D(0, -1, 0)))
    s.dimensions.append(Dimension(QVector3D(0, 0, 0), QVector3D(0, 1, 0),
                                  QVector3D(-1, 0, 0)))
    path = tmp_path / "rich.igz"
    igz.save_scene(s, path)
    return path


def _plain(tmp_path):
    s = Scene()
    _square(s, 2.0)
    path = tmp_path / "plain.igz"
    igz.save_scene(s, path)
    return path


def _state(scene):
    out = {}
    for k, v in vars(scene).items():
        if k.startswith("_") or k in _SKIP:
            continue
        if k == "layers":
            v = [(ly.name, ly.visible) for ly in v]
        out[k] = repr(v)
    return out


def test_opening_a_plain_file_drops_the_previous_section_planes(tmp_path):
    rich, plain = _rich(tmp_path), _plain(tmp_path)
    scene = Scene()
    igz.load_into(scene, rich)
    assert len(scene.section_planes) == 2      # the fixture does load them
    igz.load_into(scene, plain)
    assert scene.section_planes == []
    assert scene.show_section_planes is True
    assert scene.show_section_cuts is True


def _dimension_points(scene):
    return [((d.a.x(), d.a.y(), d.a.z()), (d.b.x(), d.b.y(), d.b.z()),
             (d.offset.x(), d.offset.y(), d.offset.z()))
            for d in scene.dimensions]


def test_opening_a_plain_file_drops_the_previous_dimensions(tmp_path):
    rich, plain = _rich(tmp_path), _plain(tmp_path)
    scene = Scene()
    igz.load_into(scene, rich)
    assert len(scene.dimensions) == 2      # the fixture does load them
    igz.load_into(scene, plain)
    assert scene.dimensions == []


def test_reopening_the_same_file_does_not_double_its_dimensions(tmp_path):
    rich = _rich(tmp_path)
    scene = Scene()
    for _ in range(3):
        igz.load_into(scene, rich)
        assert len(scene.dimensions) == 2


def test_a_file_with_dimensions_brings_exactly_its_own(tmp_path):
    rich, plain = _rich(tmp_path), _plain(tmp_path)
    scene = Scene()
    igz.load_into(scene, plain)
    igz.load_into(scene, rich)
    assert _dimension_points(scene) == [
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
        ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)),
    ]


def test_nothing_of_the_previous_document_survives_an_open(tmp_path):
    rich, plain = _rich(tmp_path), _plain(tmp_path)
    fresh = Scene()
    igz.load_into(fresh, plain)
    reused = Scene()
    igz.load_into(reused, rich)
    igz.load_into(reused, plain)
    a, b = _state(fresh), _state(reused)
    leaks = {k: (a.get(k), b.get(k)) for k in set(a) | set(b)
             if a.get(k) != b.get(k)}
    assert leaks == {}


def test_a_file_with_planes_still_brings_its_own(tmp_path):
    """The reset must not eat what the file does carry."""
    rich, plain = _rich(tmp_path), _plain(tmp_path)
    scene = Scene()
    igz.load_into(scene, plain)
    igz.load_into(scene, rich)
    assert [p.name for p in scene.section_planes] == ["Plan", "A"]
    assert scene.section_planes[0].active
    assert scene.show_section_planes is False
    assert scene.show_section_cuts is False
    assert scene.show_hidden_objects is True
    assert scene.show_hidden_geometry is True
    assert scene.show_axes is False
    assert scene.back_face_color == (0.1, 0.2, 0.3)
    assert scene.custom_scales == [33.0]
    assert [ly.name for ly in scene.layers][-1] == "Walls"


def test_new_after_a_document_with_only_planes_clears_them():
    """File ▸ New: ``Scene.clear`` skipped its reset when the document
    held nothing but section planes."""
    s = Scene()
    s.section_planes = [SectionPlane(QVector3D(0, 0, 1),
                                     QVector3D(0, 0, 1))]
    s.show_section_cuts = False
    s.clear()
    assert s.section_planes == []
    assert s.show_section_cuts is True


def _close(win):
    win._saved_version = win.viewport.scene.version     # no «save?» modal
    win.close()


def test_the_window_opens_another_file_without_the_old_planes(tmp_path):
    """Through the real File ▸ Open path: the menu toggles, the Outliner's
    section folder and the drawn picture all follow the opened file — the
    picture compared with a window that only ever opened the plain one."""
    from views.main_window import MainWindow
    rich, plain = _rich(tmp_path), _plain(tmp_path)
    win = MainWindow()
    win.show()
    QApplication.processEvents()
    try:
        assert win.open_path(rich)
        QApplication.processEvents()
        assert len(win.viewport.scene.section_planes) == 2
        assert not win._act_show_splanes.isChecked()
        assert win.open_path(plain)
        QApplication.processEvents()
        scene = win.viewport.scene
        assert scene.section_planes == []
        assert win._act_show_splanes.isChecked()
        assert win._act_show_scuts.isChecked()
        browser = getattr(win, "project_browser", None)
        if browser is not None:
            # On screen, the Outliner refreshes 300 ms after the last change
            # (on purpose: one refresh per burst of edits); hidden, when it
            # is shown. Wait for it as a person would see it.
            from PySide6.QtTest import QTest
            ol = browser.outliner
            if ol.isVisible():
                for _ in range(40):
                    if ol._sec_root is None or ol._sec_root.childCount() == 0:
                        break
                    QTest.qWait(50)
            else:
                ol.refresh()
            if ol._sec_root is not None:
                assert ol._sec_root.childCount() == 0
        vp = win.viewport
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            return                       # no GL here: the data checks stand
        vp.setFixedSize(400, 300)       # same frame as the reference
        QApplication.processEvents()
        reused = vp.render_image(320, 240)
    finally:
        _close(win)
    ref = MainWindow()
    ref.show()
    QApplication.processEvents()
    try:
        assert ref.open_path(plain)
        QApplication.processEvents()
        ref.viewport.setFixedSize(400, 300)
        QApplication.processEvents()
        expected = ref.viewport.render_image(320, 240)
    finally:
        _close(ref)
    assert reused is not None and expected is not None
    assert reused == expected


def test_a_file_already_doubled_opens_with_each_dimension_once(tmp_path):
    # #765: files saved before the fix hold each dimension many times over
    # (1024 entries for 8 in the report). Opening one heals it.
    s = Scene()
    _square(s, 2.0)
    one = (QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(0, -1, 0))
    two = (QVector3D(0, 0, 0), QVector3D(0, 1, 0), QVector3D(-1, 0, 0))
    for _ in range(8):
        s.dimensions.append(Dimension(*one))
        s.dimensions.append(Dimension(*two))
    path = tmp_path / "doubled.igz"
    igz.save_scene(s, path)
    scene = Scene()
    igz.load_into(scene, path)
    assert sorted(_dimension_points(scene)) == sorted([
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
        ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)),
    ])
    # …and saving it again writes the healed list.
    igz.save_scene(scene, path)
    again = Scene()
    igz.load_into(again, path)
    assert len(again.dimensions) == 2


def test_two_dimensions_that_differ_in_anything_both_stay(tmp_path):
    s = Scene()
    _square(s, 2.0)
    a, b = QVector3D(0, 0, 0), QVector3D(1, 0, 0)
    s.dimensions.append(Dimension(a, b, QVector3D(0, -1, 0)))
    s.dimensions.append(Dimension(a, b, QVector3D(0, -2, 0)))   # farther out
    s.dimensions.append(Dimension(a, b, QVector3D(0, -1, 0), text="A"))
    path = tmp_path / "three.igz"
    igz.save_scene(s, path)
    scene = Scene()
    igz.load_into(scene, path)
    assert len(scene.dimensions) == 3
