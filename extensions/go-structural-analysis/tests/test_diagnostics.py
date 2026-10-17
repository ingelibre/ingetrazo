import copy
import pytest
from go_structural_analysis.diagnostics import inspect_model
from go_structural_analysis.model3d import cantilever3d
from go_structural_analysis.model import benchmark
from go_structural_analysis.house_example import house_model
from go_structural_analysis.diagram_geometry import signed_cells,signed_regions

def codes(d): return {i['code'] for i in inspect_model(d)['issues']}
@pytest.mark.parametrize('factory',[cantilever3d,benchmark,house_model])
def test_clean_models_and_no_mutation(factory):
    d=factory(); old=copy.deepcopy(d); r=inspect_model(d)
    assert r['errors']==0 and d==old
    assert r['internal_stiffness']=='Not Checked' and r['capacity']=='Not Available'

def test_near_duplicate_and_reversed_member():
    d=cantilever3d(); d['nodes'].append(dict(d['nodes'][1],id='Near',x=4+5e-7))
    d['members'].append(dict(d['members'][0],id='Reverse',i='N2',j='N1'))
    assert {'coincident_nodes','duplicate_member','orphan_node'}<=codes(d)
    assert 'coincident_nodes' not in {i['code'] for i in inspect_model(d,1e-8)['issues']}

def test_overlap_vs_adjacent():
    d=cantilever3d(); d['nodes'].append(dict(d['nodes'][1],id='N3',x=6))
    d['members'].append(dict(d['members'][0],id='B2',i='N2',j='N3'))
    assert 'member_overlap' not in codes(d)
    d['nodes'][1]['x']=2; d['members'][1]['i']='N1'
    assert 'member_overlap' in codes(d)

def test_crossing_and_unsplit_joint():
    d=cantilever3d(); d['nodes'] += [dict(id='A',x=2,y=-1,z=0,support='Fixed'),dict(id='B',x=2,y=1,z=0,support='Free')]
    d['members'].append(dict(d['members'][0],id='Cross',i='A',j='B'))
    assert 'unconnected_crossing' in codes(d)
    d['nodes'].append(dict(id='Joint',x=2,y=0,z=0,support='Free'))
    assert 'node_on_member' in codes(d)

@pytest.mark.parametrize('support',['Free','Pin','Roller'])
def test_frame_rigid_body_instability(support):
    d=cantilever3d(); d['nodes'][0]['support']=support
    assert 'rigid_body_modes' in codes(d)

def test_spring_and_axial_truss_observable_modes():
    d=cantilever3d(); d['nodes'][0].update(support='Spring',springs={k:1 for k in ('UX','UY','UZ','RX','RY','RZ')})
    assert 'rigid_body_modes' not in codes(d)
    d['members'][0]['type']='Truss'
    for n in d['nodes']: n.update(support='Pin',springs={})
    assert 'rigid_body_modes' not in codes(d)
    d['members'][0].update(type='Frame',release_i=['RX'],release_j=['RX'])
    assert 'unstable_release' in codes(d)

def test_invalid_geometry_and_tolerance():
    d=cantilever3d(); d['members'][0]['j']='missing'
    assert 'missing_node' in codes(d)
    with pytest.raises(ValueError): inspect_model(d,0)

def area(cell): return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(cell,cell[1:]+cell[:1])))/2
@pytest.mark.parametrize('values',[[1,2,3],[-1,-2,-3],[2,-1,3],[0,1,0],[1,0,-1],[0,0,0]])
def test_merged_fill_preserves_area_and_sign(values):
    samples=[dict(x=i,M=v) for i,v in enumerate(values)]
    for sign in (1,-1):
        assert sum(area(c) for s,c in signed_regions(samples,'M') if s==sign)==pytest.approx(sum(area(c) for s,c in signed_cells(samples,'M') if s==sign))

def test_region_breaks_at_force_jump():
    samples=[dict(x=0,V=1),dict(x=1,V=1),dict(x=1,V=2),dict(x=2,V=2)]
    assert len(list(signed_regions(samples,'V')))==2
