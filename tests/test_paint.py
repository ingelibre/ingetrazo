

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


def test_the_imported_textures_carry_the_real_size_the_catalogue_declared():
    # The point of importing the Sweet Home 3D libraries is not the pictures:
    # it is that each one says how big it is in the real world. A brick tiled
    # at an arbitrary size reads as a mosaic. The catalogue speaks
    # centimetres and the app metres, so a texture landing at 60 m wide would
    # mean the conversion was dropped.
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "resources" / "textures"
    lib = json.loads((root / "library.json").read_text())
    items = [it for c in lib["categories"] for it in c["items"]]
    assert len(items) > 300, "the imported libraries are missing"
    for it in items:
        assert 0.005 <= it["sw"] <= 10.0, (it["name"], it["sw"])
        assert 0.005 <= it["sh"] <= 10.0, (it["name"], it["sh"])


def test_no_two_library_textures_claim_the_same_file():
    # Two entries pointing at one image means an import overwrote a texture
    # with another of the same name, and one of them is silently wrong.
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "resources" / "textures"
    lib = json.loads((root / "library.json").read_text())
    files = [it["file"] for c in lib["categories"] for it in c["items"]]
    dupes = {f for f in files if files.count(f) > 1}
    assert not dupes, sorted(dupes)[:8]


def test_every_library_image_is_actually_readable():
    # A file can exist and still not be an image (a truncated extract, a
    # format Qt was not built for). The swatch would just be blank.
    import json
    from pathlib import Path

    from PySide6.QtGui import QImage
    root = Path(__file__).resolve().parent.parent / "resources" / "textures"
    lib = json.loads((root / "library.json").read_text())
    bad = []
    for cat in lib["categories"]:
        for it in cat["items"]:
            img = QImage(str(root / "library" / it["file"]))
            if img.isNull() or img.width() == 0:
                bad.append(it["file"])
    assert not bad, bad[:8]


# ---- RAL Classic: paint you can specify --------------------------------------

def _ral():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    return json.loads((root / "resources" / "colors" / "ral.json")
                      .read_text(encoding="utf-8"))


def test_the_ral_palette_is_complete_and_well_formed():
    data = _ral()
    colors = [c for f in data["families"] for c in f["colors"]]
    assert len(colors) == 213, "RAL Classic is 213 colours"
    codes = [c["code"] for c in colors]
    assert len(set(codes)) == len(codes), "a code appears twice"
    assert all(c["code"].startswith("RAL ") for c in colors)
    for c in colors:
        assert len(c["rgb"]) == 3
        assert all(0.0 <= v <= 1.0 for v in c["rgb"]), c["code"]
        assert c["name"] and c["name_es"], c["code"]
        assert c["name"][0].isupper(), c["code"]   # a name, not a fragment


def test_a_few_ral_colours_are_the_ones_the_standard_says():
    # Spot checks against the standard, so a bad parse or a shifted row is
    # caught: white, black, the light grey every façade is painted, and the
    # traffic red of a fire door.
    by = {c["code"]: c for f in _ral()["families"] for c in f["colors"]}

    def hex_of(code):
        return "".join("%02X" % round(v * 255) for v in by[code]["rgb"])

    assert hex_of("RAL 9010") == "F7F9EF"      # Pure white
    assert hex_of("RAL 9005") == "0A0A0D"      # Jet black
    assert hex_of("RAL 7035") == "CBD0CC"      # Light grey
    assert hex_of("RAL 3020") == "C1121C"      # Traffic red
    assert by["RAL 7035"]["name_es"] == "Gris claro"
    assert by["RAL 3020"]["name_es"] == "Rojo tráfico"


def test_every_ral_colour_is_in_exactly_one_family():
    data = _ral()
    ids = [f["id"] for f in data["families"]]
    assert len(set(ids)) == len(ids) == 9
    seen = set()
    for fam in data["families"]:
        assert fam["name"] and fam["name_es"], fam["id"]
        for c in fam["colors"]:
            assert c["code"] not in seen, c["code"]
            seen.add(c["code"])
        # A family holds one RAL thousand-range and nothing else.
        assert len({c["code"][4] for c in fam["colors"]}) == 1, fam["id"]
