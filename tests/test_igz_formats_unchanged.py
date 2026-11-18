# SPDX-License-Identifier: GPL-3.0-or-later
"""The existing document formats stay exactly what they were.

The plain-JSON save for version control (``save_scene(..., fmt="json")``)
was added beside the formats 1, 2 and 3, not into them. The fingerprints
below were recorded from the writer BEFORE that work (main at bebde88d,
v0.6.2): a default save of the same scenes — and a resave of every example
document — must still produce the same document.

A plain-JSON document is fingerprinted byte for byte. A ZIP container by
its members — name, compression method, timestamp and uncompressed bytes —
so the fingerprint holds on any zlib build (a different deflate library
packs the very same members into different bytes)."""
from __future__ import annotations

import hashlib
import itertools
import zipfile
from pathlib import Path

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from formats import igz

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

#: A 4×4 brown PNG, as bytes: the image the texture test packs, the same
#: on every machine (an image encoder's output is not).
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000400000004080200000026930929"
    "000000097048597300000ec400000ec401952b0e1b0000001449444154089963ec"
    "8ed2668001260624809b030036840118deb819e60000000049454e44ae426082")

SCENE_FINGERPRINTS = {
    "format1": "14f3f466a75b1ca9e0d88886e5d03d163e157f7a87bc20b71b3bca760a40bbcd",
    "format2": "3ff5ea15fffafc295bb3ad22b11d40293a2b6f9d51b4570f9e500e78ebbbb10d",
    "format3": "55d8ad28101acb5d6d60190ddb0c78c29187565537a21c337f4ef4f8311e5cc3",
}
EXAMPLE_FINGERPRINTS = {
    "arco-yanque.igz": "47841b1c98c75881f55e1b403ec69602c1f83cb35667372c7dd254b43fd096b4",
    "banca-pergola-yanque.igz": "a69689671277576ffb7a9d27f2a492324fb612ff6a5a1aeef97aa8876e0bc791",
    "capas-prueba.igz": "c34fb859a08465a58fe99eb5a8e2ab84150e231ea48e56aff0f3a20f6c990536",
    "luminaria-solar-yanque.igz": "a771e3753d9f6f86f7afce0b0891ab7bb5ba082c890041d0a81df3f5be8bd561",
    "pestanas-prueba.igz": "bce41ef590f2b2c68050fe62c8e9772c57922eb852d78bfc83ac57944bc1753e",
    "pileta-fuente-yanque.igz": "4d8d29ba1eb2238cb61b2e546c960a86f5bd1396a51b3fb5fcbbdc1009161b97",
}


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    # The header carries the app version: pinned, so a release does not
    # count as a format change.
    monkeypatch.setattr(igz, "__version__", "0.0.0-test")
    # A group's identity is random (core.group.new_uid), and a document
    # older than the uid gets fresh ones on load: counted instead.
    import core.group
    count = itertools.count()
    monkeypatch.setattr(core.group, "new_uid",
                        lambda: f"{next(count):016x}")


def _scene(texture: Path | None = None) -> Scene:
    scene = Scene()
    m = scene.mesh
    slab = m.add_face(
        [V(0, 0, 0), V(10, 0, 0), V(10, 10, 0), V(0, 10, 0)],
        [[V(2, 2, 0), V(8, 2, 0), V(8, 8, 0), V(2, 8, 0)]])
    slab.attrs.update({"color": [0.5, 0.4, 0.3], "mat": "Madera"})
    if texture is not None:
        slab.attrs["texture"] = {"path": str(texture), "sw": 1.0, "sh": 1.0}
    m.add_face([V(0, 0, 0), V(10, 0, 0), V(10, 0, 3), V(0, 0, 3)])
    e = m.add_edge(V(20, 0, 0), V(21, 0, 0))
    e.soft = True
    proto = Mesh()
    proto.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    for dx in (0, 5):
        g = Group(proto, name=f"Silla {dx}")
        x = QMatrix4x4()
        x.translate(dx, 20, 0)
        g.xform = x
        scene.groups.append(g)
    classic = Group(name="Mesa")
    classic.mesh.add_face([V(0, 30, 0), V(2, 30, 0), V(2, 31, 0)])
    scene.groups.append(classic)
    return scene


def fingerprint(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:4] != b"PK\x03\x04":
        return hashlib.sha256(raw).hexdigest()
    h = hashlib.sha256()
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            h.update(repr((info.filename, info.compress_type,
                           info.date_time)).encode())
            h.update(hashlib.sha256(zf.read(info)).digest())
    return h.hexdigest()


def save_kind(kind: str, tmp_path: Path, monkeypatch) -> Path:
    if kind == "format3":
        monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
        monkeypatch.setattr(igz, "_BULK_MIN", 1)
    texture = None
    if kind != "format1":
        texture = tmp_path / "wood.png"
        texture.write_bytes(_PNG)
    out = tmp_path / f"{kind}.igz"
    igz.save_scene(_scene(texture), out)
    return out


@pytest.mark.parametrize("kind", sorted(SCENE_FINGERPRINTS))
def test_default_save_is_unchanged(kind, tmp_path, monkeypatch):
    out = save_kind(kind, tmp_path, monkeypatch)
    assert (out.read_bytes()[:4] == b"PK\x03\x04") == (kind != "format1")
    assert fingerprint(out) == SCENE_FINGERPRINTS[kind]


@pytest.mark.parametrize("name", sorted(EXAMPLE_FINGERPRINTS))
def test_example_resave_is_unchanged(name, tmp_path):
    scene = Scene()
    igz.load_into(scene, _EXAMPLES / name)
    out = tmp_path / name
    igz.save_scene(scene, out)
    assert fingerprint(out) == EXAMPLE_FINGERPRINTS[name]
