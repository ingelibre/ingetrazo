# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Exact settled images and unchanged snap queries for opt-in camera feedback."""
import pytest
from PySide6.QtGui import QVector3D as V, QMatrix4x4, QImage
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from core.group import Group
from core.mesh import Mesh
from views.main_window import MainWindow


def test_disabled_feedback_does_not_read_camera():
    from types import SimpleNamespace
    from views.viewport import Viewport
    class Unreadable:
        def data(self):
            raise AssertionError('disabled path must be inert')
    assert not Viewport._navigation_feedback_frame(
        SimpleNamespace(_navigation_feedback=False), Unreadable())


@pytest.mark.parametrize('context', ['normal', 'cut', 'fade', 'shadow'])
def test_feedback_restores_exact_cocoa_frame_and_snap(tmp_path, context):
    QSettings().remove('display/navigation_feedback')
    win = MainWindow(); win.resize(900, 700); win.show()
    QApplication.processEvents(); vp = win.viewport
    try:
        if vp._gl is None or not vp.isValid(): pytest.skip('requires real Cocoa GL')
        assert not vp._navigation_feedback
        mesh = Mesh()
        for z in (0, 1):
            face = mesh.add_face([V(0, 0, z), V(2, 0, z), V(2, 2, z), V(0, 2, z)])
            face.attrs['color'] = (.2, .7, .3)
        mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 0, 1), V(0, 0, 1)])
        image=QImage(2, 2, QImage.Format_RGB32); image.fill(0xffaa3344)
        path=str(tmp_path/'texture.png'); image.save(path)
        mesh.faces[-1].attrs['texture']={'path':path,'sw':1.0,'sh':1.0}
        # Soft boundary edges exercise profiles as well as ordinary edges.
        for edge in mesh.edges[:2]: edge.soft=True
        for i in range(3):
            g=Group(mesh);g.xform=QMatrix4x4();g.xform.translate(i*3,0,0)
            if i==1:g.xform.scale(-1, .7, 2)
            vp.scene.groups.append(g)
        vp.scene.version+=1;vp.camera.fit_to(V(-2,-2,-2),V(10,4,4))
        if context=='cut':
            from core.section import SectionPlane
            vp.scene.section_planes=[SectionPlane(V(0,0,.6),V(0,0,1),active=True)]
        elif context=='fade':vp.begin_group_edit(vp.scene.groups[1])
        elif context=='shadow':vp.scene.shadows.enabled=True
        def frame():
            img=vp.grabFramebuffer().convertToFormat(QImage.Format_RGB32)
            assert not img.isNull()
            return bytes(img.constBits())
        for mode in ('textures','shaded','monochrome','hidden_line','xray','wireframe'):
            vp.scene.display_style.face_mode=mode
            vp.set_navigation_feedback(True);frame()
            vp.camera.orbit(21,7,vp.height());moving=frame()
            assert vp._navigation_feedback_active
            # Exports must never inherit transient suppression.
            export=vp.render_image(300,200,overlays=False)
            vp._finish_navigation_feedback();settled=frame()
            assert not vp._navigation_feedback_active
            vp.set_navigation_feedback(False);reference=frame()
            assert settled==reference,(context,mode)
            assert export==vp.render_image(300,200,overlays=False)
            if mode=='wireframe':assert moving==reference
            elif context=='normal':assert moving!=reference
        # The timer must actually publish a full frame without another input.
        vp.set_navigation_feedback(True);frame();vp.camera.orbit(9,3,vp.height());frame()
        QTest.qWait(220)
        assert not vp._navigation_feedback_active
        restored=frame();vp.set_navigation_feedback(False)
        assert restored==frame()
        # Feedback never enters picking: compare exact kind/point values.
        def snap(enabled):
            vp.set_navigation_feedback(enabled)
            result=vp._snap_at(vp.width()/2,vp.height()/2, Qt.NoModifier)
            return (result.kind, result.point.toTuple()) if result else None
        assert snap(True)==snap(False)
    finally:
        win._saved_content=vp.scene.content_version;win.close()


def test_motion_edge_lod_preserves_large_unknown_and_rest(monkeypatch):
    import numpy as np
    from types import SimpleNamespace
    from views.viewport import Viewport, _InstanceBatch
    vp = SimpleNamespace(_frame_feedback=True, _navigation_edge_lod_px=8,
                         _INST_MIN_PX=1, _inst_pool=object())
    vp._effective_style=lambda:SimpleNamespace(face_mode='shaded')
    vp._navigation_edge_floor=lambda:Viewport._navigation_edge_floor(vp)
    vp._instances_below_a_pixel=lambda pool,scale:np.array([True,False,False])
    batch=_InstanceBatch(['small','large','unknown'])
    batch.idx=np.array([0,1,2]);batch.mats=np.zeros((3,16))
    groups={1:(None,None,batch,False)}
    result=Viewport._navigation_edge_batches(vp,groups)
    assert list(result[1][2]) == ['large','unknown']
    assert list(result[1][2].idx) == [1,2]
    assert Viewport._navigation_edge_batches(vp,groups) is result
    vp._frame_feedback=False
    assert Viewport._navigation_edge_batches(vp,groups) is groups
