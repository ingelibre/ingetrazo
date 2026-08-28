# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The online component library: what it fetches, what it caches, and what it
does when the server is not there — which must be "keep working"."""
from __future__ import annotations

import json
import zipfile

import pytest

from core import library


@pytest.fixture
def served(tmp_path, monkeypatch):
    """A published library on disk, and a cache pointed somewhere private."""
    src = tmp_path / "sitio"
    (src / "miniaturas").mkdir(parents=True)
    (src / "modelos").mkdir(parents=True)
    (src / "index.json").write_text(json.dumps({
        "version": 1, "unidad": "cm",
        "modelos": [{"id": "silla", "nombre": "Silla", "categoria": "Salón",
                     "obj": "chair.obj", "cm": ["51", "53", "80"],
                     "licencia": "CC0-1.0", "autor": "Alguien"}],
    }), encoding="utf-8")
    (src / "miniaturas" / "silla.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    with zipfile.ZipFile(src / "modelos" / "silla.zip", "w") as z:
        z.writestr("chair.obj", "mtllib chair.mtl\nv 0 0 0\n")
        z.writestr("chair.mtl", "newmtl m\nKd 1 0 0\n")
        z.writestr("wood.jpg", b"x")
    monkeypatch.setenv("INGETRAZO_LIBRARY", str(src))
    monkeypatch.setenv("INGETRAZO_TEXTURE_CACHE", str(tmp_path / "cache" / "tex"))
    return src


def test_the_index_lists_what_was_published(served):
    entries = library.index()
    assert [e["nombre"] for e in entries] == ["Silla"]
    assert entries[0]["licencia"] == "CC0-1.0"   # the terms travel with it


def test_a_model_arrives_unpacked_with_the_files_its_mtl_names(served):
    # The MTL names its images by bare filename, so they have to land beside
    # the OBJ or the import cannot resolve them.
    entry = library.index()[0]
    obj = library.model_file(entry)
    assert obj is not None and obj.name == "chair.obj"
    beside = {p.name for p in obj.parent.iterdir()}
    assert {"chair.obj", "chair.mtl", "wood.jpg"} <= beside


def test_what_was_downloaded_once_survives_the_server_going_away(served,
                                                                monkeypatch):
    entry = library.index()[0]
    assert library.model_file(entry) is not None
    assert library.thumbnail("silla") is not None

    monkeypatch.setenv("INGETRAZO_LIBRARY", str(served) + "-no-existe")
    assert library.index(), "the cached index was thrown away"
    assert library.model_file(entry) is not None
    assert library.thumbnail("silla") is not None


def test_an_unreachable_library_answers_empty_instead_of_raising(tmp_path,
                                                                 monkeypatch):
    # Working offline is one of this program's promises: a server that is not
    # there costs the catalogue, never the app.
    monkeypatch.setenv("INGETRAZO_LIBRARY", "https://0.0.0.0/nada")
    monkeypatch.setenv("INGETRAZO_TEXTURE_CACHE", str(tmp_path / "tex"))
    assert library.index() == []
    assert library.thumbnail("silla") is None
    assert library.model_file({"id": "silla", "obj": "chair.obj"}) is None


def test_a_model_zip_cannot_write_outside_its_folder(served):
    # Never trust an archive's names.
    with zipfile.ZipFile(served / "modelos" / "malo.zip", "w") as z:
        z.writestr("../../fuera.txt", "x")
        z.writestr("ok.obj", "v 0 0 0\n")
    d = library.model_dir("malo")
    assert d is not None
    assert {p.name for p in d.iterdir()} == {"fuera.txt", "ok.obj"}
    assert not (d.parent.parent / "fuera.txt").exists()
