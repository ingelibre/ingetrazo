# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""OBJ and MTL text is UTF-8 on every platform, whatever the locale says.

Python opens text files in the locale's encoding when none is given: UTF-8
on Linux and macOS, cp1252 on Windows. The OBJ exporter and importer gave
none, so on Windows a material «Mármol» went out as cp1252 (mojibake on any
other machine), a UTF-8 file came back as «MÃ¡rmol», and a byte cp1252 has
no character for stopped the import dead. The ``cp1252_locale`` fixture
plays that Windows default here, so these tests fail without the fix on
the Linux CI too."""
from __future__ import annotations

import builtins
import io

import pytest
from PySide6.QtGui import QVector3D

from core.scene import Scene
from formats import obj as obj_format


@pytest.fixture
def cp1252_locale(monkeypatch):
    """Text files opened without an encoding read and write cp1252, as
    they do on a Windows machine. Binary I/O and explicit encodings are
    left alone."""
    real_open = builtins.open

    def windows_open(file, mode="r", buffering=-1, encoding=None,
                     *args, **kwargs):
        if "b" not in mode and encoding in (None, "locale"):
            encoding = "cp1252"
        return real_open(file, mode, buffering, encoding, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", windows_open)
    monkeypatch.setattr(io, "open", windows_open)
    # pathlib resolves the default through io.text_encoding, which answers
    # "utf-8" in UTF-8 mode; make it say "locale" so windows_open sees it.
    monkeypatch.setattr(io, "text_encoding",
                        lambda encoding, stacklevel=2: encoding or "locale")


def _cube(x0: float, base: int) -> str:
    """Eight vertices and six quads of a 1 m cube at (x0, 0, 0)."""
    pts = [(x0 + dx, dy, dz) for dz in (0, 1) for dy in (0, 1)
           for dx in (0, 1)]
    quads = [(1, 3, 4, 2), (5, 6, 8, 7), (1, 2, 6, 5),
             (3, 7, 8, 4), (1, 5, 7, 3), (2, 4, 8, 6)]
    lines = [f"v {x} {y} {z}" for x, y, z in pts]
    lines += ["f " + " ".join(str(base + i) for i in q) for q in quads]
    return "\n".join(lines)


def _two_parts(first: str, second: str) -> str:
    """Two named parts, apart from each other."""
    return f"g {first}\n{_cube(0, 0)}\ng {second}\n{_cube(3, 8)}\n"


def test_the_export_is_utf8_under_a_windows_locale(tmp_path, cp1252_locale):
    scene = Scene()
    face = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0),
                                QVector3D(2, 2, 0), QVector3D(0, 2, 0)])
    face.attrs["color"] = (0.9, 0.9, 0.85)
    face.attrs["mat"] = "Mármol"
    path = tmp_path / "m.obj"
    obj_format.save_obj(scene, path)
    assert "newmtl Mármol" in (tmp_path / "m.mtl").read_bytes().decode("utf-8")
    assert "usemtl Mármol" in path.read_bytes().decode("utf-8")


def test_a_utf8_file_keeps_its_accents_under_a_windows_locale(
        tmp_path, cp1252_locale):
    path = tmp_path / "fuente.obj"
    path.write_bytes(_two_parts("Escultura_pública", "Peña").encode("utf-8"))
    scene = Scene()
    obj_format.load_obj(scene, path)
    names = [k.name for k in scene.groups[0].children]
    assert names == ["Escultura_pública", "Peña"]


def test_an_older_cp1252_file_still_imports(tmp_path):
    """Not valid UTF-8: an older Windows exporter wrote it. Its names are
    read as cp1252 instead of the import stopping on the first accent."""
    path = tmp_path / "banco.obj"
    path.write_bytes(_two_parts("Peña", "Banco").encode("cp1252"))
    scene = Scene()
    obj_format.load_obj(scene, path)
    names = [k.name for k in scene.groups[0].children]
    assert names == ["Peña", "Banco"]


def test_a_byte_order_mark_is_not_part_of_the_first_line(tmp_path):
    path = tmp_path / "bom.obj"
    path.write_bytes(b"\xef\xbb\xbfv 0 0 0\n")
    assert obj_format.read_obj_text(path).splitlines()[0] == "v 0 0 0"
