import contextlib
import copy
import csv
import io
import json
import math
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'go_structural_analysis'))
from model import benchmark,validate,ModelError
from worker import solve
from results import evaluate,model_hash,is_current,export_csv,pick_member
from reference_frame import reference,uniform_beam_displacement

CHECKS=[]

def test_axial_distributed_load():
    d=benchmark(); d['nodes'][0]['support']='Fixed'; d['nodes'][1]['support']='Free'
    d['distributed_loads'][0].update(direction='FX',w1=3.,w2=3.)
    r=run(d)['cases']['LC1']; m=r['members']['B1']; EA=d['materials'][0]['E']*d['sections'][0]['A']
    check('axial UDL reaction',r['nodes']['N1']['Rx'],-18.)
    check('axial UDL tip displacement',r['nodes']['N2']['ux'],54./EA)
    check('axial UDL N at x=1.37',evaluate(m,1.37)['N'],-18.+3.*1.37)
    check('axial UDL exact minimum',m['extrema']['N']['min']['value'],-18.)

def test_member_moment_jump():
    d=benchmark(); d['distributed_loads']=[]
    d['point_loads']=[{'member':'B1','direction':'MY','value':10.,'x':2.,'case':'LC1'}]
    r=run(d)['cases']['LC1']; m=r['members']['B1']
    check('member moment left reaction',r['nodes']['N1']['Rz'],10./6.)
    check('member moment right reaction',r['nodes']['N2']['Rz'],-10./6.)
    check('member moment jump',evaluate(m,2.,'right')['M']-evaluate(m,2.,'left')['M'],10.)
    check('member moment exact maximum',m['extrema']['M']['max']['value'],20./3.)
    check('member moment maximum position',m['extrema']['M']['max']['x'],2.)

def test_nodal_moment_at_released_rotation():
    d=benchmark(); d['members'][0]['release_j']=True
    d['point_loads']=[{'node':'N2','direction':'MY','value':10.,'case':'LC1'}]
    with pytest.raises(ModelError,match='cannot be transmitted'): validate(d)

def test_inspector_invalid_side():
    m=run(benchmark())['cases']['LC1']['members']['B1']
    with pytest.raises(ValueError,match='side'): evaluate(m,3.,'invalid')

def test_truss_selfweight_lumped_at_joints():
    d=benchmark(); d['self_weight']=True; d['distributed_loads']=[]
    d['nodes'].append({'id':'N3','x':3.,'z':3.,'support':'Free'})
    base=dict(d['members'][0],type='Truss')
    d['members']=[base,dict(base,id='T2',i='N1',j='N3'),dict(base,id='T3',i='N3',j='N2')]
    d['point_loads']=[{'node':'N3','direction':'FZ','value':-10.,'case':'LC1'}]
    r=run(d)['cases']['LC1']; density=d['materials'][0]['rho']*d['sections'][0]['A']; diagonal=math.sqrt(18.)
    check('truss SW reaction',r['nodes']['N1']['Rz'],5.+density*(6.+2.*diagonal)/2.)
    check('truss SW diagonal N',evaluate(r['members']['T2'],diagonal/2.)['N'],(10.+density*diagonal)/math.sqrt(2.))
    for mid,m in r['members'].items():
        check('truss SW '+mid+' moment',max(abs(v['value']) for v in m['extrema']['M'].values()),0.)
@pytest.fixture(scope='module',autouse=True)
def save_checks():
    yield
    root=Path(__file__).parents[1]/'artifacts'/'v0.1.3'; root.mkdir(parents=True,exist_ok=True)
    (root/'engineering-checks.json').write_text(json.dumps(CHECKS,indent=2),encoding='utf-8')

def check(name,actual,expected,rel=1e-7,abs_tol=1e-8):
    tolerance=max(abs_tol,rel*abs(expected)); passed=abs(actual-expected)<=tolerance
    CHECKS.append({'name':name,'actual':float(actual),'reference':float(expected),'absolute_error':float(abs(actual-expected)),'tolerance':float(tolerance),'status':'Passed' if passed else 'Failed'})
    assert passed,f'{name}: {actual} vs {expected}, tolerance {tolerance}'

def run(d):
    with contextlib.redirect_stdout(io.StringIO()): r=solve(d)
    for c,v in r['cases'].items():
        for i,k in enumerate(['FX','FZ','M_plane']): check(c+' equilibrium '+k,v['equilibrium']['residual'][i],0,abs_tol=v['equilibrium']['tolerance'][i])
    return r

@pytest.mark.parametrize('load',['UDL','Point'])
def test_simple(load):
    d=benchmark()
    if load=='Point': d['distributed_loads']=[]; d['point_loads']=[{'node':'N2','direction':'FX','value':0,'case':'LC1'},{'member':'B1','direction':'FZ','value':20,'x':3,'case':'LC1'}]
    r=run(d)['cases']['LC1']; m=r['members']['B1']; EI=200000000*8e-5
    check(load+' left reaction',r['nodes']['N1']['Rz'],30 if load=='UDL' else -10)
    check(load+' moment',max(abs(v['value']) for v in m['extrema']['M'].values()),45 if load=='UDL' else 30)
    check(load+' deflection',evaluate(m,3)['d'],-5*10*6**4/(384*EI) if load=='UDL' else 20*6**3/(48*EI))

@pytest.mark.parametrize('load',['UDL','Point'])
def test_cantilever(load):
    d=benchmark(); d['nodes'][0]['support']='Fixed'; d['nodes'][1]['support']='Free'
    if load=='Point': d['distributed_loads']=[]; d['point_loads']=[{'node':'N2','direction':'FZ','value':-10,'case':'LC1'}]
    r=run(d)['cases']['LC1']; EI=200000000*8e-5
    check('cantilever '+load+' reaction',r['nodes']['N1']['Rz'],60 if load=='UDL' else 10)
    check('cantilever '+load+' end moment',r['nodes']['N1']['My'],180 if load=='UDL' else 60)
    check('cantilever '+load+' deflection',r['nodes']['N2']['uz'],-10*6**4/(8*EI) if load=='UDL' else -10*6**3/(3*EI))

def continuous(spans):
    d=benchmark(); d['nodes']=[{'id':f'N{i}','x':i*6.,'z':0.,'support':'Pin' if i==0 else 'Roller'} for i in range(spans+1)]
    d['members']=[dict(d['members'][0],id=f'B{i}',i=f'N{i}',j=f'N{i+1}') for i in range(spans)]
    d['distributed_loads']=[{'member':f'B{i}','direction':'FZ','w1':-10.,'w2':-10.,'case':'LC1'} for i in range(spans)]
    return d

@pytest.mark.parametrize('spans',[2,3])
def test_continuous(spans):
    d=continuous(spans); r=run(d)['cases']['LC1']; ref=reference(d)
    expected=[22.5,75,22.5] if spans==2 else [24,66,66,24]
    for i,value in enumerate(expected): check(f'{spans} spans R{i}',r['nodes'][f'N{i}']['Rz'],value)
    check(f'{spans} spans interior hogging',evaluate(r['members']['B0'],6)['M'],45 if spans==2 else 36)
    for mid,m in r['members'].items(): check(f'{spans} spans {mid} mid deflection',evaluate(m,3)['d'],uniform_beam_displacement(d,mid,3,ref))

def portal():
    d=benchmark(); d['nodes']=[{'id':'A','x':0.,'z':0.,'support':'Fixed'},{'id':'B','x':0.,'z':4.,'support':'Free'},{'id':'C','x':6.,'z':4.,'support':'Free'},{'id':'D','x':6.,'z':0.,'support':'Fixed'}]
    d['members']=[dict(d['members'][0],id=mid,i=a,j=b,type='Frame') for mid,a,b in [('AB','A','B'),('BC','B','C'),('CD','C','D')]]; d['distributed_loads']=[]
    return d

@pytest.mark.parametrize('direction',['FX','FZ'])
def test_portal(direction):
    d=portal()
    if direction=='FX': d['point_loads']=[{'node':'B','direction':'FX','value':10,'case':'LC1'}]
    else: d['distributed_loads']=[{'member':'BC','direction':'FZ','w1':-10,'w2':-10,'case':'LC1'}]
    r=run(d)['cases']['LC1']; ref,_,_=reference(d)
    for n,v in ref.items():
        for k in ['ux','uz','rotation','Rx','Rz','My']: check(f'portal {direction} {n} {k}',r['nodes'][n][k],v[k])

def test_inclined():
    d=benchmark(); d['nodes'][0]['support']='Fixed'; d['nodes'][1].update(x=-6,z=4,support='Free'); d['distributed_loads']=[]
    d['point_loads']=[{'node':'N2','direction':'FX','value':7,'case':'LC1'},{'node':'N2','direction':'FZ','value':-10,'case':'LC1'}]
    r=run(d)['cases']['LC1']; ref,_,_=reference(d)
    for n,v in ref.items():
        for k in ['ux','uz','rotation','Rx','Rz','My']: check('inclined '+n+' '+k,r['nodes'][n][k],v[k])
    p=evaluate(r['members']['B1'],r['members']['B1']['L'])
    for k in ['ux','uz']: check('inclined transformed '+k,p[k],ref['N2'][k])

def test_truss_axial():
    d=benchmark(); d['nodes'].append({'id':'N3','x':3.,'z':3.,'support':'Free'}); d['distributed_loads']=[]; d['members'][0]['type']='Truss'
    d['members']+=[dict(d['members'][0],id='T2',i='N1',j='N3'),dict(d['members'][0],id='T3',i='N3',j='N2')]
    d['point_loads']=[{'node':'N3','direction':'FZ','value':-10,'case':'LC1'}]; r=run(d)['cases']['LC1']
    for mid,expected in [('B1',-5),('T2',10/math.sqrt(2)),('T3',10/math.sqrt(2))]:
        check('truss '+mid+' axial',evaluate(r['members'][mid],1)['N'],expected)
        check('truss '+mid+' end M',r['members'][mid]['end_forces']['i']['M'],0)

@pytest.mark.parametrize('both',[False,True])
def test_releases(both):
    d=benchmark(); d['nodes'][0]['support']='Fixed'; d['nodes'][1]['support']='Fixed'; d['members'][0]['release_j']=True
    if both: d['members'][0]['release_i']=True
    r=run(d)['cases']['LC1']; m=r['members']['B1']
    check('release j end moment',m['end_forces']['j']['M'],0)
    check('released beam left reaction',r['nodes']['N1']['Rz'],30 if both else 37.5)
    check('released beam right reaction',r['nodes']['N2']['Rz'],30 if both else 22.5)
    if both: check('both released midpoint D',evaluate(m,3)['d'],-5*10*6**4/(384*200000000*8e-5))

@pytest.mark.parametrize('loaded',[False,True])
def test_release_instability(loaded):
    d=benchmark(); d['nodes'][0]['support']='Fixed'; d['nodes'][1]['support']='Free'; d['members'][0].update(release_i=True,release_j=True)
    if not loaded: d['distributed_loads']=[]
    # Exercise the solver directly: never swallow a failed reference assertion.
    with pytest.raises(RuntimeError,match='singular|unstable'): solve(d)

@pytest.mark.parametrize('weight',[False,True])
def test_weight_and_cases(weight):
    d=benchmark(); d['self_weight']=weight; d['cases']=['LC1','LC2']; d['point_loads']=[{'node':'N1','direction':'FZ','value':-5,'case':'LC2'}]
    r=run(d)['cases']; extra=76.98*.01*6 if weight else 0
    check('LC1 selfweight '+str(weight),sum(n['Rz'] for n in r['LC1']['nodes'].values()),60+extra)
    check('LC2 selfweight '+str(weight),sum(n['Rz'] for n in r['LC2']['nodes'].values()),5+extra)

def test_off_grid_extrema_and_jumps():
    d=benchmark(); d['distributed_loads']=[]; a=1.37; P=20.; L=6.; EI=200000000*8e-5
    d['point_loads']=[{'member':'B1','direction':'FZ','value':-P,'x':a,'case':'LC1'}]; m=run(d)['cases']['LC1']['members']['B1']
    t=math.sqrt((L*L-a*a)/3); x=L-t; deflection=-P*a*t*(L*L-a*a-t*t)/(6*L*EI)
    check('off-grid M',m['extrema']['M']['min']['value'],-P*a*(L-a)/L)
    check('off-grid M location',m['extrema']['M']['min']['x'],a)
    check('off-grid D location',m['extrema']['d']['min']['x'],x)
    check('off-grid D',m['extrema']['d']['min']['value'],deflection)
    check('shear jump right-left',evaluate(m,a,'right')['V']-evaluate(m,a,'left')['V'],-P)

def test_triangular_udl():
    d=benchmark(); d['distributed_loads'][0]['w1']=0; r=run(d)['cases']['LC1']; m=r['members']['B1']
    check('triangular left R',r['nodes']['N1']['Rz'],10)
    check('triangular right R',r['nodes']['N2']['Rz'],20)
    check('triangular M location',m['extrema']['M']['min']['x'],6/math.sqrt(3))
    check('triangular M magnitude',abs(m['extrema']['M']['min']['value']),10*6**2/(9*math.sqrt(3)))

def test_exact_inspection_csv_and_stale(tmp_path):
    d=benchmark(); r=run(d); assert is_current(d,r)
    m=r['cases']['LC1']['members']['B1']; x=2.345
    expected=-10*x*(6**3-2*6*x*x+x**3)/(24*200000000*8e-5)
    check('inspector arbitrary x',evaluate(m,x)['d'],expected)
    paths=export_csv(tmp_path,d,r,'LC1'); assert len(paths)==5
    with open(paths[0],encoding='utf-8-sig') as f: rows=list(csv.reader(f))
    assert rows[0]==['Case','Node','UX [m]','UZ [m]','Rotation [rad]']
    d['distributed_loads'][0]['w1']=-9; assert not is_current(d,r)
    with pytest.raises(ValueError,match='out of date'): export_csv(tmp_path,d,r,'LC1')
    with pytest.raises(ValueError): evaluate(m,7)

def test_hit_selection_pan_zoom():
    projected=[('B1',(100,200),(700,200))]
    assert pick_member(400,203,projected)==('B1',.5)
    assert pick_member(880,410,[('B1',(280,410),(1480,410))])==('B1',.5)
    assert pick_member(400,230,projected) is None

def test_release_validation_and_old_result():
    d=benchmark(); d['members'][0]['release_i']='yes'
    with pytest.raises(ModelError): validate(d)
    assert not is_current(benchmark(),{'cases':{}})
