# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
import numpy as np
from views.vertex_index import index_vertices


def test_index_roundtrip_preserves_every_byte_and_triangle_order():
    rng = np.random.default_rng(6)
    a = rng.normal(size=(130, 6)).astype(np.float32)
    a[0, 1] = -0.0
    a = a[rng.integers(0, 130, size=5000)]
    raw, ix = index_vertices(a.tobytes(), 24)
    assert ix
    result = np.frombuffer(raw, 'V24')[np.frombuffer(ix, np.uint32)]
    assert result.tobytes() == a.tobytes()
    no = np.arange(60, dtype=np.float32).reshape(10, 6).tobytes()
    assert index_vertices(no, 24) == (no, b'')


def test_indexed_tape_opcode_and_fallback(monkeypatch):
    from views.viewport import _GlTape
    calls = []
    t = _GlTape()
    t.draw_indexed(lambda *a: calls.append(a), 4, 9, 6, 2)
    assert t.ops == [(11, 4, 6, 36, 2)]
    t.replay(None)
    assert len(calls) == 2
    assert tuple(calls[0][i] for i in (0, 1, 2, 4)) == (4, 6, 0x1405, 2)
    assert int(calls[0][3]) == 36


import pytest


@pytest.mark.parametrize('context', ['normal', 'cut', 'fade', 'shadow'])
def test_indexed_cocoa_exact_rgb32(monkeypatch, tmp_path, context):
    from PySide6.QtGui import QVector3D as V, QMatrix4x4, QImage
    from PySide6.QtWidgets import QApplication
    from core.group import Group
    from core.mesh import Mesh
    from views.main_window import MainWindow
    from views import vertex_index
    win = MainWindow(); win.resize(900, 700); win.show()
    QApplication.processEvents(); vp = win.viewport
    try:
        if vp._gl is None or not vp.isValid(): pytest.skip('requires real OpenGL')
        m = Mesh()
        m.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)]).attrs['color'] = (.2, .7, .3)
        m.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 0, 2)]).attrs['color'] = (.9, .1, .4)
        for j in range(12):
            m.add_face([V(0, j*.1, 0), V(2, j*.1, 0), V(2, (j+1)*.1, 0), V(0, (j+1)*.1, 0)])
        for texture_index in range(2):
            image = QImage(2, 2, QImage.Format_RGB32)
            image.fill(0xffaa3344 + texture_index * 0x224422)
            path = str(tmp_path / f'texture{texture_index}.png'); image.save(path)
            for j in range(12):
                f = m.add_face([V(0, j*.1, 1+texture_index), V(2, j*.1, 1+texture_index),
                                V(2, (j+1)*.1, 1+texture_index), V(0, (j+1)*.1, 1+texture_index)])
                f.attrs['texture'] = {'path': path, 'sw': 1.0, 'sh': 1.0}
        for i in range(6):
            g = Group(m); g.xform = QMatrix4x4(); g.xform.translate(i*3, 0, 0)
            g.xform.rotate(i*19, V(1, 2, 3))
            if i % 2: g.xform.scale(-1, .7, 2)
            vp.scene.groups.append(g)
        vp.scene.version += 1; vp.camera.fit_to(V(-2, -3, -2), V(20, 5, 5))
        from core.section import SectionPlane
        if context == 'cut':
            vp.scene.section_planes = [SectionPlane(V(0, 0, .6), V(0, 0, 1), active=True)]
        elif context == 'fade':
            vp.set_edit_rest_mode('fade'); vp.begin_group_edit(vp.scene.groups[1])
        elif context == 'shadow':
            vp.scene.shadows.enabled = True
        real = vertex_index.index_vertices
        for mode in ('textures', 'shaded', 'monochrome', 'hidden_line', 'xray'):
            vp.scene.display_style.face_mode = mode
            for view in ('top', 'iso'):
                vp.camera.set_view(view)
                frames = []
                for packing in (lambda raw, stride: (raw, b''), real):
                    monkeypatch.setattr(vertex_index, 'index_vertices', packing)
                    vp.reset_document_caches(); vp.scene.version += 1
                    # Force both arms to rebuild: rust-0510 keeps camera
                    # batches/tapes and the shadow framebuffer separately.
                    vp._forget_frame_records()
                    vp._frame_cache = None
                    vp._shadow_key = None
                    img = vp.render_image(400, 300, overlays=False).convertToFormat(QImage.Format_RGB32)
                    frames.append(bytes(img.constBits()))
                    # The second frame exercises the recorded native tape too.
                    again = vp.render_image(400, 300, overlays=False).convertToFormat(QImage.Format_RGB32)
                    assert bytes(again.constBits()) == frames[-1]
                    if packing is real:
                        assert any(e.get('vcol_index_vbo') is not None for e in vp._proto_draw.values())
                        assert any(e.get('tex_index_vbo') is not None for e in vp._proto_draw.values())
                assert frames[0] == frames[1], (mode, view)
    finally:
        win._saved_content = vp.scene.content_version; win.close()


def test_native_indexed_replay_preserves_unsigned_offset_and_instance_count():
    import ctypes
    from core import _native
    native = _native.available()
    if native is None:
        pytest.skip('private native kernel required')
    calls = []
    callback_type = ctypes.CFUNCTYPE(None, ctypes.c_uint, ctypes.c_int,
                                   ctypes.c_uint, ctypes.c_void_p, ctypes.c_int)
    callback = callback_type(lambda *args: calls.append(args))
    pointer = ctypes.cast(callback, ctypes.c_void_p).value
    try:
        tape = native.GlReplay([pointer] * 12)
    except ValueError:
        pytest.skip('updated indexed replay kernel required')
    assert tape.run(np.array([[11, 4, 300, 128, 7]], np.int64), np.zeros((1, 4), np.float32)) == 1
    assert calls == [(4, 300, 0x1405, 128, 7)]
    legacy = native.GlReplay([pointer] * 11)
    with pytest.raises(ValueError, match='opcode'):
        legacy.run(np.array([[11, 4, 300, 128, 7]], np.int64), np.zeros((1, 4), np.float32))
