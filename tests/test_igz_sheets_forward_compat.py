# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A model saved by a NEWER IngeTrazo must still open here: sheet records
with fields this version does not know load with those keys dropped, and
a sheet that cannot be rebuilt at all is skipped, never the whole file."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.composition import Composicion, MarcoVista


def test_unknown_sheet_fields_are_dropped_not_fatal():
    d = {"name": "L-01", "future_key": 1,
         "frames": [{"scale_n": 50.0, "view_key": "std:top",
                     "hologram": True, "pen_glow_mm": 2}],
         "texts": [{"text": "hola", "sparkle": "yes"}],
         "cotas": [{"x_mm": 1, "dx_mm": 10, "laser": 3}],
         "niveles": [{"z_m": 1.0, "telepathy": 0}],
         "llamadas": [{"number": "1", "portal": "x"}],
         "cajetin": {"lamina": "L-01", "wormhole": []}}
    c = Composicion.from_dict(d)
    assert isinstance(c.frames[0], MarcoVista) and c.frames[0].scale_n == 50.0
    assert c.texts[0].text == "hola" and c.cotas[0].dx_mm == 10
    assert c.niveles[0].z_m == 1.0 and c.llamadas[0].number == "1"
    assert c.cajetin.lamina == "L-01"


def test_a_broken_sheet_is_skipped_and_the_others_load(tmp_path):
    import json
    from core.scene import Scene
    from formats import igz
    scene = Scene()
    scene.compositions.append(Composicion(name="buena"))
    path = tmp_path / "m.igz"
    igz.save_scene(scene, path)
    # a texture-less .igz is plain JSON: corrupt the sheet list by hand —
    # one record that cannot be rebuilt, one fine
    doc = json.loads(path.read_text(encoding="utf-8"))
    payload = doc["scene"]
    assert payload["compositions"][0]["name"] == "buena"
    payload["compositions"] = [
        {"name": "rota", "border": {"on": True, "mm": "ancho"}},   # float("ancho")
        {"name": "sana", "frames": "not-a-list",                   # skipped list
         "texts": [{"text": "ok"}, "junk", 7]}]                    # junk skipped
    path.write_text(json.dumps(doc), encoding="utf-8")
    back = Scene()
    igz.load_into(back, path)
    assert [c.name for c in back.compositions] == ["sana"]
    sana = back.compositions[0]
    assert sana.frames == [] and [t.text for t in sana.texts] == ["ok"]
