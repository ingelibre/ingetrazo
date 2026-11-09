# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A recreated GL context (the viewport moved to another window — what the
MultiView extension does) must not leave lazily made GL objects behind: the
image-plane VAO of the old context was bound in the new one and the app
segfaulted (10-10). initializeGL forgets them; the next frame remakes them."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_the_lazy_gl_objects_are_forgotten_when_the_context_is_remade():
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    try:
        sentinel = object()
        for name in vp._LAZY_GL:
            setattr(vp, name, sentinel)
        vp._proto_draw = {"k": sentinel}
        vp._fbo_size = (640, 480)
        vp._forget_context_objects()
        assert all(getattr(vp, name) is None for name in vp._LAZY_GL)
        assert vp._proto_draw == {}
        assert vp._fbo_size == (0, 0)
    finally:
        win._saved_version = vp.scene.version
        win.close()
