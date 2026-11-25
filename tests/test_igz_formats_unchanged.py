# SPDX-License-Identifier: GPL-3.0-or-later
"""The existing document formats stay exactly what they were.

The plain-JSON save for version control (``save_scene(..., fmt="json")``)
was added beside the formats 1, 2 and 3, not into them. The fingerprints
below were recorded from the writer BEFORE that work (main at bebde88d,
v0.6.2): a default save of the same scenes — and a resave of every example
document — must still produce the same document.

Re-recorded once on the 0.6.3 integration when batch 3 was merged (19-11),
after checking member by member that the only differences are optional
keys older readers ignore: the document's ``ifc_namespace`` (#1236), the
uid a pre-uid group now derives from it instead of a fresh random one
(#1236, so IFC GlobalIds stay stable across opens), and the five fog
fields a non-default display style now writes (#1139).

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
    "format1": "1a9896a000e204097c28bb58099fa8079414c3037832c0d593a43dc3e0ae574e",
    "format2": "e4a80180974c857086ae8ea75d13f229a5b5c6123c2f18bee870bd0e50821503",
    "format3": "dbd3015084bf45dee3548f6e687e05057b1d5635c27ddcaa44eab5fc8d9a1799",
}
EXAMPLE_FINGERPRINTS = {
    "arco-yanque.igz": "618fe8eed2a53e39f0eb9826fa7f9a4237a296048f2f117c906a3732d68219a2",
    "banca-pergola-yanque.igz": "0794d9b73bbe9b6654340927068cb85c2561c1363c014029f1f1b5c3526472ca",
    # Re-recorded on the 0.6.3 base (n63-tanda-e, c511b2e7) when PR #1494
    # was merged: that example has a legend, and 0.6.3 writes a legend's
    # new optional fields (editable rows, a background) — added with
    # defaults, an older file opens the same. The PR's writer gives the
    # same document as that base, which is what this test guards.
    "capas-prueba.igz": "9d1e0b1828801a4863dfc57e94161367f7d3a7c0e800d5cc81772b0c1730013e",
    "luminaria-solar-yanque.igz": "06479e076ed3cab8f9a97c40b6d963b093eb397dba413030087657728f521e99",
    "pestanas-prueba.igz": "5fe020d57bc410ebadfe34ec4db91e75d248753e28d89707a79df65550fd39b6",
    "pileta-fuente-yanque.igz": "4fa5286c8afe2d14882c68c82a6e6030b0b3618a73093f9fdbab12ae58ed21c9",
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
    scene = _scene(texture)
    # PR #1236: a new document draws a random IFC namespace; pinned here.
    scene.ifc_namespace = "0123456789abcdef0123456789abcdef"
    igz.save_scene(scene, out)
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
