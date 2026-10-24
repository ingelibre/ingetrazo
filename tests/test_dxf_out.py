"""The view-to-DXF writer (issue #428): a real header, units, layers and
linetypes, written with ezdxf so Illustrator, LibreCAD and AutoCAD read it."""
import ezdxf
import pytest
from ezdxf import recover

from formats.dxf_out import save_dxf_layers, save_dxf_lines

GROUPS = [
    ("Planta 1", [(0.0, 0.0, 2.0, 0.0), (2.0, 0.0, 2.0, 3.0)]),
    ("Planta 1-PERFIL", [(0.0, 0.0, 0.0, 3.0)]),
    ("Planta 1-CORTE", []),
    ("Planta 1-OCULTAS", [(0.0, 1.0, 2.0, 1.0)], "DASHED"),
]


def _read(path):
    doc = ezdxf.readfile(str(path))
    auditor = doc.audit()
    assert not auditor.errors and not auditor.fixes
    return doc


def test_header_version_and_audit(tmp_path):
    path = tmp_path / "v.dxf"
    save_dxf_layers(path, GROUPS)
    doc = _read(path)
    assert doc.dxfversion == "AC1015"          # R2000, read by every CAD
    assert doc.header["$INSUNITS"] == 6        # metres by default
    text = path.read_text(encoding="cp1252")
    assert "SECTION\n  2\nHEADER" in text.replace("\r", "")


def test_layers_linetypes_and_entity_count(tmp_path):
    path = tmp_path / "v.dxf"
    n = save_dxf_layers(path, GROUPS)
    doc = _read(path)
    assert n == 4
    lines = list(doc.modelspace().query("LINE"))
    assert len(lines) == 4
    assert {layer.dxf.name for layer in doc.layers} >= {
        "PLANTA_1", "PLANTA_1-PERFIL", "PLANTA_1-CORTE", "PLANTA_1-OCULTAS"}
    assert doc.layers.get("PLANTA_1-OCULTAS").dxf.linetype == "DASHED"
    assert doc.layers.get("PLANTA_1").dxf.linetype == "CONTINUOUS"
    assert "DASHED" in doc.linetypes
    assert sum(1 for e in lines if e.dxf.layer == "PLANTA_1") == 2


def test_no_dashed_layer_still_has_continuous(tmp_path):
    path = tmp_path / "v.dxf"
    save_dxf_lines(path, [(0.0, 0.0, 9.258, 0.0)], layer="PLANTA")
    doc = _read(path)
    (line,) = doc.modelspace().query("LINE")
    assert line.dxf.end.x == pytest.approx(9.258)
    assert line.dxf.layer == "PLANTA"
    assert "CONTINUOUS" in doc.linetypes


@pytest.mark.parametrize("unit,code,scale", [
    ("m", 6, 1.0), ("cm", 5, 100.0), ("mm", 4, 1000.0),
    ("in", 1, 1 / 0.0254), ("ft-in-frac", 2, 1 / 0.3048)])
def test_units_set_insunits_and_scale_the_coordinates(tmp_path, unit, code,
                                                      scale):
    path = tmp_path / "v.dxf"
    save_dxf_lines(path, [(0.0, 0.0, 2.0, 3.0)], units=unit)
    doc = _read(path)
    assert doc.header["$INSUNITS"] == code
    (line,) = doc.modelspace().query("LINE")
    assert line.dxf.end.x == pytest.approx(2.0 * scale)
    assert line.dxf.end.y == pytest.approx(3.0 * scale)


def test_dash_pattern_follows_the_units(tmp_path):
    path = tmp_path / "v.dxf"
    save_dxf_layers(path, [("H", [(0, 0, 1, 0)], "DASHED")], units="mm")
    doc = _read(path)
    dashes = [t.value for t in doc.linetypes.get("DASHED").pattern_tags.tags
              if t.code == 49]
    assert dashes == pytest.approx([500.0, -250.0])     # 0.5 m dash, 0.25 m gap


def test_awkward_layer_names_are_made_valid(tmp_path):
    path = tmp_path / "v.dxf"
    save_dxf_lines(path, [(0, 0, 1, 1)], layer='A<b>/c:"d"|e')
    doc = _read(path)
    (line,) = doc.modelspace().query("LINE")
    assert line.dxf.layer in doc.layers
    _, auditor = recover.readfile(str(path))
    assert not auditor.has_errors


def test_empty_export_is_valid(tmp_path):
    path = tmp_path / "v.dxf"
    assert save_dxf_layers(path, [("VISTA", [])]) == 0
    assert len(list(_read(path).modelspace())) == 0
