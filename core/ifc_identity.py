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

    Derive it from the content, not the filename, so reopening or moving an
    unchanged old file gives the same identity. The next save writes it
    explicitly.
    """
    try:
        return uuid.UUID(str(value)).hex
    except (ValueError, AttributeError):
        return uuid.uuid5(uuid.NAMESPACE_URL, _legacy_key(path)).hex


#: Below this size a legacy document keeps the whole-file SHA-256 key of
#: 0.6.3 (roughly 1 ms per MB), so a file opened there and exported
#: without saving keeps its GlobalIds. Above it the hash is what costs.
_FULL_HASH_LIMIT = 64 * 1024 * 1024


def _legacy_key(path) -> str:
    """A content key for a document without a namespace.

    A large ZIP document is keyed by its central directory: every member's
    name, CRC-32 and sizes, plus the file size. That is read from the end
    of the file instead of hashing all of it, and a change to any member
    still changes the key. A plain-JSON document is read whole by the
    loader anyway, so it keeps the full SHA-256.
    """
    import os
    import zipfile
    with open(path, "rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        if size > _FULL_HASH_LIMIT and stream.read(4) == b"PK\x03\x04":
            stream.seek(0)
            try:
                with zipfile.ZipFile(stream) as archive:
                    members = [[i.filename, i.CRC, i.file_size,
                                i.compress_size, i.compress_type]
                               for i in archive.infolist()]
            except zipfile.BadZipFile:
                members = None
            if members is not None:
                key = json.dumps([size, members],
                                 ensure_ascii=True, separators=(",", ":"))
                digest = hashlib.sha256(key.encode("ascii")).hexdigest()
                return "ingetrazo:legacy-zip:" + digest
        stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return "ingetrazo:legacy:" + digest


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
