# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""An import statement costs over a microsecond under PySide's hook; these
run per placement, several times a frame pass: 1.4 M of them to open the
plant of #158, ~2 s of it."""
import builtins
from types import SimpleNamespace

import pytest

from core.group import Group, new_uid
from core.mesh import Mesh
from core.scene import Scene
from views import array_bake  # noqa: F401 — the real one is imported by now
from views.viewport import _array_bake, _paint_of, _proto_wrapper


@pytest.fixture
def imports(monkeypatch):
    seen = []
    real = builtins.__import__

    def spy(name, *a, **k):
        seen.append(name)
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", spy)
    return seen


def test_paint_of_imports_nothing(imports):
    vp = SimpleNamespace(scene=Scene())
    g = Group(Mesh(), name="g")
    imports.clear()
    assert _paint_of(vp, g) is None
    assert imports == []


def test_paint_of_with_layer_colours_imports_nothing(imports):
    vp = SimpleNamespace(scene=Scene())
    vp.scene.display_style.color_by_layer = True
    g = Group(Mesh(), name="g")
    _paint_of(vp, g)
    imports.clear()
    _paint_of(vp, g)
    assert imports == []


def test_a_prototype_stand_in_imports_nothing(imports):
    vp = SimpleNamespace()
    m = Mesh()
    a = _proto_wrapper(vp, m)
    imports.clear()
    assert _proto_wrapper(vp, m) is a
    assert imports == []


def test_a_layer_state_imports_nothing(imports):
    s = Scene()
    g = Group(Mesh(), name="g")
    imports.clear()
    assert s._layer_state(g) == (True, False)
    assert imports == []


def test_a_new_uid_imports_nothing(imports):
    imports.clear()
    assert len(new_uid()) == 16
    assert imports == []


def test_the_bake_module_is_the_module():
    assert _array_bake() is array_bake
