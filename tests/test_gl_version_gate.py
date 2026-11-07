# SPDX-License-Identifier: GPL-3.0-or-later
"""A context below OpenGL 3.3 gets no shaders and no GL objects (issue #751).

Qt's software fallback on Windows (``opengl32sw.dll``) hands out a 3.0
context; the ``#version 330 core`` shaders cannot compile there, and the
GL objects made and freed on it were the likely source of the crashes. CI
has no GPU, so the viewport runs here against a fake GL."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

import core.glinfo
from core.glinfo import GL_RENDERER, GL_VENDOR, GL_VERSION
from views import viewport as viewport_module
from views.viewport import GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, Viewport


class _FakeGL:
    def __init__(self, version):
        self.strings = {GL_VENDOR: "Mesa", GL_RENDERER: "llvmpipe",
                        GL_VERSION: version}
        self.calls: list = []

    def initializeOpenGLFunctions(self):
        pass

    def glGetString(self, enum):
        return self.strings[enum]

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, args))


class _Compiled(Exception):
    pass


class _Signal:
    def __init__(self):
        self.sent: list = []

    def emit(self, value):
        self.sent.append(value)

    def connect(self, slot):
        self.sent.append(slot)


class _Context:
    def __init__(self):
        self.aboutToBeDestroyed = _Signal()


class _Viewport:
    """Just what initializeGL, resizeGL and paintGL touch."""

    def __init__(self):
        self._gl = None
        self._program = None
        self.glReady = _Signal()
        self.gl_context = _Context()

    def context(self):
        return self.gl_context

    def _forget_context_objects(self):
        pass

    def release_gl_textures(self):
        pass

    def _compile_program(self):
        raise _Compiled

    def _sync_axes(self):
        pass

    def _sync_projection(self):
        pass


@pytest.fixture
def viewport(monkeypatch):
    monkeypatch.setattr(core.glinfo, "write_gl_report", lambda info: None)
    return _Viewport()


def _initialize(viewport, monkeypatch, version):
    fake = _FakeGL(version)
    monkeypatch.setattr(viewport_module, "QOpenGLFunctions", lambda context: fake)
    Viewport.initializeGL(viewport)
    return fake


def test_gl_3_0_compiles_nothing_and_only_clears(viewport, monkeypatch):
    fake = _initialize(viewport, monkeypatch, "3.0 Mesa 11.2.2")
    assert viewport._program is None
    assert viewport.glReady.sent[0]["supported"] is False
    assert viewport.glReady.sent[0]["version"] == "3.0 Mesa 11.2.2"
    # Nothing to free at teardown, so nothing runs on the dying context.
    assert viewport.gl_context.aboutToBeDestroyed.sent == []

    fake.calls.clear()
    Viewport.resizeGL(viewport, 800, 600)        # would make the scene FBO
    Viewport.paintGL(viewport)
    assert fake.calls == [("glClear", (GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT,))]


def test_gl_4_6_goes_on_to_compile_the_shaders(viewport, monkeypatch):
    with pytest.raises(_Compiled):
        _initialize(viewport, monkeypatch, "4.6.0 NVIDIA 552.44")


def test_the_error_names_renderer_and_version_once(monkeypatch):
    from views import main_window
    shown: list = []
    monkeypatch.setattr(main_window.QMessageBox, "critical",
                        lambda parent, title, text: shown.append(text))

    class _Window:
        pass

    window = _Window()
    info = {"version": "3.0 Mesa 11.2.2",
            "renderer": "Gallium 0.4 on llvmpipe (LLVM 3.6, 256 bits)"}
    main_window.MainWindow._warn_gl_unsupported(window, info)
    main_window.MainWindow._warn_gl_unsupported(window, info)
    assert len(shown) == 1
    assert "OpenGL 3.0 Mesa 11.2.2" in shown[0]
    assert "llvmpipe" in shown[0]
