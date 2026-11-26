# SPDX-License-Identifier: GPL-3.0-or-later
"""``ingetrazo --headless``: no window, the document opened, the AI bridge
listening — and an exit code that says how it ended."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "capas-prueba.igz"


def test_the_flags_pick_the_mode():
    from main import _wants_cli, _wants_headless
    assert _wants_headless(["--headless", "--ai-bridge"])
    assert _wants_headless(["--headless", "--help"])
    # The PDF export is window-less already: it keeps its own line.
    assert not _wants_headless(["--headless", "-i", "a.igz", "-p"])
    assert _wants_cli(["--headless", "-i", "a.igz", "-p"])
    assert not _wants_headless(["Casa.igz"])


def test_the_command_line():
    from main import _parse_headless
    a = _parse_headless(["--headless", "--ai-bridge", "--open", "C.igz",
                         "--port", "0", "--allow-save", "--save-format",
                         "json", "--allow-shutdown"])
    assert a.open_file == Path("C.igz") and a.port == 0
    assert a.allow_save and a.allow_shutdown and a.save_format == "json"
    assert not a.no_mcp_python
    b = _parse_headless(["--headless", "--ai-bridge"])
    assert not b.allow_save and not b.allow_shutdown
    for flag in ("--no_mcp_python", "--no-mcp-python"):
        assert _parse_headless(["--headless", "--ai-bridge",
                                flag]).no_mcp_python
    assert b.save_format is None and b.port is None
    with pytest.raises(SystemExit):
        _parse_headless(["--headless"])                 # nothing to do
    with pytest.raises(SystemExit):
        _parse_headless(["--headless", "--ai-bridge", "--save-format",
                         "xml"])


# ---- The real thing, in a process of its own ---------------------------------

def _has_display() -> bool:
    """Whether the native Qt platform can run here (it has OpenGL; the
    offscreen one the suite uses has none, so nothing renders there)."""
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _start(tmp_path, *extra, stdin=subprocess.DEVNULL, native=False):
    ready = tmp_path / "ready.txt"
    cmd = [sys.executable, str(ROOT / "main.py"), "--headless",
           "--ai-bridge", "--port", "0", "--ready-file", str(ready), *extra]
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    if native:
        env.pop("QT_QPA_PLATFORM")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdin=stdin,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc, ready


def _wait_ready(proc, ready, timeout=90.0) -> int | None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if ready.is_file():
            return int(ready.read_text())
        if proc.poll() is not None:
            return None
        time.sleep(0.1)
    proc.kill()
    raise AssertionError("the headless IngeTrazo never got ready")


class _Client:
    def __init__(self, port: int) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=120)
        self.n = 0
        self.buf = b""
        self.ids: dict | None = None

    def call(self, tool: str, **args) -> dict:
        # #892: every request but list_documents names its window and
        # document; the window-less IngeTrazo has exactly one.
        if tool != "list_documents" and self.ids is None:
            doc = self.call("list_documents")["result"]["documents"][0]
            self.ids = {"instance_id": doc["instance_id"],
                        "document_id": doc["document_id"]}
        self.n += 1
        self.sock.sendall((json.dumps(
            {"id": self.n, "tool": tool, "args": args,
             **(self.ids if tool != "list_documents" else {})})
            + "\n").encode())
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line)

    def close(self) -> None:
        self.sock.close()


def _finish(proc, timeout=60.0) -> tuple[int, str]:
    if proc.stdin is not None and proc.stdin.closed:
        # Closed by the test itself: communicate() would flush it first,
        # and on POSIX that raises on a closed file (Windows skips it).
        proc.stdin = None
    try:
        _out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        _out, err = proc.communicate()
        raise AssertionError("the headless IngeTrazo did not end")
    return proc.returncode, err.decode("utf-8", "replace")


def test_a_missing_document_ends_it_at_once(tmp_path):
    proc, ready = _start(tmp_path, "--open", str(tmp_path / "nope.igz"))
    code, err = _finish(proc)
    assert code == 3
    assert "no such file" in err
    assert not ready.exists()


def test_a_broken_document_ends_it_before_the_bridge(tmp_path):
    bad = tmp_path / "bad.igz"
    bad.write_text("{ this is not json")
    proc, ready = _start(tmp_path, "--open", str(bad))
    code, err = _finish(proc, timeout=120)
    assert code == 3, err
    assert "could not open" in err
    assert not ready.exists()


def test_a_taken_port_is_its_own_code(tmp_path):
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    try:
        port = busy.getsockname()[1]
        cmd = [sys.executable, str(ROOT / "main.py"), "--headless",
               "--ai-bridge", "--port", str(port)]
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        done = subprocess.run(cmd, cwd=str(ROOT), env=env, timeout=120,
                              stdin=subprocess.DEVNULL, capture_output=True)
    finally:
        busy.close()
    assert done.returncode == 4, done.stderr


def test_open_work_save_as_json_and_shut_down(tmp_path):
    doc = tmp_path / "Casa.igz"
    shutil.copy(EXAMPLE, doc)
    proc, ready = _start(tmp_path, "--open", str(doc), "--allow-save",
                         "--save-format", "json", "--allow-shutdown")
    port = _wait_ready(proc, ready)
    assert port, _finish(proc)
    c = _Client(port)
    try:
        info = c.call("document_info")["result"]
        assert Path(info["path"]) == doc
        assert info["saving_allowed"] and info["shutdown_allowed"]
        assert info["save_format"] == "json"
        before = c.call("query_model")["result"]["edges"]
        r = c.call("run_python", code=(
            "mesh.add_edge(QVector3D(50, 50, 0), QVector3D(51, 50, 0))"))
        assert r["ok"] and not r["result"].get("error"), r
        # Unsaved: no shutdown without saying so.
        r = c.call("shutdown")
        assert not r["ok"] and "unsaved" in r["error"]
        r = c.call("save_document")
        assert r["ok"], r
        assert r["result"]["format"] == "json"
        r = c.call("shutdown")
        assert r["ok"] and r["result"]["shutting_down"]
    finally:
        c.close()
    code, err = _finish(proc)
    assert code == 0, err
    raw = doc.read_bytes()
    assert raw.startswith(b"{\n")                    # plain JSON
    assert not (tmp_path / "Casa.igz.bak").exists()  # no backup litter
    data = json.loads(raw)
    assert len(data["scene"]["edges"]) == before + 1


@pytest.mark.skipif(not _has_display(),
                    reason="no display: nothing renders without OpenGL")
def test_views_and_sheets_come_out_as_files(tmp_path):
    """The automatic extraction of views: a scene to a PNG, the sheets to
    a PDF — rendered for real (the hidden window has its GL context on the
    native platform; nothing reaches the screen)."""
    from PySide6.QtGui import QImage
    doc = tmp_path / "Casa.igz"
    shutil.copy(ROOT / "examples" / "arco-yanque.igz", doc)
    proc, ready = _start(tmp_path, "--open", str(doc), "--allow-shutdown",
                         native=True)
    port = _wait_ready(proc, ready)
    assert port, _finish(proc)
    c = _Client(port)
    try:
        r = c.call("run_python", code=(
            "from core.saved_views import SavedView\n"
            "scene.saved_views.append(SavedView.capture("
            "'Vista', scene, viewport.camera))"))
        assert r["ok"] and not r["result"].get("error"), r
        png = tmp_path / "out" / "vista.png"
        r = c.call("export_view", view="Vista", path=str(png), width=400,
                   height=300)
        assert r["ok"], r
        img = QImage(str(png))
        assert (img.width(), img.height()) == (400, 300)
        assert len({img.pixel(x, y) for x in range(0, 400, 20)
                    for y in range(0, 300, 20)}) > 1     # not a blank
        if c.call("document_info")["result"]["sheets"]:
            pdf = tmp_path / "out" / "laminas.pdf"
            r = c.call("export_pdf", path=str(pdf))
            assert r["ok"], r
            assert pdf.read_bytes().startswith(b"%PDF")
        r = c.call("shutdown", discard_changes=True)
        assert r["ok"], r
    finally:
        c.close()
    code, err = _finish(proc)
    assert code == 0, err


def test_the_gates_stay_shut_without_their_flags(tmp_path):
    doc = tmp_path / "Casa.igz"
    shutil.copy(EXAMPLE, doc)
    original = doc.read_bytes()
    proc, ready = _start(tmp_path, "--open", str(doc), stdin=subprocess.PIPE)
    port = _wait_ready(proc, ready)
    assert port, _finish(proc)
    c = _Client(port)
    try:
        r = c.call("save_document")
        assert not r["ok"] and "--allow-save" in r["error"]
        r = c.call("shutdown", discard_changes=True)
        assert not r["ok"] and "--allow-shutdown" in r["error"]
    finally:
        c.close()
    assert doc.read_bytes() == original
    proc.terminate()
    code, _err = _finish(proc)
    # Ended from outside: never 0. (Windows' TerminateProcess makes it 1;
    # a POSIX SIGTERM goes through the handler: 5.)
    assert code != 0
    if sys.platform != "win32":
        assert code == 5


def test_stdin_closing_ends_it_with_5(tmp_path):
    proc, ready = _start(tmp_path, "--exit-on-stdin-eof",
                         stdin=subprocess.PIPE)
    assert _wait_ready(proc, ready), _finish(proc)
    proc.stdin.close()
    code, _err = _finish(proc)
    assert code == 5
