# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
import numpy as np
import pytest
from views.gl_commands import compact_tape


def replay(ops, vals):
    state = {('active',): 123}; primitives=[]
    for row, floats in zip(ops, vals.view(np.uint32)):
        code,a,b,c,d=map(int,row)
        if code in (0,11):
            first,count=(b,c) if code==0 else (c//4,b)
            for instance in range(d):
                for triangle in range(first,first+count,3):
                    primitives.append((code,a,instance,triangle,dict(state)))
        elif code in (2,3,4):state[('uniform',a)]=(code,b,tuple(floats))
        elif code in (5,6):state[('cap',a)]=code==5
        elif code==9:state[('active',)]=a
        elif code==10:state[('texture',state[('active',)],a)]=b
        else:state[(code,)]=a
    return primitives,state


@pytest.mark.parametrize('size,multiunit', [(30,False),(200,False),(200,True)])
def test_compaction_preserves_every_ordered_primitive_and_final_state(size,multiunit):
    rng=np.random.default_rng(19);ops=[];vals=[]
    def op(code,a=0,b=0,c=0,d=0,value=0.):
        ops.append((code,a,b,c,d));vals.append((value,0.,0.,0.))
    for i in range(size):
        op(9,33984+(i%2 if multiunit else 0));op(10,3553,int(rng.integers(1,4)))
        op(1,i%3);op(3,9,value=float(i%4));op(7,1028);op(7,1028)
        # Duplicate uniforms include signed zero, which is not rounded away.
        value=-0. if i%2 else 0.
        op(3,10,value=value);op(3,10,value=value)
        count=int(rng.integers(1,4))*3;n=int(rng.integers(1,3))
        op(0,4,i*12,count,n);op(10,3553,0)
    ops=np.array(ops,np.int64);vals=np.array(vals,np.float32)
    a,b=compact_tape(ops,vals)
    assert replay(ops,vals)==replay(a,b)
    assert len(a)<len(ops)


@pytest.mark.parametrize('code',[0,11])
@pytest.mark.parametrize('instances',[1,2])
def test_adjacent_triangle_ranges_merge_only_for_one_instance(code,instances):
    rows=[(code,4,0,3,instances),(code,4,3,6,instances)] if code==0 else [
        (code,4,3,0,instances),(code,4,6,12,instances)]
    ops=np.array(rows,np.int64);vals=np.zeros((2,4),np.float32)
    a,b=compact_tape(ops,vals)
    assert replay(ops,vals)==replay(a,b)
    assert len(a)==(1 if instances==1 else 2)


def test_unknown_opcode_keeps_tape_and_inputs_are_immutable():
    ops=np.array([[99,0,0,0,0]],np.int64);vals=np.zeros((1,4),np.float32)
    assert compact_tape(ops,vals)[0] is ops


@pytest.mark.parametrize('context', ['normal', 'cut', 'fade', 'shadow'])
def test_compacted_tape_cocoa_exact_rgb32(monkeypatch, tmp_path, context):
    from PySide6.QtGui import QVector3D as V, QMatrix4x4, QImage
    from PySide6.QtWidgets import QApplication
    from core.group import Group
    from core.mesh import Mesh
    from views.main_window import MainWindow
    from views import gl_commands
    win = MainWindow(); win.resize(900, 700); win.show()
    QApplication.processEvents(); vp = win.viewport
    try:
        if vp._gl is None or not vp.isValid(): pytest.skip('requires real OpenGL')
        m = Mesh()
        m.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)]).attrs['color'] = (.2, .7, .3)
        m.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 0, 2)]).attrs['color'] = (.9, .1, .4)
        for j in range(12):
            m.add_face([V(0, j*.1, 0), V(2, j*.1, 0), V(2, (j+1)*.1, 0), V(0, (j+1)*.1, 0)])
        for texture_index in range(2):
            image = QImage(2, 2, QImage.Format_RGB32)
            image.fill(0xffaa3344 + texture_index * 0x224422)
            path = str(tmp_path / f'texture{texture_index}.png'); image.save(path)
            for j in range(12):
                f = m.add_face([V(0, j*.1, 1+texture_index), V(2, j*.1, 1+texture_index),
                                V(2, (j+1)*.1, 1+texture_index), V(0, (j+1)*.1, 1+texture_index)])
                f.attrs['texture'] = {'path': path, 'sw': 1.0, 'sh': 1.0}
        for i in range(6):
            g = Group(m); g.xform = QMatrix4x4(); g.xform.translate(i*3, 0, 0)
            g.xform.rotate(i*19, V(1, 2, 3))
            if i % 2: g.xform.scale(-1, .7, 2)
            vp.scene.groups.append(g)
        vp.scene.version += 1; vp.camera.fit_to(V(-2, -3, -2), V(20, 5, 5))
        from core.section import SectionPlane
        if context == 'cut':
            vp.scene.section_planes = [SectionPlane(V(0, 0, .6), V(0, 0, 1), active=True)]
        elif context == 'fade':
            vp.set_edit_rest_mode('fade'); vp.begin_group_edit(vp.scene.groups[1])
        elif context == 'shadow':
            vp.scene.shadows.enabled = True
        real = gl_commands.compact_tape
        for mode in ('textures', 'shaded', 'monochrome', 'hidden_line', 'xray'):
            vp.scene.display_style.face_mode = mode
            for view in ('top', 'iso'):
                vp.camera.set_view(view)
                frames = []
                for packing in (lambda ops, vals: (ops, vals), real):
                    monkeypatch.setattr(gl_commands, 'compact_tape', packing)
                    vp.reset_document_caches(); vp.scene.version += 1
                    vp._forget_frame_records()
                    vp._frame_cache = None
                    vp._shadow_key = None
                    img = vp.render_image(400, 300, overlays=False).convertToFormat(QImage.Format_RGB32)
                    frames.append(bytes(img.constBits()))
                    # The second frame exercises the recorded native tape too.
                    again = vp.render_image(400, 300, overlays=False).convertToFormat(QImage.Format_RGB32)
                    assert bytes(again.constBits()) == frames[-1]
                assert frames[0] == frames[1], (mode, view)
    finally:
        win._saved_content = vp.scene.content_version; win.close()

