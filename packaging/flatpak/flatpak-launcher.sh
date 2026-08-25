#!/bin/sh
# IngeTrazo's launcher inside the Flatpak sandbox.
#
# Qt is left to auto-detect the platform: under Wayland the sandbox gets
# WAYLAND_DISPLAY but no DISPLAY, so forcing xcb would fail to connect
# (learned in IngePresupuestos/IngeCAD, same launcher shape).
#
# pip installed the dependencies under /app's prefix; the runtime's python
# does not look there on its own, whatever its version happens to be.
PYVER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
export PYTHONPATH="/app/lib/python${PYVER}/site-packages:${PYTHONPATH}"
# Work from the user's own directory, NOT from /app. Anything that resolves a
# relative path against the working directory — a file dialog above all — would
# otherwise hand the host a sandbox-only path: the portal draws the chooser
# outside the sandbox and answers "/app/ingetrazo not found". Python puts the
# script's own directory on sys.path, so the imports do not need the cd.
cd "${HOME:-/}" 2>/dev/null || cd /
exec python3 /app/ingetrazo/main.py "$@"
