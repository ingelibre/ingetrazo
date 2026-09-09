# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Recover from a platform that cannot give us the OpenGL context we ask for.

Reported by e-mail on 2026-09-09 (Ubuntu 24.04, GNOME 46 on Wayland,
NVIDIA Quadro P600): every context creation failed with

    QEGLPlatformContext: Failed to create context: 3009

3009 is hex — ``EGL_BAD_MATCH``: that driver's EGL has no desktop-OpenGL
config to match the 3.3 Core context :func:`main._configure_surface_format`
asks for. The same driver serves the very same request through GLX under
X11 without a murmur, so the machine runs IngeTrazo perfectly; it just
never got the chance, because nothing fell back. And because the request
is the *default* format, it poisons Qt's own backing store too
(``Failed to create QRhi for QBackingStoreRhiSupport``), so what the user
sees is not a broken viewport — it is an app that does not open.

``QT_QPA_PLATFORM="wayland;xcb"`` (what AppRun sets) does NOT cover this.
Qt walks that list while *loading the platform plugin*, and the Wayland
plugin loads fine; the failure comes one step later, at the first context.
By then the list is spent and there is no retry.

Two moves, cheapest first:

1. **Ask for less.** The stencil buffer and multisampling are the parts of
   the format most likely to have no matching config, and the viewport
   needs neither on the widget surface — it renders into its own
   ``CombinedDepthStencil`` FBO and blits (see CLAUDE.md). Depth stays:
   without it, hidden-line removal degrades silently.
2. **Re-exec under XCB.** One process restart on a machine that would
   otherwise show nothing at all.

Both are last resorts that cost nothing when the driver behaves: on a
working setup the first probe succeeds and this module is one context
creation, discarded.
"""
from __future__ import annotations

import contextlib
import os
import sys

#: Marks the re-exec'd child, so a machine where X11 fails too gives up
#: with a diagnosis instead of restarting itself forever.
GUARD_ENV = "INGETRAZO_GL_FALLBACK"


@contextlib.contextmanager
def _quiet():
    """Swallow Qt's warnings while we deliberately try to fail.

    The probe's whole job is to provoke the error the user reported; left
    to print, it would put the very ``3009`` line we are recovering from in
    front of the user of a build that recovers fine.
    """
    from PySide6.QtCore import qInstallMessageHandler
    previous = qInstallMessageHandler(lambda *_args: None)
    try:
        yield
    finally:
        qInstallMessageHandler(previous)


def _can_create(fmt) -> bool:
    """Whether this platform can give us a context with *fmt*.

    A context needs no surface to be created, which is what makes this
    cheap enough to run on every start.
    """
    from PySide6.QtGui import QOpenGLContext
    context = QOpenGLContext()
    context.setFormat(fmt)
    try:
        with _quiet():
            return bool(context.create())
    except Exception:        # a platform plugin with no GL at all
        return False


def leaner(fmt):
    """*fmt* minus the two pieces most likely to have no matching config,
    or None when it has neither and there is nothing left to give up."""
    from PySide6.QtGui import QSurfaceFormat
    if fmt.stencilBufferSize() <= 0 and fmt.samples() <= 0:
        return None
    lean = QSurfaceFormat(fmt)
    lean.setStencilBufferSize(0)
    lean.setSamples(0)
    return lean


def _restart_under_xcb(platform_name: str) -> str:
    """Re-exec this very process with ``QT_QPA_PLATFORM=xcb``.

    ``os.execv`` keeps the PID, which matters inside an AppImage: the outer
    runtime holds the SquashFS mount open for as long as its child lives,
    and the child is us.
    """
    if os.environ.get(GUARD_ENV):
        return "failed"                  # the XCB attempt is what just died
    if not platform_name.startswith("wayland"):
        return "failed"                  # already on X11: nowhere left to go
    if not os.environ.get("DISPLAY"):
        # Wayland with no XWayland, or a Flatpak that was only granted
        # --socket=fallback-x11 (which hands over nothing while Wayland is
        # up). Nothing to fall back TO; say so rather than restart blind.
        return "no-x11"
    os.environ[GUARD_ENV] = "1"
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    # Frozen: argv[0] IS sys.executable, so passing both would duplicate it.
    argv = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
    # Said before the exec, because after it this process no longer exists:
    # a restart nobody announced looks like a crash in the log.
    print("IngeTrazo: this driver cannot create an OpenGL context under "
          "Wayland; restarting under X11.", file=sys.stderr, flush=True)
    try:
        os.execv(sys.executable, [sys.executable] + argv)
    except OSError:
        os.environ.pop(GUARD_ENV, None)
        return "failed"
    return "restarting"                  # unreachable: execv does not return


def ensure_gl_context(app) -> str:
    """Make sure something on this machine can create a GL context.

    Call it once, after the QApplication exists (a context needs a platform
    integration) and before the first window. Returns a word for the log
    and the About box:

    ``ok``          the format we asked for works — the normal path;
    ``reduced``     it works without stencil/multisampling, now the default;
    ``restarting``  never returned, the process is already the XCB one;
    ``xcb``         we are the restarted process and here GL works;
    ``no-x11``      Wayland cannot, and there is no X11 to escape to;
    ``failed``      no context anywhere; the caller reports it to the user.
    """
    from PySide6.QtGui import QSurfaceFormat

    wanted = QSurfaceFormat.defaultFormat()
    if _can_create(wanted):
        return "xcb" if os.environ.get(GUARD_ENV) else "ok"

    lean = leaner(wanted)
    if lean is not None and _can_create(lean):
        QSurfaceFormat.setDefaultFormat(lean)
        print("IngeTrazo: this driver refused the full OpenGL format; "
              "continuing without stencil buffer and multisampling.",
              file=sys.stderr)
        return "reduced"

    outcome = _restart_under_xcb(app.platformName())
    if outcome == "no-x11":
        print("IngeTrazo: this driver cannot create an OpenGL 3.3 context "
              "under Wayland, and no X11 display is available to fall back "
              "on. Under Flatpak, grant it X11:\n"
              "  flatpak override --user --socket=x11 com.ingetrazo.IngeTrazo",
              file=sys.stderr)
    return outcome
