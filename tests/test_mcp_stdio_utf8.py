# SPDX-License-Identifier: GPL-3.0-or-later
"""The MCP server reads and writes its stdio as UTF-8, whatever the
locale says. On Windows the pipes default to cp1252, and a «Küche» sent
by the client arrived as «KÃ¼che»."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ingetrazo_mcp.py"


def test_non_ascii_from_the_client_arrives_unchanged():
    # Force the Windows situation on every platform: a non-UTF-8 locale
    # encoding for the pipes.
    env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "Küche_Straße", "arguments": {}}}
    out = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=str(ROOT), env=env,
        input=(json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"),
        capture_output=True, timeout=60)
    reply = json.loads(out.stdout.decode("utf-8").splitlines()[0])
    # An unknown tool's error names it, so the name shows what arrived.
    text = reply["result"]["content"][0]["text"]
    assert text == "Unknown tool: Küche_Straße", text
