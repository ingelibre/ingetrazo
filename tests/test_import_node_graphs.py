# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A node listed twice is not walked twice (COLLADA and glTF import).

Each level of a file that places the next node twice doubles the walk: a
3 KB COLLADA file or a 1 KB glTF asked for billions of placements and the
import never ended, filling the memory as it went. COLLADA placements are
counted before anything is built; a glTF node is placed once, as its spec
says (one parent at most).
"""
from __future__ import annotations

import time

import pytest

from core.scene import Scene
from formats import dae
from formats.glb import _node_transforms

_NSDECL = 'xmlns="http://www.collada.org/2005/11/COLLADASchema"'


def _doubling_dae(tmp_path, levels):
    """Library node k places node k+1 twice; the last one is a triangle."""
    nodes = []
    for k in range(levels):
        if k == levels - 1:
            body = '<instance_geometry url="#tri"/>'
        else:
            body = (f'<instance_node url="#L{k + 1}"/>'
                    f'<node><matrix>1 0 0 1 0 1 0 0 0 0 1 0 0 0 0 1</matrix>'
                    f'<instance_node url="#L{k + 1}"/></node>')
        nodes.append(f'<node id="L{k}">{body}</node>')
    text = f"""<?xml version="1.0"?>
<COLLADA {_NSDECL} version="1.4.1">
  <asset><up_axis>Z_UP</up_axis></asset>
  <library_geometries><geometry id="tri"><mesh>
    <source id="p"><float_array id="pa" count="9">0 0 0 1 0 0 0 1 0</float_array>
      <technique_common><accessor source="#pa" count="3" stride="3"/>
      </technique_common></source>
    <vertices id="v"><input semantic="POSITION" source="#p"/></vertices>
    <triangles count="1"><input semantic="VERTEX" source="#v" offset="0"/>
      <p>0 1 2</p></triangles>
  </mesh></geometry></library_geometries>
  <library_nodes>{"".join(nodes)}</library_nodes>
  <library_visual_scenes><visual_scene id="s">
    <node name="root"><instance_node url="#L0"/></node>
  </visual_scene></library_visual_scenes>
  <scene><instance_visual_scene url="#s"/></scene>
</COLLADA>"""
    path = tmp_path / f"doubling-{levels}.dae"
    path.write_text(text)
    return path


def test_a_dae_that_doubles_at_every_level_is_refused_at_once(tmp_path):
    path = _doubling_dae(tmp_path, 32)              # 2^32 placements
    t0 = time.perf_counter()
    with pytest.raises(ValueError, match="malformed"):
        dae.load_dae(Scene(), path)
    assert time.perf_counter() - t0 < 5


def test_a_dae_below_the_limit_still_imports(tmp_path):
    import xml.etree.ElementTree as ET
    path = _doubling_dae(tmp_path, 6)
    # Each level is itself, the next one and a plain node holding it again.
    assert dae._placements(ET.parse(path).getroot()) == 95
    s = Scene()
    dae.load_dae(s, path)
    assert s.mesh.faces or s.groups


def test_the_placement_count_expands_instances_once_per_library_node():
    import xml.etree.ElementTree as ET
    root = ET.fromstring(f"""<COLLADA {_NSDECL}>
  <library_nodes>
    <node id="leg"/>
    <node id="table"><instance_node url="#leg"/><instance_node url="#leg"/>
      <instance_node url="#leg"/><instance_node url="#leg"/></node>
  </library_nodes>
  <library_visual_scenes><visual_scene id="s">
    <node name="room"><instance_node url="#table"/>
      <node name="other"><instance_node url="#table"/></node></node>
  </visual_scene></library_visual_scenes>
</COLLADA>""")
    # room + 2 tables (each 1 + 4 legs) + the plain node «other»
    assert dae._placements(root) == 1 + 1 + 2 * 5


def test_a_gltf_node_listed_twice_is_placed_once():
    nodes = [{"children": [k + 1, k + 1]} for k in range(39)] + [{"mesh": 0}]
    js = {"scenes": [{"nodes": [0]}], "nodes": nodes}
    t0 = time.perf_counter()
    placed = _node_transforms(js)                  # 2^40 walks before
    assert time.perf_counter() - t0 < 5
    assert sorted(i for i, _w in placed) == list(range(40))


def test_a_gltf_node_inside_itself_does_not_overflow():
    js = {"scenes": [{"nodes": [0]}],
          "nodes": [{"children": [1]}, {"children": [0], "mesh": 0}]}
    assert sorted(i for i, _w in _node_transforms(js)) == [0, 1]


def test_a_gltf_without_scenes_places_each_child_under_its_parent():
    """The roots are the nodes nobody holds: every node walked as a root
    brought each child a second time, at the origin."""
    js = {"nodes": [{"mesh": 0},                      # a child listed first
                    {"translation": [5, 0, 0], "children": [0]}]}
    placed = _node_transforms(js)
    assert [i for i, _w in placed] == [1, 0]
    world = dict(placed)[0]
    assert list(world[:3, 3]) == [5.0, 0.0, 0.0]
