# SPDX-License-Identifier: GPL-3.0-or-later
"""An owned import must restore the caller's cyclic collector on every exit."""
import gc

import pytest

from formats import skp_openskp as adapter


@pytest.mark.parametrize("initially_enabled", [False, True])
@pytest.mark.parametrize("failure", [None, RuntimeError, KeyboardInterrupt])
def test_adapter_defers_collection_and_restores_state(monkeypatch,
                                                     initially_enabled, failure):
    original_state = gc.isenabled()
    model, payload = object(), object()
    seen = []

    def build(source, name, path):
        seen.append((source, name, path, gc.isenabled()))
        if failure:
            raise failure("interrupted adaptation")
        return payload

    monkeypatch.setattr(adapter, "_adapt_inner", build)
    try:
        (gc.enable if initially_enabled else gc.disable)()
        if failure:
            with pytest.raises(failure):
                adapter._adapt(model, "sample", "sample.skp")
        else:
            assert adapter._adapt(model, "sample", "sample.skp") is payload
        assert seen == [(model, "sample", "sample.skp", False)]
        assert gc.isenabled() is initially_enabled
    finally:
        (gc.enable if original_state else gc.disable)()
