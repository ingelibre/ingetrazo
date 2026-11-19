# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Persistent IFC identity, independent of STEP numbers and display names.

The document namespace travels in .igz. Elements use the group's durable
uid, or a face tag's uid scoped to its owning placement. UUID5 derives the
spatial skeleton, quantities and relationships without mutating on export.
"""
from __future__ import annotations

import hashlib
import json
import uuid

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


def new_identity() -> str:
    return uuid.uuid4().hex


def compressed_guid(value: uuid.UUID) -> str:
    n = value.int
    return "".join(_CHARS[(n >> (6 * i)) & 63] for i in range(21, -1, -1))


def stable_guid(namespace: str, *parts) -> str:
    # JSON prevents ambiguous concatenation ("a/b", "c" vs "a", "b/c").
    key = json.dumps(parts, ensure_ascii=True, separators=(",", ":"))
    return compressed_guid(uuid.uuid5(uuid.UUID(namespace), key))


def document_identity(value, path) -> str:
    """Read a valid namespace; migrate legacy documents deterministically.

    Hash bytes, not the filename, so reopening or moving an unchanged old
    file gives the same identity. The next save writes it explicitly.
    """
    try:
        return uuid.UUID(str(value)).hex
    except (ValueError, AttributeError):
        with open(path, "rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return uuid.uuid5(uuid.NAMESPACE_URL, "ingetrazo:legacy:" + digest).hex


def object_identity(obj) -> tuple:
    group = obj.get("group")
    if group is not None:
        return ("group", group.uid)
    tag = obj["faces"][0].attrs["ifc"]
    # The integer id is still the modeller's grouping key. New tags have a
    # UUID too, so deleting the last object and reusing its id is safe.
    token = tag.get("uid") or ("legacy", tag.get("id"))
    owner = obj.get("owner")
    return ("faces", owner.uid if owner is not None else None, token)
