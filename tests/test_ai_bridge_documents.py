# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Observable bridge routing, lifecycle, and transactional execution boundaries."""
from __future__ import annotations

import json
import os
import socket
import threading
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from core import ai_discovery
from plugins.ai_bridge import _bridge_of


@pytest.fixture
def bridge_window(monkeypatch, tmp_path):
    monkeypatch.setenv("INGETRAZO_AI_REGISTRY", str(tmp_path / "registry"))
    monkeypatch.delenv("INGETRAZO_AI_PORT", raising=False)
    monkeypatch.delenv("INGETRAZO_AI_HOST", raising=False)
    windows = []

    def create(*, start=True):
        from views.main_window import MainWindow
        window = MainWindow()
        window._confirm_discard = lambda *args, **kwargs: True
        windows.append(window)
        bridge = _bridge_of(window.viewport)
        if start:
            bridge.start()
        return window, bridge

    yield create
    for window in windows:
        window._ai_bridge.stop()
        window.close()
    QApplication.instance().processEvents()


def _request(tool, args=None, *, target=None, **outer):
    request = {"id": 37, "tool": tool, "args": args or {}}
    if target is not None:
        request.update(instance_id=target["instance_id"],
                       document_id=target["document_id"])
    request.update(outer)
    return request


def _begin_exchange(port, payload):
    out = {}

    def worker():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
                sock.sendall(payload)
                sock.shutdown(socket.SHUT_WR)
                buf = b""
                while b"\n" not in buf:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                out["data"] = buf
        except Exception as exc:
            out["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread, out


def _finish_exchange(thread, out):
    deadline = time.monotonic() + 10.0
    while thread.is_alive() and time.monotonic() < deadline:
        QApplication.instance().processEvents()
        thread.join(timeout=0.01)
    assert not thread.is_alive(), "bridge request did not finish"
    if "error" in out:
        raise out["error"]
    return out["data"]


def _ask(bridge, tool, args=None, *, target=None, **outer):
    request = _request(tool, args, target=target, **outer)
    thread, out = _begin_exchange(
        bridge.port, (json.dumps(request) + "\n").encode())
    raw = _finish_exchange(thread, out)
    assert raw, "bridge closed without replying"
    reply = json.loads(raw.split(b"\n", 1)[0])
    assert reply["id"] == request["id"]
    return reply


def _document(bridge):
    reply = _ask(bridge, "list_documents", instance_id=bridge.instance_id)
    assert reply["ok"], reply
    document, = reply["result"]["documents"]
    return document


def _queue_request(bridge, request):
    """Wait for the worker to queue dispatch without processing Qt events."""
    submitted = threading.Event()

    def queued(job):
        submitted.set()

    bridge._dispatch.connect(queued, Qt.DirectConnection)
    try:
        thread, out = _begin_exchange(
            bridge.port, (json.dumps(request) + "\n").encode())
        assert submitted.wait(timeout=5.0), "request never reached the bridge"
    finally:
        bridge._dispatch.disconnect(queued)
    return thread, out


def test_windows_publish_independent_endpoints_and_live_documents(bridge_window):
    first, a = bridge_window()
    second, b = bridge_window()
    assert a.port != b.port
    records = {record["instance_id"]: record for record in ai_discovery.read_endpoints()}
    assert set(records) == {a.instance_id, b.instance_id}
    assert records[a.instance_id]["port"] == a.port
    assert records[b.instance_id]["port"] == b.port
    doc_a, doc_b = _document(a), _document(b)
    assert doc_a["document_id"] != doc_b["document_id"]
    assert doc_a["pid"] == doc_b["pid"] == os.getpid()
    assert doc_a["instance_id"] == a.instance_id
    assert doc_b["instance_id"] == b.instance_id

    edges_a = len(first.viewport.scene.mesh.edges)
    edges_b = len(second.viewport.scene.mesh.edges)
    code = "mesh.add_edge(QVector3D(0,0,0), QVector3D(2,0,0))"
    assert _ask(a, "run_python", {"code": code}, target=doc_a)["result"]["changed"]
    assert len(first.viewport.scene.mesh.edges) == edges_a + 1
    assert len(second.viewport.scene.mesh.edges) == edges_b
    assert not _ask(b, "run_python", {"code": code}, target=doc_a)["ok"]
    assert not _ask(b, "list_documents", instance_id=a.instance_id)["ok"]
    # An explicitly forwarded endpoint may learn the instance through discovery.
    assert _ask(b, "list_documents")["result"]["documents"] == [doc_b]

    port = a.port
    assert a.start() == port
    assert len(ai_discovery.read_endpoints()) == 2
    a.stop()
    a.stop()
    assert [record["instance_id"] for record in ai_discovery.read_endpoints()] == [b.instance_id]
    assert _document(b)["document_id"] == doc_b["document_id"]


def test_every_document_tool_rejects_missing_or_stale_ids(bridge_window):
    window, bridge = bridge_window()
    target = _document(bridge)
    tools = ("run_python", "query_model", "screenshot", "undo", "redo")
    invalid = ({}, {"instance_id": target["instance_id"]},
               {"document_id": target["document_id"]},
               {"instance_id": "old-window", "document_id": target["document_id"]},
               {"instance_id": target["instance_id"], "document_id": "old-document"})
    edges = len(window.viewport.scene.mesh.edges)
    for tool in tools:
        for identity in invalid:
            assert not _ask(bridge, tool, {"code": (
                "mesh.add_edge(QVector3D(0,0,0), QVector3D(2,0,0))")}
                if tool == "run_python" else {}, **identity)["ok"]
    assert len(window.viewport.scene.mesh.edges) == edges
    unknown = _ask(bridge, "no_such_tool", target=target)
    assert not unknown["ok"] and "unknown tool" in unknown["error"]


def test_metadata_tracks_application_dirty_state_without_retargeting(bridge_window, tmp_path):
    window, bridge = bridge_window()
    scene = window.viewport.scene
    window._saved_version = scene.version
    clean = _document(bridge)
    assert clean["dirty"] is False
    scene.bump_view()
    selected = _document(bridge)
    assert selected["dirty"] is False
    assert selected["revision"] == clean["revision"]

    window._import_name = "imported-model.obj"
    window._update_title()
    imported = _document(bridge)
    assert imported["name"] == "imported-model.obj"
    assert imported["path"] is None
    window._current_path = tmp_path / "saved-model.igz"
    window._update_title()
    saved = _document(bridge)
    assert saved["path"] == str(window._current_path.resolve())
    assert saved["name"] == "saved-model.igz"
    assert saved["title"] == window.windowTitle()
    assert saved["document_id"] == imported["document_id"] == clean["document_id"]

    _ask(bridge, "run_python", {"code": (
        "mesh.add_edge(QVector3D(0,0,0), QVector3D(2,0,0))")}, target=saved)
    changed = _document(bridge)
    assert changed["dirty"] == window._is_dirty() is True
    assert changed["revision"] == scene.content_version
    assert changed["document_id"] == clean["document_id"]
    window._saved_version = scene.version
    assert _document(bridge)["dirty"] is False


@pytest.mark.parametrize("replacement", ["clear", "set_document"])
def test_replacement_rejects_queued_old_ids_and_discards_python_scope(bridge_window, replacement):
    from core.history import History
    from core.scene import Scene
    window, bridge = bridge_window()
    target = _document(bridge)
    assert _ask(bridge, "run_python", {"code": "old_mesh = mesh\nmarker = 91"},
                target=target)["ok"]
    thread, out = _queue_request(bridge, _request("run_python", {"code": (
        "mesh.add_edge(QVector3D(0,0,0), QVector3D(2,0,0))")}, target=target))
    if replacement == "clear":
        window.viewport.scene.clear()
    else:
        scene = Scene()
        window.viewport.set_document(scene, History(scene))
    edges = len(window.viewport.scene.mesh.edges)
    reply = json.loads(_finish_exchange(thread, out))
    assert not reply["ok"]
    assert len(window.viewport.scene.mesh.edges) == edges
    current = _document(bridge)
    assert current["document_id"] != target["document_id"]
    reply = _ask(bridge, "run_python", {"code": (
        "print('marker' in globals(), 'old_mesh' in globals())")}, target=current)
    assert reply["result"]["stdout"].strip() == "False False"


def test_group_edit_changes_mesh_but_not_document_or_python_scope(bridge_window):
    from core.group import Group
    window, bridge = bridge_window()
    scene = window.viewport.scene
    group = Group(name="Editable group")
    scene.groups.append(group)
    target = _document(bridge)
    _ask(bridge, "run_python", {"code": "marker = 91"}, target=target)
    scene.begin_group_edit(group)
    try:
        assert _document(bridge)["document_id"] == target["document_id"]
        reply = _ask(bridge, "run_python", {"code": "print(marker, mesh is scene.mesh)"},
                     target=target)
        assert reply["result"]["stdout"].strip() == "91 True"
    finally:
        scene.end_group_edit()
    assert _document(bridge)["document_id"] == target["document_id"]


def test_document_replacement_in_progress_exposes_no_tools(bridge_window, monkeypatch):
    window, bridge = bridge_window()
    target = _document(bridge)
    calls = []
    for tool in ("list_documents", "run_python", "query_model", "screenshot", "undo", "redo"):
        monkeypatch.setattr(bridge, f"_tool_{tool}", lambda **args: calls.append(args))
    window.viewport.setUpdatesEnabled(False)
    try:
        assert not _ask(bridge, "list_documents")["ok"]
        for tool in ("run_python", "query_model", "screenshot", "undo", "redo"):
            assert not _ask(bridge, tool, target=target)["ok"]
    finally:
        window.viewport.setUpdatesEnabled(True)
    assert calls == []


def test_stop_closes_idle_socket_and_allows_pinned_restart(bridge_window, monkeypatch):
    _, bridge = bridge_window()
    port = bridge.port
    thread = bridge._thread
    with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
        bridge.stop()
        try:
            assert sock.recv(1) == b""
        except ConnectionResetError:
            pass
    assert not thread.is_alive()
    assert not bridge.running and bridge.port is None
    assert ai_discovery.read_endpoints() == []
    monkeypatch.setenv("INGETRAZO_AI_PORT", str(port))
    assert bridge.start() == port
    assert _document(bridge)["instance_id"] == bridge.instance_id
    assert len(ai_discovery.read_endpoints()) == 1


def test_stop_and_window_close_cancel_already_queued_operations(bridge_window):
    window, bridge = bridge_window()
    target = _document(bridge)
    edges = len(window.viewport.scene.mesh.edges)
    request = _request("run_python", {"code": (
        "mesh.add_edge(QVector3D(0,0,0), QVector3D(2,0,0))")}, target=target)
    thread, out = _queue_request(bridge, request)
    bridge.stop()
    bridge.start()
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    QApplication.instance().processEvents()
    assert len(window.viewport.scene.mesh.edges) == edges
    assert _document(bridge)["document_id"] == target["document_id"]

    window._confirm_discard = lambda *args: False
    assert not window.close()
    assert bridge.running
    assert len(ai_discovery.read_endpoints()) == 1
    thread, out = _queue_request(bridge, request)
    window._confirm_discard = lambda *args: True
    assert window.close()
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    QApplication.instance().processEvents()
    assert len(window.viewport.scene.mesh.edges) == edges
    assert not bridge.running
    assert ai_discovery.read_endpoints() == []


def test_registration_failure_releases_the_bound_port(bridge_window, monkeypatch):
    _, bridge = bridge_window()
    port = bridge.port
    bridge.stop()
    monkeypatch.setenv("INGETRAZO_AI_PORT", str(port))

    def fail_registration(*args):
        raise OSError("registry unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(ai_discovery, "register", fail_registration)
        with pytest.raises(OSError, match="registry unavailable"):
            bridge.start()
    assert not bridge.running and bridge.port is None
    assert ai_discovery.read_endpoints() == []
    assert bridge.start() == port
    assert _document(bridge)["instance_id"] == bridge.instance_id


def test_relative_registry_is_removed_after_working_directory_changes(
        bridge_window, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INGETRAZO_AI_REGISTRY", "registry")
    _, bridge = bridge_window()
    record = tmp_path / "registry" / f"{bridge.instance_id}.json"
    assert record.exists()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    bridge.stop()
    assert not record.exists()




def test_bridge_runs_python_transactionally(bridge_window):
    window, bridge = bridge_window()
    vp = window.viewport
    target = _document(bridge)
    edges = len(vp.scene.mesh.edges)
    reply = _ask(bridge, "run_python", {"code": (
        "mesh.add_edge(QVector3D(0,0,0), QVector3D(2,0,0))")}, target=target)
    assert reply["ok"] and reply["result"]["changed"] is True
    assert len(vp.scene.mesh.edges) == edges + 1
    assert _ask(bridge, "undo", target=target)["result"]["ok"]
    assert len(vp.scene.mesh.edges) == edges
    assert _ask(bridge, "redo", target=target)["result"]["ok"]
    assert len(vp.scene.mesh.edges) == edges + 1
    assert _ask(bridge, "undo", target=target)["result"]["ok"]
    depth = len(vp.history.undo_stack)
    reply = _ask(bridge, "run_python", {"code": (
        "mesh.add_edge(QVector3D(9,0,0), QVector3D(9,9,0))\n"
        "raise RuntimeError('boom')")}, target=target)
    assert reply["ok"] and reply["result"]["changed"] is False
    assert reply["result"]["error"]
    assert len(vp.scene.mesh.edges) == edges
    assert len(vp.history.undo_stack) == depth
    reply = _ask(bridge, "run_python", {"code": "print(len(mesh.edges))"}, target=target)
    assert reply["ok"] and reply["result"]["changed"] is False
    assert reply["result"]["stdout"].strip() == str(edges)
    assert len(vp.history.undo_stack) == depth
    assert _ask(bridge, "query_model", target=target)["result"]["edges"] == edges
    assert _document(bridge)["document_id"] == target["document_id"]


def test_a_sheet_made_through_the_bridge_is_one_undoable_step(bridge_window):
    from core.history import AddEdgeCommand
    window, bridge = bridge_window()
    vp = window.viewport
    vp.history.execute(AddEdgeCommand(QVector3D(0, 0, 0), QVector3D(3, 0, 0)))
    edges = len(vp.scene.mesh.edges)
    sheets = len(vp.scene.compositions)
    target = _document(bridge)
    add = ("from core.composition import Composicion\n"
           "c = Composicion(name='A1')\n"
           "c.frames.append(c.default_frame())\n"
           "scene.compositions.append(c)\n")
    reply = _ask(bridge, "run_python", {"code": add}, target=target)
    assert reply["ok"] and reply["result"]["changed"] is True
    assert len(vp.scene.compositions) == sheets + 1
    assert _ask(bridge, "undo", target=target)["result"]["ok"]
    assert len(vp.scene.compositions) == sheets
    assert len(vp.scene.mesh.edges) == edges
    assert _ask(bridge, "redo", target=target)["result"]["ok"]
    assert vp.scene.compositions[-1].name == "A1"
    assert _ask(bridge, "undo", target=target)["result"]["ok"]
    reply = _ask(bridge, "run_python", {"code": add + "raise RuntimeError('boom')"},
                 target=target)
    assert reply["result"]["error"] and reply["result"]["changed"] is False
    assert len(vp.scene.compositions) == sheets
    assert len(vp.scene.mesh.edges) == edges


def test_http_request_body_cannot_execute_a_valid_targeted_operation(bridge_window):
    window, bridge = bridge_window()
    target = _document(bridge)
    edges = len(window.viewport.scene.mesh.edges)
    body = (json.dumps(_request("run_python", {"code": (
        "mesh.add_edge(QVector3D(0,0,0), QVector3D(7,0,0))")}, target=target)) + "\n").encode()
    request = (
        f"POST / HTTP/1.1\r\nHost: 127.0.0.1:{bridge.port}\r\n"
        "Origin: https://example.com\r\n"
        "Content-Type: text/plain;charset=UTF-8\r\n"
        f"Content-Length: {len(body)}\r\n\r\n").encode() + body
    thread, out = _begin_exchange(bridge.port, request)
    reply = json.loads(_finish_exchange(thread, out))
    assert not reply["ok"]
    assert len(window.viewport.scene.mesh.edges) == edges
    assert _ask(bridge, "run_python", {"code": "1 + 1"}, target=target)["ok"]
