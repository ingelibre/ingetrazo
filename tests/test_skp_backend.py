# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SKP import seam (``formats/skp.py``): container detection, the pure-backend
cascade, and the NeedsConverter fallback signal."""
from __future__ import annotations

import zipfile

import pytest

from formats import skp as skp_format


def test_detect_format_vff_zip(tmp_path):
    p = tmp_path / "new.skp"
    with zipfile.ZipFile(p, "w") as zf:  # v2021+ is a ZIP container
        zf.writestr("model.dat", b"\x00\x01\x02")
    assert skp_format.detect_format(p) == "vff"


def test_detect_format_legacy_binary(tmp_path):
    p = tmp_path / "old.skp"
    p.write_bytes(b"\xff\xfe\x00SketchUp Model")  # not a ZIP → legacy blob
    assert skp_format.detect_format(p) == "legacy"


def test_detect_format_unknown_when_empty(tmp_path):
    p = tmp_path / "empty.skp"
    p.write_bytes(b"")
    assert skp_format.detect_format(p) == "unknown"
    assert skp_format.detect_format(tmp_path / "missing.skp") == "unknown"


def test_no_pure_backend_today_falls_to_converter(tmp_path):
    # With no parser wired, every file must signal NeedsConverter so the UI
    # runs skp2dae — this is what preserves today's behaviour exactly.
    p = tmp_path / "x.skp"
    p.write_bytes(b"\xff\xfe\x00stuff")
    assert skp_format.can_handle(p) is False
    with pytest.raises(skp_format.NeedsConverter) as exc:
        skp_format.load_skp(object(), p)
    assert exc.value.format == "legacy"
    assert exc.value.path == p


def test_backends_status_reports_openskp_unavailable():
    status = dict(skp_format.backends_status())
    assert status.get("openskp") is False  # stub, not wired yet


def test_cascade_uses_an_available_backend(tmp_path, monkeypatch):
    # Prove the seam: a wired backend that supports the file's format is used,
    # and load_skp returns its name (no NeedsConverter).
    loaded = {}

    class FakeBackend:
        name = "fake"

        def available(self):
            return True

        def supports(self, fmt):
            return fmt == "legacy"

        def load(self, scene, path, progress=None):
            loaded["path"] = path
            if progress:
                progress(1.0, "done")

    monkeypatch.setattr(skp_format, "_BACKENDS", [FakeBackend()])
    p = tmp_path / "y.skp"
    p.write_bytes(b"\x01\x02legacy-bytes")
    assert skp_format.can_handle(p) is True
    calls = []
    used = skp_format.load_skp("scene", p, progress=lambda f, t: calls.append(t))
    assert used == "fake"
    assert loaded["path"] == p
    assert calls == ["done"]


def test_cascade_skips_backend_that_does_not_support_format(tmp_path, monkeypatch):
    class VffOnly:
        name = "vffonly"

        def available(self):
            return True

        def supports(self, fmt):
            return fmt == "vff"

        def load(self, scene, path, progress=None):  # pragma: no cover
            raise AssertionError("must not be called for a legacy file")

    monkeypatch.setattr(skp_format, "_BACKENDS", [VffOnly()])
    p = tmp_path / "z.skp"
    p.write_bytes(b"\x01\x02not-a-zip")  # legacy
    assert skp_format.can_handle(p) is False
    with pytest.raises(skp_format.NeedsConverter):
        skp_format.load_skp("scene", p)
