# SPDX-License-Identifier: GPL-3.0-or-later
"""The AI bridge's document tools: open, save (behind its gate), export a
scene as a picture, export the sheets — in a window, in process."""
from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage

from tests.test_ai_bridge import _ask


@pytest.fixture
def bridged(monkeypatch):
    from plugins.ai_bridge import _Bridge
    from views.main_window import MainWindow
    monkeypatch.setenv("INGETRAZO_AI_PORT", "0")
    win = MainWindow()
    bridge = _Bridge(win.viewport)
    bridge.start()
    try:
        yield win, bridge
    finally:
        bridge.stop()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_saving_follows_the_panel_checkbox(bridged, tmp_path):
    from plugins.ai_bridge import ALLOW_SAVE_KEY
    win, bridge = bridged
    out = tmp_path / "a.igz"
    st = QSettings()
    try:
        st.setValue(ALLOW_SAVE_KEY, "0")
        r = _ask(bridge, "save_document", {"path": str(out)})
        assert not r["ok"] and "Allow the agent to save" in r["error"]
        assert not out.exists()
        st.setValue(ALLOW_SAVE_KEY, "1")
        r = _ask(bridge, "save_document", {"path": str(out),
                                           "format": "json"})
        assert r["ok"], r
        assert r["result"]["format"] == "json"
        assert out.read_bytes().startswith(b"{\n")
        assert win._current_path == out
        assert not win._doc_is_dirty(win._doc)
        # The command line's word is final, either way.
        bridge.allow_save = False
        r = _ask(bridge, "save_document")
        assert not r["ok"]
    finally:
        st.remove(ALLOW_SAVE_KEY)


def test_save_refuses_what_is_not_an_igz(bridged, tmp_path):
    _win, bridge = bridged
    bridge.allow_save = True
    r = _ask(bridge, "save_document")
    assert not r["ok"] and "give a path" in r["error"]
    r = _ask(bridge, "save_document", {"path": str(tmp_path / "a.txt")})
    assert not r["ok"] and ".igz" in r["error"]
    r = _ask(bridge, "save_document", {"path": str(tmp_path / "a.igz"),
                                       "format": "xml"})
    assert not r["ok"] and "xml" in r["error"]


def test_open_document_says_when_it_could_not(bridged, tmp_path):
    _win, bridge = bridged
    r = _ask(bridge, "open_document", {"path": str(tmp_path / "nope.igz")})
    assert not r["ok"] and "no such file" in r["error"]
    bad = tmp_path / "bad.igz"
    bad.write_text("{ not json")
    r = _ask(bridge, "open_document", {"path": str(bad)})
    assert not r["ok"] and "could not open" in r["error"]


def test_open_document_opens_and_reports(bridged, tmp_path):
    from formats import igz
    from tests.test_igz_formats_unchanged import _scene
    src = tmp_path / "doc.igz"
    igz.save_scene(_scene(), src)
    win, bridge = bridged
    r = _ask(bridge, "open_document", {"path": str(src)})
    assert r["ok"], r
    assert r["result"]["path"] == str(src)
    assert r["result"]["modified"] is False


def test_a_plain_json_document_stays_plain_json(bridged, tmp_path,
                                                monkeypatch):
    """Opened from the plain-JSON layout and saved under Automatic, a
    textured document must not turn into a ZIP: Git would only say
    «binary files differ» from then on."""
    from core import general_settings
    from formats import igz
    from tests.test_igz_formats_unchanged import _PNG, _scene
    monkeypatch.setattr(general_settings, "value",
                        lambda name, default=None, settings=None:
                        "auto" if name == "save_format" else default)
    png = tmp_path / "wood.png"
    png.write_bytes(_PNG)
    src = tmp_path / "doc" / "Casa.igz"
    src.parent.mkdir()
    igz.save_scene(_scene(png), src, fmt="json")
    win, bridge = bridged
    bridge.allow_save = True
    assert _ask(bridge, "open_document", {"path": str(src)})["ok"]
    assert win.save_format() == "json"
    r = _ask(bridge, "save_document")
    assert r["ok"] and r["result"]["format"] == "json", r
    assert src.read_bytes().startswith(b"{")
    # Asked for by name, the other format still wins — and sticks.
    r = _ask(bridge, "save_document", {"format": "auto"})
    assert r["ok"] and src.read_bytes().startswith(b"PK"), r
    assert win.save_format() == "auto"


def test_export_view_puts_everything_back(bridged, tmp_path):
    """The picture itself needs a GL context, which a window never shown
    has not: tests/test_headless.py checks the PNG. Here: whatever the
    render did, the camera is back and a saved document stays saved."""
    from PySide6.QtGui import QVector3D
    from core.saved_views import SavedView
    win, bridge = bridged
    vp = win.viewport
    vp.scene.mesh.add_edge(QVector3D(0, 0, 0), QVector3D(3, 0, 0))
    view = SavedView.capture("Frente", vp.scene, vp.camera)
    view.yaw += 1.0
    view.distance *= 2
    vp.scene.saved_views.append(view)
    win._saved_version = vp.scene.version            # saved, as it were
    yaw, dist = vp.camera.yaw, vp.camera.distance
    out = tmp_path / "views" / "frente.png"
    r = _ask(bridge, "export_view", {"view": "Frente", "path": str(out),
                                     "width": 320, "height": 200})
    if r["ok"]:
        img = QImage(str(out))
        assert (img.width(), img.height()) == (320, 200)
    else:
        assert "did not render" in r["error"]
    assert (vp.camera.yaw, vp.camera.distance) == (yaw, dist)
    assert not win._doc_is_dirty(win._doc)
    r = _ask(bridge, "export_view", {"view": "Nope", "path": str(out)})
    assert not r["ok"] and "Frente" in r["error"]


def test_export_pdf_needs_sheets(bridged, tmp_path):
    win, bridge = bridged
    win.viewport.scene.compositions.clear()
    r = _ask(bridge, "export_pdf", {"path": str(tmp_path / "x.pdf")})
    assert not r["ok"] and "no sheets" in r["error"]


def test_document_info(bridged):
    _win, bridge = bridged
    r = _ask(bridge, "document_info")
    assert r["ok"]
    info = r["result"]
    assert info["path"] is None and info["shutdown_allowed"] is False
    assert info["save_format"] in ("auto", "json")
    json.dumps(info)                                  # all plain values


def test_shutdown_is_off_in_the_window(bridged):
    _win, bridge = bridged
    r = _ask(bridge, "shutdown", {"discard_changes": True})
    assert not r["ok"] and "--allow-shutdown" in r["error"]
