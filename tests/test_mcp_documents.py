# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""One MCP connection explicitly targets live documents, never window focus."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import threading
import time

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from formats import igz


@pytest.fixture
def documents(tmp_path, monkeypatch):
    from views.main_window import MainWindow

    monkeypatch.setenv("INGETRAZO_AI_REGISTRY", str(tmp_path / "bridges"))
    monkeypatch.delenv("INGETRAZO_AI_PORT", raising=False)
    monkeypatch.delenv("INGETRAZO_AI_HOST", raising=False)
    windows = []
    try:
        for name in ("Building", "Site"):
            directory = tmp_path / name
            directory.mkdir()
            mesh = Mesh()
            mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(0, 1, 0)])
            path = directory / "model.igz"  # duplicate basenames must work
            igz.save_scene(Scene(groups=[Group(mesh, name)]), path)
            window = MainWindow()
            windows.append(window)
            assert window.open_path(path)
            assert window._ai_bridge_section.start()
        script = Path(__file__).resolve().parents[1] / "scripts/ingetrazo_mcp.py"
        spec = importlib.util.spec_from_file_location("_multi_document_client", script)
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
        yield client, windows
    finally:
        for window in windows:
            window._saved_version = window.viewport.scene.version
            window.close()
        QApplication.processEvents()


def _call(client, name, **arguments):
    """Run the real TCP client while Qt dispatches requests on its UI thread."""
    result = {}

    def worker():
        try:
            result["reply"] = client.handle({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            })["result"]
        except Exception as exc:
            result["exception"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while thread.is_alive() and time.monotonic() < deadline:
        QApplication.processEvents()
        thread.join(0.005)
    assert not thread.is_alive(), "MCP request did not finish"
    if "exception" in result:
        raise result["exception"]
    return result["reply"]


def _result(client, name, **arguments):
    result = _call(client, name, **arguments)
    assert not result.get("isError"), result
    return result["content"][0]["text"]


def _list(client):
    return json.loads(_result(client, "list_documents"))["documents"]


def _query(client, document_id):
    return json.loads(_result(client, "query_model", document_id=document_id))


def test_one_client_keeps_queries_edits_and_undo_in_the_selected_document(documents):
    client, windows = documents
    listed = _list(client)
    assert {d["path"] for d in listed} == {str(w._current_path.resolve()) for w in windows}
    assert all(not d["dirty"] for d in listed)
    by_path = {d["path"]: d["document_id"] for d in listed}
    a, b = [by_path[str(w._current_path.resolve())] for w in windows]
    assert a != b
    assert _query(client, a)["group_names"] == ["Building"]
    assert _query(client, b)["group_names"] == ["Site"]
    _result(client, "run_python", document_id=a,
            code="mesh.add_edge(QVector3D(0,0,0), QVector3D(2,0,0))")
    assert _query(client, a)["edges"] == 1
    assert _query(client, b)["edges"] == 0
    dirty = {d["document_id"]: d["dirty"] for d in _list(client)}
    assert dirty == {a: True, b: False}
    _result(client, "run_python", document_id=b,
            code="mesh.add_edge(QVector3D(0,0,0), QVector3D(3,0,0))")
    assert json.loads(_result(client, "undo", document_id=a))["ok"]
    assert _query(client, a)["edges"] == 0
    assert _query(client, b)["edges"] == 1
    assert json.loads(_result(client, "redo", document_id=a))["ok"]
    assert _query(client, a)["edges"] == 1
    assert windows[1].viewport.scene.mesh.edges[0].length() == pytest.approx(3)


def test_open_new_save_and_close_have_explicit_target_lifetimes(documents, tmp_path):
    client, windows = documents
    window = windows[0]
    a = next(d["document_id"] for d in _list(client)
             if d["path"] == str(window._current_path.resolve()))
    _result(client, "run_python", document_id=a, code="remembered = groups[0]")
    # Saving/renaming the current document must not invalidate its identity.
    renamed = tmp_path / "renamed.igz"
    window._do_save(renamed)
    assert next(d for d in _list(client) if d["document_id"] == a)["path"] == str(renamed)
    assert _query(client, a)["group_names"] == ["Building"]
    # Reopening even the same path creates a new lifetime and clears scope.
    assert window.open_path(renamed)
    fresh = next(d["document_id"] for d in _list(client) if d["path"] == str(renamed))
    assert fresh != a
    for tool in ("query_model", "run_python", "screenshot", "undo", "redo"):
        args = {"code": "mesh.add_edge(QVector3D(0,0,0), QVector3D(5,0,0))"} if tool == "run_python" else {}
        assert _call(client, tool, document_id=a, **args)["isError"]
    assert _query(client, fresh)["edges"] == 0
    assert _result(client, "run_python", document_id=fresh,
                   code="print('remembered' in globals())").startswith("False")
    assert _call(client, "undo")["isError"]  # never guess the sole/active window
    window._saved_version = window.viewport.scene.version
    window._on_new()
    assert _call(client, "query_model", document_id=fresh)["isError"]
    remaining = next(d["document_id"] for d in _list(client) if d["path"] is None)
    window._saved_version = window.viewport.scene.version
    assert window.close()
    assert all(d["document_id"] != remaining for d in _list(client))
    assert _call(client, "undo", document_id=remaining)["isError"]
    assert _query(client, _list(client)[0]["document_id"])["group_names"] == ["Site"]


def test_copied_registry_configuration_works_from_another_directory(
        documents, monkeypatch, tmp_path):
    client, windows = documents
    for window in windows:
        window._ai_bridge_section.stop()
    app_directory = tmp_path / "app"
    client_directory = tmp_path / "client"
    app_directory.mkdir()
    client_directory.mkdir()
    monkeypatch.chdir(app_directory)
    monkeypatch.setenv("INGETRAZO_AI_REGISTRY", "bridges")
    window = windows[0]
    assert window._ai_bridge_section.start()
    monkeypatch.chdir(client_directory)
    # Refreshing/copying after cwd changes must still name the published
    # registry, not a second directory under the new cwd.
    window._ai_bridge_section._refresh()
    instructions = window._ai_bridge_section._text.toPlainText()
    config, _ = json.JSONDecoder().raw_decode(instructions[instructions.index("{"):])
    server = config["mcpServers"]["ingetrazo"]
    monkeypatch.setenv("INGETRAZO_AI_REGISTRY",
                       server["env"]["INGETRAZO_AI_REGISTRY"])
    listed = _list(client)
    assert len(listed) == 1
    assert listed[0]["path"] == str(window._current_path.resolve())
    assert _query(client, listed[0]["document_id"])["group_names"] == ["Building"]
