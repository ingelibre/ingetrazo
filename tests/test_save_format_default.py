# SPDX-License-Identifier: GPL-3.0-or-later
"""PR #1494 merged into 0.6.3: the plain-JSON save is an option beside the
.igz of always, never instead of it (Marco, 19-11: «compatibilidad total
hacia atrás; el .igz de siempre sigue siendo el predeterminado»).

Also the two things the merge had to put together by hand: the document's
picture (0.6.3) with the plain-JSON layout (the PR), and ``--server`` (the
short form Marco asked for) with the PR's ``--headless``."""
from __future__ import annotations

import json
import os
import struct
import zlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _png() -> bytes:
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
            + chunk(b"IEND", b""))


def _scene():
    from PySide6.QtGui import QVector3D as V
    from core.scene import Scene
    scene = Scene()
    scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    return scene


def test_the_default_save_format_is_the_igz_of_always(tmp_path,
                                                      monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from views import main_window as mw
    # Nobody chose a save format (whatever this machine's settings say).
    real = mw._gs.value
    monkeypatch.setattr(mw._gs, "value", lambda key, default=None, *a, **k: (
        default if key == "save_format" else real(key, default, *a, **k)))
    win = mw.MainWindow()
    try:
        assert win.save_format() == "auto"
        out = tmp_path / "casa.igz"
        stats = win.write_document(out)
        assert stats["format"] == "auto"
        raw = out.read_bytes()
        if raw[:4] == b"PK\x03\x04":
            # The new document's scale figure is textured: a container,
            # as Automatic has always packed it.
            import io
            import zipfile
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                data = json.loads(zf.read("document.json"))
        else:
            data = json.loads(raw)
        assert "layout" not in data and "assets" not in data
        assert data["igz_format"] in (1, 2, 3)
        assert not (tmp_path / "casa.assets").exists()
        assert win.viewport.scene.saved_layout is None
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_picture_goes_into_the_container_never_into_plain_json(tmp_path):
    from formats import igz
    png = _png()
    auto = tmp_path / "auto.igz"
    igz.save_scene(_scene(), auto, thumbnail=png)
    assert auto.read_bytes()[:4] == b"PK\x03\x04"
    assert igz.read_thumbnail(auto) == png
    plain = tmp_path / "plano.igz"
    igz.save_scene(_scene(), plain, thumbnail=png, fmt="json")
    data = json.loads(plain.read_text(encoding="utf-8"))
    assert data["layout"] == "plain-json"
    assert igz.read_thumbnail(plain) is None
    assert not (tmp_path / "plano.assets").exists()      # no stray PNG
    from core.scene import Scene
    for path in (auto, plain):
        back = Scene()
        igz.load_into(back, path)
        assert len(back.mesh.faces) == 1


@pytest.mark.parametrize("argv, expected", [
    (["--server"], ["--headless", "--ai-bridge"]),
    (["--server", "/x/casa.igz", "--port", "0"],
     ["--headless", "--ai-bridge", "--open", "/x/casa.igz", "--port", "0"]),
    (["--port", "4800", "--server", "casa.igz", "--allow-save"],
     ["--headless", "--ai-bridge", "--port", "4800", "--open", "casa.igz",
      "--allow-save"]),
    (["--server", "--open", "a.igz", "--save-format", "json"],
     ["--headless", "--ai-bridge", "--open", "a.igz", "--save-format",
      "json"]),
])
def test_server_is_the_short_form_of_headless(argv, expected):
    import main
    assert main._server_argv(argv) == expected
    # And the PR's parser takes it: one mode, one parser.
    args = main._parse_headless(main._server_argv(argv))
    assert args.headless and args.ai_bridge
