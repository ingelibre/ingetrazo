"""IngeTrazo entry point.

Free 3D modeler for architecture, civil engineering, and 3D printing.
Part of the IngePresupuestos ecosystem (modeling → quantity takeoff → budget).

Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
Licensed under GPL-3.0-or-later. See LICENSE.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Native Wayland is the default. Known cosmetic tradeoff (2026-07-12): the
# compositor interleaves stale GL viewport frames under fast zoom bursts (a
# brief ghost/double image; flawless under XWayland, but XWayland degrades
# mixed-DPI multi-monitor setups — the audience's common rig). Escape hatch
# if the ghost bothers you: run with QT_QPA_PLATFORM=xcb. Re-test the ghost
# when Mutter/Qt update; no app-side workaround cured it (see CLAUDE.md).

from PySide6.QtCore import QLocale, QSettings, Qt
from PySide6.QtGui import QColor, QPalette, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from core import i18n


def _apply_dark_theme(app: QApplication) -> None:
    """Force dark UI chrome regardless of the desktop theme.

    The 3D viewport is dark by design; light menus and title bar clash with
    it. ``setColorScheme`` drives the platform pieces (Wayland client-side
    title bar, native menus); the Fusion style + palette cover every widget
    so the look does not depend on whatever desktop theme is installed
    (matches IngeCAD's main.py — keep both in sync).
    """
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    app.setStyle("Fusion")

    window = QColor(45, 45, 48)
    base = QColor(37, 37, 40)
    text = QColor(224, 224, 224)
    disabled = QColor(128, 128, 128)
    highlight = QColor(42, 93, 143)

    p = QPalette()
    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, window)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.PlaceholderText, disabled)
    p.setColor(QPalette.Button, window)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor(255, 96, 96))
    p.setColor(QPalette.ToolTipBase, QColor(58, 58, 61))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Highlight, highlight)
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.Link, QColor(74, 163, 224))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.HighlightedText):
        p.setColor(QPalette.Disabled, role, disabled)
    app.setPalette(p)


def _init_language() -> None:
    """Load the saved UI language, or default to the system locale.

    Reads the persisted choice from :class:`QSettings`; on first run, falls back
    to Spanish when the OS locale is Spanish, English otherwise.
    """
    saved = QSettings().value("language")
    if not saved:
        saved = "es" if QLocale.system().language() == QLocale.Spanish else "en"
    i18n.set_language(str(saved))

from views.main_window import MainWindow


def _configure_surface_format() -> None:
    """Request an OpenGL 3.3 Core context with an explicit 24-bit depth buffer.

    Without this, hidden-line removal silently degrades: some platforms hand
    QOpenGLWidget a context with no (or 16-bit) depth buffer, and faces stop
    occluding back-facing edges.
    """
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    # NO setSamples here: MSAA lives in the viewport's offscreen scene FBO
    # (whose blit to the widget is the resolve). A multisampled widget/window
    # surface never antialiased the blitted scene, and its extra resolve step
    # interleaved stale frames on Wayland — the "ghost image" during fast zoom.
    QSurfaceFormat.setDefaultFormat(fmt)


def _open_document_in(window, doc: "Path") -> None:
    """Open *doc* in *window*: .igz as the document, .skp imported through
    the native backend after the first paint (big models parse for seconds —
    the window must be visible, not frozen pre-show). Shared by the initial
    launch and the single-instance second-launch handler."""
    ext = doc.suffix.lower()
    if ext == ".igz":
        window.open_path(doc)
    elif ext == ".skp":
        from PySide6.QtCore import QTimer

        def _open_skp():
            if window.import_skp_path(doc) and hasattr(window, "_on_zoom_extents"):
                window._on_zoom_extents()

        QTimer.singleShot(0, _open_skp)


def _self_check() -> int:
    """Report whether this install can find everything it needs; --check.

    A packaged build can be missing a shader, a translation or a texture and
    still start, then fail the first time the user needs the piece. This is
    what CI asserts on after building the AppImage, and what to run when an
    install misbehaves. (Same contract as IngeCAD's --check.)
    """
    import shutil

    from core.paths import app_root, is_frozen
    from core.version import __version__

    root = app_root()
    print(f"IngeTrazo {__version__}")
    print(f"  packaged   : {'yes' if is_frozen() else 'no (running from the repo)'}")
    print(f"  app root   : {root}")

    problems: list[str] = []
    # Only files something actually reads at runtime.
    for label, path in (
        ("vertex shader", root / "resources" / "shaders" / "basic.vert"),
        ("fragment shader", root / "resources" / "shaders" / "basic.frag"),
        ("translations", root / "i18n" / "es.json"),
        ("texture library", root / "resources" / "textures" / "library.json"),
        ("components", root / "resources" / "components" / "components.json"),
        ("app icon", root / "resources" / "icons" / "ingetrazo_256.png"),
    ):
        ok = path.is_file()
        print(f"  {label:<15}: {'found' if ok else 'MISSING'}  {path}")
        if not ok:
            problems.append(label)

    # The .skp fallback converter is optional (user-installed, runs under
    # Wine); report presence without failing on absence.
    wine = shutil.which("wine")
    skp2dae = Path.home() / ".local" / "share" / "skp2dae" / "skp2dae.exe"
    print(f"  wine (optional): {wine or 'not installed'}")
    print(f"  skp2dae (opt.) : {skp2dae if skp2dae.is_file() else 'not installed'}")

    if problems:
        print(f"\nNOT OK — missing: {', '.join(problems)}")
        return 1
    print("\nOK")
    return 0


def main() -> int:
    if "--check" in sys.argv[1:]:
        return _self_check()
    # Hang autopsy (Linux): `kill -USR1 <pid>` dumps every thread's Python
    # stack to stderr, so a frozen main loop names its exact line without a
    # debugger or elevated ptrace. No-op where SIGUSR1 doesn't exist.
    try:
        import faulthandler
        import signal as _signal
        faulthandler.register(_signal.SIGUSR1, all_threads=True)
    except (ImportError, AttributeError, ValueError):
        pass
    _configure_surface_format()
    app = QApplication(sys.argv)
    app.setApplicationName("IngeTrazo")
    app.setOrganizationName("IngeTrazo")
    # Application icon (window title bar, task bar / dock). Generated by
    # scripts/gen_app_icon.py; the QIcon picks the right size per context.
    from PySide6.QtGui import QIcon
    icon = QIcon()
    from core.paths import app_root

    icon_dir = app_root() / "resources" / "icons"
    for size in (16, 32, 48, 64, 128, 256, 512):
        p = icon_dir / f"ingetrazo_{size}.png"
        if p.exists():
            icon.addFile(str(p))
    app.setWindowIcon(icon)
    # Wayland matches the running window to its .desktop entry (and thus the
    # dock icon) by this name — see scripts/install_desktop.sh.
    app.setDesktopFileName("ingetrazo")
    _apply_dark_theme(app)
    _init_language()
    window = MainWindow()

    # Single instance: if IngeTrazo is already running, hand the document to
    # that window and quit — so a second double-click opens the file in the
    # existing window instead of spawning a rival instance that the desktop
    # then kills as a duplicate (the 'it doesn't open' failure). Fail-open:
    # any socket trouble just launches a normal standalone instance.
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    _SOCKET = "ingetrazo-single-instance"
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    probe = QLocalSocket()
    probe.connectToServer(_SOCKET)
    if probe.waitForConnected(200):
        probe.write((arg + "\n").encode("utf-8"))
        probe.flush()
        probe.waitForBytesWritten(300)
        # Only cede if the running instance ACKS — a hung or window-less
        # zombie holding the socket must NOT swallow the launch (that was
        # the 'it does not open' failure). No ack in 1.5s → launch anyway.
        if probe.waitForReadyRead(1500) and bytes(probe.readAll()).startswith(b"ok"):
            probe.disconnectFromServer()
            return 0                   # the running instance took over
        probe.disconnectFromServer()
    # No responsive server — become one. A stale socket (crash / unresponsive
    # peer) is cleared by removeServer before listen; if even that fails we
    # run as a plain window with no server, still fully functional.
    server = QLocalServer()
    QLocalServer.removeServer(_SOCKET)
    if not server.listen(_SOCKET):
        server = None

    def _handle_second_launch():
        conn = server.nextPendingConnection()
        if conn is None:
            return
        if conn.waitForReadyRead(300):
            path = bytes(conn.readAll()).decode("utf-8", "replace").strip()
            if path:
                _open_document_in(window, Path(path))
        conn.write(b"ok\n")            # ACK so the caller knows we are alive
        conn.flush()
        conn.waitForBytesWritten(300)
        conn.disconnectFromServer()
        window.show()
        window.raise_()
        window.activateWindow()

    if server is not None:
        server.newConnection.connect(_handle_second_launch)
        app._single_instance_server = server    # keep it alive
        # Drop the socket file on exit so no stale server lingers to swallow
        # the next launch.
        app.aboutToQuit.connect(lambda: QLocalServer.removeServer(_SOCKET))

    # A document passed on the command line (the OS file association's
    # double-click hands it as argv[1]) opens right away.
    if arg:
        doc = Path(arg)
        if doc.exists():
            _open_document_in(window, doc)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
