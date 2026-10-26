import math
import numpy as np
import pytest
from PySide6.QtGui import QVector3D as V
from core.camera import OrbitCamera, NEAR_FLOOR


def camera():
    c = OrbitCamera(); c.distance = 20; c.look_from(V(0,0,0),V(0,1,0))
    return c


@pytest.mark.parametrize('distance', [10,50,200])
def test_depth_fit_resolves_one_mm(distance):
    c = camera(); c.fit_depth_range([[-1,distance,-1]],[[1,distance+.005,1]])
    n,f = c.near_plane(),c.far_plane()
    assert 0 < n < distance < f
    step = distance**2 * (f-n)/(f*n*(2**24-1))
    assert step < .001/10


def test_inside_unknown_and_changed_camera_are_conservative():
    c = camera(); c.fit_depth_range([[-1,-1,-1]],[[1,20,1]])
    assert c.near_plane() == .1
    c.fit_depth_range([[-1,10,-1]],[[1,11,1]])
    c.move_eye(V(0,10,0))
    assert c.near_plane() == .1  # stale fit must never clip a later view
    c.fit_depth_range([[-np.inf]*3],[[np.inf]*3])
    assert c.near_plane() == .1


def test_side_culling_does_not_use_old_far_plane():
    c = camera(); c.fit_depth_range([[1e6,1,-1],[-1,20000,-1]],[[1e6+1,2,1],[1,20001,1]])
    assert c.near_plane() > 10000
    assert c.far_plane() > 20001


def test_two_point_and_orthographic():
    c = camera(); c.two_point=True;c.pitch=math.radians(30)
    eye=c.eye();f=c._level_forward()
    p=c.target
    c.fit_depth_range([p.toTuple()],[p.toTuple()])
    assert c.near_plane() == pytest.approx(20*math.cos(c.pitch)*.95,abs=1e-4)
    c.perspective=False
    assert c.far_plane()==10000


@pytest.mark.parametrize('context', ['normal','cut','fade','shadow'])
def test_cocoa_nonfighting_geometry_pixels(monkeypatch, context):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QMatrix4x4
    from views.main_window import MainWindow
    from core.group import Group
    from core.mesh import Mesh
    win=MainWindow();win.resize(900,700);win.show();QApplication.processEvents()
    vp=win.viewport
    try:
        if not vp.isValid():pytest.skip('requires Cocoa GL')
        vp.scene.show_axes=False
        mesh=Mesh()
        mesh.add_face([V(1,1,.25),V(3,1,.25),V(3,3,.25),V(1,3,.25)]).attrs['color']=(.2,.7,.3)
        mesh.add_face([V(1,1,1),V(3,1,1),V(3,3,1),V(1,3,1)]).attrs['color']=(.7,.2,.3)
        for i in range(3):
            g=Group(mesh);g.xform=QMatrix4x4();g.xform.translate(i*3,0,0)
            if i==1:g.xform.scale(-1,.7,2)
            vp.scene.groups.append(g)
        vp.scene.version+=1;vp.camera.fit_to(V(-3,-3,-2),V(12,4,4))
        if context=='cut':
            from core.section import SectionPlane
            vp.scene.section_planes=[SectionPlane(V(0,0,.6),V(0,0,1),active=True)]
        elif context=='fade':vp.set_edit_rest_mode('fade');vp.begin_group_edit(vp.scene.groups[1])
        elif context=='shadow':vp.scene.shadows.enabled=True
        fit=vp._fit_scene_depth
        for mode in ('shaded','textures','monochrome','hidden_line','xray','wireframe'):
            vp.scene.display_style.face_mode=mode
            images=[]
            for fn in (lambda:setattr(vp.camera,'_depth_range',None),fit):
                monkeypatch.setattr(vp,'_fit_scene_depth',fn)
                image=vp.render_image(400,300,overlays=False).convertToFormat(QImage.Format_RGB32)
                images.append(np.frombuffer(image.constBits(),np.uint8).copy())
            if not np.array_equal(*images):
                a,b=[i.reshape(300,400,4) for i in images]
                y,x=np.where(np.any(a!=b,axis=2))
                print('DIFF', list(zip(x.tolist(),y.tolist())), a[y,x].tolist(), b[y,x].tolist())
            assert np.array_equal(*images),(context,mode,int(np.count_nonzero(images[0]!=images[1])))
    finally:
        win._saved_content=vp.scene.content_version;win.close()


@pytest.mark.parametrize('empty', [False, True])
def test_unknown_bounds_are_cached_and_empty_groups_do_not_block_fit(empty):
    from types import SimpleNamespace as NS
    from core.mesh import Mesh
    from views.viewport import Viewport
    mesh=Mesh()
    if not empty:
        mesh.add_face([V(0,0,0),V(1,0,0),V(0,1,0)])
    group=NS(mesh=mesh,xform=object())
    scene=NS(edit_group=None,guides=[],shadows=NS(enabled=False),
             mesh=Mesh(),content_version=0,version=0,image_planes=[],
             entity_visible=lambda g:True)
    calls=[]
    def box(g):
        calls.append(g)
        return None if g is group else ((-1,10,-1),(1,11,1))
    vp=NS(camera=camera(),scene=scene,_placements_epoch=lambda:0,
          _placements=lambda:[group,NS(mesh=Mesh(),xform=object())],
          _placement_bbox=box,_base_map_showing=lambda:False,
          _terrain_showing=lambda:False,_photo_showing=lambda:False)
    Viewport._fit_scene_depth(vp);count=len(calls)
    Viewport._fit_scene_depth(vp)
    assert len(calls)==count
    assert (vp.camera.near_plane() > 1) == empty
    scene.content_version+=1
    Viewport._fit_scene_depth(vp)
    assert len(calls)==2*count


@pytest.mark.parametrize('two_point', [False,True])
def test_depth_fit_keeps_all_editing_rays_exact(two_point):
    from types import SimpleNamespace as NS
    from views.viewport import Viewport
    c=camera();c.two_point=two_point
    vp=NS(camera=c,width=lambda:1124,height=lambda:835)
    points=[(x,y) for x in (0,50,562,1000,1123) for y in (0,80,417,750,834)]
    def rays():
        return [tuple(v.toTuple() for v in Viewport._pixel_to_ray(vp,x,y))
                for x,y in points]
    before=rays()
    c.fit_depth_range([[-30,150,-30]],[[30,300,30]])
    assert c.near_plane() > 100
    fitted=c._depth_range
    assert rays()==before
    assert c._depth_range is fitted


def test_axiswise_bounds_reductions_match_original_exactly():
    rng=np.random.default_rng(13)
    lo=rng.uniform(-300,300,(20000,3));hi=lo+rng.uniform(0,50,(20000,3))
    for direction in rng.uniform(-1,1,(20,3)):
        old=(np.where(direction>=0,lo,hi)*direction).sum(axis=1)
        p=[lo[:,i] if direction[i]>=0 else hi[:,i] for i in range(3)]
        new=(p[0]*direction[0]+p[1]*direction[1])+p[2]*direction[2]
        np.testing.assert_array_equal(new,old)
