# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A document's geometry blocks are inflated side by side (#1092): each block
is its bytes, in order, and a damaged one fails as when read alone."""
from __future__ import annotations

import zipfile

import pytest

from formats import igz


def _archive(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def test_every_member_is_its_bytes(tmp_path):
    members = {f"geom/{k}.bin": bytes([k]) * (1000 + k * 977)
               for k in range(40)}
    path = tmp_path / "a.zip"
    _archive(path, members)
    with zipfile.ZipFile(path) as zf:
        got = igz._read_members(zf, list(members))
    assert got == members and list(got) == list(members)


def test_none_and_one(tmp_path):
    path = tmp_path / "a.zip"
    _archive(path, {"geom/0.bin": b"x"})
    with zipfile.ZipFile(path) as zf:
        assert igz._read_members(zf, []) == {}
        assert igz._read_members(zf, ["geom/0.bin"]) == {"geom/0.bin": b"x"}


def test_a_damaged_member_fails_as_alone(tmp_path):
    members = {f"geom/{k}.bin": bytes(range(256)) * 40 for k in range(6)}
    path = tmp_path / "a.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    raw = bytearray(path.read_bytes())
    at = raw.index(b"geom/3.bin") + 200
    raw[at] ^= 0xFF
    path.write_bytes(raw)
    with zipfile.ZipFile(path) as zf:
        with pytest.raises(zipfile.BadZipFile, match="geom/3.bin"):
            igz._read_members(zf, list(members))
