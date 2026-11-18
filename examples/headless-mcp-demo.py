# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A window-less IngeTrazo driven over MCP, end to end — what an agent in a
CI runner does, played by a small script.

    python examples/headless-mcp-demo.py [OUTPUT_FOLDER]

(from the IngeTrazo folder; the output defaults to ``headless-demo/``). It
starts the MCP server in its one-command form

    scripts/ingetrazo_mcp.py --headless --allow-save --save-format json
                             --allow-shutdown

which starts an IngeTrazo of its own with no window, and then speaks MCP
JSON-RPC to it exactly as Claude would:

    initialize → tools/list → run_python (build a small house) →
    screenshot (a PNG over MCP) → export_view (two scenes) →
    save_document (plain JSON + Casita.assets/) → shutdown → exit code 0

It needs a display (the views are OpenGL renders, in a window that never
reaches the screen). See docs/ai-bridge.md ▸ «Sin ventana».
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class McpClient:
    """Just enough of an MCP client: one JSON-RPC line out, one back."""

    def __init__(self, *server_args: str) -> None:
        env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "ingetrazo_mcp.py"),
             *server_args],
            cwd=str(ROOT), env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.n = 0

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        msg = {"jsonrpc": "2.0", "id": self.n, "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read().decode("utf-8", "replace")
            raise SystemExit(f"the MCP server ended "
                             f"(code {self.proc.wait()}):\n{err}")
        return json.loads(line)

    def call(self, name: str, **args) -> dict:
        """A tool call; the result (``content``, ``isError``)."""
        return self.rpc("tools/call", {"name": name,
                                       "arguments": args})["result"]

    def tool(self, name: str, **args) -> tuple[list[str], list[dict]]:
        """A tool call that must work: its texts and images."""
        t0 = time.monotonic()
        res = self.call(name, **args)
        texts = [c["text"] for c in res["content"] if c["type"] == "text"]
        images = [c for c in res["content"] if c["type"] == "image"]
        took = time.monotonic() - t0
        if res.get("isError"):
            raise SystemExit(f"{name} failed: {' '.join(texts)}")
        first = texts[0].splitlines()[0] if texts else ""
        print(f"  {name:<14} {took:4.1f} s  {first[:70]}"
              + (f"  [{len(images)} image]" if images else ""))
        return texts, images

    def end(self) -> int:
        self.proc.stdin.close()
        return self.proc.wait(timeout=60)


# One run_python call: one undo step, rolled back whole if it fails.
BUILD = """
house(width=6, depth=4, wall_height=2.8, thickness=0.2, roof="gable",
      overhang=0.4, doors=[("S", 2.5, 0.9, 2.1)],
      windows=[("S", 0.8, 1.0, 1.2, 1.0), ("S", 4.2, 1.0, 1.2, 1.0),
               ("E", 1.4, 1.0, 1.2, 1.0)], name="Casita")
box((-0.5, -3.5, 0), (7, 3.3, 0.15), name="Terrace",
    color=(0.72, 0.68, 0.6, 1.0))
box((1.0, -2.6, 0.15), (1.6, 0.9, 0.75), name="Table",
    color=(0.55, 0.36, 0.2, 1.0))
trunk = revolve([(0.15, 0), (0.12, 1.6)], name="Trunk",
                color=(0.4, 0.26, 0.13, 1.0), segments=16)
crown = revolve([(0.0, 1.4), (1.1, 1.9), (1.2, 2.6), (0.8, 3.3), (0.0, 3.6)],
                name="Crown", color=(0.25, 0.55, 0.25, 1.0), segments=24)
for g in (trunk, crown):
    for v in list(g.mesh.vertices):
        g.mesh.move_vertex(v, QVector3D(9.0, -1.0, 0))
extrude([(2.5, -6), (3.6, -6), (3.6, -3.5), (2.5, -3.5)], 0, 0.05,
        name="Path", color=(0.6, 0.6, 0.62, 1.0))
print(len(groups), "groups")
"""

# Where to look from, and three scenes (saved views) to export by name.
CAMERA_AND_SCENES = """
from core.saved_views import SavedView
cam = viewport.camera
def look(x, y, z, distance, yaw, pitch):
    cam.target = QVector3D(x, y, z)
    cam.distance, cam.yaw, cam.pitch = distance, yaw, pitch
look(4.0, -0.5, 1.4, 20.0, -1.05, 0.42)
scene.saved_views.append(SavedView.capture("Perspective", scene, cam))
look(3.0, 2.0, 1.2, 18.0, -1.5708, 0.05)
scene.saved_views.append(SavedView.capture("Front", scene, cam))
look(4.0, 0.0, 0.0, 24.0, -1.5708, 1.55)
scene.saved_views.append(SavedView.capture("Plan", scene, cam))
look(4.0, -0.5, 1.4, 20.0, -1.05, 0.42)
viewport.update()
print([v.name for v in scene.saved_views])
"""


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "headless-demo").resolve()
    out.mkdir(parents=True, exist_ok=True)
    doc = out / "Casita.igz"

    t0 = time.monotonic()
    mcp = McpClient("--headless", "--allow-save", "--save-format", "json",
                    "--allow-shutdown")
    info = mcp.rpc("initialize", {})["result"]["serverInfo"]
    print(f"MCP server {info['name']} {info['version']} with a headless "
          f"IngeTrazo, ready in {time.monotonic() - t0:.1f} s")
    tools = [t["name"] for t in mcp.rpc("tools/list")["result"]["tools"]]
    print("tools:", ", ".join(tools))

    mcp.tool("run_python", code=BUILD)
    mcp.tool("run_python", code=CAMERA_AND_SCENES)
    _texts, images = mcp.tool("screenshot", width=1280, height=800)
    (out / "screenshot.png").write_bytes(base64.b64decode(images[0]["data"]))
    for view in ("Front", "Plan"):
        mcp.tool("export_view", view=view, width=1280, height=800,
                 path=str(out / f"scene-{view.lower()}.png"))

    # Unsaved work is never lost by accident: shutdown says so.
    refused = mcp.call("shutdown")
    assert refused["isError"], refused
    print("  shutdown       refused while unsaved, as it should be")

    mcp.tool("save_document", path=str(doc))
    mcp.tool("shutdown")
    code = mcp.end()
    print(f"exit code {code} (0: ended by the agent's shutdown)")
    print(f"{doc}: {doc.stat().st_size:,} bytes of plain JSON, images in "
          f"{doc.with_suffix('.assets').name}/")
    print("pictures:", ", ".join(sorted(p.name for p in out.glob("*.png"))))
    return code


if __name__ == "__main__":
    sys.exit(main())
