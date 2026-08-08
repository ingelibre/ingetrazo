# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Rasterize the application icon from ``resources/icons/ingetrazo.svg``.

    python scripts/gen_app_icon.py

Outputs, all committed because a clone must be installable without Inkscape:

    resources/icons/ingetrazo_<size>.png   16..512, for hicolor and the web
    resources/icons/ingetrazo.ico          for ingetrazo.spec and the Inno setup

Run ``scripts/gen_doc_icons.py`` AFTER this one: the .igz document icons
composite ``ingetrazo_256.png`` as their badge, so they must come second.

HISTORY, because it changes how you edit the icon. Until 2026-08-07 the master
was ``ingetrazo_master.png`` (816 px) and this script only rescaled it — there
was no vector source at all, so the mark could not be changed without redrawing
it, and 816 px was a hard ceiling. The SVG is now the single source of truth: it
was rebuilt as geometry from that raster and verified against it at 96.2 % IoU on
the blue area, the remainder being exactly the hairline outline the raster had.

Needs Inkscape and ImageMagick on PATH. Inkscape rather than QImage's SVG
loader because the same renderer then produces these and the ones
``install_desktop.sh`` writes into the icon theme.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "resources" / "icons"
SVG = ICONS / "ingetrazo.svg"

SIZES = (512, 256, 128, 64, 48, 32, 16)
# 512 stays out of the .ico: it adds about a megabyte and Windows never asks for
# more than 256.
ICO_SIZES = (256, 128, 64, 48, 32, 16)


def main() -> int:
    for tool in ("inkscape", "magick"):
        if not shutil.which(tool):
            print(f"!! {tool} is not on PATH", file=sys.stderr)
            return 1
    if not SVG.is_file():
        print(f"!! missing {SVG}", file=sys.stderr)
        return 1

    for size in SIZES:
        out = ICONS / f"ingetrazo_{size}.png"
        subprocess.run(["inkscape", "-w", str(size), "-h", str(size),
                        str(SVG), "-o", str(out)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("wrote", out.name)

    ico = ICONS / "ingetrazo.ico"
    subprocess.run(["magick", *[str(ICONS / f"ingetrazo_{s}.png") for s in ICO_SIZES],
                    str(ico)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("wrote", ico.name)
    print("\nNow run: python scripts/gen_doc_icons.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
