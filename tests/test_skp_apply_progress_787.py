# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Building a big .skp scene keeps the window alive (#787).

After the parse (on a worker thread), ``apply_payload`` built the whole
scene on the UI thread without ever calling the progress callback — on a
946 000-face file that ran for minutes and Windows marked the window "Not
Responding". It reports progress now, throttled, and only while every
group already in the scene is complete (the callback pumps events, so the
viewport may paint)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.scene import Scene  # noqa: E402
from formats import skp as skp_format  # noqa: E402


def _square(x):
    return [(x, 0.0, 0.0), (x + 1.0, 0.0, 0.0), (x + 1.0, 1.0, 0.0),
            (x, 1.0, 0.0)]


def _payload(n_groups=30, n_soft=20000):
    groups = []
    for i in range(n_groups):
        sq = _square(2.0 * i)
        soft = [(sq[0], sq[1])] * (n_soft if i == 0 else 1)
        groups.append({"name": f"g{i}", "faces": [(sq, [], {})],
                       "soft_edges": soft})
    proto = {"name": "p", "faces": [(_square(0.0), [], {})],
             "soft_edges": [], "instances": [
                 [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 5, 1]]}
    return {"groups": groups, "protos": [proto]}


def test_the_build_reports_progress(monkeypatch):
    import time
    clock = [0.0]

    def fake():                 # every reading a second later: no throttle
        clock[0] += 1.0
        return clock[0]
    monkeypatch.setattr(time, "monotonic", fake)
    scene = Scene()
    seen = []

    def progress(frac, text):
        # Whatever is already in the scene is whole: no empty group.
        assert all(g.mesh.faces or g.children for g in scene.groups)
        seen.append(frac)
    skp_format.apply_payload(scene, _payload(), progress=progress)
    assert len(scene.groups) == 31
    # Within the soft-edge loop too, not only between groups.
    assert len(seen) > 31
    assert all(0.75 <= f <= 0.96 for f in seen)
    assert seen == sorted(seen)


def test_the_reports_are_throttled():
    scene = Scene()
    seen = []
    skp_format.apply_payload(scene, _payload(),
                             progress=lambda f, t: seen.append(f))
    assert 1 <= len(seen) <= 3          # a fast build: barely a report
    assert len(scene.groups) == 31


def test_without_a_callback_nothing_changes():
    a, b = Scene(), Scene()
    skp_format.apply_payload(a, _payload(3, 2))
    skp_format.apply_payload(b, _payload(3, 2), progress=lambda f, t: None)
    assert len(a.groups) == len(b.groups) == 4
    assert ([len(g.mesh.faces) for g in a.groups]
            == [len(g.mesh.faces) for g in b.groups])
