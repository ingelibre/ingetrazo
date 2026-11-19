# SPDX-License-Identifier: GPL-3.0-or-later
"""The raw OpenSKP parse runs with cyclic collection paused and restores it."""
import gc
from types import SimpleNamespace

import pytest

from formats import skp_openskp as adapter


@pytest.mark.parametrize("initially_enabled", [False, True])
@pytest.mark.parametrize("failure", [None, RuntimeError, KeyboardInterrupt])
def test_raw_parse_pauses_collection_and_restores_state(initially_enabled,
                                                        failure):
    original_state = gc.isenabled()
    model = object()
    seen = []

    class File:
        def parse(self):
            seen.append(("parse", gc.isenabled()))
            if failure:
                raise failure("interrupted parse")
            return model

    openskp = SimpleNamespace(SkpFile=SimpleNamespace(open=lambda p: File()))
    compat = SimpleNamespace(
        resolve_face_layers=lambda m: seen.append(("layers", m, gc.isenabled())))
    try:
        (gc.enable if initially_enabled else gc.disable)()
        if failure:
            with pytest.raises(failure):
                adapter._parse_raw(openskp, compat, "sample.skp")
            assert seen == [("parse", False)]
        else:
            assert adapter._parse_raw(openskp, compat, "sample.skp") is model
            assert seen == [("parse", False), ("layers", model, False)]
        assert gc.isenabled() is initially_enabled
    finally:
        (gc.enable if original_state else gc.disable)()
