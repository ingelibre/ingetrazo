import copy
import pytest
from go_structural_analysis.model3d import cantilever3d
from go_structural_analysis.model import benchmark
from go_structural_analysis.worker import solve
from go_structural_analysis.results import evaluate
from go_structural_analysis.continuous_graph import graph_data,inspect_chain

def split(model,reverse=False,rotation=0):
    model=copy.deepcopy(model); a,b=model['nodes'][:2]; member=model['members'][0]
    midpoint=dict(id='Joint',**{k:(a.get(k,0)+b.get(k,0))/2 for k in ('x','y','z')})
    if model.get('schema')!=2: midpoint.pop('y')
    midpoint['support']='Free'; model['nodes'].append(midpoint)
    first=dict(member,id='A',j='Joint'); second=dict(member,id='B',i='Joint')
    if reverse: second['i'],second['j']=second['j'],second['i']
    if model.get('schema')==2: second['rotation']=rotation
    model['members']=[first,second]
    for load in model.get('distributed_loads',[]):
        raise AssertionError('Use nodal loading in split fixture')
    return model

@pytest.mark.parametrize('reverse,rotation',[(False,0),(True,0),(False,37),(True,37)])
def test_3d_split_reverse_rotated_common_axes_matches_unsplit_solver(reverse,rotation):
    model=cantilever3d(); model['distributed_loads']=[]; model['self_weight']=False; model['combinations']={}
    model['sections'][0]['Iy']=model['sections'][0]['Iz']
    model['point_loads']=[dict(node='N2',direction=direction,value=value,case='DL') for direction,value in [('FX',5),('FY',7),('FZ',-11),('MX',2),('MY',3),('MZ',4)]]
    original=solve(model)['cases']['DL']['members'][model['members'][0]['id']]
    divided=split(model,reverse,rotation); before=copy.deepcopy(divided); members=solve(divided)['cases']['DL']['members']
    for quantity in ('N','Vy','Vz','T','My','Mz','D'):
        data=graph_data(divided,members,'A',quantity); assert len(data['records'])==2 and data['L']==pytest.approx(original['L'])
        for record in data['records']:
            result=members[record['id']]
            for ratio in (.1,.5,.9):
                local_x=ratio*result['L']; s=record['start']+(local_x if record['forward'] else result['L']-local_x)
                assert inspect_chain(result,data['reference'],quantity,local_x)==pytest.approx(evaluate(original,s)[quantity],rel=1e-7,abs=1e-9),(reverse,rotation,quantity,s)
        assert data['extrema']['min']['value']==pytest.approx(original['extrema'][quantity]['min']['value'],rel=1e-7,abs=1e-9)
        assert data['extrema']['max']['value']==pytest.approx(original['extrema'][quantity]['max']['value'],rel=1e-7,abs=1e-9)
    assert divided==before

@pytest.mark.parametrize('reverse',[False,True])
def test_2d_split_common_coordinates_signs_and_exact_extrema(reverse):
    model=benchmark(); model['nodes'][0]['support']='Fixed'; model['nodes'][1]['support']='Free'
    model['distributed_loads']=[]; model['self_weight']=False; model['combinations']={}
    model['point_loads']=[dict(node=model['nodes'][1]['id'],direction='FZ',value=-10,case=model['cases'][0])]
    original=solve(model)['cases'][model['cases'][0]]['members'][model['members'][0]['id']]
    divided=split(model,reverse); members=solve(divided)['cases'][model['cases'][0]]['members']
    for quantity in ('N','V','M','d'):
        data=graph_data(divided,members,'A',quantity)
        for record in data['records']:
            m=members[record['id']]; x=m['L']*.37; s=record['start']+(x if record['forward'] else m['L']-x)
            assert inspect_chain(m,data['reference'],quantity,x)==pytest.approx(evaluate(original,s)[quantity],rel=1e-7,abs=1e-9)
        for kind in ('min','max'): assert data['extrema'][kind]['value']==pytest.approx(original['extrema'][quantity][kind]['value'],rel=1e-7,abs=1e-9)

def test_joint_point_load_keeps_real_shear_jump_and_moment_continuity():
    model=cantilever3d(); model['distributed_loads']=[]; model['point_loads']=[]; model['self_weight']=False; model['combinations']={}
    model=split(model); model['point_loads']=[dict(node='Joint',direction='FZ',value=-10,case='DL')]
    members=solve(model)['cases']['DL']['members']
    shear=graph_data(model,members,'A','Vy'); moment=graph_data(model,members,'A','Mz')
    assert shear['series'][0][-1][0]==pytest.approx(shear['series'][1][0][0])
    assert abs(shear['series'][0][-1][1]-shear['series'][1][0][1])==pytest.approx(10)
    assert moment['series'][0][-1][1]==pytest.approx(moment['series'][1][0][1],abs=1e-9)

def test_overlapping_members_are_not_false_continuous_graph():
    model=cantilever3d(); model['distributed_loads']=[]; model=split(model)
    model['members'].append(dict(model['members'][0],id='Overlap'))
    # Geometry validation is display-only here; no solve of the duplicated model.
    members={mid:dict(basis=[[1,0,0],[0,0,1],[0,-1,0]]) for mid in ('A','B','Overlap')}
    with pytest.raises(ValueError,match='overlapping'): graph_data(model,members,'A','N')
