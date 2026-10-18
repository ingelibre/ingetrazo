# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The recorded instanced passes hold the GL context's own function
tables; once the context is gone (or remade) the viewport must hold none
of them — a stale PySide wrapper kept past its context was handed back
for a new object made at the same address, and another viewport's
initializeGL failed with a QOpenGLExtraFunctions for a context."""
from __future__ import annotations

_RECORDS = ("_lean_faces_rec", "_lean_edges_rec", "_gl_replay_memo",
            "_inst_frame_memo", "_frame_instanced")


def test_context_teardown_forgets_the_tapes():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        for forget in (vp._forget_context_objects, vp.release_gl_textures):
            for name in _RECORDS:
                setattr(vp, name, ("recorded", object()))
            forget()
            assert all(getattr(vp, n, None) is None for n in _RECORDS)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
