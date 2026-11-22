# SPDX-License-Identifier: GPL-3.0-or-later
"""Saving runs with the garbage collector off, like opening a document and
applying a .skp import do (mass construction of small containers): the
collector's state is put back afterwards, whatever happened in between."""
from __future__ import annotations

import gc

import pytest
from PySide6.QtGui import QVector3D as V

from core.scene import Scene
from formats import igz


def _scene() -> Scene:
    scene = Scene()
    scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    return scene


def test_the_collector_is_off_while_saving_and_back_on_after(
        tmp_path, monkeypatch):
    seen = []
    real = igz._pack_textures

    def spy(payload):
        seen.append(gc.isenabled())
        return real(payload)
    monkeypatch.setattr(igz, "_pack_textures", spy)
    assert gc.isenabled()
    igz.save_scene(_scene(), tmp_path / "a.igz")
    assert seen == [False]
    assert gc.isenabled()


def test_a_collector_already_off_stays_off(tmp_path):
    gc.disable()
    try:
        igz.save_scene(_scene(), tmp_path / "a.igz")
        assert not gc.isenabled()
    finally:
        gc.enable()


def test_a_failed_save_puts_the_collector_back(tmp_path, monkeypatch):
    def boom(payload):
        raise RuntimeError("no room on the disk")
    monkeypatch.setattr(igz, "_pack_textures", boom)
    with pytest.raises(RuntimeError):
        igz.save_scene(_scene(), tmp_path / "bad.igz")
    assert gc.isenabled()
