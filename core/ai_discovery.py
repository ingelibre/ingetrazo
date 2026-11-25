# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Stdlib-only discovery shared by application windows and the MCP process.

Records identify endpoints, not documents: document metadata and identities
are always obtained from the live window before routing a request.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

PROTOCOL = 2


def registry_directory() -> Path:
    """A private per-user directory, overridable for sandboxes and tunnels."""
    override = os.environ.get("INGETRAZO_AI_REGISTRY")
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return base / "IngeTrazo" / "ai-bridges"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "IngeTrazo" / "ai-bridges"
    # Flatpak rewrites XDG_STATE_HOME per app. Discovery must instead be
    # shared with native windows and a host-side MCP process (home is
    # exposed by our Flatpak manifest). Use the explicit registry override
    # when a container needs a different shared mount.
    return Path.home() / ".local" / "state" / "ingetrazo" / "ai-bridges"


def register(instance_id: str, port: int) -> Path:
    """Publish one complete endpoint atomically; never replace another window."""
    directory = registry_directory().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    record = {"protocol": PROTOCOL, "instance_id": instance_id,
              "pid": os.getpid(), "host": "127.0.0.1", "port": port}
    path = directory / f"{instance_id}.json"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=directory, prefix=".", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def read_endpoints() -> list[dict]:
    """Ignore incomplete/foreign records; liveness is checked by the client."""
    records = []
    for path in sorted(registry_directory().glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(record, dict) or record.get("protocol") != PROTOCOL
                    or not isinstance(record.get("instance_id"), str)
                    or path.name != record["instance_id"] + ".json"
                    or record.get("host") != "127.0.0.1"
                    or type(record.get("port")) is not int
                    or not 0 < record["port"] < 65536):
                continue
        except (OSError, ValueError):
            continue
        records.append(record)
    return records
