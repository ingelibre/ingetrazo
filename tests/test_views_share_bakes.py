# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The views of one document draw from one set of bakes.

Splitting the plaza (1 035 objects) into four views took 16.7 s the first
time: each new view baked the whole model again — the chunks of the
groups, the instances' derived chunks, the prototypes' stand-ins — though
none of that depends on the view, only its upload to each view's own GL
context does. A document now has one store of those bakes, shared by
every viewport that shows it; a view that joins draws from what the
window's view baked. Another document is another store, and a reload in
the same document still empties it (an id reused by a new group must not
meet an old entry)."""
from __future__ import annotations

import gc
import sys
import weakref

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core.group import Group                             # noqa: E402
from core.mesh import Mesh                               # noqa: E402
from core.scene import Scene                             # noqa: E402
from views import array_bake                             # noqa: E402
from views import viewport as VPM                        # noqa: E402


def _gl_usable() -> bool:
    """A GL context that can be made current. The offscreen platform on
    Windows has none: no view ever bakes there, and QOpenGLTexture without
    a current context is an access violation (ronda Windows 0.6.2)."""
    from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
    ctx = QOpenGLContext()
    if not ctx.create():
        return False
    surface = QOffscreenSurface()
    surface.create()
    ok = surface.isValid() and ctx.makeCurrent(surface)
    if ok:
        ctx.doneCurrent()
    return ok


pytestmark = pytest.mark.skipif(not _gl_usable(),
                                reason="no usable OpenGL context")


def _box(mesh, x0, y0, z0, s=1.0):
    x1, y1, z1 = x0 + s, y0 + s, z0 + s
    for loop in (
            [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],
            [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
            [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
            [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)],
            [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],
            [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]):
        mesh.add_face([V(*p) for p in loop])


def _fill(scene, n=6):
    """Groups, an instanced pair sharing a prototype, loose faces."""
    for k in range(n):
        m = Mesh()
        _box(m, 2.0 * k, 0, 0, 1.0)
        scene.groups.append(Group(m, f"g{k}"))
    proto = Mesh()
    _box(proto, 0, 0, 0, 0.8)
    from PySide6.QtGui import QMatrix4x4
    for k in range(3):
        g = Group(proto, "inst")
        xf = QMatrix4x4()
        xf.translate(2.0 * k, 3.0, 0.0)
        g.xform = xf
        scene.groups.append(g)
    _box(scene.loose_mesh, 0, -3, 0, 1.0)
    scene.version += 1


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 800)
    w.show()
    _fill(w.viewport.scene)
    w.viewport.notify_scene_changed()
    QApplication.processEvents()
    w.viewport.grabFramebuffer()
    w.viewport.grabFramebuffer()
    yield w
    for doc in list(w._documents):
        doc.saved_content = doc.viewport.scene.content_version
    w._saved_version = w.viewport.scene.version
    w.close()


def _views(win):
    return [c.viewport for c in win._doc.view_grid.cells
            if c.viewport is not None]


def test_the_views_that_join_bake_nothing_the_window_baked(win, monkeypatch):
    main = win.viewport
    baked_before = len(main._group_chunks)
    assert baked_before > 0
    bakes = []
    real = array_bake.bake

    def counted(*a, **k):
        bakes.append(1)
        return real(*a, **k)

    monkeypatch.setattr(array_bake, "bake", counted)
    chunks = []
    real_chunk = VPM.Viewport._group_chunk

    def spy(self, group):
        n = len(self._group_chunks)
        out = real_chunk(self, group)
        if len(self._group_chunks) != n:
            chunks.append(group)
        return out

    monkeypatch.setattr(VPM.Viewport, "_group_chunk", spy)
    win.set_view_layout("four")
    QApplication.processEvents()
    for vp in _views(win):
        vp.grabFramebuffer()
    QApplication.processEvents()
    extras = [vp for vp in _views(win) if vp is not main]
    assert len(extras) == 3
    # One store: the same dicts, nothing added to them by the new views.
    for vp in extras:
        assert vp._group_chunks is main._group_chunks
        assert vp._inst_chunks is main._inst_chunks
        assert vp._proto_wrappers is main._proto_wrappers
    assert bakes == [] and chunks == []
    assert len(main._group_chunks) == baked_before


def test_a_view_draws_from_the_shared_bakes_what_it_draws_from_its_own(win):
    """The picture of a view that joined, drawn from the window's bakes,
    is the picture it draws from bakes of its own, pixel for pixel."""
    win.set_view_layout("four")
    QApplication.processEvents()
    main = win.viewport
    # The front view: the boxes show their sides, a picture with some
    # colour in it (from above they are flat squares of one grey).
    extra = next(c.viewport for c in win._doc.view_grid.cells
                 if c.view == "front")
    assert extra is not main
    lo, hi = main.scene.bounds()
    extra.camera.fit_to(lo, hi, 1.2)
    # Both pictures from a cold view (its memos dropped, the shared bakes
    # kept): a warm view and a cold one differ by a few pixels of their
    # own, before any sharing — the one variable here is whose bakes.
    extra.reset_document_caches(keep_bakes=True)
    extra._vbo_parts.clear()
    extra._edges_version = -1
    extra.notify_scene_changed()            # as a document switch does
    QApplication.processEvents()
    extra.grabFramebuffer()
    shared = extra.grabFramebuffer()
    assert extra._group_chunks is main._group_chunks
    # The same view, its caches its own and empty, as at a document
    # boundary (the memos that hang off the bakes go too): it bakes
    # everything again.
    extra.reset_document_caches()
    for name in VPM._SHARED_BAKES:
        setattr(extra, name, {})
    extra._vbo_parts.clear()
    extra._edges_version = -1
    extra.notify_scene_changed()
    QApplication.processEvents()
    extra.grabFramebuffer()
    own = extra.grabFramebuffer()
    assert all(getattr(extra, n) is not getattr(main, n)
               for n in VPM._SHARED_BAKES)
    from core import _native
    if _native.native is None:
        # On Python the groups bake into the chunk caches: it did bake
        # again. (The Rust engine draws a built model through its instance
        # path, whose geometry lives on the meshes themselves.)
        assert len(extra._group_chunks) > 0
    assert own.size() == shared.size() and own == shared
    # And the picture is of the model, not of the sky alone: more than one
    # colour in the middle rows, where the boxes stand.
    import numpy as np
    rgb = own.convertToFormat(own.Format.Format_RGB32)
    px = np.frombuffer(rgb.constBits(), np.uint8,
                       count=rgb.sizeInBytes()).reshape(
        rgb.height(), rgb.bytesPerLine() // 4, 4)[:, :rgb.width(), :3]
    middle = px[px.shape[0] // 3: 2 * px.shape[0] // 3]
    assert len(np.unique(middle.reshape(-1, 3), axis=0)) > 20


def test_another_document_is_another_store_and_a_reload_empties_it():
    from views.viewport import Viewport
    vp = Viewport(None)
    _fill(vp.scene)
    vp.notify_scene_changed()
    vp.resize(400, 300)
    vp.show()
    QApplication.processEvents()
    vp.grabFramebuffer()
    vp.grabFramebuffer()
    old_scene, old_chunks = vp.scene, vp._group_chunks
    assert len(old_chunks) > 0
    assert VPM._bake_store_of(old_scene)["_group_chunks"] is old_chunks
    # The GL side alone goes on a move: the bakes stay.
    vp.reset_document_caches(keep_bakes=True)
    assert len(vp._group_chunks) == len(old_chunks) > 0
    # A document boundary: the old store emptied, a new store bound.
    from core.history import History
    new = Scene()
    vp.set_document(new, History(new))
    assert vp._group_chunks is not old_chunks and len(vp._group_chunks) == 0
    assert len(old_chunks) == 0
    assert vp._group_chunks is VPM._bake_store_of(new)["_group_chunks"]
    # The old scene gone, its store goes with it.
    key = id(old_scene)
    del old_scene, old_chunks
    gc.collect()
    hit = VPM._BAKE_STORES.get(key)
    assert hit is None or hit[0]() is not None     # gone, or another's
    vp.close()


def test_a_texture_is_decoded_once_for_every_view(tmp_path, monkeypatch):
    """Each view's GL context uploads its own texture, from one decoding
    of the file; a changed file is decoded again."""
    import os
    import time
    from PySide6.QtGui import QColor, QImage
    from views.viewport import Viewport
    png = tmp_path / "t.png"
    img = QImage(8, 8, QImage.Format_RGBA8888)
    img.fill(QColor(200, 30, 30))
    img.save(str(png))
    made = []
    real = VPM.QImage

    class Counting(real):
        def __init__(self, *a):
            if a and isinstance(a[0], str):
                made.append(a[0])
            super().__init__(*a)

    monkeypatch.setattr(VPM, "QImage", Counting)
    VPM._DECODED_TEXTURES.pop(str(png), None)
    vps = [Viewport(None), Viewport(None)]
    try:
        for vp in vps:
            vp.resize(200, 150)
            vp.show()
        QApplication.processEvents()
        for vp in vps:
            vp.makeCurrent()
            try:
                tex = vp._get_texture(str(png))
                assert tex is not None and vp._get_texture(str(png)) is tex
            finally:
                vp.doneCurrent()
        assert made == [str(png)]                 # decoded once, two uploads
        # The file changed: decoded again for the next upload.
        time.sleep(0.01)
        img.fill(QColor(30, 200, 30))
        img.save(str(png))
        os.utime(str(png), None)
        vps[0]._tex_cache.clear()
        vps[0].makeCurrent()
        try:
            vps[0]._get_texture(str(png))
        finally:
            vps[0].doneCurrent()
        assert made == [str(png), str(png)]
    finally:
        for vp in vps:
            vp.close()
