# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The grouped-photo workflow is translated in every shipped language."""
import json
from pathlib import Path

import pytest

from core.i18n import LANGUAGE_NAMES


@pytest.mark.parametrize("language", sorted(set(LANGUAGE_NAMES) - {"en"}))
def test_photo_group_messages_are_translated(language):
    catalog = json.loads((Path(__file__).resolve().parents[1]
                          / "i18n" / f"{language}.json").read_text(encoding="utf-8"))
    messages = (
        "Group photos separately from model geometry",
        "Make a component from photos separately from model geometry",
        "This group contains a photo, not editable geometry — explode it to edit the image",
        "Image corner placed — move the pointer and click to set its size, or type a width and press Enter (Esc cancels)",
        "Image placed at its natural display size — use Image size… for an exact model width",
    )
    for message in messages:
        assert catalog.get(message, "").strip(), (language, message)
