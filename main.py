"""IngeTrazo entry point.

Free 3D modeler for architecture, engineering and 3D design.
Part of the IngePresupuestos ecosystem (modeling → quantity takeoff → budget).

Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
Licensed under GPL-3.0-or-later. See LICENSE.
"""
from __future__ import annotations

import faulthandler
import os
import sys
from pathlib import Path

# PyInstaller's Windows bootloader points DLL lookup at _MEIPASS, while the
# PySide6 wheel keeps Qt6Core.dll beside its extension modules in PySide6/.
# Set Qt's extension directory before importing QtCore; native modules in the
# rest of the bundle are registered after Qt has loaded below.
if sys.platform == "win32" and getattr(sys, "frozen", False):
    import ctypes

    _qt_dll_dir = Path(sys._MEIPASS) / "PySide6"
    if _qt_dll_dir.is_dir():
        ctypes.windll.kernel32.SetDllDirectoryW(str(_qt_dll_dir))

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

from PySide6.QtCore import (QEvent, QLibraryInfo, QLocale, QSettings, Qt,
                            QTranslator)
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

# SetDllDirectoryW is needed for Qt above, but it also replaces PyInstaller's
# default DLL search directory. Re-add _MEIPASS now that Qt is loaded so other
# bundled native extensions can resolve their private runtime dependencies.
if sys.platform == "win32" and getattr(sys, "frozen", False):
    _bundle_dll_handle = os.add_dll_directory(str(sys._MEIPASS))

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
    _install_qt_translator(str(saved))


class _ButtonsOnlyTranslator(QTranslator):
    """Qt's own catalog, limited to the standard button texts.

    ``qtbase_<lang>.qm`` also names the keys — «Control+Mayúsculas+Re Pág»
    for Ctrl+Shift+PgUp in menus, tooltips and the shortcut editor — and
    the shortcuts stay in English on purpose. The button texts live in
    these contexts; everything else is left untranslated."""

    _CONTEXTS = frozenset({"QPlatformTheme", "QMessageBox",
                           "QDialogButtonBox"})

    def __init__(self) -> None:
        super().__init__()
        self._qt = QTranslator()

    def load_qt(self, lang: str) -> bool:
        folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        return self._qt.load(f"qtbase_{lang.replace('-', '_')}", folder)

    def isEmpty(self) -> bool:
        return self._qt.isEmpty()

    def translate(self, context, source, disambiguation=None, n=-1):
        if context not in self._CONTEXTS:
            return None                   # not ours: Qt keeps its text
        return self._qt.translate(context, source, disambiguation, n)


#: Kept alive for the whole session: Qt drops a translator that is freed.
_qt_translator: QTranslator | None = None


def _install_qt_translator(lang: str) -> None:
    """Let Qt name its standard buttons in ``lang`` too.

    Our catalog only covers ``tr()`` strings; the standard buttons of
    QMessageBox and QDialogButtonBox (OK, Cancel, Yes, No…) come from
    Qt's own ``qtbase_<lang>.qm``, which PySide6 ships. Without it they
    stayed in English under every language. A missing file just leaves
    them in English, as before."""
    global _qt_translator
    if lang == "en":
        return
    translator = _ButtonsOnlyTranslator()
    if translator.load_qt(lang):
        QApplication.installTranslator(translator)
        _qt_translator = translator

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
    # The extensions first, if the window deferred them (#440): one of them
    # may own this file type. A no-op once they are loaded.
    if hasattr(window, "load_extensions"):
        window.load_extensions()
    ext = doc.suffix.lower()
    if ext == ".skp" and not getattr(
            window, "_startup_splash_progress", None):
        from PySide6.QtCore import QTimer

        def _open_skp():
            if window.import_skp_path(doc) and hasattr(window, "_on_zoom_extents"):
                window._on_zoom_extents()

        QTimer.singleShot(0, _open_skp)
    elif (ext in {".igz", ".dae", ".skp", ".dxf", ".dwg"}
          or ext in getattr(window, "file_openers", {})):
        window.open_path(doc)       # an extension's own type goes to its opener


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
        # File-open events stay queued until the startup cover is gone and
        # plugins have had a chance to register their file handlers.
        self.open_window = None
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
        ("startup artwork", root / "resources" / "ui"
                            / "startup_blueprint.png"),
        ("components", root / "resources" / "components" / "components.json"),
        ("app icon", root / "resources" / "icons" / "ingetrazo_256.png"),
    ):
        ok = path.is_file()
        print(f"  {label:<15}: {'found' if ok else 'MISSING'}  {path}")
        if not ok:
            problems.append(label)

    # DWG import goes through LibreDWG's dwg2dxf (#101). Linux and Windows
    # packages carry it and a package without it is broken. macOS gets it
    # from release-macos.yml (built from the LibreDWG tarball), so a macOS
    # build from a plain checkout legitimately has none: reported, not
    # fatal. find_dwg2dxf ignores a binary built for another OS, so the
    # Linux ELF kept in vendor/ is never mistaken for a working converter.
    from formats.dwg_bridge import find_dwg2dxf
    dwg = find_dwg2dxf()
    print(f"  DWG converter  : {'found' if dwg else 'MISSING'}  {dwg or ''}")
    if dwg is None and is_frozen() and sys.platform != "darwin":
        problems.append("DWG converter")

    # The optional native kernels (rust/ingetrazo_core): without them the
    # Python code runs, so a missing module is not a fault — except in a
    # build that promises them, which sets INGETRAZO_REQUIRE_RUST. The
    # engine is off by default (Preferences), so the check asks whether
    # the module is there and loads, not whether it is on.
    from core._native import available, engine
    mod = available()
    print(f"  engine         : {engine()}"
          + (f" (Rust {mod.__version__} available)" if mod else ""))
    if mod is None and os.environ.get("INGETRAZO_REQUIRE_RUST") == "1":
        problems.append("native engine")

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

    # The bundled extensions are loaded by path, so the package builder
    # never sees what they import. 0.5.6 left views.fold_section out and the
    # AI assistant, the MCP bridge and Render with Blender showed «error
    # loading» on Windows (#208): import each one here, as the app would.
    import importlib.util
    broken = []
    for plugin in sorted((root / "plugins").glob("*.py")):
        if plugin.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"_check_plugin_{plugin.stem}", plugin)
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
        except Exception as exc:  # noqa: BLE001 - any failure is the report
            broken.append(f"{plugin.stem} ({exc})")
    print(f"  extensions     : {'all load' if not broken else 'BROKEN'}"
          f"  {'; '.join(broken)}")
    if broken:
        problems.append("extensions")

    # openskp ships a blank .skp template that its writer builds files on
    # top of. IngeTrazo does not distribute it and has no .skp export: a
    # bundle that still carries it is a packaging regression.
    try:
        from importlib import resources

        scaffold = resources.files("openskp") / "_scaffold" / "blank_v17.skp"
        shipped = scaffold.is_file()
    except Exception:  # openskp itself missing: reported below
        shipped = False
    print(f"  skp template   : {'SHIPPED (remove it)' if shipped else 'not shipped'}")
    if shipped and getattr(sys, "frozen", False):
        problems.append(".skp writer template shipped")

    # openskp 1.3.0 triangulates with mapbox_earcut, a NATIVE extension that
    # ``import openskp`` needs before it will load at all. Reported on its
    # own line.
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

    # Qt's own catalog for the standard buttons (see _install_qt_translator).
    # Optional: without the file the buttons stay in English, as before, so
    # it is reported but never fails the check.
    try:
        from PySide6.QtCore import QLibraryInfo
        folder = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
        have = sorted(f.stem[len("qtbase_"):] for f in folder.glob("qtbase_*.qm"))
        where = f"{len(have)} languages, es {'yes' if 'es' in have else 'NO'}  {folder}"
    except Exception as exc:  # noqa: BLE001
        where = f"({exc})"
    print(f"  Qt buttons (opt): {where}")

    # Qt's HTTPS (extension manager, map tiles): the Windows package ships
    # no OpenSSL backend, so Qt never picks up a foreign libssl left in
    # System32 (#564). Read from the plugin folder: asking Qt which
    # backends exist would itself load OpenSSL.
    if sys.platform == "win32":
        try:
            from PySide6.QtCore import QLibraryInfo
            tls = Path(QLibraryInfo.path(
                QLibraryInfo.LibraryPath.PluginsPath)) / "tls"
            have = sorted(p.stem for p in tls.glob("*.dll"))
        except Exception as exc:  # noqa: BLE001
            have, tls = [], f"({exc})"
        print(f"  TLS (Qt)       : {', '.join(have) or 'none'}  {tls}")
        if is_frozen() and ("qopensslbackend" in have
                            or "qschannelbackend" not in have):
            problems.append("Qt TLS backend")

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
    # HTTPS from Python (the AI assistant) must find a CA bundle: the macOS
    # package asked for one where only the build machine had it (#198).
    from core.tls import ensure_once
    ensure_once()
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
    # The experimental Rust engine: if the last start with it on never
    # drew its first frame, this one goes back to the normal engine (and
    # says so below); --python-engine does it for one run.
    from core import _native
    engine_fell_back = _native.start_guard(sys.argv[1:])
    from core.i18n import tr

    # Avoid flashing a splash in a second process that is about to hand its
    # file to the already-running window.
    from PySide6.QtNetwork import QLocalSocket
    early_new_window = "--new-window" in sys.argv[1:]
    early_args = [a for a in sys.argv[1:]
                  if a not in ("--new-window", _native.FLAG)]
    early_arg = early_args[0] if early_args else str(
        app.pending_open_path or "")
    early_probe_connected = False
    if not early_new_window:
        early_probe = QLocalSocket()
        early_probe.connectToServer("ingetrazo-single-instance")
        if early_probe.waitForConnected(200):
            early_probe_connected = True
            early_probe.write((early_arg + "\n").encode("utf-8"))
            early_probe.flush()
            early_probe.waitForBytesWritten(300)
            if (early_probe.waitForReadyRead(1500)
                    and bytes(early_probe.readAll()).startswith(b"ok")):
                early_probe.disconnectFromServer()
                _native.start_ok()
                return 0
            early_probe.disconnectFromServer()

    from views.startup_splash import StartupSplash
    startup_splash = StartupSplash()
    startup_splash.show()
    startup_splash.repaint()
    # The extensions' setup waits until the window is on screen (#440).
    window = MainWindow(defer_extensions=True)
    # From here on, a FileOpen Apple Event (macOS double-click / Open With,
    # or a second one while this instance is already the running app — see
    # _App.event) opens straight into this window, no process handoff
    # needed: unlike Linux/Windows, macOS delivers it to the ALREADY-RUNNING
    # process instead of spawning a new one.
    # From here on, FileOpen Apple Events and secondary launches can be
    # deferred until plugin handlers and saved panel positions are ready.
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    _SOCKET = "ingetrazo-single-instance"
    # File ▸ New Window starts a second IngeTrazo with --new-window: it must
    # NOT hand over to the running one like a double-click does, or the
    # new window never appears (issue #76).
    new_window = "--new-window" in sys.argv[1:]
    args = [a for a in sys.argv[1:]
            if a not in ("--new-window", _native.FLAG)]
    arg = args[0] if args else ""
    if not arg and app.pending_open_path is not None:
        # A cold macOS launch by double-click: no argv, the path arrived as
        # the FileOpen event queued before `open_window` was set above.
        arg = str(app.pending_open_path)
        app.pending_open_path = None
    probe = QLocalSocket()
    if not new_window and not early_probe_connected:
        probe.connectToServer(_SOCKET)
    if (not new_window and not early_probe_connected
            and probe.waitForConnected(200)):
        probe.write((arg + "\n").encode("utf-8"))
        probe.flush()
        probe.waitForBytesWritten(300)
        # Only cede if the running instance ACKS — a hung or window-less
        # zombie holding the socket must NOT swallow the launch (that was
        # the 'it does not open' failure). No ack in 1.5s → launch anyway.
        if probe.waitForReadyRead(1500) and bytes(probe.readAll()).startswith(b"ok"):
            probe.disconnectFromServer()
            # The running instance took over: this start ends here, with
            # nothing wrong (the engine guard must not count it as failed).
            _native.start_ok()
            return 0
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

    startup_ready = False
    pending_instance_paths: list[Path] = []

    def _handle_second_launch():
        conn = server.nextPendingConnection()
        if conn is None:
            return
        if conn.waitForReadyRead(300):
            path = bytes(conn.readAll()).decode("utf-8", "replace").strip()
            if path:
                if startup_ready:
                    _open_document_in(window, Path(path))
                else:
                    pending_instance_paths.append(Path(path))
        conn.write(b"ok\n")            # ACK so the caller knows we are alive
        conn.flush()
        conn.waitForBytesWritten(300)
        conn.disconnectFromServer()
        if startup_ready:
            window.show()
            window.raise_()
            window.activateWindow()

    if server is not None:
        server.newConnection.connect(_handle_second_launch)
        app._single_instance_server = server    # keep it alive
        # Drop the socket file on exit so no stale server lingers to swallow
        # the next launch.
        app.aboutToQuit.connect(lambda: QLocalServer.removeServer(_SOCKET))

    from PySide6.QtCore import QTimer

    # The branded cover is smaller than the application window. Keep the
    # real workspace fully transparent while it initializes underneath it,
    # otherwise the edges of the window appear before startup has finished.
    window.setWindowOpacity(0.0)
    window.show()

    def _first_frame_drawn():
        # This start reached the screen: the engine guard is satisfied.
        try:
            window.viewport.frameSwapped.disconnect(_first_frame_drawn)
        except (RuntimeError, TypeError):
            pass
        _native.start_ok()
    window.viewport.frameSwapped.connect(_first_frame_drawn)
    def _after_first_frame():
        # Register extensions behind the splash, then let the main window's
        # queued dock-fit/layout work run before revealing the workspace.
        startup_splash.set_progress(
            tr("Loading plugins"), 7, tr("Scanning installed plugins…"))
        try:
            window.load_extensions(progress=startup_splash.set_progress)
        except Exception:  # noqa: BLE001 — a faulty extension must not trap startup
            import logging
            logging.getLogger("ingetrazo.plugins").exception(
                "unexpected error while finishing extension startup")
        startup_splash.set_progress(
            tr("Arranging workspace"), 97,
            tr("Waiting for plugin toolbars to finish…"))

        # Plugin setup can start a Ruby host and return before that host has
        # sent its initial toolbar batch. Keep the cover up until those hosts
        # report ready, then allow their startup timers to publish any final
        # toolbar changes before applying the saved layout one last time.
        import time
        wait_started = time.monotonic()
        quiet_since = None
        last_toolbar_change = wait_started
        last_toolbar_revision = window.startup_toolbar_revision()
        last_progress_detail = None
        layout_poll = QTimer(window)
        layout_poll.setInterval(50)

        def _poll_plugin_layout():
            nonlocal quiet_since, last_toolbar_change
            nonlocal last_toolbar_revision, last_progress_detail
            now = time.monotonic()
            revision = window.startup_toolbar_revision()
            if revision != last_toolbar_revision:
                last_toolbar_revision = revision
                last_toolbar_change = now

            pending = window.pending_startup_extension_hosts()
            if pending:
                quiet_since = None
                detail = tr("Waiting for {name}…", name=pending[0])
                if detail != last_progress_detail:
                    startup_splash.set_progress(
                        tr("Loading plugins"), 95, detail)
                    last_progress_detail = detail
                if now - wait_started < 25:
                    return
                import logging
                logging.getLogger("ingetrazo.plugins").warning(
                    "startup continuing while extension hosts are still "
                    "starting: %s", ", ".join(pending))
                layout_poll.stop()
                window.settle_startup_layout()
                startup_splash.set_progress(
                    tr("Arranging workspace"), 99,
                    tr("Opening with the plugins that are ready…"))
                QTimer.singleShot(100, _finish_startup)
                return

            if quiet_since is None:
                quiet_since = now
                last_progress_detail = tr("Confirming plugin toolbar positions…")
                startup_splash.set_progress(
                    tr("Arranging workspace"), 97, last_progress_detail)
            # The Ruby compatibility hosts service their startup timers at
            # most once a second. A longer quiet window catches those bars,
            # then one final restore keeps them from appearing in the wrong
            # row after the main window is uncovered.
            if (now - quiet_since >= 1.35
                    and now - last_toolbar_change >= 0.35):
                layout_poll.stop()
                window.settle_startup_layout()
                startup_splash.set_progress(
                    tr("Arranging workspace"), 99,
                    tr("Opening your workspace…"))
                QTimer.singleShot(100, _finish_startup)

        window._startup_layout_poll = layout_poll
        layout_poll.timeout.connect(_poll_plugin_layout)
        layout_poll.start()

    def _finish_startup():
        # Keep the splash up while the launch document is parsed and its
        # drawing data is prepared. Importers route their normal progress
        # milestones into this cover instead of opening a second progress UI.
        initial_documents = []
        if arg:
            startup_doc = Path(arg)
            if startup_doc.exists():
                initial_documents.append(startup_doc)

        def _take_queued_documents():
            documents = []
            if app.pending_open_path is not None:
                documents.append(app.pending_open_path)
                app.pending_open_path = None
            if pending_instance_paths:
                documents.extend(pending_instance_paths)
                pending_instance_paths.clear()
            return documents

        initial_documents.extend(_take_queued_documents())
        initial_seen: set[str] = set()
        documents = []
        for doc in initial_documents:
            key = str(doc).casefold()
            if key not in initial_seen:
                initial_seen.add(key)
                documents.append(doc)
        seen_documents: set[str] = set()

        def _finish_after_files():
            nonlocal startup_ready
            more_documents = _take_queued_documents()
            if more_documents:
                _open_startup_documents(more_documents)
                return

            startup_ready = True
            app.open_window = window
            window._startup_splash_progress = None
            # Reveal the prepared workspace only after plugins, layout, and
            # any launch file have completed. The splash remains on top until
            # the opacity change has taken effect.
            window.setWindowOpacity(1.0)
            startup_splash.close()
            window.raise_()
            window.activateWindow()

            if engine_fell_back:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    window, tr("Rust engine (experimental)"),
                    tr("IngeTrazo did not open the last time with the experimental "
                       "Rust engine on, so it is back on the normal engine. You can "
                       "turn it on again in Preferences ▸ General."))

            # The optional first-run units prompt follows any requested opening,
            # so it cannot obscure a large file's loading progress.
            QTimer.singleShot(0, window.offer_units_at_start)
            _offer_appimage_integration(window)

        def _check_startup_queue():
            more_documents = _take_queued_documents()
            if more_documents:
                _open_startup_documents(more_documents)
            else:
                _finish_after_files()

        def _open_startup_documents(batch):
            unique = []
            for doc in batch:
                key = str(doc).casefold()
                if key not in seen_documents:
                    seen_documents.add(key)
                    unique.append(doc)
            if not unique:
                QTimer.singleShot(150, _check_startup_queue)
                return

            doc = unique.pop(0)
            # Preserve any additional documents until the next pass. This
            # also drains file-open requests received while a large model is
            # being parsed.
            pending_instance_paths[0:0] = unique
            heading = tr("Opening {name}", name=doc.name)
            startup_splash.set_progress(heading, 87,
                                        tr("Preparing file…"))

            def _report_file_progress(title, fraction, detail):
                value = 87 + round(max(0.0, min(1.0, fraction)) * 12)
                startup_splash.set_progress(
                    heading, min(99, value), detail or title)

            window._startup_splash_progress = _report_file_progress
            try:
                _open_document_in(window, doc)
            except Exception:  # noqa: BLE001 — keep a failed opener from trapping startup
                import logging
                logging.getLogger("ingetrazo.startup").exception(
                    "could not open startup file %s", doc)
            finally:
                window._startup_splash_progress = None

            startup_splash.set_progress(
                tr("Finalizing workspace"), 99,
                tr("Finishing {name}…", name=doc.name))
            QTimer.singleShot(0, _check_startup_queue)

        if documents:
            _open_startup_documents(documents)
        else:
            QTimer.singleShot(150, _check_startup_queue)

    QTimer.singleShot(0, _after_first_frame)
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


def _exit_now(code) -> None:
    """Leave without tearing the model down object by object. Everything
    that must reach the disk has by now: the window closed, the document
    was saved or discarded, and the settings are synced here. What is left
    is freeing millions of Python objects one at a time, which on a big
    model kept the process — and its gigabytes — alive for a minute after
    the window was gone (issue #158, @pacaeiro: 21 406 groups, 6.7 GB)."""
    import logging
    from PySide6.QtCore import QSettings
    QSettings().sync()
    logging.shutdown()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os._exit(code if isinstance(code, int) else 0)


if __name__ == "__main__":
    _exit_now(main())
