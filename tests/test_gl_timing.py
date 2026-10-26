# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Timer collection never waits on unfinished work or changes rendered pixels."""
import numpy as np
import pytest

from views.gl_timing import GpuTimings


class Query:
    def __init__(self):
        self.ready = False
        self.active = False
        self.destroyed = False

    def create(self):
        return True

    def begin(self):
        assert not self.active
        self.active = True

    def end(self):
        assert self.active
        self.active = False

    def isResultAvailable(self):
        return self.ready

    def waitForResult(self):
        assert self.ready, 'must not wait for GPU work'
        return 1_234_567

    def destroy(self):
        self.destroyed = True


def test_bounded_queries_only_read_available_results_and_reuse_objects():
    lines = []
    timer = GpuTimings(lambda *a, **k: lines.append(a), Query, limit=2)
    timer.frame(7)
    timer.begin('faces')
    timer.begin('edges')
    timer.end()
    timer.frame(8)
    timer.begin('faces')
    assert len(timer._queries) == 2
    assert lines[0][0] == 'gpu_dropped'
    timer._queries[0].ready = True
    timer.frame(9)
    assert len(timer._pending) == 1
    assert lines[-1][1] == 1.234567
    assert 'frame=7 pass=faces' in lines[-1][2]
    timer.begin('depth_readback')
    assert len(timer._queries) == 2
    queries = list(timer._queries)
    timer.destroy()
    assert all(q.destroyed and not q.active for q in queries)
    assert not timer._pending


def test_unsupported_query_disables_sampling():
    class Unavailable(Query):
        def create(self):
            return False
    lines = []
    timer = GpuTimings(lambda *a, **k: lines.append(a), Unavailable)
    for i in range(3):
        timer.frame(i)
        timer.begin('faces')
        timer.end()
    assert [line[0] for line in lines] == ['gpu_unavailable']


def _pixels(image):
    image = image.convertToFormat(image.Format.Format_RGB32)
    return np.frombuffer(image.constBits(), np.uint8).reshape(
        image.height(), image.bytesPerLine())[:, :image.width() * 4].copy()


def test_cocoa_gpu_passes_are_nonnegative_and_pixel_identical(monkeypatch):
    from PySide6.QtGui import QVector3D as V
    from PySide6.QtWidgets import QApplication
    from core.group import Group
    from core.mesh import Mesh
    import views.viewport as vm
    from views.main_window import MainWindow

    lines = []
    monkeypatch.setattr(vm, '_PERF', True)
    monkeypatch.setattr(vm, '_plog', lambda *a, **k: lines.append(a))
    win = MainWindow()
    win.resize(900, 700)
    win.show()
    QApplication.processEvents()
    vp = win.viewport
    try:
        if vp._gl is None or not vp.isValid():
            pytest.skip('requires Cocoa or another real OpenGL platform')
        mesh = Mesh()
        mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)])
        vp.scene.groups.append(Group(mesh))
        vp.scene.version += 1
        vp.camera.fit_to(V(-1, -1, -1), V(3, 3, 1))
        monkeypatch.setattr(vp, '_annotations_need_depth', lambda: True)
        for view in ('top', 'iso'):
            vp.camera.set_view(view)
            vp.repaint()
            timed = _pixels(vp.grabFramebuffer())
            vp.makeCurrent()
            vp._gl.glFinish()  # test only: guarantee completed samples
            vp._gpu_timings.frame(vp._tick + 1)
            vp.doneCurrent()
            with monkeypatch.context() as patch:
                patch.setattr(vm, '_PERF', False)
                vp.repaint()
                plain = _pixels(vp.grabFramebuffer())
            np.testing.assert_array_equal(timed, plain)
        samples = [line for line in lines if line[0] == 'gpu_pass']
        assert samples, 'a real GL context must produce timer results'
        assert all(line[1] >= 0 for line in samples)
        for name in ('faces', 'edges', 'silhouettes', 'overlay', 'blit', 'depth_readback'):
            assert any(f'pass={name} ' in line[2] for line in samples)
        # Queries also end on the export early-return path.
        vp.render_image(320, 240, overlays=False)
        assert vp._gpu_timings._active is None
    finally:
        win._saved_content = vp.scene.content_version
        win.close()
