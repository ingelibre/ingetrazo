# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Consumer-visible discovery, routing and transport behavior over real TCP."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import io
import json
from pathlib import Path
import socket
import socketserver
import threading

import pytest

from core.ai_discovery import register

ROOT = Path(__file__).resolve().parents[1]


def _client(monkeypatch, **env):
    for key in ("INGETRAZO_AI_HOST", "INGETRAZO_AI_PORT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    spec = importlib.util.spec_from_file_location(
        "_mcp_client_under_test", ROOT / "scripts" / "ingetrazo_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch, tmp_path):
    monkeypatch.setenv("INGETRAZO_AI_REGISTRY", str(tmp_path / "registry"))


class Endpoint:
    """Controlled bridge peer; each handler consumes exactly one request."""

    def __init__(self, instance_id):
        self.instance_id = instance_id
        self.document = {
            "document_id": instance_id + ":original",
            "instance_id": instance_id,
            "pid": 123,
            "name": "same.igz",
            "path": f"/{instance_id}/same.igz",
            "title": "same.igz — IngeTrazo",
            "dirty": False,
            "revision": 0,
        }
        self.requests = []
        self.operation_result = {"changed": True, "stdout": "edited\n"}
        self.drop_operation = False
        self.bad_reply_id = False
        self.ignore_instance = False

    def reply(self, request):
        self.requests.append(request)
        response = {"id": request["id"], "ok": True}
        if self.bad_reply_id:
            response["id"] += 1
        instance_id = request.get("instance_id")
        if (not self.ignore_instance and instance_id is not None
                and instance_id != self.instance_id):
            return dict(response, ok=False, error="Wrong instance; list_documents again")
        if request["tool"] == "list_documents":
            return dict(response, result={"documents": [dict(self.document)]})
        if (instance_id != self.instance_id
                or request.get("document_id") != self.document["document_id"]):
            return dict(response, ok=False, error="Stale document; list_documents again")
        if self.drop_operation:
            self.document["revision"] += 1
            return None
        if request["tool"] == "query_model":
            result = {"name": self.instance_id, "revision": self.document["revision"]}
        else:
            result = self.operation_result
        return dict(response, result=result)

    @property
    def operations(self):
        return [request for request in self.requests
                if request["tool"] != "list_documents"]


@contextmanager
def _endpoint(instance_id, *, publish=True):
    endpoint = Endpoint(instance_id)

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            request = json.loads(self.rfile.readline())
            reply = endpoint.reply(request)
            if reply is not None:
                self.wfile.write((json.dumps(reply) + "\n").encode())

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    endpoint.port = server.server_address[1]
    record = register(instance_id, endpoint.port) if publish else None
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield endpoint
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        if record is not None:
            record.unlink(missing_ok=True)


def _call(module, name, arguments=None, request_id=1):
    response = module.handle({
        "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    })
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == request_id
    assert "error" not in response
    return response["result"]


def _text(result):
    return result["content"][0]["text"]


def _documents(module):
    result = _call(module, "list_documents")
    assert not result["isError"]
    return json.loads(_text(result))["documents"]


@pytest.mark.parametrize("tool", ["run_python", "query_model", "screenshot", "undo", "redo"])
@pytest.mark.parametrize("document_id", [None, "", " ", 12])
def test_missing_document_ids_fail_without_contacting_any_window(monkeypatch, tool, document_id):
    module = _client(monkeypatch)
    with _endpoint("first") as endpoint:
        arguments = {"code": "print('must not run')"}
        if document_id is not None:
            arguments["document_id"] = document_id
        result = _call(module, tool, arguments)
        assert result["isError"]
        assert "document_id" in _text(result)
        assert "list_documents" in _text(result)
        assert endpoint.requests == []


def test_stale_document_never_falls_back_to_another_window(monkeypatch):
    module = _client(monkeypatch)
    with _endpoint("first") as first, _endpoint("second") as second:
        old_id = first.document["document_id"]
        assert len(_documents(module)) == 2
        first.document["document_id"] = "first:replacement"
        result = _call(module, "run_python", {"document_id": old_id, "code": "mutate()"})
        assert result["isError"]
        assert "list_documents" in _text(result)
        assert first.operations == second.operations == []
        assert {document["document_id"] for document in _documents(module)} == {
            "first:replacement", second.document["document_id"]}


def test_discovery_omits_stopped_endpoints_and_operations_fail_closed(monkeypatch):
    module = _client(monkeypatch)
    with _endpoint("stopped") as endpoint:
        old_id = _documents(module)[0]["document_id"]
        port = endpoint.port
    # A crash can leave a registry record even after its listening socket closes.
    register("stopped", port)
    assert _documents(module) == []
    result = _call(module, "undo", {"document_id": old_id})
    assert result["isError"]
    assert "list_documents" in _text(result)
    assert "bridge" in _text(result)


def test_registry_is_read_live_for_later_enabled_windows(monkeypatch):
    module = _client(monkeypatch)
    assert _documents(module) == []
    with _endpoint("later") as endpoint:
        assert _documents(module) == [endpoint.document]
    assert _documents(module) == []


def test_zero_port_discovers_automatically_assigned_endpoints(monkeypatch):
    module = _client(monkeypatch, INGETRAZO_AI_PORT=0)
    with _endpoint("automatic") as endpoint:
        assert _documents(module) == [endpoint.document]
        result = _call(module, "query_model", {
            "document_id": endpoint.document["document_id"]})
        assert not result["isError"]
        assert len(endpoint.operations) == 1


def test_reused_port_cannot_turn_stale_registry_identity_into_target(monkeypatch):
    module = _client(monkeypatch)
    with _endpoint("replacement", publish=False) as endpoint:
        register("previous", endpoint.port)
        # Even a peer ignoring the requested instance cannot impersonate the record.
        endpoint.ignore_instance = True
        assert _documents(module) == []
        result = _call(module, "run_python", {
            "document_id": "previous:original", "code": "mutate()"})
        assert result["isError"]
        assert endpoint.operations == []
        assert all(request["instance_id"] == "previous" for request in endpoint.requests)


def test_explicit_tunnel_discovers_identity_and_excludes_local_registry(monkeypatch):
    with _endpoint("local"), _endpoint("tunnel", publish=False) as tunnel:
        module = _client(monkeypatch, INGETRAZO_AI_HOST="localhost",
                         INGETRAZO_AI_PORT=tunnel.port)
        assert _documents(module) == [tunnel.document]
        result = _call(module, "query_model", {
            "document_id": tunnel.document["document_id"]})
        assert not result["isError"]
        assert "instance_id" not in tunnel.requests[0]
        assert tunnel.operations[0]["instance_id"] == "tunnel"
        assert tunnel.operations[0]["document_id"] == "tunnel:original"
        rejected = _call(module, "query_model", {"document_id": "local:original"})
        assert rejected["isError"]
        assert len(tunnel.operations) == 1


def test_unreachable_tunnel_names_address_and_recovery_action(monkeypatch):
    # Reserve a port without listening, ensuring connection refusal without an external host.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        module = _client(monkeypatch, INGETRAZO_AI_HOST="127.0.0.1",
                         INGETRAZO_AI_PORT=port)
        assert _documents(module) == []
        result = _call(module, "query_model", {"document_id": "gone:document"})
    assert result["isError"]
    assert f"127.0.0.1:{port}" in _text(result)
    assert "list_documents" in _text(result)
    assert "Start bridge" in _text(result)


def test_mutation_is_sent_once_even_when_reply_is_lost(monkeypatch):
    module = _client(monkeypatch)
    with _endpoint("first") as endpoint:
        endpoint.drop_operation = True
        result = _call(module, "run_python", {
            "document_id": endpoint.document["document_id"], "code": "mutate()"})
        assert result["isError"]
        assert "not retried" in _text(result)
        assert endpoint.document["revision"] == 1
        assert len(endpoint.operations) == 1
        # The next deliberate call uses a new connection, not a broken global socket.
        endpoint.drop_operation = False
        query = _call(module, "query_model", {
            "document_id": endpoint.document["document_id"]})
        assert json.loads(_text(query))["revision"] == 1
        assert len(endpoint.operations) == 2


def test_mismatched_discovery_reply_id_is_not_trusted(monkeypatch):
    module = _client(monkeypatch)
    with _endpoint("first") as endpoint:
        endpoint.bad_reply_id = True
        assert _documents(module) == []
        result = _call(module, "redo", {"document_id": "first:original"})
        assert result["isError"]
        assert endpoint.operations == []


def test_mismatched_operation_reply_id_is_error_without_replay(monkeypatch):
    module = _client(monkeypatch)
    with _endpoint("first") as endpoint:
        # Change the reply ID only for the targeted operation, after successful discovery.
        original_reply = endpoint.reply

        def reply(request):
            response = original_reply(request)
            if request["tool"] != "list_documents":
                response["id"] += 1
            return response

        endpoint.reply = reply
        result = _call(module, "undo", {"document_id": endpoint.document["document_id"]})
        assert result["isError"]
        assert "request ID" in _text(result)
        assert len(endpoint.operations) == 1


def test_transaction_failure_remains_structured_tool_error(monkeypatch):
    module = _client(monkeypatch)
    with _endpoint("first") as endpoint:
        endpoint.operation_result = {
            "stdout": "before failure\n", "stderr": "details\n",
            "changed": False, "error": "invalid recipe",
        }
        result = _call(module, "run_python", {
            "document_id": endpoint.document["document_id"], "code": "invalid()"})
        assert result["isError"]
        assert "before failure" in _text(result)
        assert "stderr:\ndetails" in _text(result)
        assert "ROLLED BACK" in _text(result)
        assert "invalid recipe" in _text(result)
        assert "changed: False" in _text(result)


def test_stdio_preserves_initialize_notifications_and_json_rpc(monkeypatch):
    module = _client(monkeypatch)
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "list_documents", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "not_a_tool"}},
        {"jsonrpc": "2.0", "id": 5, "method": "not_a_method"},
    ]
    stdin = io.StringIO("\n".join(json.dumps(message) for message in messages) + "\n")
    stdout = io.StringIO()
    monkeypatch.setattr(module.sys, "stdin", stdin)
    monkeypatch.setattr(module.sys, "stdout", stdout)
    module.main()
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [response["id"] for response in responses] == [1, 2, 3, 4, 5]
    assert all(response["jsonrpc"] == "2.0" for response in responses)
    initialize = responses[0]["result"]
    assert initialize["protocolVersion"] == "2024-11-05"
    assert initialize["capabilities"] == {"tools": {}}
    assert initialize["serverInfo"]["name"] == "ingetrazo"
    assert "list_documents" in initialize["instructions"]
    assert responses[1]["result"] == {}
    assert json.loads(_text(responses[2]["result"])) == {"documents": []}
    assert responses[3]["result"]["isError"]
    assert responses[4]["error"]["code"] == -32601
