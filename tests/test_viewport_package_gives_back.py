# SPDX-License-Identifier: GPL-3.0-or-later
"""A module a test fakes on views.viewport and gives back reaches every part
again: a faked ``sys`` left in one part made later tests crash."""
import sys
from types import SimpleNamespace

import pytest

from views import viewport as viewport_module


def _parts_holding_sys():
    return [m for n, m in sorted(sys.modules.items())
            if (n == "views.viewport" or n.startswith("views.viewport."))
            and "sys" in vars(m)]


def test_a_faked_sys_given_back_is_the_real_one_in_every_part():
    assert _parts_holding_sys()
    mp = pytest.MonkeyPatch()
    mp.setattr(viewport_module, "sys", SimpleNamespace(platform="darwin"))
    assert all(vars(m)["sys"].platform == "darwin" for m in _parts_holding_sys())
    mp.undo()
    assert all(vars(m)["sys"] is sys for m in _parts_holding_sys())


def test_importing_a_part_does_not_spread_it_over_the_others():
    import views.viewport.render as render
    assert viewport_module.render is render
    for m in _parts_holding_sys():
        assert vars(m).get("render", render) is render or m is render
