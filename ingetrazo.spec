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
]

# Optional trees (present today, tolerated if pruned later).
for opt_src, opt_dst in [
    ('resources/styles', 'resources/styles'),
    ('resources/fonts', 'resources/fonts'),
]:
    if (ROOT / opt_src).is_dir():
        datas.append((opt_src, opt_dst))

# ── Hidden imports ───────────────────────────────────────────────────────────
hiddenimports = [
    # Qt submodules sometimes missed by static analysis.
    'PySide6.QtOpenGL',
    'PySide6.QtOpenGLWidgets',
    'PySide6.QtNetwork',        # tile/DEM fetch (georef)
    # Lazily imported project modules (inside functions) — listed for safety.
    'core.text3d',
    'core.textlabel',
    # The bundled plugins import these at RUN time, so static analysis never
    # sees them and they were left out: the AI assistant died on load with
    # "cannot import name 'ai' from 'core'" in every packaged build.
    'core.ai',
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
    'openskp.geometry',
    'openskp.transforms',
    'openskp.materials',
    'openskp.metadata',
    'openskp.triangulator',
    'openskp.create',
    'openskp.edit',
    'openskp.errors',
    'openskp.scene',
]

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
    binaries=[],
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
_HOST_ONLY = {'libX11.so.6', 'libX11-xcb.so.1', 'libxcb-glx.so.0'}
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

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ingetrazo',
)
