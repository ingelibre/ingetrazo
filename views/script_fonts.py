# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""An interface font that holds the language's script (Lao, #850).

On Windows the interface font (Segoe UI) has no Lao. Qt then draws each
Lao letter from a fallback font while the vowel and tone marks are
placed for another one, and they come out apart from their consonant
(«ໄຟລ໌» read «ໄຟລ ໌» in the 0.5.11 Windows round). Putting a font that
carries the script first in the application font keeps a whole Lao word
in one font, so its marks compose; Latin letters and digits come from
that font too or, when it lacks them, from the usual one after it.

Only where this was seen (Windows) and only for these languages: every
other language, and Lao on Linux and macOS (fontconfig and Core Text
pick one font for the word), start exactly as before.
"""
from __future__ import annotations

import sys

#: Language → fonts that carry its script, best first. Leelawadee UI
#: ships with Windows 8 and later (Lao, Thai and Latin); Lao UI with
#: Windows 7; Noto Sans Lao when the user installed it.
SCRIPT_FONTS: dict[str, tuple[str, ...]] = {
    "lo": ("Leelawadee UI", "Lao UI", "Noto Sans Lao UI", "Noto Sans Lao"),
}

#: Platforms whose own font fallback breaks these scripts apart.
_PLATFORMS = ("win32",)


def script_font_for(lang: str | None, installed, platform: str | None = None
                    ) -> str | None:
    """The first font of :data:`SCRIPT_FONTS` for ``lang`` that is in
    ``installed`` on ``platform`` (default: this one), or ``None``."""
    platform = sys.platform if platform is None else platform
    if platform not in _PLATFORMS:
        return None
    base = str(lang or "").split("-")[0].split("_")[0].lower()
    have = set(installed)
    for name in SCRIPT_FONTS.get(base, ()):
        if name in have:
            return name
    return None


def apply_script_font(app, lang: str | None, platform: str | None = None
                      ) -> bool:
    """At start-up, after the language is chosen: put the script's font
    first in the application font. Returns whether it did; nothing
    changes when it does not."""
    from PySide6.QtGui import QFontDatabase
    name = script_font_for(lang, QFontDatabase.families(), platform)
    if name is None:
        return False
    font = app.font()
    families = [name] + [f for f in (font.families() or [font.family()])
                         if f and f != name]
    font.setFamilies(families)
    app.setFont(font)
    return True
