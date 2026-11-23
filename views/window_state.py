# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The window's saved layout (``QMainWindow.saveState``), read and mended.

A layout restored while no panel answers to the names it holds leaves Qt
a place kept for each name, and the next ``saveState`` writes those
places next to the panels' real ones: the same panel twice. Restored,
the panel goes to the first, often a group of its own — Properties stood
alone at the top of the side tray, the other tabs under it, start after
start. Restore default toolbars did it: it restored the factory layout
with the panels renamed out of its way.

Two helpers, both on the bytes of a saved layout:

- :func:`without_repeated_docks` — every panel once, in its last place
  (the one it was moved to after the kept place was made);
- :func:`with_toolbars_of` — one layout's panels with another's toolbars,
  so the factory toolbars come back without touching a panel.

Both give ``None`` for bytes they do not read whole (another Qt version,
a cut blob): the caller then goes on with the layout as it was.

The format is Qt's own (``QMainWindowLayoutState::saveState``), big
endian: a version header, the dock section (``0xfd``), the floating tab
groups (``0xf9``) and the toolbar section (``0xfe``/``0xfc``)."""
from __future__ import annotations

import struct

_VERSION_MARKER = 0xff
_DOCKS = 0xfd
_FLOATING_TABS = 0xf9
_TOOLBARS = 0xfe
_TOOLBARS_EX = 0xfc
_SEQUENCE = 0xfc
_TABS = 0xfa
_WIDGET = 0xfb
_FLOATING = 0x02


class _Unreadable(Exception):
    pass


class _Reader:
    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    def take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise _Unreadable
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def u8(self) -> int:
        return self.take(1)[0]

    def i32(self) -> int:
        return struct.unpack(">i", self.take(4))[0]

    def name(self) -> str | None:
        n = struct.unpack(">I", self.take(4))[0]
        if n == 0xffffffff:
            return None
        if n % 2:
            raise _Unreadable
        return self.take(n).decode("utf-16-be")

    def at_end(self) -> bool:
        return self.pos >= len(self.data)


def _put_name(name: str | None) -> bytes:
    if name is None:
        return struct.pack(">I", 0xffffffff)
    raw = name.encode("utf-16-be")
    return struct.pack(">I", len(raw)) + raw


# A group of panels (QDockAreaLayoutInfo): {"tab": front index or None,
# "orient": int, "items": [...]}. An item is ("dock", name, flags, ints)
# or ("group", ints, group).

def _read_group(r: _Reader) -> dict:
    marker = r.u8()
    if marker == _TABS:
        tab = r.i32()
    elif marker == _SEQUENCE:
        tab = None
    else:
        raise _Unreadable
    orient = r.u8()
    count = r.i32()
    if count < 0:
        raise _Unreadable
    items = []
    for _ in range(count):
        kind = r.u8()
        if kind == _WIDGET:
            name = r.name()
            flags = r.u8()
            items.append(("dock", name, flags, r.take(16)))
        elif kind == _SEQUENCE:
            ints = r.take(16)
            items.append(("group", ints, _read_group(r)))
        else:
            raise _Unreadable
    return {"tab": tab, "orient": orient, "items": items}


def _write_group(group: dict) -> bytes:
    out = bytearray()
    if group["tab"] is None:
        out.append(_SEQUENCE)
    else:
        out.append(_TABS)
        out += struct.pack(">i", group["tab"])
    out.append(group["orient"])
    out += struct.pack(">i", len(group["items"]))
    for item in group["items"]:
        if item[0] == "dock":
            _, name, flags, ints = item
            out.append(_WIDGET)
            out += _put_name(name) + bytes([flags]) + ints
        else:
            _, ints, sub = item
            out.append(_SEQUENCE)
            out += ints + _write_group(sub)
    return bytes(out)


def _skip_toolbars(r: _Reader, marker: int) -> None:
    lines = r.i32()
    if lines < 0:
        raise _Unreadable
    for _ in range(lines):
        r.i32()                                  # the area
        count = r.i32()
        if count < 0:
            raise _Unreadable
        for _ in range(count):
            r.name()
            r.u8()                               # shown, orientation
            if marker == _TOOLBARS_EX:
                r.take(16)                       # pos, size, geometry
            else:
                r.take(12)


def _sections(state: bytes):
    """``(header, [(marker, parsed or raw bytes)])``: the dock section
    parsed, the others as their bytes, marker included."""
    r = _Reader(bytes(state))
    if r.i32() != _VERSION_MARKER:
        raise _Unreadable
    r.i32()                                      # the window's version
    header = r.data[:r.pos]
    sections = []
    while not r.at_end():
        start = r.pos
        marker = r.u8()
        if marker == _DOCKS:
            count = r.i32()
            if not 0 <= count <= 4:
                raise _Unreadable
            areas = []
            for _ in range(count):
                head = r.take(12)                # area, its width and height
                areas.append((head, _read_group(r)))
            tail = r.take(24)                    # centre size, corners
            sections.append((marker, {"areas": areas, "tail": tail}))
        elif marker == _FLOATING_TABS:
            rect = r.take(16)
            sections.append((marker, {"rect": rect, "group": _read_group(r)}))
        elif marker in (_TOOLBARS, _TOOLBARS_EX):
            _skip_toolbars(r, marker)
            sections.append((marker, r.data[start:r.pos]))
        else:
            raise _Unreadable
    return header, sections


def _write(header: bytes, sections) -> bytes:
    out = bytearray(header)
    for marker, body in sections:
        if marker == _DOCKS:
            out.append(_DOCKS)
            out += struct.pack(">i", len(body["areas"]))
            for head, group in body["areas"]:
                out += head + _write_group(group)
            out += body["tail"]
        elif marker == _FLOATING_TABS:
            out.append(_FLOATING_TABS)
            out += body["rect"] + _write_group(body["group"])
        else:
            out += body
    return bytes(out)


def _groups(sections):
    for marker, body in sections:
        if marker == _DOCKS:
            for _head, group in body["areas"]:
                yield group
        elif marker == _FLOATING_TABS:
            yield body["group"]


def _dock_names(group: dict):
    for item in group["items"]:
        if item[0] == "dock":
            yield item[1]
        else:
            yield from _dock_names(item[2])


def _drop(group: dict, drop: dict) -> None:
    """Take out of ``group`` the first ``drop[name]`` entries of each name
    (in the order the layout lists them), and the groups left empty."""
    kept = []
    front = group["tab"]
    new_front = None if front is None else -1
    for i, item in enumerate(group["items"]):
        if item[0] == "dock":
            name = item[1]
            if drop.get(name, 0) > 0:
                drop[name] -= 1
                continue
        else:
            _drop(item[2], drop)
            if not item[2]["items"]:
                continue
        if front is not None and i == front:
            new_front = len(kept)
        kept.append(item)
    group["items"] = kept
    group["tab"] = new_front


def without_repeated_docks(state) -> bytes | None:
    """``state`` with each panel once, in the last place it lists for it;
    ``None`` when it repeats none, or cannot be read."""
    try:
        header, sections = _sections(bytes(state))
    except (_Unreadable, UnicodeDecodeError, struct.error):
        return None
    seen: dict = {}
    for group in _groups(sections):
        for name in _dock_names(group):
            seen[name] = seen.get(name, 0) + 1
    drop = {name: n - 1 for name, n in seen.items() if n > 1 and name}
    if not drop:
        return None
    for group in _groups(sections):
        _drop(group, drop)
    for marker, body in sections:
        if marker == _DOCKS:
            body["areas"] = [(head, g) for head, g in body["areas"]
                             if g["items"]]
    sections = [(m, b) for m, b in sections
                if m != _FLOATING_TABS or b["group"]["items"]]
    return _write(header, sections)


def repeated_docks(state) -> set:
    """The names ``state`` lists more than once (empty when unreadable)."""
    try:
        _header, sections = _sections(bytes(state))
    except (_Unreadable, UnicodeDecodeError, struct.error):
        return set()
    seen: dict = {}
    for group in _groups(sections):
        for name in _dock_names(group):
            seen[name] = seen.get(name, 0) + 1
    return {name for name, n in seen.items() if n > 1}


def with_toolbars_of(panels, toolbars) -> bytes | None:
    """The layout ``panels`` with the toolbars of ``toolbars`` instead of
    its own; ``None`` when either cannot be read or ``toolbars`` has none."""
    try:
        header, own = _sections(bytes(panels))
        _h, other = _sections(bytes(toolbars))
    except (_Unreadable, UnicodeDecodeError, struct.error):
        return None
    bars = [(m, b) for m, b in other if m in (_TOOLBARS, _TOOLBARS_EX)]
    if not bars:
        return None
    docks = [(m, b) for m, b in own if m in (_DOCKS, _FLOATING_TABS)]
    return _write(header, docks + bars)
