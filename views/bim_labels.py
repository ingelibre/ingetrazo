# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ibrahim Halim Gokbulut (h-skycloud).
"""Human-facing IFC labels. Stored tags and exports always use the code."""
from core.i18n import tr


def class_label(code: str) -> str:
    return tr(code)
