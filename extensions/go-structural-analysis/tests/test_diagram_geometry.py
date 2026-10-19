import math
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'go_structural_analysis'))
from diagram_geometry import arrow_geometry,signed_cells,reaction_components,moment_geometry

def test_reactions_independent_axes():
    assert reaction_components(-7.,10.)==[('Rx',-7.,0.,-7.),('Rz',0.,10.,10.)]
    assert reaction_components(0.,5.)==[('Rz',0.,5.,5.)]
    assert reaction_components(0.,0.)==[]

@pytest.mark.parametrize('value',[10.,-10.])
def test_moment_direction_and_anchor(value):
    center=(35.,45.); points,head=moment_geometry(center,value)
    assert all(math.dist(p,center)==pytest.approx(24.) for p in points)
    a,b=points[:2]; ax,ay=a[0]-center[0],-(a[1]-center[1]); bx,by=b[0]-center[0],-(b[1]-center[1])
    assert (ax*by-ay*bx)*value>0
    assert head[0]==points[-1]

def test_zero_moment_hidden():
    assert moment_geometry((0.,0.),0.) is None

@pytest.mark.parametrize('direction',[(0,1),(0,-1),(1,0),(-1,0),(3,-4)])
def test_arrow_tip_anchored(direction):
    tail,tip,left,right=arrow_geometry((25.,30.),direction)
    assert tip==(25.,30.)
    assert math.dist(tail,tip)==pytest.approx(40.)
    assert sum((tip[i]-tail[i])*direction[i] for i in range(2))>0
    assert math.dist(left,tip)==pytest.approx(math.dist(right,tip))

def test_arrow_zero_hidden():
    assert arrow_geometry((0,0),(0,0)) is None

def test_signed_fill_crossing_and_discontinuity():
    cells=list(signed_cells([{'x':0,'V':2},{'x':3,'V':-1},{'x':3,'V':4},{'x':4,'V':4}],'V'))
    assert [s for s,_ in cells]==[1,-1,1]
    assert cells[0][1][-1]==(2.,0.)
    assert cells[1][1][0]==(2.,0.)
    for sign,points in cells:
        assert all(sign*y>=0 for x,y in points)

def test_zero_diagram_unfilled():
    assert list(signed_cells([{'x':0,'N':0},{'x':6,'N':0}],'N'))==[]
