

def test_glass_paints_translucent_and_undoes(monkeypatch):
    # The library's glass carries opacity: painting stamps it, an opaque
    # repaint clears it, and the eyedropper samples it.
    from PySide6.QtGui import QVector3D
    from core.scene import Scene
    from core.history import History
    from core.history import (CompoundCommand, SetFaceColorCommand,
                              SetFaceOpacityCommand, SetFaceTextureCommand)
    scene = Scene()
    hist = History(scene)
    f = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                             QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
    hist.execute(CompoundCommand([
        SetFaceTextureCommand([f], {"path": "glass.png", "sw": 1, "sh": 1}),
        SetFaceOpacityCommand([f], 0.45),
    ]))
    assert f.attrs["opacity"] == 0.45
    hist.execute(CompoundCommand([
        SetFaceColorCommand([f], (1.0, 0.0, 0.0)),
        SetFaceTextureCommand([f], None),
        SetFaceOpacityCommand([f], None),   # opaque paint clears the glass
    ]))
    assert "opacity" not in f.attrs
    assert hist.undo() and f.attrs["opacity"] == 0.45
    assert hist.undo() and "opacity" not in f.attrs


def test_library_glass_item_declares_opacity():
    import json
    from pathlib import Path
    lib = json.loads((Path(__file__).resolve().parent.parent / "resources" /
                      "textures" / "library.json").read_text())
    glass = next(c for c in lib["categories"] if c["id"] == "glass")
    assert all(0.0 < it["opacity"] < 1.0 for it in glass["items"])


def test_library_files_exist_and_declare_real_sizes():
    # Every library item must point at a real PNG with a positive tile
    # size — a typo'd path shows an empty swatch silently otherwise.
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "resources" / "textures"
    lib = json.loads((root / "library.json").read_text())
    cats = {c["id"] for c in lib["categories"]}
    assert {"wood", "stone", "ground", "floor", "water"} <= cats
    names = set()
    for cat in lib["categories"]:
        for it in cat["items"]:
            assert (root / "library" / it["file"]).exists(), it["file"]
            assert it["sw"] > 0 and it["sh"] > 0, it["name"]
            names.add(it["name"])
    # The urgent-project set (2026-08-25) stays available.
    assert {"wood_bark", "stone_rock", "stone_river_pebbles",
            "grass_lawn", "paving_concrete", "water_calm"} <= names
