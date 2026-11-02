# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fewer malloc arenas on Linux (glibc).

glibc gives every thread that allocates its own arena, and an arena hands
little back to the system once it is fragmented. Opening a big document
prefetches its lazy meshes on worker threads (the Rust engine), so each
reopening left a few more megabytes stranded in those arenas: plaza.igz
opened 15 times in a row grew ~9 MB each time and never settled. With two
arenas the same run settles, ~110 MB lower, opening just as fast
(release check of 0.5.10, 2026-10-23)."""
from __future__ import annotations

import sys

#: glibc's mallopt() parameter for the arena cap.
M_ARENA_MAX = -8
ARENAS = 2


def limit() -> bool:
    """Cap the arenas, before any thread allocates. True when it applied
    (Linux with glibc); elsewhere nothing happens."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6")
        return bool(libc.mallopt(M_ARENA_MAX, ARENAS))
    except (OSError, AttributeError):
        return False                    # not glibc (musl…): leave it


def trim() -> bool:
    """Hand the heap's free pages back to the system (glibc malloc_trim).

    Closing a big project frees gigabytes, but glibc keeps them: the
    system monitor saw the SPR's tab close drop only ~1 GB of ~5.8 GB,
    and a trim right after took it to ~1 GB in all. True when it ran
    (Linux with glibc); elsewhere nothing happens."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
        return True
    except (OSError, AttributeError):
        return False                    # not glibc (musl…): leave it
