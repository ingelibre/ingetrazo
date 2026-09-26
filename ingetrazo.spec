# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for IngeTrazo.

Produces (one-dir mode):
- Windows: dist\\ingetrazo\\  (ingetrazo.exe + DLLs + _internal resources)
- Linux:   dist/ingetrazo/   (binary + libs)

Build:
    pyinstaller ingetrazo.spec --noconfirm

The same spec works on every platform (mirrors ingepresupuestos.spec in the
sibling repo). Runtime resource lookups are repo-root-relative
(``Path(__file__).parents[1] / "resources"``), which in the frozen one-dir
layout resolves inside ``_internal/`` — so every data destination below
mirrors the repo layout exactly.

Rendering note (Windows): Qt 6 picks desktop OpenGL and falls back to the
bundled software rasterizer (``opengl32sw.dll``, shipped by the PySide6
wheel) when the driver can't give a 3.3 core context — both paths satisfy
the viewport's requirements, no forcing needed.
"""
import site
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()

# ── Bundled assets — destinations MIRROR the repo layout ─────────────────────
datas = [
    ('resources/shaders/*.vert',   'resources/shaders'),
    ('resources/shaders/*.frag',   'resources/shaders'),
    ('resources/icons/*.png',      'resources/icons'),
    ('resources/icons/*.ico',      'resources/icons'),
    ('resources/icons/mimetypes/*.ico', 'resources/icons/mimetypes'),
    ('resources/mime/*.xml',       'resources/mime'),
    ('resources/colors/*.json',    'resources/colors'),
    ('resources/textures/*.png',   'resources/textures'),
    ('resources/textures/library.json', 'resources/textures'),
    # Factory window layout (Marco's toolbar arrangement, harvested
    # 2026-08-31): fresh profiles restore it; user changes override it.
    ('resources/ui/*.state',       'resources/ui'),
    # The library itself — a whole tree, and it was MISSING: the Materials
    # tray read library.json and then found no images, so every category
    # came up empty in the packaged build (the Flatpak copies all of
    # resources/ and was fine, which is why it went unnoticed).
    ('resources/textures/library', 'resources/textures/library'),
    # Starter components are .igz since 0.3.7: one group per file with its
    # images packed inside, so the tray works with no network. (A stale glob
    # here is a HARD PyInstaller error, not a warning — the .glb set is gone.)
    ('resources/components/*.igz', 'resources/components'),
    ('resources/components/components.json', 'resources/components'),
    ('resources/components/people.json', 'resources/components'),
    ('resources/components/SOURCES.md', 'resources/components'),
    ('resources/components/*.png', 'resources/components'),
    ('resources/components/thumbs/*.png', 'resources/components/thumbs'),
    ('i18n/*.json',                'i18n'),
    # Bundled plugins (Extensions menu) — discovered by file path at runtime.
    ('plugins/*.py',               'plugins'),
    # Example extensions: shipped but NOT loaded — Extensions ▸ Example
    # extensions copies one into the user's plugins folder on request.
    # Whole folder: an example extension can be a package (CAM, PR #132).
    ('examples/extensions',        'examples/extensions'),
    # The MCP server (stdlib-only): `ingetrazo --mcp` runs it by path, and
    # the console build below makes it a program of its own on Windows.
    ('scripts/ingetrazo_mcp.py',   'scripts'),
]

# Optional trees (present today, tolerated if pruned later).
for opt_src, opt_dst in [
    ('resources/styles', 'resources/styles'),
    ('resources/fonts', 'resources/fonts'),
]:
    if (ROOT / opt_src).is_dir():
        datas.append((opt_src, opt_dst))

# The DWG satellite (LibreDWG dwg2dxf, see vendor/libredwg/SOURCES.md):
# Linux-only ELF, found by formats/dwg_bridge.py at vendor/libredwg/bin
# inside the bundle. The Windows build skips it — DWG on Windows stays a
# documented gap until a dwg2dxf.exe exists.
import sys as _sys
if _sys.platform.startswith("linux"):
    datas.append(('vendor/libredwg/bin/dwg2dxf', 'vendor/libredwg/bin'))

# ── Hidden imports ───────────────────────────────────────────────────────────
hiddenimports = [
    # Qt submodules sometimes missed by static analysis.
    'PySide6.QtOpenGL',
    'PySide6.QtOpenGLWidgets',
    'PySide6.QtNetwork',        # tile/DEM fetch (georef)
    # Lazily imported project modules (inside functions) — listed for safety.
    'core.text3d',
    'core.textlabel',
]

# ezdxf (DXF/DWG import) is imported INSIDE functions — without this the
# packaged build ships with CAD import dead (the core.ai lesson again).
# collect_submodules because ezdxf lazy-loads its own internals too.
from PyInstaller.utils.hooks import collect_submodules
hiddenimports += collect_submodules('ezdxf')
# manifold3d (Solid Tools) is imported inside core.solids' functions — one
# self-contained native extension module (libstdc++/libm/libc only).
hiddenimports += ['manifold3d', 'core.solids', 'tools.solid_tools']
# Copy/Paste between windows (#76): imported lazily by the viewport and
# the main window.
hiddenimports += ['formats.clip']
hiddenimports += [
    # The bundled plugins import these at RUN time, so static analysis never
    # sees them and they were left out: the AI assistant died on load with
    # "cannot import name 'ai' from 'core'" in every packaged build.
    'core.ai',
    # The recipe book both AI doors read. It reaches the bundle only
    # through a plugin (the assistant) and a by-path script (the MCP
    # server), so analysis never sees it — and its absence is SILENT: the
    # server falls back to a short string and the model goes back to
    # probing the API, which is the very waste it exists to stop.
    'core.ai_recipes',
    'core.bim',
    'tools.place_group',
    'tools.paste',
    'georef.points',
    'georef.terrain',
    'georef.dem',
    'georef.profile',
    # Pure-Python .skp backend (upstream openskp: classic-MFC + VFF readers
    # and the legacy writer) — imported lazily by formats/skp.py and
    # formats/skp_out.py.
    'openskp',
    'openskp.model',
    'openskp._core',
    'openskp.legacy',
    'openskp.vff',
    'openskp.parser',
    'openskp.transforms',
    'openskp.materials',
    'openskp.metadata',
    'openskp.triangulator',
    'openskp.create',
    'openskp.edit',
    'openskp.errors',
    'openskp.scene',
]
# The rest of openskp (export/*, _face_groups, instanced_scene, codegen…)
# plus its PACKAGE DATA: create.py loads ``_scaffold/blank_v17.skp`` via
# importlib.resources and PyInstaller never bundles non-Python files on its
# own. Without this every PyInstaller build (Windows exe, AppImage, tar)
# died on Export ▸ SketchUp with "[Errno 2] No such file or directory:
# …\\_internal\\openskp\\_scaffold\\blank_v17.skp" (reported from Windows,
# 0.4.1). The Flatpak was fine because it ships the whole site-packages.
from PyInstaller.utils.hooks import collect_data_files
hiddenimports += collect_submodules('openskp')
datas += collect_data_files('openskp')
# openskp 1.3.0 triangulates with mapbox_earcut instead of Shapely, so the
# reader now pulls a NATIVE extension (_core*.so) that did not exist in the
# dependency tree before. ``import openskp`` fails outright without it, so
# a bundle that misses it is dead on arrival — the same shape of failure as
# the missing scaffold in 0.4.1. PyInstaller would probably follow the
# import on its own; "probably" is what cost us that release, so it is
# named here and ``main.py --check`` verifies it in CI.
hiddenimports += collect_submodules('mapbox_earcut')
# …and naming it was not enough. The Windows wheel is repaired with
# delvewheel: ``_core.pyd`` is linked against DLLs that live in a SIBLING
# directory of the package, ``site-packages/mapbox_earcut.libs/``, exactly
# like numpy.libs and shapely.libs. Those two work because
# pyinstaller-hooks-contrib ships hooks for them; mapbox_earcut has none,
# so the .pyd travelled without its dependencies and the bundle died with
# «DLL load failed while importing _core: The specified module could not
# be found» — which, because openskp imports it at module level, means no
# SketchUp import or export at all. Caught by ``--check`` on the v0.4.3
# tag, which is what that check is for.
#
# The DLLs go to the bundle root: PyInstaller puts sys._MEIPASS on the DLL
# search path, and delvewheel's own ``os.add_dll_directory`` preamble
# cannot help here because it resolves a path relative to a __file__ that
# does not exist in a frozen app.
from PyInstaller.utils.hooks import collect_dynamic_libs
_earcut_libs = collect_dynamic_libs('mapbox_earcut')
for _sp in site.getsitepackages() + [site.getusersitepackages()]:
    _sib = Path(_sp) / 'mapbox_earcut.libs'
    if _sib.is_dir():
        _earcut_libs += [(str(f), '.') for f in _sib.iterdir() if f.is_file()]
        break
print('spec: mapbox_earcut native files: %d' % len(_earcut_libs))

excludes = [
    'tkinter',
    'matplotlib',
    'pandas',
    'IPython',
    'jupyter',
    'numpy.tests',
    # Dev-only IFC validator: heavy, never imported by the app itself.
    'ifcopenshell',
    'pytest',
]

a = Analysis(
    ['main.py'],
    pathex=[str(ROOT)],
    binaries=_earcut_libs,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
# ── The X client libraries come from the HOST, never from here ───────────────
# Bundling libX11 puts a SECOND copy of it in the process: Qt loads ours
# through $ORIGIN while the host's GL driver loads the system one, and the
# Display of one is not the Display of the other. Mesa tolerates it; NVIDIA
# does not, and the packaged builds die at start-up with
#   qt.glx: qglx_findConfig: Failed to finding matching FBConfig
#   Could not initialize GLX
# (issue #6 — the tarball and the AppImage fail on an NVIDIA + X11 machine
# where the same tag from source works). Note that `libxcb.so.1` was never
# bundled, which is what makes the split possible in the first place.
#
# Only these three go: they are on every system that can draw a window at
# all, and every one of them is also loaded by the host's GL driver. The
# other libxcb-* helpers stay — Qt's xcb plugin needs them and a minimal
# host may not have them.
#
# 2026-09-15, issue #6 again (v0.3.19, NVIDIA + Ubuntu 24.04): with the X
# libraries gone the bundle still aborts inside Qt's GLX integration while
# the same tag from pip PySide6 runs — so the culprit is something else the
# bundle carries and pip does not. The C++ runtime: PyInstaller ships the
# build runner's ``libstdc++.so.6`` / ``libgcc_s.so.1`` (Ubuntu 22.04,
# GLIBCXX ≤ 3.4.30) and they are loaded FIRST, so a driver library that
# was built against a newer runtime fails to load and GLX has no vendor
# to talk to. The AppImage exclude list has carried both for years for
# exactly that reason («Workaround for: libstdc++.so.6: version
# GLIBCXX_3.4.21 not found»); every desktop has a runtime at least as
# new as the runner's, which is all the bundled Qt needs — the pip wheels
# never bring their own either. ``libglib-2.0.so.0`` goes for the same
# reason: the host's GIO modules (gvfs, loaded through the platform theme)
# expect the host's GLib, and the bundled older one produced the
# ``g_task_set_static_name`` noise in every report.
_HOST_ONLY = {'libX11.so.6', 'libX11-xcb.so.1', 'libxcb-glx.so.0',
              'libstdc++.so.6', 'libgcc_s.so.1', 'libglib-2.0.so.0'}
if sys.platform.startswith('linux'):
    _before = len(a.binaries)
    a.binaries = [b for b in a.binaries
                  if Path(b[0]).name not in _HOST_ONLY]
    print('spec: dropped %d bundled X libraries (issue #6)'
          % (_before - len(a.binaries)))

pyz = PYZ(a.pure, a.zipped_data)

icon = None
if sys.platform == 'win32':
    win_ico = ROOT / 'resources' / 'icons' / 'ingetrazo.ico'
    if win_ico.exists():
        icon = str(win_ico)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ingetrazo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # UPX sometimes breaks PySide6 — never enable
    console=False,              # GUI app, no terminal window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

# ── ingetrazo-mcp: a CONSOLE program for Claude Desktop / Claude Code ───────
# MCP clients talk over stdin/stdout; a windowed exe may have no std handles
# to give them, so Windows gets a console build of the stdlib-only server
# sharing this bundle's _internal/. Spawned with pipes it opens no window.
mcp_a = Analysis(
    ['scripts/ingetrazo_mcp.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=['core.ai_recipes'],       # its recipe book, read at import
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
mcp_pyz = PYZ(mcp_a.pure)
mcp_exe = EXE(
    mcp_pyz,
    mcp_a.scripts,
    [],
    exclude_binaries=True,
    name='ingetrazo-mcp',
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=icon,
)

coll = COLLECT(
    exe,
    mcp_exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    mcp_a.binaries,
    mcp_a.zipfiles,
    mcp_a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ingetrazo',
)

# ── macOS: wrap the onedir COLLECT as a double-clickable .app ────────────────
# ingetrazo-mcp rides along inside Contents/MacOS/ as a sibling binary (same
# onedir the other platforms ship); nothing launches it but a stdio-speaking
# MCP client that already knows its path, so it does not need its own bundle.
if sys.platform == 'darwin':
    from core.version import __version__ as _version
    mac_icon = ROOT / 'resources' / 'icons' / 'ingetrazo.icns'
    app = BUNDLE(
        coll,
        name='IngeTrazo.app',
        icon=str(mac_icon) if mac_icon.exists() else None,
        bundle_identifier='com.ingetrazo.IngeTrazo',
        info_plist={
            'CFBundleName': 'IngeTrazo',
            'CFBundleDisplayName': 'IngeTrazo',
            'CFBundleShortVersionString': _version,
            'CFBundleVersion': _version,
            'NSHighResolutionCapable': True,
            # PyInstaller's own Info.plist template defaults this to True,
            # which makes macOS treat the bundle as agent-only: no Dock icon,
            # no window, no menu bar — a GUI app must say so explicitly.
            'LSBackgroundOnly': False,
            'NSHumanReadableCopyright': 'GPL-3.0-or-later — Marco Sumari Tellez and IngeTrazo contributors',
            # .igz / .skp double-click-to-open, same association the other
            # platforms register (packaging/ingetrazo.desktop, the .iss).
            'CFBundleDocumentTypes': [
                {
                    'CFBundleTypeName': 'IngeTrazo document',
                    'CFBundleTypeExtensions': ['igz'],
                    'CFBundleTypeRole': 'Editor',
                    'LSHandlerRank': 'Owner',
                },
                {
                    'CFBundleTypeName': 'SketchUp document',
                    'CFBundleTypeExtensions': ['skp'],
                    'CFBundleTypeRole': 'Editor',
                    'LSHandlerRank': 'Alternate',
                },
            ],
        },
    )
