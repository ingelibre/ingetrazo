"""IngeTrazo entry point.

Free 3D modeler for architecture, engineering and 3D design.
Part of the IngePresupuestos ecosystem (modeling → quantity takeoff → budget).

Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
Licensed under GPL-3.0-or-later. See LICENSE.
"""
from __future__ import annotations

import faulthandler
import sys
from pathlib import Path

# Black box: a native crash (GL driver, Qt) kills the process without a
# Python traceback — faulthandler leaves the Python stacks of every thread
# in this file so the next "it just closed" has an autopsy. It lives in the
# user's log folder (core.paths.user_log_dir), beside ingetrazo-errors.log:
# the install folder is read-only under Program Files, and a windowed .exe
# has no sys.stderr to fall back on (the v0.3.8/v0.3.9 Windows startup
# crash: "sys.stderr is None").
from core.paths import open_crash_log
_crash_log = open_crash_log()
if _crash_log is not None:
    faulthandler.enable(file=_crash_log)
elif sys.stderr is not None:
    faulthandler.enable()

# Native Wayland is the default. Known cosmetic tradeoff (2026-07-12): the
# compositor interleaves stale GL viewport frames under fast zoom bursts (a
# brief ghost/double image; flawless under XWayland, but XWayland degrades
# mixed-DPI multi-monitor setups — the audience's common rig). Escape hatch
# if the ghost bothers you: run with QT_QPA_PLATFORM=xcb. Re-test the ghost
# when Mutter/Qt update; no app-side workaround cured it (see CLAUDE.md).

from PySide6.QtCore import QEvent, QLocale, QSettings, Qt
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from core import i18n


def _init_language() -> None:
    """Load the saved UI language, or default to the system locale.

    Reads the persisted choice from :class:`QSettings`; on first run, falls back
    to Spanish when the OS locale is Spanish, Brazilian Portuguese when it is
    Portuguese, English otherwise.
    """
    saved = QSettings().value("language")
    if not saved:
        system = QLocale.system()
        if system.language() == QLocale.Spanish:
            saved = "es"
        elif system.language() == QLocale.Portuguese:
            # The Brazilian Portuguese catalogue (PR #54, @dafrobozao)
            # serves every Portuguese locale until a pt-PT one exists.
            saved = "pt-BR"
        else:
            saved = "en"
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
    if ext == ".igz" or ext in getattr(window, "file_openers", {}):
        window.open_path(doc)       # an extension's own type goes to its opener
    elif ext == ".skp":
        from PySide6.QtCore import QTimer

        def _open_skp():
            if window.import_skp_path(doc) and hasattr(window, "_on_zoom_extents"):
                window._on_zoom_extents()

        QTimer.singleShot(0, _open_skp)


class _App(QApplication):
    """QApplication subclass so macOS's file-open Apple Event reaches the
    same code path as the argv-based association used on Linux/Windows.

    Double-clicking an associated file on Linux/Windows hands the path as
    plain ``argv[1]`` (see the single-instance block in ``main()``); macOS
    never does that — Launch Services always starts the app with a bare
    argv and delivers the path afterwards as a ``QFileOpenEvent``
    (``QEvent.FileOpen``, Qt's wrapper for the OS's ``kAEOpenDocuments``
    Apple Event). Without this override a macOS double-click on a ``.igz``
    silently opened a blank "Untitled" window — the document never arrived.
    """

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self.open_window = None            # set once MainWindow exists
        self.pending_open_path: Path | None = None

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.FileOpen:
            path = Path(e.file())
            if self.open_window is not None:
                _open_document_in(self.open_window, path)
            else:
                # Arrived before MainWindow exists — a cold macOS launch can
                # deliver it this early. main() flushes this once it does.
                self.pending_open_path = path
            return True
        return super().event(e)


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

    # ``ingetrazo --mcp`` runs scripts/ingetrazo_mcp.py by path, and that
    # server reads its recipe book from core.ai_recipes. The Flatpak of
    # 0.4.9 shipped without scripts/ at all: the app ran, and the MCP door
    # was simply dead — the same family as the skp scaffold below. A recipe
    # book that fails to import is worse than missing, because the server
    # still answers and the model goes back to probing the API by hand.
    script = root / "scripts" / "ingetrazo_mcp.py"
    ok = script.is_file()
    print(f"  MCP server     : {'found' if ok else 'MISSING'}  {script}")
    if not ok:
        problems.append("MCP server")
    try:
        from core.ai_recipes import reference

        text = reference()
        ok = "revolve(" in text and "house(" in text
        where = f"{len(text)} chars"
    except Exception as exc:  # noqa: BLE001 - unimportable in this bundle
        ok, where = False, f"({exc})"
    print(f"  AI recipe book : {'found' if ok else 'MISSING'}  {where}")
    if not ok:
        problems.append("AI recipe book")

    # The .skp writer builds every file on top of openskp's bundled blank
    # (``_scaffold/blank_v17.skp``, package data PyInstaller doesn't collect
    # by itself): a bundle without it starts fine and dies on Export ▸
    # SketchUp with "[Errno 2]" — 0.4.1 on Windows shipped exactly that.
    try:
        from importlib import resources

        scaffold = resources.files("openskp") / "_scaffold" / "blank_v17.skp"
        ok = scaffold.is_file()
        where = str(scaffold)
    except Exception as exc:  # openskp itself missing or unimportable
        ok, where = False, f"({exc})"
    print(f"  skp scaffold   : {'found' if ok else 'MISSING'}  {where}")
    if not ok:
        problems.append("skp scaffold")

    # openskp 1.3.0 triangulates with mapbox_earcut, a NATIVE extension that
    # ``import openskp`` needs before it will load at all. Reported on its
    # own line: without it the scaffold probe above fails too, and its
    # message would blame the wrong thing.
    try:
        import mapbox_earcut  # noqa: F401
        ok, where = True, getattr(mapbox_earcut, "__file__", "?")
    except Exception as exc:  # noqa: BLE001 — a bundle without the .so
        ok, where = False, f"({exc})"
    print(f"  earcut (openskp): {'found' if ok else 'MISSING'}  {where}")
    if not ok:
        problems.append("mapbox_earcut")

    # The Solid Tools' boolean kernel, another native extension imported
    # only when a tool runs — a bundle without it fails at the first click.
    try:
        import manifold3d  # noqa: F401
        ok, where = True, getattr(manifold3d, "__file__", "?")
    except Exception as exc:  # noqa: BLE001
        ok, where = False, f"({exc})"
    print(f"  manifold3d     : {'found' if ok else 'MISSING'}  {where}")
    if not ok:
        problems.append("manifold3d")

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


def _run_mcp_server() -> int:
    """``ingetrazo --mcp``: the stdio MCP server, from the packaged app —
    no Python install needed on the user's machine. The script is shipped
    as data and run by path so the checkout and the package share one file.
    A windowed Windows exe has no console, but a client that spawns us with
    pipes hands valid handles and Python wires them up; when it did not,
    there is nobody to talk to and we say so."""
    from core.paths import app_root
    script = app_root() / "scripts" / "ingetrazo_mcp.py"
    if sys.stdin is None or sys.stdout is None:
        try:
            sys.stdin = open(0, "r", encoding="utf-8")
            sys.stdout = open(1, "w", encoding="utf-8")
        except OSError:
            return 2
    import runpy
    runpy.run_path(str(script), run_name="__main__")
    return 0


def main() -> int:
    if "--check" in sys.argv[1:]:
        return _self_check()
    if "--mcp" in sys.argv[1:]:
        return _run_mcp_server()
    # Hang autopsy (Linux): `kill -USR1 <pid>` dumps every thread's Python
    # stack to stderr, so a frozen main loop names its exact line without a
    # debugger or elevated ptrace. No-op where SIGUSR1 doesn't exist.
    try:
        import faulthandler
        import signal as _signal
        faulthandler.register(_signal.SIGUSR1, all_threads=True)
    except (ImportError, AttributeError, ValueError):
        pass
    # Hybrid laptops (Intel + NVIDIA/AMD): claim the discrete GPU before any
    # GL context exists — a first run on the Intel chip is the classic
    # "IngeTrazo is unusably slow on Windows".
    from core.gpu_prefs import ensure_high_performance_gpu
    try:
        gpu_pref = ensure_high_performance_gpu()
    except Exception:
        gpu_pref = "failed"
    # Wayland with a fractional display scale composes a GL window through a
    # slow path (frames p90 149 ms vs 30 ms under XWayland on the same
    # model): start under xcb there unless the user chose otherwise.
    from core.platform_choice import apply_platform_preference
    try:
        platform_forced = apply_platform_preference()
    except Exception:
        platform_forced = None
    _configure_surface_format()
    app = _App(sys.argv)
    app.setProperty("platform_forced", platform_forced)
    app.setApplicationName("IngeTrazo")
    app.setOrganizationName("IngeTrazo")
    app.setProperty("gpu_pref", gpu_pref)
    # A driver that cannot serve the format we just asked for takes the
    # whole app down with it, window included — and Qt's own
    # "wayland;xcb" list never retries, because it is spent before the
    # first context. Ask for less, or come back under XCB; the call does
    # not return when it restarts us. See core/gl_fallback.py.
    from core.gl_fallback import ensure_gl_context
    gl_fallback = ensure_gl_context(app)
    app.setProperty("gl_fallback", gl_fallback)
    if gl_fallback == "failed":
        print("IngeTrazo: no OpenGL 3.3 context on this machine — the "
              "viewport will not draw. Send ingetrazo-gl.txt from the log "
              "folder.", file=sys.stderr)
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
    # dock icon) by this name — see scripts/install_desktop.sh. Inside the
    # Flatpak the entry is the app id: a window claiming "ingetrazo" there
    # matched nothing, so the shell (and GNOME Software's Open button, which
    # waits for the launched app to appear) never tied it to the launcher.
    import os as _os
    app.setDesktopFileName(_os.environ.get("FLATPAK_ID") or "ingetrazo")
    # Light or dark chrome: follows the desktop by default, live
    # (Preferences ▸ General ▸ Theme pins one). See views/theme.py.
    from views.theme import apply_theme
    apply_theme(app)
    _init_language()
    # Long hints wrap into a box instead of a strip across the window.
    from views.tooltips import WrappingToolTips
    tooltips = WrappingToolTips(app)
    app.installEventFilter(tooltips)
    window = MainWindow()
    # From here on, a FileOpen Apple Event (macOS double-click / Open With,
    # or a second one while this instance is already the running app — see
    # _App.event) opens straight into this window, no process handoff
    # needed: unlike Linux/Windows, macOS delivers it to the ALREADY-RUNNING
    # process instead of spawning a new one.
    app.open_window = window

    # Single instance: if IngeTrazo is already running, hand the document to
    # that window and quit — so a second double-click opens the file in the
    # existing window instead of spawning a rival instance that the desktop
    # then kills as a duplicate (the 'it doesn't open' failure). Fail-open:
    # any socket trouble just launches a normal standalone instance.
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    _SOCKET = "ingetrazo-single-instance"
    # File ▸ New Window starts a second IngeTrazo with --new-window: it must
    # NOT hand over to the running one like a double-click does, or the
    # new window never appears (issue #76).
    new_window = "--new-window" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if a != "--new-window"]
    arg = args[0] if args else ""
    if not arg and app.pending_open_path is not None:
        # A cold macOS launch by double-click: no argv, the path arrived as
        # the FileOpen event queued before `open_window` was set above.
        arg = str(app.pending_open_path)
        app.pending_open_path = None
    probe = QLocalSocket()
    if not new_window:
        probe.connectToServer(_SOCKET)
    if not new_window and probe.waitForConnected(200):
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
    # An extra window stays out of it: the first one keeps answering
    # double-clicks, and this one must not tear down its socket.
    server = None
    if not new_window:
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
    _offer_appimage_integration(window)
    return app.exec()


def _offer_appimage_integration(window) -> None:
    """Running as an AppImage that is not in the applications menu yet:
    offer to add it, once (Help ▸ Add to the applications menu stays
    available). The answer «not now» is remembered per AppImage path."""
    from core.appimage import appimage_path, is_integrated
    img = appimage_path()
    if img is None or is_integrated(img):
        return
    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtWidgets import QMessageBox
    st = QSettings()
    if str(st.value("appimage/declined", "")) == str(img):
        return

    def ask():
        from core.i18n import tr
        box = QMessageBox(window)
        box.setWindowTitle(tr("Add IngeTrazo to the applications menu?"))
        box.setText(tr(
            "You are running IngeTrazo as an AppImage. Add a launcher with "
            "its icon to your applications menu, and associate .igz files "
            "with it? Nothing is copied: the launcher points at this file, "
            "so keep it where it is."))
        yes = box.addButton(tr("Add to menu"), QMessageBox.AcceptRole)
        box.addButton(tr("Not now"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            window.add_appimage_to_menu()
        else:
            st.setValue("appimage/declined", str(img))

    QTimer.singleShot(600, ask)


if __name__ == "__main__":
    sys.exit(main())
