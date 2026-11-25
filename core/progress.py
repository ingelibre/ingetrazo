# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""How far a long piece of work has come, for whoever wants to show it.

A big model's export works for minutes in the window's own thread: the
hidden lines, the visible faces. Within :func:`reporting`, the loops of
that work call :func:`tick` and the listener hears, every tenth of a
second or so, how far it has come — a bar can show it, let the window
paint and let the person give up. Outside it, :func:`tick` costs a
lookup."""
from __future__ import annotations

import time
from contextlib import contextmanager

#: Seconds between two reports.
REPORT_EVERY = 0.1

#: The listener of the work going on now (see :func:`reporting`).
_report = None


class _Reporter:
    """Hands ``progress`` how far the work has come, every
    :data:`REPORT_EVERY` seconds at most."""

    def __init__(self, progress) -> None:
        self.progress = progress
        self.done = 0.0
        self.told = time.monotonic()

    def __call__(self, done=None) -> None:
        if done is not None:
            self.done = done
        now = time.monotonic()
        if now - self.told >= REPORT_EVERY:
            self.progress(self.done)
            self.told = time.monotonic()


def tick(done=None) -> None:
    """Tell whoever is listening how far the work has come, from 0 to 1 —
    ``None``: as far as last said, the work only still going."""
    r = _report
    if r is not None:
        r(done)


@contextmanager
def reporting(progress):
    """Within it, the long work calls ``progress(done)`` — ``done`` from 0
    to 1 — every tenth of a second or so. ``progress`` may raise to stop
    the work there: the exception leaves the work as any other does."""
    global _report
    was, _report = _report, _Reporter(progress)
    try:
        yield
    finally:
        _report = was
