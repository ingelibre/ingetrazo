# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The material registry (core.materials): identity over the face attrs.

The design contract: baked attrs (color/texture) stay the render truth;
``attrs["mat"]`` adds identity. The registry rides the scene, serializes
with the document (textures embedded like any other), and the .skp import
keeps SketchUp's material names instead of dissolving them into anonymous
colours."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import zipfile
from types import SimpleNamespace as NS

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.materials import Material, register                     # noqa: E402
from core.scene import Scene                                      # noqa: E402
from formats import igz as igz_format                             # noqa: E402
from formats import skp as skp_format                             # noqa: E402


def _quad(mesh, z=0.0):
    return mesh.add_face([QVector3D(0, 0, z), QVector3D(2, 0, z),
                          QVector3D(2, 2, z), QVector3D(0, 2, z)])


# ---- Material / register --------------------------------------------------

def test_material_roundtrip_and_stamp():
    mat = Material("Concreto visto", color=(0.62, 0.60, 0.58), opacity=0.9)
    again = Material.from_dict(mat.to_dict())
    assert again == mat
    stamp = mat.face_attrs()
    assert stamp == {"mat": "Concreto visto",
                     "color": (0.62, 0.60, 0.58), "opacity": 0.9}


def test_register_is_idempotent_for_identical_recipes():
    reg: dict = {}
    a = Material("Wood", color=(0.5, 0.3, 0.1))
    assert register(reg, a) == "Wood"
    assert register(reg, Material("Wood", color=(0.5, 0.3, 0.1))) == "Wood"
    assert len(reg) == 1


def test_register_renames_on_recipe_conflict():
    """Same name, different recipe: neither silently repaints the other."""
    reg: dict = {}
    register(reg, Material("Wood", color=(0.5, 0.3, 0.1)))
    final = register(reg, Material("Wood", color=(0.9, 0.9, 0.9)))
    assert final == "Wood (2)"
    assert reg["Wood (2)"].name == "Wood (2)"
    assert len(reg) == 2


# ---- .igz round trip ------------------------------------------------------

def test_igz_roundtrip_plain(tmp_path):
    scene = Scene()
    f = _quad(scene.mesh)
    f.attrs.update(Material("Ladrillo", color=(0.7, 0.3, 0.2)).face_attrs())
    scene.materials["Ladrillo"] = Material("Ladrillo", color=(0.7, 0.3, 0.2))

    path = tmp_path / "doc.igz"
    igz_format.save_scene(scene, path)
    loaded = Scene()
    igz_format.load_into(loaded, path)

    assert set(loaded.materials) == {"Ladrillo"}
    assert loaded.materials["Ladrillo"].color == (0.7, 0.3, 0.2)
    face = loaded.mesh.faces[0]
    assert face.attrs["mat"] == "Ladrillo"
    assert tuple(face.attrs["color"]) == (0.7, 0.3, 0.2)


def test_igz_embeds_registry_texture(tmp_path):
    """A textured material in the registry: its image is embedded in the
    ZIP container and the path comes back real on load — the same
    treatment face textures always had."""
    img = tmp_path / "ladrillo.png"
    from PySide6.QtGui import QImage
    QImage(4, 4, QImage.Format.Format_RGB32).save(str(img))

    scene = Scene()
    tex = {"path": str(img), "sw": 1.0, "sh": 1.0}
    mat = Material("Ladrillo visto", texture=dict(tex))
    scene.materials[mat.name] = mat
    f = _quad(scene.mesh)
    f.attrs.update(mat.face_attrs())

    path = tmp_path / "doc.igz"
    igz_format.save_scene(scene, path)
    assert zipfile.is_zipfile(path)                    # container form
    with zipfile.ZipFile(path) as zf:
        assert sum(1 for n in zf.namelist()
                   if n.startswith("textures/")) == 1  # shared, stored once

    loaded = Scene()
    igz_format.load_into(loaded, path)
    reloaded = loaded.materials["Ladrillo visto"]
    assert reloaded.texture and os.path.exists(reloaded.texture["path"])
    assert loaded.mesh.faces[0].attrs["texture"]["path"] \
        == reloaded.texture["path"]                    # same extraction


# ---- .skp import ----------------------------------------------------------

def _fake_model(materials):
    root = NS(
        id=0, name="ROOT_MODEL",
        vertices={1: NS(id=1, x=0, y=0, z=0), 2: NS(id=2, x=10, y=0, z=0),
                  3: NS(id=3, x=10, y=10, z=0)},
        edges={10: NS(id=10, v1_id=1, v2_id=2), 11: NS(id=11, v1_id=2, v2_id=3),
               12: NS(id=12, v1_id=3, v2_id=1)},
        faces={20: NS(id=20, loops=[[(10, 1), (11, 1), (12, 1)]],
                      normal=(0, 0, 1), material_id=next(iter(materials)))},
        instances=[],
    )
    return NS(definitions={0: root}, materials_by_id=materials)


def test_skp_import_registers_named_material():
    from formats import skp_openskp
    model = _fake_model({7: NS(name="Concreto visto", color=(158, 153, 148),
                               transparency=1.0, id=7, texture=None)})
    payload = skp_openskp._adapt(model, "obra")
    assert payload["materials"] == [
        {"name": "Concreto visto",
         "color": [158 / 255.0, 153 / 255.0, 148 / 255.0]}]
    attrs = payload["groups"][0]["faces"][0][2]
    assert attrs["mat"] == "Concreto visto"

    scene = Scene()
    skp_format.apply_payload(scene, payload)
    assert "Concreto visto" in scene.materials
    face = scene.groups[0].mesh.faces[0]
    assert face.attrs["mat"] == "Concreto visto"


def test_skp_reimport_does_not_duplicate():
    from formats import skp_openskp
    model = _fake_model({7: NS(name="Wood", color=(255, 0, 0),
                               transparency=1.0, id=7, texture=None)})
    scene = Scene()
    skp_format.apply_payload(scene, skp_openskp._adapt(model, "a"))
    skp_format.apply_payload(scene, skp_openskp._adapt(model, "a"))
    assert list(scene.materials) == ["Wood"]


def test_skp_import_remaps_on_conflict_with_document():
    """The document already has a DIFFERENT 'Wood': the import's Wood lands
    as 'Wood (2)' and the imported faces follow the rename."""
    from formats import skp_openskp
    scene = Scene()
    scene.materials["Wood"] = Material("Wood", color=(0.1, 0.1, 0.1))
    model = _fake_model({7: NS(name="Wood", color=(255, 0, 0),
                               transparency=1.0, id=7, texture=None)})
    skp_format.apply_payload(scene, skp_openskp._adapt(model, "a"))
    assert set(scene.materials) == {"Wood", "Wood (2)"}
    face = scene.groups[0].mesh.faces[0]
    assert face.attrs["mat"] == "Wood (2)"
    assert scene.materials["Wood"].color == (0.1, 0.1, 0.1)   # untouched
