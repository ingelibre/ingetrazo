# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Seekable scratch storage for one large IGZ save, never a document cache."""
import json
import tempfile

_CHUNK = 1024 * 1024


class Fragment:
    """An immutable byte range; the owning save closes the scratch file."""

    def __init__(self, file, offset, size):
        self.file, self.offset, self.size = file, offset, size

    def chunks(self):
        offset, remaining = self.offset, self.size
        while remaining:
            self.file.seek(offset)
            data = self.file.read(min(_CHUNK, remaining))
            if not data:
                raise OSError("Truncated IGZ scratch data")
            yield data
            offset += len(data)
            remaining -= len(data)


class SaveStream:
    """Keep geometry blocks and completed mesh JSON on disk, one mesh at a time."""

    def __init__(self):
        self.file = tempfile.TemporaryFile()
        self.geometry = {}
        self.blobs = {}
        self.resolved = {}
        self.missing = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.file.close()

    def __len__(self):
        return len(self.geometry)

    def __iter__(self):
        return iter(self.geometry)

    def __getitem__(self, member):
        return self.geometry[member]

    def __setitem__(self, member, data):
        self.geometry[member] = self.store((data,))

    def store(self, chunks):
        # A document can read existing ranges of this SAME file while being
        # appended. Seek explicitly on both paths, and batch small JSON tokens.
        start = self.file.seek(0, 2)
        size = 0
        pending = bytearray()
        for chunk in chunks:
            pending.extend(chunk)
            if len(pending) >= _CHUNK:
                self.file.seek(0, 2)
                size += self.file.write(pending)
                pending.clear()
        if pending:
            self.file.seek(0, 2)
            size += self.file.write(pending)
        return Fragment(self.file, start, size)

    def json(self, value):
        return self.store(plain_json_chunks(value))

    def document(self, value):
        return self.store(json_chunks(value))


def plain_json_chunks(value):
    """Encode completed mesh records in bounded batches with the C encoder.

    The largest batch is 256 faces/attributes/edges, rather than a complete
    scene or mesh. This preserves stdlib float/escaping semantics without a
    Python generator call for every coordinate and attribute scalar.
    """
    if isinstance(value, dict):
        yield b"{"
        for i, (key, item) in enumerate(value.items()):
            if i:
                yield b","
            header = json.dumps({key: None}, separators=(",", ":"), allow_nan=False)
            yield header[1:-5].encode("utf-8")
            yield from plain_json_chunks(item)
        yield b"}"
    elif isinstance(value, (list, tuple)):
        yield b"["
        for start in range(0, len(value), 256):
            if start:
                yield b","
            batch = json.dumps(value[start:start + 256], separators=(",", ":"),
                               allow_nan=False)
            yield batch[1:-1].encode("utf-8")
        yield b"]"
    else:
        yield json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")


def json_chunks(value):
    """Compact stdlib JSON with already-encoded mesh ranges spliced verbatim.

    Scalar lists use the C encoder together (matrices, coordinates, colours).
    Dictionaries/lists of records stay incremental. No float formatting or
    escaping is reimplemented here; allow_nan=False retains the strict writer.
    """
    if isinstance(value, Fragment):
        yield from value.chunks()
    elif isinstance(value, dict):
        yield b"{"
        for i, (key, item) in enumerate(value.items()):
            if i:
                yield b","
            if isinstance(key, str):
                yield json.dumps(key).encode("utf-8")
                yield b":"
            else:
                # Let the stdlib convert supported non-string keys and reject
                # unsupported ones, exactly as for the complete document.
                header = json.dumps({key: None}, separators=(",", ":"), allow_nan=False)
                yield header[1:-5].encode("utf-8")
            yield from json_chunks(item)
        yield b"}"
    elif isinstance(value, (list, tuple)) and any(
            isinstance(v, (dict, list, tuple, Fragment)) for v in value):
        yield b"["
        for i, item in enumerate(value):
            if i:
                yield b","
            yield from json_chunks(item)
        yield b"]"
    else:
        yield json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
