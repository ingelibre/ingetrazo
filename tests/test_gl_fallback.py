# SPDX-License-Identifier: GPL-3.0-or-later
"""Recovering from a driver that will not give us a GL context.

The machine that reported this (Ubuntu 24.04 + GNOME 46 on Wayland, NVIDIA
Quadro P600, 2026-09-09) is not one CI can rent, so what is pinned here is
the DECISION TABLE around the probe, with the probe itself stubbed: which
outcome each situation produces, and above all that the process never
restarts itself twice.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QSurfaceFormat

from core import gl_fallback


class _App:
    """Stands in for the QApplication: the probe only asks it one thing."""

    def __init__(self, platform="wayland"):
        self._platform = platform

    def platformName(self):
        return self._platform


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(gl_fallback.GUARD_ENV, raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    # Both of these are process-wide, and the code under test writes to
    # them for real: registering them with monkeypatch is what puts them
    # back for whatever test file runs next in the same interpreter.
    monkeypatch.setenv("QT_QPA_PLATFORM",
                       os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    original = QSurfaceFormat.defaultFormat()
    yield
    QSurfaceFormat.setDefaultFormat(original)


def _format(stencil=8, samples=0):
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(stencil)
    if samples:
        fmt.setSamples(samples)
    return fmt


# ---- the leaner format ----------------------------------------------------

def test_leaner_gives_up_stencil_and_multisampling_but_keeps_depth():
    lean = gl_fallback.leaner(_format(stencil=8, samples=4))
    assert lean.stencilBufferSize() == 0
    assert lean.samples() == 0
    assert lean.depthBufferSize() == 24, "depth is what hidden-line needs"
    assert lean.majorVersion() == 3 and lean.minorVersion() == 3


def test_leaner_says_so_when_there_is_nothing_left_to_drop():
    assert gl_fallback.leaner(_format(stencil=0, samples=0)) is None


# ---- the decision table ---------------------------------------------------

def test_a_working_driver_costs_one_probe_and_nothing_else(monkeypatch):
    monkeypatch.setattr(gl_fallback, "_can_create", lambda fmt: True)
    monkeypatch.setattr(os, "execv", _never)
    assert gl_fallback.ensure_gl_context(_App()) == "ok"


def test_the_lean_format_is_tried_before_giving_up_on_wayland(monkeypatch):
    QSurfaceFormat.setDefaultFormat(_format(stencil=8, samples=4))
    monkeypatch.setattr(gl_fallback, "_can_create",
                        lambda fmt: fmt.stencilBufferSize() == 0)
    monkeypatch.setattr(os, "execv", _never)

    assert gl_fallback.ensure_gl_context(_App()) == "reduced"
    # And it becomes the format every later window is built with.
    assert QSurfaceFormat.defaultFormat().stencilBufferSize() == 0


def test_no_context_at_all_restarts_under_xcb(monkeypatch):
    QSurfaceFormat.setDefaultFormat(_format())
    monkeypatch.setattr(gl_fallback, "_can_create", lambda fmt: False)
    seen = {}

    def _fake_execv(path, argv):
        seen["path"], seen["argv"] = path, argv
        raise _Executed

    monkeypatch.setattr(os, "execv", _fake_execv)
    with pytest.raises(_Executed):
        gl_fallback.ensure_gl_context(_App())
    assert os.environ["QT_QPA_PLATFORM"] == "xcb"
    assert os.environ[gl_fallback.GUARD_ENV] == "1"


def test_the_restarted_process_does_not_restart_again(monkeypatch):
    """The point of the guard: no loop where X11 fails too."""
    QSurfaceFormat.setDefaultFormat(_format())
    monkeypatch.setenv(gl_fallback.GUARD_ENV, "1")
    monkeypatch.setattr(gl_fallback, "_can_create", lambda fmt: False)
    monkeypatch.setattr(os, "execv", _never)
    assert gl_fallback.ensure_gl_context(_App(platform="xcb")) == "failed"


def test_already_on_x11_has_nowhere_to_go(monkeypatch):
    QSurfaceFormat.setDefaultFormat(_format())
    monkeypatch.setattr(gl_fallback, "_can_create", lambda fmt: False)
    monkeypatch.setattr(os, "execv", _never)
    assert gl_fallback.ensure_gl_context(_App(platform="xcb")) == "failed"


def test_wayland_without_xwayland_says_so_instead_of_restarting(monkeypatch):
    """A Flatpak given only --socket=fallback-x11 lands here: Wayland is up,
    so the X11 socket was never handed over and DISPLAY is empty."""
    QSurfaceFormat.setDefaultFormat(_format())
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(gl_fallback, "_can_create", lambda fmt: False)
    monkeypatch.setattr(os, "execv", _never)
    assert gl_fallback.ensure_gl_context(_App()) == "no-x11"


def test_the_restarted_process_reports_that_it_is_the_xcb_one(monkeypatch):
    monkeypatch.setenv(gl_fallback.GUARD_ENV, "1")
    monkeypatch.setattr(gl_fallback, "_can_create", lambda fmt: True)
    monkeypatch.setattr(os, "execv", _never)
    assert gl_fallback.ensure_gl_context(_App(platform="xcb")) == "xcb"


class _Executed(Exception):
    """os.execv does not return; this is how the stub says it was reached."""


def _never(*_args, **_kwargs):
    raise AssertionError("the process restarted when it should not have")


def test_the_viewport_does_not_ask_the_dropped_stencil_back(monkeypatch):
    """The recovery is only real if the widget honours it.

    `Viewport.__init__` forces its own format — it has to, because many
    platforms ignore setDefaultFormat for QOpenGLWidget — so a format built
    from scratch there would ask for the stencil buffer that gl_fallback
    just gave up, and the driver we were rescuing would refuse the widget
    exactly as it refused everything else. Depth and samples stay ours.
    """
    from PySide6.QtWidgets import QApplication

    QSurfaceFormat.setDefaultFormat(_format(stencil=0))
    app = QApplication.instance() or QApplication([])
    assert app is not None

    from views.viewport import Viewport
    fmt = Viewport().format()

    assert fmt.stencilBufferSize() == 0, "asked the dropped stencil back"
    assert fmt.depthBufferSize() == 24, "hidden-line removal needs depth"
    assert fmt.samples() == 0, "MSAA belongs to the scene FBO, not the widget"
    assert (fmt.majorVersion(), fmt.minorVersion()) == (3, 3)
