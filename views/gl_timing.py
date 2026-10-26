# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Bounded, nonblocking GL_TIME_ELAPSED telemetry for one current GL context.

Qt's timer query begin/end use GL_TIME_ELAPSED. Results describe elapsed GPU
command-stream time, including starvation, not hardware utilisation. Only read
available results from earlier frames; never wait for an unfinished query.
"""
from time import perf_counter

from PySide6.QtOpenGL import QOpenGLTimerQuery


class GpuTimings:
    """Own query objects until the viewport's context is about to disappear."""

    def __init__(self, log, factory=QOpenGLTimerQuery, limit=128):
        self._log = log
        self._factory = factory
        self._limit = limit
        self._queries = []
        self._free = []
        self._pending = []
        self._active = None
        self._enabled = True
        self._frame = 0

    def frame(self, number):
        """Collect finished older samples without flushing or stalling GL."""
        # Recover a query left open by an interrupted paint before reuse.
        self.end()
        self._frame = number
        pending = []
        for query, frame, name, cpu_ms in self._pending:
            if not query.isResultAvailable():
                pending.append((query, frame, name, cpu_ms))
                continue
            gpu_ms = query.waitForResult() / 1_000_000
            self._log("gpu_pass", gpu_ms,
                      f"frame={frame} pass={name} gpu_ms={gpu_ms:.3f} "
                      f"cpu_ms={cpu_ms:.3f}", floor=0.0)
            self._free.append(query)
        self._pending = pending

    def begin(self, name):
        """Start a nonoverlapping pass; drop samples if the bounded pool fills."""
        self.end()
        if not self._enabled:
            return
        if self._free:
            query = self._free.pop()
        elif len(self._queries) < self._limit:
            query = self._factory()
            if not query.create():
                self._enabled = False
                self._log("gpu_unavailable", 0.0, "timer query creation failed", floor=0.0)
                return
            self._queries.append(query)
        else:
            self._log("gpu_dropped", 0.0, f"frame={self._frame} pass={name}", floor=0.0)
            return
        query.begin()
        self._active = (query, self._frame, name, perf_counter())

    def end(self):
        """End the active pass without retrieving its result."""
        if self._active is None:
            return
        query, frame, name, start = self._active
        query.end()
        self._pending.append((query, frame, name, (perf_counter() - start) * 1000))
        self._active = None

    def destroy(self):
        """Release all queries with their owning context current."""
        self.end()
        for query in self._queries:
            if isinstance(query, QOpenGLTimerQuery):
                # Delete the QObject while its context is current. Qt 6.11's
                # destroy() clears its context pointer, but its destructor
                # still dereferences that pointer when a context is current.
                import shiboken6
                shiboken6.delete(query)
            else:
                query.destroy()
        self._queries.clear()
        self._pending.clear()
        self._free.clear()
