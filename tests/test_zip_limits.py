# SPDX-License-Identifier: GPL-3.0-or-later
"""An archive from outside cannot unpack to all the memory there is.

A "zip bomb" (a few kilobytes inflating to gigabytes) opened as a .igz,
a KMZ, a .skp or pasted from the clipboard is refused before anything is
read, and the real documents still open."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from core import zip_limits
from core.paths import app_root
from core.scene import Scene
from formats import igz

#: Enough to be over RATIO_FROM, as uniform as a bomb's: about 40 KB packed.
_BOMB = 40 << 20


def _bomb(path: Path, member: str = "document.json", extra=()) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member, b" " * _BOMB)
        for name, data in extra:
            zf.writestr(name, data)
    return path


def test_a_bomb_igz_is_refused_before_it_is_read(tmp_path, monkeypatch):
    path = _bomb(tmp_path / "bomb.igz")
    assert path.stat().st_size < 1 << 20
    read = []
    monkeypatch.setattr(zipfile.ZipFile, "read",
                        lambda self, *a, **k: read.append(a) or b"")
    with pytest.raises(zip_limits.ArchiveTooLarge):
        igz.load_into(Scene(), path)
    assert read == []


def _document(tmp_path, extra=()) -> Path:
    """A real (empty) document as a .igz archive, with ``extra`` members."""
    plain = tmp_path / "plain.igz"
    igz.save_scene(Scene(), plain)
    path = tmp_path / "doc.igz"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("document.json", plain.read_bytes())
        for name, data in extra:
            zf.writestr(name, data)
    return path


def test_the_archive_itself_opens(tmp_path):
    igz.load_into(Scene(), _document(tmp_path))


def test_a_bomb_hidden_in_a_texture_is_refused_too(tmp_path):
    path = _document(tmp_path, [("textures/0000-wood.png", b"\0" * _BOMB)])
    with pytest.raises(zip_limits.ArchiveTooLarge):
        igz.load_into(Scene(), path)


def test_too_much_in_all_is_refused_even_when_each_member_is_fine(tmp_path, monkeypatch):
    # Many small members, each under RATIO_FROM, that together inflate far
    # more than RATIO times.
    path = tmp_path / "many.igz"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(8):
            z.writestr(f"t{i}.bin", b"\0" * (1 << 20))
    monkeypatch.setattr(zip_limits, "MAX_TOTAL", 4 << 20)
    with zipfile.ZipFile(path) as z, pytest.raises(zip_limits.ArchiveTooLarge):
        zip_limits.check(z)


def test_a_big_real_document_is_not_refused_for_its_size(tmp_path, monkeypatch):
    # Past MAX_TOTAL but compressed like a real model (SPR.igz: 3.2 GB at
    # 20 times): it must still open.
    path = _document(tmp_path)
    monkeypatch.setattr(zip_limits, "MAX_TOTAL", 10)
    igz.load_into(Scene(), path)


@pytest.mark.parametrize("name", ["arco-yanque.igz", "pileta-fuente-yanque.igz",
                                  "banca-pergola-yanque.igz",
                                  "luminaria-solar-yanque.igz"])
def test_the_example_documents_still_open(name):
    scene = Scene()
    igz.load_into(scene, app_root() / "examples" / name)
    assert scene.mesh.faces or scene.groups


def test_a_member_never_unpacks_past_its_declared_size(tmp_path):
    """What the check relies on: zipfile stops at a member's declared size
    and fails its CRC, it does not hand back what the data really holds."""
    path = tmp_path / "liar.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a", b"x" * 100_000)
    raw = bytearray(path.read_bytes())
    # Declare 1000 bytes in both headers (local at 22, central dir at +24).
    local = raw.index(b"PK\x03\x04")
    central = raw.index(b"PK\x01\x02")
    raw[local + 22:local + 26] = (1000).to_bytes(4, "little")
    raw[central + 24:central + 28] = (1000).to_bytes(4, "little")
    path.write_bytes(bytes(raw))
    with zipfile.ZipFile(path) as zf:
        with pytest.raises(zipfile.BadZipFile):
            zf.read("a")


def test_a_bomb_kmz_is_refused(tmp_path):
    from georef.geoimport import parse_kmz
    path = _bomb(tmp_path / "bomb.kmz", "doc.kml")
    with pytest.raises(zip_limits.ArchiveTooLarge):
        parse_kmz(path)


def test_a_bomb_on_the_clipboard_is_not_a_clipboard(tmp_path):
    from formats import clip
    data = _bomb(tmp_path / "clip.zip", "scene.igz",
                 extra=[("clip.json", b"{}")]).read_bytes()
    assert clip.decode(data) is None


def test_a_skp_whose_thumbnail_is_a_bomb_reads_as_not_empty(tmp_path):
    """The thumbnail only tells an empty .skp from one the parser could not
    read; a bomb in its place is «any doubt»: not empty."""
    from types import SimpleNamespace
    from formats import skp_openskp
    path = _bomb(tmp_path / "bomb.skp", "meta/model_thumbnail.png")
    model = SimpleNamespace(definitions=None, root=SimpleNamespace())
    assert skp_openskp._is_empty_model(model, path, False) is False
