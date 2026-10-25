# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Large saves retain the exact legacy JSON/ZIP bytes with bounded scratch reads."""
import io
import json
import tracemalloc
import zipfile

import pytest

from core.scene import Scene
from formats import igz, igz_stream
from tests.test_igz_format3 import _scene


class _RetainedStream(dict):
    """Reference: keep mesh dictionaries/blobs, encode the whole JSON in one call."""

    def __init__(self):
        super().__init__()
        self.blobs, self.resolved, self.missing = {}, {}, 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def json(self, value):
        return value

    def document(self, value):
        return json.dumps(value, separators=(",", ":"), allow_nan=False)


def _old_container(path, doc, blobs, fast=False, deflated=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for member, data, compression in [
            (igz._DOC_ENTRY, doc, zipfile.ZIP_DEFLATED),
            *((m, deflated[m], zipfile.ZIP_DEFLATED) for m in sorted(deflated or ())),
            *((m, blobs[m], zipfile.ZIP_STORED) for m in sorted(blobs)),
        ]:
            info = zipfile.ZipInfo(member, date_time=igz._ZIP_EPOCH)
            info.compress_type = compression
            archive.writestr(info, data, compresslevel=1 if fast else None)
    path.write_bytes(buf.getvalue())


@pytest.mark.parametrize("binary", [False, True])
def test_full_save_matches_retained_json_and_original_zip(tmp_path, monkeypatch, binary):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 1 if binary else 10**9)
    scene = _scene(tmp_path)
    scene.plugin_data = {"unicode": {7: ["é", "\\\"\n", -0.0, 1e-20]}}
    before, after = tmp_path / "before.igz", tmp_path / "after.igz"
    result = igz.save_scene(scene, after)
    with monkeypatch.context() as m:
        m.setattr(igz_stream, "SaveStream", _RetainedStream)
        m.setattr(igz, "_write_container", _old_container)
        assert igz.save_scene(scene, before) == result
    assert before.read_bytes() == after.read_bytes()
    # Neither embedding nor spooling mutates the scene's texture paths.
    assert "path" in scene.mesh.faces[0].attrs["texture"]
    loaded = Scene()
    igz.load_into(loaded, after)
    assert loaded.groups[0].mesh is loaded.groups[1].mesh


def test_json_fragments_match_stdlib_and_can_read_their_own_spool():
    leaf = {7: [None, True, False, -0.0, 1e-200, "é\\\"\n"], None: "null key"}
    with igz_stream.SaveStream() as stream:
        fragment = stream.json(leaf)
        actual = stream.document({"nested": [fragment, {"again": fragment}]})
        expected = {"nested": [leaf, {"again": leaf}]}
        assert b"".join(actual.chunks()) == json.dumps(
            expected, separators=(",", ":"), allow_nan=False).encode()


def test_many_completed_meshes_do_not_accumulate_encoded_bytes():
    tracemalloc.start()
    try:
        with igz_stream.SaveStream() as stream:
            fragments = [stream.json(["x" * 1024] * 1024) for _ in range(20)]
            assert sum(f.size for f in fragments) > 20_000_000
            _current, peak = tracemalloc.get_traced_memory()
            assert peak < 5_000_000
            assert all(len(chunk) <= igz_stream._CHUNK
                       for chunk in fragments[0].chunks())
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize("error", [OSError, RuntimeError, KeyboardInterrupt])
def test_write_failure_preserves_old_file_and_closes_scratch(tmp_path, monkeypatch, error):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 1)
    path = tmp_path / "old.igz"
    path.write_bytes(b"original document")
    opened = []
    original = igz_stream.tempfile.TemporaryFile

    def temporary_file(*args, **kwargs):
        result = original(*args, **kwargs)
        opened.append(result)
        return result

    def fail(*args, **kwargs):
        raise error("injected write failure")

    monkeypatch.setattr(igz_stream.tempfile, "TemporaryFile", temporary_file)
    monkeypatch.setattr(zipfile._ZipWriteFile, "write", fail)
    with pytest.raises(error, match="injected"):
        igz.save_scene(_scene(tmp_path), path)
    assert path.read_bytes() == b"original document"
    assert not path.with_name(path.name + ".part").exists()
    assert opened and all(f.closed for f in opened)


def test_missing_texture_is_counted_once_across_spooled_meshes(tmp_path, monkeypatch):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    scene = _scene(tmp_path)
    for group in scene.groups:
        group.mesh.faces[0].attrs["texture"] = {"path": "/absent-r5c.png"}
    assert igz.save_scene(scene, tmp_path / "missing.igz") == {"embedded": 1, "missing": 1}


def test_nonfinite_fragment_preserves_existing_document(tmp_path, monkeypatch):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    scene = _scene(tmp_path)
    scene.groups[-1].mesh.vertices[0].position.setX(float("nan"))
    path = tmp_path / "old.igz"
    path.write_bytes(b"original")
    with pytest.raises(igz.NonFiniteDocumentError):
        igz.save_scene(scene, path)
    assert path.read_bytes() == b"original"
    assert not path.with_name(path.name + ".part").exists()
