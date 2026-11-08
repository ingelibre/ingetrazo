#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fail if a Mach-O file in a macOS bundle asks for a newer macOS than given.

    scripts/check_macos_minos.py dist/IngeTrazo.app 12.0

The dynamic loader refuses such a file when it is loaded, which for a Qt plugin
or a NumPy module is long after the app seemed to work (#1123). Needs ``otool``.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

_MAGICS = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe",
           b"\xbe\xba\xfe\xca"}


def minimum_versions(otool_output: str) -> list[str]:
    """The minimum macOS of each slice, from ``otool -l``: ``minos`` of
    LC_BUILD_VERSION, or ``version`` of the older LC_VERSION_MIN_MACOSX."""
    found = []
    command = None
    for line in otool_output.splitlines():
        words = line.split()
        if len(words) == 2 and words[0] == "cmd":
            command = words[1]
        elif len(words) == 2 and (
                (command == "LC_BUILD_VERSION" and words[0] == "minos")
                or (command == "LC_VERSION_MIN_MACOSX"
                    and words[0] == "version")):
            found.append(words[1])
    return found


def _key(version: str) -> tuple[int, ...]:
    parts = [int(p) for p in re.findall(r"\d+", version)]
    return tuple(parts + [0] * (3 - len(parts)))


def too_new(versions: list[str], limit: str) -> list[str]:
    return [v for v in versions if _key(v) > _key(limit)]


def _is_macho(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) in _MAGICS
    except OSError:
        return False


def main(bundle: str, limit: str) -> int:
    checked = 0
    bad = []
    for folder, _dirs, files in os.walk(bundle):
        for name in files:
            path = os.path.join(folder, name)
            if os.path.islink(path) or not _is_macho(path):
                continue
            output = subprocess.run(["otool", "-l", path], capture_output=True,
                                    text=True, check=False).stdout
            checked += 1
            over = too_new(minimum_versions(output), limit)
            if over:
                bad.append((path, max(over, key=_key)))
    for path, version in bad:
        print(f"{version}  {path}")
    print(f"{checked} Mach-O files, {len(bad)} ask for more than macOS {limit}")
    return 1 if bad or not checked else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
