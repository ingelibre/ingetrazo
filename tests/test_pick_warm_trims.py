"""The pick index's warm-up hands the heap it freed back to the system, once,
when its last thread is done (#1092)."""
from __future__ import annotations

import numpy as np

from core import malloc_arenas
from views.viewport import _PickWarm


class _Mod:
    """An engine whose prototypes record the calls and may fail."""


def _base(n=8):
    v = np.zeros((n, 3), dtype="f4")
    return {"v0": v, "e1": v, "e2": v, "edges": np.zeros((0, 6), dtype="f4"),
            "tri_ent": np.arange(n), "rev": 1}


def test_the_last_thread_trims_once(monkeypatch):
    calls = []
    monkeypatch.setattr(malloc_arenas, "trim", lambda: calls.append(1))
    bases = [_base() for _ in range(40)]
    warm = _PickWarm(_Mod(), [], [], bases)
    warm.join()
    assert len(warm.bounds) == 40
    assert calls == [1]


def test_a_job_that_fails_does_not_lose_the_trim(monkeypatch):
    calls = []
    monkeypatch.setattr(malloc_arenas, "trim", lambda: calls.append(1))
    warm = _PickWarm(_Mod(), [("k", {})], [], [])   # no such arrays: raises
    warm.join()
    assert warm.protos == {}
    assert calls == [1]
