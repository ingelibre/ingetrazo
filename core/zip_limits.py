# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""How much an archive from outside may unpack to (a .igz, a KMZ, a .skp's
thumbnail, the clipboard, a library model).

Each member is read whole into memory, so a "zip bomb", a few megabytes
that inflate to tens of gigabytes, would take all of it and the system would
kill the application. Real documents stay far from these limits: the .igz
files measured (old JSON and format 3, up to 150 MB unpacked) compress 4 to
40 times, while deflate reaches about 1000 times only on data as uniform as
a bomb's. A member's declared size bounds what Python's zipfile returns for
it (it stops there and checks the CRC), so checking the declared sizes is
enough.
"""
from __future__ import annotations

import zipfile

#: Everything an archive may unpack to, all its members together.
MAX_TOTAL = 4 << 30
#: A member this big must not be more compressed than RATIO times.
RATIO_FROM = 32 << 20
RATIO = 200


class ArchiveTooLarge(zipfile.BadZipFile):
    """The archive unpacks to more than it may (a BadZipFile, so the
    callers that already refuse a damaged archive refuse this one too)."""


def check(archive: zipfile.ZipFile, name: str = "") -> None:
    """Raise :class:`ArchiveTooLarge` when ``archive`` would unpack to more
    than :data:`MAX_TOTAL`, or holds a member over :data:`RATIO_FROM` more
    compressed than :data:`RATIO` times."""
    label = name or "the archive"
    total = 0
    for info in archive.infolist():
        total += info.file_size
        if info.file_size > RATIO_FROM and \
                info.file_size > RATIO * max(info.compress_size, 1):
            raise ArchiveTooLarge(
                f"{label}: {info.filename} unpacks to {info.file_size} bytes "
                f"from {info.compress_size}; refused.")
    if total > MAX_TOTAL:
        raise ArchiveTooLarge(
            f"{label} unpacks to {total} bytes, more than {MAX_TOTAL}; refused.")


def read(archive: zipfile.ZipFile, member: str) -> bytes:
    """``archive.read(member)``, refused like :func:`check` when that one
    member is too big (for readers that take one member of an archive)."""
    info = archive.getinfo(member)
    if info.file_size > MAX_TOTAL or (
            info.file_size > RATIO_FROM
            and info.file_size > RATIO * max(info.compress_size, 1)):
        raise ArchiveTooLarge(
            f"{member} unpacks to {info.file_size} bytes from "
            f"{info.compress_size}; refused.")
    return archive.read(member)
