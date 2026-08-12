#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
#
# Build the IngeTrazo Linux artifacts: a single-file AppImage and a plain
# tarball of the same PyInstaller bundle.
#
#     packaging/build-appimage.sh [outdir]
#
# Needs: the project venv with the runtime deps. Downloads appimagetool on
# first run. (Adapted from IngeCAD's packaging/build-appimage.sh — keep the
# two in sync; the only structural differences are that IngeTrazo has no
# vendored converter binaries and its spec lives at the repo root.)
#
# WHERE TO BUILD THIS: an AppImage links against the glibc of the machine
# that made it, so one built on Ubuntu 26.04 will not start on 24.04 or
# 22.04. The release workflow uses the oldest runner we support for exactly
# that reason; building here is for testing on this machine.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${1:-$ROOT/dist}
WORK=${INGETRAZO_BUILD_DIR:-$ROOT/build}
PYTHON=${PYTHON:-$ROOT/venv/bin/python}
ARCH=${ARCH:-x86_64}

cd "$ROOT"
VERSION=$("$PYTHON" -c 'from core.version import __version__; print(__version__)')
APPDIR="$WORK/IngeTrazo.AppDir"
APPIMAGE="$OUT/IngeTrazo-$VERSION-$ARCH.AppImage"

echo "==> IngeTrazo $VERSION -> $APPIMAGE"

echo "==> PyInstaller"
"$PYTHON" -m PyInstaller --version >/dev/null 2>&1 \
    || "$PYTHON" -m pip install --quiet pyinstaller
rm -rf "$APPDIR" "$WORK/pyi"
"$PYTHON" -m PyInstaller --noconfirm \
    --distpath "$WORK/pyi" --workpath "$WORK/pyi-work" \
    ingetrazo.spec

echo "==> the bundle finds its own data"
# Before wrapping it in an AppImage, ask the bundle itself. A missing shader
# or texture starts fine and only fails when the user needs it.
"$WORK/pyi/ingetrazo/ingetrazo" --check

echo "==> tarball"
# The same bundle, without the AppImage wrapper: extract and run. For users
# whose distro lacks FUSE (the classic AppImage complaint) or who want to
# unpack under /opt. Ships the desktop file and icon for manual integration.
TARDIR="$WORK/IngeTrazo-$VERSION"
TARBALL="$OUT/IngeTrazo-$VERSION-linux-$ARCH.tar.gz"
rm -rf "$TARDIR"
mkdir -p "$TARDIR" "$OUT"
cp -a "$WORK/pyi/ingetrazo/." "$TARDIR/"
cp packaging/ingetrazo.desktop resources/icons/ingetrazo_256.png "$TARDIR/"
cat > "$TARDIR/README.txt" <<'TXT'
IngeTrazo — portable Linux build
================================

Run it:            ./ingetrazo          (or: ./ingetrazo model.igz)
Self-diagnosis:    ./ingetrazo --check

No installation required. To add a launcher and the .igz/.skp icons,
edit the Exec= line of ingetrazo.desktop to this folder's path and copy
it to ~/.local/share/applications/.

Prefer the AppImage from the same release if your distro has FUSE.
TXT
tar -C "$WORK" -czf "$TARBALL" "IngeTrazo-$VERSION"
printf '%s  (%s)\n' "$TARBALL" "$(du -h "$TARBALL" | cut -f1)"

echo "==> AppDir"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps" \
         "$APPDIR/usr/share/metainfo"
cp -a "$WORK/pyi/ingetrazo/." "$APPDIR/usr/bin/"

# AppImage wants the icon and desktop file at the AppDir root as well.
cp resources/icons/ingetrazo_256.png \
   "$APPDIR/usr/share/icons/hicolor/256x256/apps/ingetrazo.png"
cp resources/icons/ingetrazo_256.png "$APPDIR/ingetrazo.png"
sed 's|^Exec=.*|Exec=ingetrazo %f|; s|^Icon=.*|Icon=ingetrazo|' \
    packaging/ingetrazo.desktop > "$APPDIR/usr/share/applications/ingetrazo.desktop"
cp "$APPDIR/usr/share/applications/ingetrazo.desktop" "$APPDIR/ingetrazo.desktop"

# AppRun: keep the launcher tiny and let Qt find its own plugins, which the
# PyInstaller bundle already lays out next to the binary.
cat > "$APPDIR/AppRun" <<'SH'
#!/bin/sh
HERE=$(dirname "$(readlink -f "$0")")
# Wayland first, X11 as the fallback, unless the user forces one.
[ -z "$QT_QPA_PLATFORM" ] && export QT_QPA_PLATFORM="wayland;xcb"
exec "$HERE/usr/bin/ingetrazo" "$@"
SH
chmod +x "$APPDIR/AppRun"

echo "==> appimagetool"
TOOL="$WORK/appimagetool-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
    mkdir -p "$WORK"
    curl -fsSL -o "$TOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod +x "$TOOL"
fi

mkdir -p "$OUT"
rm -f "$APPIMAGE"
# --appimage-extract-and-run: appimagetool is itself an AppImage and needs
# FUSE otherwise, which a CI container does not have.
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" "$APPIMAGE"

echo "==> the AppImage answers --check"
"$APPIMAGE" --check

printf '\n%s  (%s)\n' "$APPIMAGE" "$(du -h "$APPIMAGE" | cut -f1)"
