# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Section planes — SketchUp's sections (help.sketchup.com "Slicing a Model
to Peer Inside").

A section plane is an object in the model: an origin + a unit normal. The
ACTIVE plane cuts the display — everything on the normal's side disappears
(``Reverse`` flips it). Only ONE plane can be the active cut in the model
context, exactly like SketchUp; placing a new plane makes it the active one.
Planes carry a name and a symbol (SketchUp 2018+) shown on their frame.

The cut is display-only scaffolding, never topology: geometry is untouched,
the renderer clips (``gl_ClipDistance``), picks/snaps filter by the plane,
and the sheet composer's hidden-line pass clips before projecting — that is
the whole point of the track (real plans and cross-sections on the sheets).
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

_last_uid = 0


def _take_uid(wanted: int | None) -> int:
    """A fresh uid, or ``wanted`` (from a loaded file) while keeping the
    counter ahead so later fresh uids never collide."""
    global _last_uid
    if wanted is None:
        _last_uid += 1
        return _last_uid
    wanted = int(wanted)
    if wanted > _last_uid:
        _last_uid = wanted
    return wanted


class SectionPlane:
    """Origin + unit normal (+ name/symbol). ``active`` = the cutting one."""

    __slots__ = ("point", "normal", "name", "symbol", "active", "uid")

    def __init__(self, point: QVector3D, normal: QVector3D,
                 name: str = "", symbol: str = "",
                 active: bool = False, uid: int | None = None) -> None:
        self.point = QVector3D(point)
        n = QVector3D(normal)
        if n.length() < 1e-12:
            n = QVector3D(0.0, 0.0, 1.0)
        self.normal = n.normalized()
        self.name = name
        self.symbol = symbol
        self.active = bool(active)
        #: Stable identity for scenes (.igz SavedView references) — survives
        #: reordering and deletion of OTHER planes.
        self.uid = _take_uid(uid)

    def flip(self) -> None:
        """SketchUp's Reverse: the cut hides the other side."""
        self.normal = -self.normal

    def side(self, p: QVector3D) -> float:
        """Signed distance: > 0 is the HIDDEN side (the normal's side)."""
        return QVector3D.dotProduct(self.normal, p - self.point)

    # ---- Serialisation (.igz) ------------------------------------------------
    def to_dict(self) -> dict:
        entry = {
            "point": [self.point.x(), self.point.y(), self.point.z()],
            "normal": [self.normal.x(), self.normal.y(), self.normal.z()],
            "uid": self.uid,
        }
        if self.name:
            entry["name"] = self.name
        if self.symbol:
            entry["symbol"] = self.symbol
        if self.active:
            entry["active"] = True
        return entry

    @classmethod
    def from_dict(cls, raw: dict) -> "SectionPlane":
        return cls(QVector3D(*raw["point"]), QVector3D(*raw["normal"]),
                   name=raw.get("name", ""), symbol=raw.get("symbol", ""),
                   active=bool(raw.get("active", False)),
                   uid=raw.get("uid"))

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        state = " ACTIVE" if self.active else ""
        return f"SectionPlane({self.symbol or self.uid}{state})"
