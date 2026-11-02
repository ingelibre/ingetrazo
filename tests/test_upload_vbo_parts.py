# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""``Viewport._upload_vbo`` sends only what changed (#158, «sin lag»).

Putting an object down on the plant of #158 re-joined every buffer whole
(hundreds of MB) to send a tail. Now the head the GPU holds is not joined,
and parts of unchanged sizes are each written in place. Whatever it sends,
the buffer must read as the parts joined."""
from __future__ import annotations

import random
from types import SimpleNamespace

from views.viewport import Viewport


class FakeVBO:
    def __init__(self):
        self.data = bytearray()
        self.sent = 0

    def bind(self):
        pass

    def release(self):
        pass

    def allocate(self, n):
        self.data = bytearray(n)          # a realloc keeps nothing

    def write(self, off, raw, n):
        assert off + n <= len(self.data)
        self.data[off:off + n] = raw[:n]
        self.sent += n


def _up(vp, vbo, parts):
    total = Viewport._upload_vbo(vp, vbo, "edges", parts)
    assert total == sum(map(len, parts))
    assert bytes(vbo.data[:total]) == b"".join(parts)


def test_a_moved_part_alone_is_sent():
    vp = SimpleNamespace(_vbo_parts={})
    vbo = FakeVBO()
    parts = [bytes([i]) * (100 + i) for i in range(50)]
    _up(vp, vbo, parts)
    vbo.sent = 0
    parts = list(parts)
    parts[3] = bytes([200]) * len(parts[3])       # same size, new content
    _up(vp, vbo, parts)
    assert vbo.sent == len(parts[3])


def test_a_shorter_part_sends_from_it_on():
    vp = SimpleNamespace(_vbo_parts={})
    vbo = FakeVBO()
    parts = [bytes([i]) * 64 for i in range(20)]
    _up(vp, vbo, parts)
    vbo.sent = 0
    parts = parts[:5] + parts[6:]                  # one left out (a preview)
    _up(vp, vbo, parts)
    assert vbo.sent == 64 * 14


def test_random_sequences_always_read_as_the_parts():
    rng = random.Random(5)
    vp = SimpleNamespace(_vbo_parts={})
    vbo = FakeVBO()
    parts = [bytes([rng.randrange(256)]) * rng.randrange(1, 40)
             for _ in range(30)]
    for _ in range(200):
        op = rng.randrange(4)
        parts = list(parts)
        i = rng.randrange(len(parts))
        if op == 0:
            parts[i] = bytes([rng.randrange(256)]) * len(parts[i])
        elif op == 1:
            parts[i] = bytes([rng.randrange(256)]) * rng.randrange(1, 40)
        elif op == 2 and len(parts) > 1:
            del parts[i]
        else:
            parts.insert(i, bytes([rng.randrange(256)]) * rng.randrange(1, 90))
        _up(vp, vbo, parts)
