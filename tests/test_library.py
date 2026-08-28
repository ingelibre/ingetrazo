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


def _load(obj, entry):
    """The model as the tray inserts it, and the size it ends up."""
    from core.scene import Scene
    from formats import obj as _obj
    scene = Scene()
    _obj.load_obj(scene, obj, matrix=library.model_matrix(entry, obj))
    pts = [v for f in scene.mesh.faces for v in f.vertices] or \
          [v for g in scene.groups for f in g.mesh.faces for v in f.vertices]
    return tuple(round((max(a) - min(a)) * 100, 2) for a in
                 ([p.x() for p in pts], [p.y() for p in pts],
                  [p.z() for p in pts]))


def _box(tmp_path, name, w, d, h):
    """An OBJ box ``w`` x ``d`` x ``h`` in the catalogue's Y-up space."""
    p = tmp_path / name
    v = [(0, 0, 0), (w, 0, 0), (w, h, 0), (0, h, 0),
         (0, 0, d), (w, 0, d), (w, h, d), (0, h, d)]
    faces = [(1, 2, 3, 4), (5, 6, 7, 8), (1, 2, 6, 5),
             (2, 3, 7, 6), (3, 4, 8, 7), (4, 1, 5, 8)]
    p.write_text("".join("v %g %g %g\n" % t for t in v) +
                 "".join("f %d %d %d %d\n" % f for f in faces))
    return p


def test_a_model_arrives_standing_up_and_the_size_the_catalogue_promised(
        tmp_path):
    # The file is Y-up and in units of its own; the catalogue says the piece
    # is 51 x 53 x 80 cm. Both have to be honoured or a bus lands on its side
    # (and a 126 cm handrail arrives 3 cm long).
    obj = _box(tmp_path, "chair.obj", 2.0, 3.0, 5.0)     # arbitrary units
    entry = {"cm": ["51", "53", "80"]}
    assert _load(obj, entry) == (51.0, 53.0, 80.0)


def test_the_catalogues_own_rotation_is_applied_before_the_fit(tmp_path):
    # Some entries carry a 3x3 that turns the model before it is sized. Here
    # it swaps Y and Z, so the file's 5-long axis becomes the depth.
    obj = _box(tmp_path, "pen.obj", 2.0, 3.0, 5.0)
    entry = {"cm": ["20", "50", "30"],
             "rot": ["1", "0", "0", "0", "0", "1", "0", "-1", "0"]}
    assert _load(obj, entry) == (20.0, 50.0, 30.0)


def test_a_flat_model_is_not_collapsed_by_the_fit(tmp_path):
    # A pane of glass has no thickness to fit, so that axis borrows the
    # others' scale instead of dividing by zero.
    obj = _box(tmp_path, "pane.obj", 2.0, 0.0, 4.0)
    entry = {"cm": ["100", "1", "200"]}
    w, d, h = _load(obj, entry)
    assert (w, h) == (100.0, 200.0)
    assert d == 0.0


def test_an_entry_without_a_size_still_loads(tmp_path):
    # A catalogue that says nothing must not produce a zero-sized model.
    obj = _box(tmp_path, "x.obj", 2.0, 3.0, 5.0)
    assert all(v > 0 for v in _load(obj, {}))


def test_a_download_says_who_it_is(monkeypatch, tmp_path):
    # Cloudflare — which is what serves ingetrazo.com — answers 403 to
    # Python's default "Python-urllib/3.x". A request that does not identify
    # itself comes back Forbidden, and the whole online library is dead
    # while curl on the same machine works fine. It cost a live deploy to
    # find; it should cost a test to find again.
    import urllib.request

    seen = {}

    class _Resp:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen["ua"] = req.get_header("User-agent")
        return _Resp()

    monkeypatch.setenv("INGETRAZO_LIBRARY", "https://ingetrazo.com/biblioteca")
    monkeypatch.setenv("INGETRAZO_TEXTURE_CACHE", str(tmp_path / "tex"))
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    library.index(refresh=True)

    ua = seen.get("ua")
    assert ua, "the request carried no User-Agent"
    assert "urllib" not in ua.lower()
    assert "IngeTrazo" in ua


def test_previews_are_fetched_in_the_background_and_then_come_from_disk(served):
    # Browsing must not wait on the network one preview at a time: that is
    # what made a screenful of them take twenty seconds. The tray asks for
    # what it can see and paints what has landed.
    import time

    assert library.cached_thumbnail("silla") is None   # nothing yet
    library.prefetch_thumbnails(["silla"])
    for _ in range(100):                                # up to 5 s
        if library.cached_thumbnail("silla") is not None:
            break
        time.sleep(0.05)
    assert library.cached_thumbnail("silla") is not None


def test_asking_for_the_same_preview_again_costs_nothing(served):
    # The tray calls this on every tick with the same visible rows, so a
    # repeat must be free — not a second download, and never a hang.
    import time

    library.prefetch_thumbnails(["silla"])
    for _ in range(100):
        if library.cached_thumbnail("silla") is not None:
            break
        time.sleep(0.05)
    before = library.cached_thumbnail("silla").stat().st_mtime_ns
    for _ in range(20):
        library.prefetch_thumbnails(["silla"])
    time.sleep(0.2)
    assert library.cached_thumbnail("silla").stat().st_mtime_ns == before


def test_a_preview_that_cannot_be_had_never_raises(tmp_path, monkeypatch):
    # A blank square is the right answer to an unreachable server; an
    # exception on a worker thread is not.
    monkeypatch.setenv("INGETRAZO_LIBRARY", "https://0.0.0.0/nada")
    monkeypatch.setenv("INGETRAZO_TEXTURE_CACHE", str(tmp_path / "tex"))
    library.prefetch_thumbnails(["no-existe"])
    import time
    time.sleep(0.3)
    assert library.cached_thumbnail("no-existe") is None


def test_the_catalogues_categories_are_said_in_the_interface_language():
    # The entries carry the category in Spanish, because that is what the
    # source catalogues ship. Reading an English interface and finding
    # "Cocina" in the filter is the catalogue's word leaking through ours.
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication([])

    from core.i18n import current_language, set_language
    from views.library_dialog import LibraryDialog

    was = current_language()
    try:
        set_language("en")
        assert LibraryDialog._cat_label("Cocina") == "Kitchen"
        assert LibraryDialog._cat_label("Puertas y Ventanas") == \
            "Doors and windows"
        set_language("es")
        assert LibraryDialog._cat_label("Cocina") == "Cocina"
        # A category the map does not know still shows, untranslated,
        # rather than coming out blank.
        assert LibraryDialog._cat_label("Inventada") == "Inventada"
    finally:
        set_language(was)


def test_a_model_is_named_in_the_interface_language():
    # The catalogue names every model in both, one to one. An English
    # interface listing "Camarera con ruedas" is the catalogue's word
    # leaking through ours, the same way its categories did.
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication([])

    from core.i18n import current_language, set_language
    from views.library_dialog import LibraryDialog

    entry = {"nombre": "Silla", "nombre_en": "Chair", "id": "x"}
    was = current_language()
    try:
        set_language("en")
        assert LibraryDialog._name_of(entry) == "Chair"
        set_language("es")
        assert LibraryDialog._name_of(entry) == "Silla"
        # An older index has no English name; it must still say something.
        set_language("en")
        assert LibraryDialog._name_of({"nombre": "Silla"}) == "Silla"
        assert LibraryDialog._name_of({}) == "?"
    finally:
        set_language(was)
