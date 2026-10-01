# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The DWG bridge (D3): LibreDWG as a satellite process, plus the two DXF
repairs its 0.14 output needs before ezdxf will touch it. The repairs are
IngeCAD's, ported scars and all; the round-trip test drives the REAL
converters when the bundle is present."""
from __future__ import annotations

from pathlib import Path

import pytest

from formats import dwg_bridge


def _pairs(*items):
    return "\n".join(str(x) for x in items)


# ---- The DXF repairs --------------------------------------------------------
def test_null_handles_are_stripped(tmp_path):
    dxf = tmp_path / "t.dxf"
    dxf.write_text(_pairs(0, "SECTION", 2, "BLOCKS",
                          0, "ENDBLK", 5, 0,
                          0, "ENDSEC", 0, "EOF"))
    dwg_bridge._strip_null_handles(dxf)
    lines = dxf.read_text(encoding="utf-8").split("\n")
    assert "ENDBLK" in lines
    for i in range(0, len(lines) - 1, 2):
        assert not (lines[i].strip() == "5" and lines[i + 1].strip() == "0")


def test_reused_handles_are_renumbered_first_owner_keeps_it(tmp_path):
    dxf = tmp_path / "t.dxf"
    dxf.write_text(_pairs(
        0, "SECTION", 2, "TABLES",
        0, "BLOCK_RECORD", 5, 2,          # the legitimate owner
        0, "ENDSEC",
        0, "SECTION", 2, "OBJECTS",
        0, "LAYOUT", 5, 2,                # the thief (LibreDWG#1356)
        0, "ENDSEC", 0, "EOF"))
    fixed = dwg_bridge._dedupe_handles(dxf)
    assert fixed == 1
    lines = [ln.strip() for ln in dxf.read_text(encoding="utf-8").split("\n")]
    handles = [lines[i + 1] for i in range(0, len(lines) - 1, 2)
               if lines[i] == "5"]
    assert handles[0] == "2"              # the table record kept its handle
    assert handles[1] != "2"              # the layout got a fresh one
    assert len(set(handles)) == len(handles)


def test_handseed_header_value_is_not_an_object_handle(tmp_path):
    dxf = tmp_path / "t.dxf"
    dxf.write_text(_pairs(
        0, "SECTION", 2, "HEADER",
        9, "$HANDSEED", 5, 2,             # header VALUE, not a handle
        0, "ENDSEC",
        0, "SECTION", 2, "TABLES",
        0, "BLOCK_RECORD", 5, 2,
        0, "ENDSEC", 0, "EOF"))
    assert dwg_bridge._dedupe_handles(dxf) == 0   # no false collision


# ---- Tool discovery ---------------------------------------------------------
def test_missing_converter_raises_the_bridge_error(tmp_path, monkeypatch):
    monkeypatch.setattr(dwg_bridge, "find_dwg2dxf", lambda: None)
    with pytest.raises(dwg_bridge.DwgBridgeError):
        dwg_bridge.dwg_to_dxf(tmp_path / "x.dwg")


def test_discard_only_touches_our_own_temp_dirs(tmp_path):
    keeper = tmp_path / "fixtures" / "x.dxf"
    keeper.parent.mkdir()
    keeper.write_text("data")
    dwg_bridge.discard_temp_dxf(keeper)
    assert keeper.exists()                # fixture paths must survive


# ---- The real satellite (when the bundle is present) ------------------------
_have_tools = (dwg_bridge.find_dwg2dxf() is not None
               and dwg_bridge._find_tool("dxf2dwg") is not None)


@pytest.mark.skipif(not _have_tools, reason="LibreDWG bundle not present")
def test_dwg_round_trip_through_the_real_converters(tmp_path):
    """DXF → dxf2dwg → DWG → dwg_to_dxf → our importer: the geometry that
    went in comes out, through the actual satellite binaries."""
    import ezdxf

    from core.scene import Scene
    from formats.dxf_in import load_dxf

    doc = ezdxf.new("R2000")              # the version our build writes
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0))
    msp.add_circle((5, 5), 2.0)
    src = tmp_path / "obra.dxf"
    doc.saveas(str(src))

    dwg = tmp_path / "obra.dwg"
    tool = dwg_bridge._find_tool("dxf2dwg")
    dwg_bridge._run([str(tool), "-y", "-o", str(dwg), str(src)], dwg)
    assert dwg.stat().st_size > 0

    dxf = dwg_bridge.dwg_to_dxf(dwg)
    try:
        scene = Scene()
        stats = load_dxf(scene, dxf, scale=1.0, name="obra")
    finally:
        dwg_bridge.discard_temp_dxf(dxf)
    assert not dxf.exists()               # the temp went with its dir
    assert stats["edges"] >= 9            # the line + the flattened circle
    g = scene.groups[0]
    assert g.name == "obra"               # the USER's name, not "converted"
    curves = {e.curve for e in g.mesh.edges if e.curve is not None}
    assert len(curves) == 1               # the circle survived as one contour


# ---- Every package carries the converter (#101) ------------------------------

def test_windows_looks_for_the_exe_beside_its_dlls(tmp_path, monkeypatch):
    """«El conversor de LibreDWG (dwg2dxf) no está disponible en esta
    instalación» (#101, #180): Windows now ships dwg2dxf.exe, and the
    bridge must look for that name there."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "dwg2dxf.exe").write_bytes(b"MZ")
    monkeypatch.setattr(dwg_bridge, "_VENDOR_BIN", bin_dir)
    monkeypatch.setattr(dwg_bridge, "_SIBLING_BIN", tmp_path / "none")
    monkeypatch.setattr(dwg_bridge.shutil, "which", lambda name: None)
    monkeypatch.setattr(dwg_bridge.sys, "platform", "win32")
    assert dwg_bridge.find_dwg2dxf() == bin_dir / "dwg2dxf.exe"
    monkeypatch.setattr(dwg_bridge.sys, "platform", "linux")
    assert dwg_bridge.find_dwg2dxf() is None     # the bare name is not there


def _root():
    from pathlib import Path
    return Path(__file__).resolve().parents[1]


def test_the_flatpak_installs_the_converter():
    recipe = (_root() / "packaging/flatpak/com.ingetrazo.IngeTrazo.yml").read_text(encoding="utf-8")
    assert ("vendor/libredwg/bin/dwg2dxf ${FLATPAK_DEST}/ingetrazo/"
            "vendor/libredwg/bin/dwg2dxf") in recipe
    assert "vendor/libredwg/SOURCES.md" in recipe


def test_the_spec_bundles_it_on_all_three_platforms():
    spec = (_root() / "ingetrazo.spec").read_text(encoding="utf-8")
    for name in ('"dwg2dxf.exe"', '"libredwg-0.dll"', '"libiconv-2.dll"',
                 '"linux": ["dwg2dxf"]', '"darwin": ["dwg2dxf"]'):
        assert name in spec
    win = (_root() / ".github/workflows/build-windows.yml").read_text(encoding="utf-8")
    assert "libredwg-$V-win64.zip" in win and "sha256sum -c" in win
    mac = (_root() / ".github/workflows/release-macos.yml").read_text(encoding="utf-8")
    assert "programs/dwg2dxf" in mac and "shasum -a 256 -c" in mac


def test_check_reports_the_converter(capsys):
    import main
    main._self_check()
    assert "DWG converter" in capsys.readouterr().out
