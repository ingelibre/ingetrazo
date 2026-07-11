# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""COLLADA (.dae) import — SketchUp-style documents."""
from __future__ import annotations

from core.orient import is_closed, signed_volume
from core.scene import Scene
from formats.dae import load_dae

_NSDECL = 'xmlns="http://www.collada.org/2005/11/COLLADASchema"'


def _cube_dae(tmp_path, up="Z_UP", meter="1.0"):
    """A unit cube as triangles, one red material, one instanced node."""
    # 8 corners of the unit cube (Z_UP coordinates).
    pos = ("0 0 0  1 0 0  1 1 0  0 1 0  "
           "0 0 1  1 0 1  1 1 1  0 1 1")
    tris = ("0 3 2 0 2 1  4 5 6 4 6 7  0 1 5 0 5 4  "
            "1 2 6 1 6 5  2 3 7 2 7 6  3 0 4 3 4 7")
    text = f"""<?xml version="1.0"?>
<COLLADA {_NSDECL} version="1.4.1">
  <asset><unit meter="{meter}"/><up_axis>{up}</up_axis></asset>
  <library_effects>
    <effect id="fx-red"><profile_COMMON><technique sid="t">
      <lambert><diffuse><color>1 0 0 1</color></diffuse></lambert>
    </technique></profile_COMMON></effect>
  </library_effects>
  <library_materials>
    <material id="mat-red"><instance_effect url="#fx-red"/></material>
  </library_materials>
  <library_geometries>
    <geometry id="cube"><mesh>
      <source id="cube-pos">
        <float_array id="cube-pos-arr" count="24">{pos}</float_array>
        <technique_common>
          <accessor source="#cube-pos-arr" count="8" stride="3"/>
        </technique_common>
      </source>
      <vertices id="cube-v">
        <input semantic="POSITION" source="#cube-pos"/>
      </vertices>
      <triangles count="12" material="RED">
        <input semantic="VERTEX" source="#cube-v" offset="0"/>
        <p>{tris}</p>
      </triangles>
    </mesh></geometry>
  </library_geometries>
  <library_visual_scenes>
    <visual_scene id="scene">
      <node id="n1">
        <instance_geometry url="#cube">
          <bind_material><technique_common>
            <instance_material symbol="RED" target="#mat-red"/>
          </technique_common></bind_material>
        </instance_geometry>
      </node>
    </visual_scene>
  </library_visual_scenes>
</COLLADA>
"""
    p = tmp_path / "cube.dae"
    p.write_text(text)
    return p


def test_triangulated_cube_comes_back_as_six_quads(tmp_path):
    scene = Scene()
    load_dae(scene, _cube_dae(tmp_path))
    m = scene.mesh
    assert len(m.faces) == 6                       # coplanar-merged
    assert all(len(f.loop) == 4 for f in m.faces)
    assert is_closed(m)
    assert abs(signed_volume(m) - 1.0) < 1e-6
    # the bound material's diffuse colour landed on the faces
    assert all(f.attrs.get("color") == [1.0, 0.0, 0.0] for f in m.faces)


def test_y_up_and_inches_convert_to_zup_metres(tmp_path):
    scene = Scene()
    load_dae(scene, _cube_dae(tmp_path, up="Y_UP", meter="0.0254"))
    m = scene.mesh
    assert is_closed(m)
    assert abs(signed_volume(m) - 0.0254 ** 3) < 1e-9
    zs = sorted({round(v.position.z(), 6) for v in m.vertices})
    assert zs == [0.0, 0.0254]                     # COLLADA Y became world Z


def test_instanced_component_with_transform(tmp_path):
    # SketchUp components: geometry lives in library_nodes, the scene
    # instances it with a transform.
    body = f"""<?xml version="1.0"?>
<COLLADA {_NSDECL} version="1.4.1">
  <asset><up_axis>Z_UP</up_axis></asset>
  <library_geometries>
    <geometry id="tri"><mesh>
      <source id="p"><float_array id="pa" count="9">0 0 0  1 0 0  0 1 0</float_array>
        <technique_common><accessor source="#pa" count="3" stride="3"/></technique_common>
      </source>
      <vertices id="v"><input semantic="POSITION" source="#p"/></vertices>
      <polylist count="1">
        <input semantic="VERTEX" source="#v" offset="0"/>
        <vcount>3</vcount><p>0 1 2</p>
      </polylist>
    </mesh></geometry>
  </library_geometries>
  <library_nodes>
    <node id="comp"><instance_geometry url="#tri"/></node>
  </library_nodes>
  <library_visual_scenes>
    <visual_scene id="scene">
      <node id="a"><instance_node url="#comp"/></node>
      <node id="b"><translate>10 0 0</translate><instance_node url="#comp"/></node>
    </visual_scene>
  </library_visual_scenes>
</COLLADA>
"""
    p = tmp_path / "comp.dae"
    p.write_text(body)
    scene = Scene()
    load_dae(scene, p)
    xs = sorted(round(v.position.x(), 3) for v in scene.mesh.vertices)
    assert len(scene.mesh.faces) == 2              # both instances imported
    assert 10.0 in xs and 11.0 in xs               # the translate applied


def test_empty_document_raises(tmp_path):
    p = tmp_path / "empty.dae"
    p.write_text(f'<?xml version="1.0"?><COLLADA {_NSDECL} version="1.4.1"/>')
    scene = Scene()
    try:
        load_dae(scene, p)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
