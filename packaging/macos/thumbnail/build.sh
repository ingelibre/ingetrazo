#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
#
# Build the .igz thumbnail extension and put it in IngeTrazo.app:
#
#     packaging/macos/thumbnail/build.sh dist/IngeTrazo.app [arch] [min-macOS]
#
# arch defaults to this Mac's (uname -m), the minimum macOS to 14.0, as the
# release job asks of the rest of the bundle. Only the Command Line Tools
# are needed (swiftc and codesign), not Xcode.
#
# The extension lands in Contents/PlugIns/IngeTrazoThumbnail.appex, signed
# ad hoc with the sandbox entitlement an app extension must have. The app
# is then signed again, so its seal covers the extension: nested code
# first, the bundle around it last.
set -euo pipefail

APP="${1:?usage: build.sh IngeTrazo.app [arch] [min-macOS]}"
ARCH="${2:-$(uname -m)}"
MINOS="${3:-14.0}"
HERE="$(cd "$(dirname "$0")" && pwd)"
APPEX="$APP/Contents/PlugIns/IngeTrazoThumbnail.appex"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' \
    "$APP/Contents/Info.plist")"

echo "==> .igz thumbnail extension ($ARCH, macOS $MINOS+)"
rm -rf "$APPEX"
mkdir -p "$APPEX/Contents/MacOS"
swiftc -O -target "$ARCH-apple-macos$MINOS" \
    -application-extension -parse-as-library \
    -module-name IngeTrazoThumbnail \
    -Xlinker -e -Xlinker _NSExtensionMain \
    -framework QuickLookThumbnailing \
    "$HERE/ThumbnailProvider.swift" "$HERE/IgzThumbnail.swift" \
    -o "$APPEX/Contents/MacOS/IngeTrazoThumbnail"
sed -e "s/@VERSION@/$VERSION/g" -e "s/@MINOS@/$MINOS/g" \
    "$HERE/Info.plist" > "$APPEX/Contents/Info.plist"
plutil -lint "$APPEX/Contents/Info.plist" >/dev/null

codesign --force --sign - --entitlements "$HERE/Thumbnail.entitlements" "$APPEX"
codesign --force --sign - "$APP"
codesign --verify --deep --strict "$APP"
