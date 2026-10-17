import copy
import json
import pytest
from go_structural_analysis.model import benchmark
from go_structural_analysis.model3d import cantilever3d
from go_structural_analysis.worker import solve
from go_structural_analysis.safety import current,state,validate_result
from go_structural_analysis.results import export_csv,export_report,evaluate

@pytest.mark.parametrize('dimension',[2,3])
def test_linear_combination_and_safety(dimension,tmp_path):
    d=benchmark() if dimension==2 else cantilever3d()
    if dimension==2:
        d['cases']=['D','L']; d['distributed_loads'][0]['case']='D'
        d['point_loads']=[dict(member='B1',x=2,direction='FZ',value=-3,case='L')]
    d['combinations']={'A':{d['cases'][0]:1.4,d['cases'][1]:1.7},'B':{d['cases'][0]:-.9,d['cases'][1]:-1}}
    r=solve(d); assert current(d,r) and state(d,r)=='Current'
    for node in r['cases']['A']['nodes']:
        for k,v in r['cases']['A']['nodes'][node].items():
            # D magnitude is nonlinear; Cartesian displacement/forces are linear.
            if k=='D': continue
            expected=1.4*r['cases'][d['cases'][0]]['nodes'][node][k]+1.7*r['cases'][d['cases'][1]]['nodes'][node][k]
            assert v==pytest.approx(expected,abs=1e-8)
    for mid,m in r['cases']['A']['members'].items():
        for end,forces in m['end_forces'].items():
            for k,v in forces.items():
                expected=1.4*r['cases'][d['cases'][0]]['members'][mid]['end_forces'][end][k]+1.7*r['cases'][d['cases'][1]]['members'][mid]['end_forces'][end][k]
                assert v==pytest.approx(expected,abs=1e-8)
    assert set(r['envelope']['combinations'])=={'A','B'}
    d['sections'][0]['A']*=2
    assert state(d,r)=='Stale' and state(d,r,'Running')=='Running' and state(d,r,'Failed')=='Failed'
    with pytest.raises(ValueError,match='out of date'): export_csv(tmp_path,d,r,'A')
    with pytest.raises(ValueError,match='out of date'): export_report(tmp_path/'current.json',d,r)
    paths=export_csv(tmp_path/'archive',d,r,'A',archived=True)
    assert all('Archived/Stale' in open(p,encoding='utf-8-sig').read() for p in paths)
    export_report(tmp_path/'archive.json',d,r,archived=True)
    report=json.loads((tmp_path/'archive.json').read_text())
    assert report['input_model']['sections'][0]['A']!=d['sections'][0]['A']
    assert report['code_compliance']=='Not Available'

@pytest.mark.parametrize('kind',['nonfinite','equilibrium','version'])
def test_unsafe_result_rejected(kind):
    r=solve(benchmark()); first=r['cases']['LC1']
    if kind=='nonfinite': first['nodes']['N1']['ux']=float('nan')
    if kind=='equilibrium': first['equilibrium']['residual'][0]=1e6
    if kind=='version': r['version']='unknown'
    with pytest.raises(ValueError): validate_result(r)

@pytest.mark.parametrize('field',['nodes','members','materials','sections','point_loads','distributed_loads','combinations','solver_settings'])
def test_input_fingerprint_invalidation(field):
    d=cantilever3d(); r=solve(d); changed=copy.deepcopy(d)
    changed[field]=dict(changed.get(field,{}),changed=True) if field in ('combinations','solver_settings') else changed[field]+[{'changed':True}]
    assert not current(changed,r)

def test_legacy_selfweight_new_single_dead_case():
    d=benchmark(); d['cases']=['D','L']; d['distributed_loads']=[]; d.update(self_weight=True,self_weight_case='D',combinations={'U':{'D':1.4,'L':1.7}})
    r=solve(d); assert r['cases']['L']['nodes']['N1']['Rz']==0
    assert r['cases']['U']['nodes']['N1']['Rz']==pytest.approx(1.4*r['cases']['D']['nodes']['N1']['Rz'])

def test_archived_failed_attempt_keeps_valid_snapshot(tmp_path):
    d=benchmark(); r=solve(d); r['safety']['invalidated_by_failure']=True
    assert not current(d,r)
    paths=export_csv(tmp_path,d,r,'LC1',archived=True)
    assert paths and all('Archived/Stale' in open(p,encoding='utf-8-sig').read() for p in paths)
    export_csv(tmp_path,d,r,'LC1',archived=True)

def test_running_api_export_gate(tmp_path):
    d=benchmark(); r=solve(d); r['safety']['running']=True
    assert not current(d,r)
    with pytest.raises(ValueError,match='out of date'): export_report(tmp_path/'current.json',d,r)
    paths=export_csv(tmp_path,d,r,'LC1',archived=True)
    assert paths

@pytest.mark.parametrize('method',['ASD','LRFD'])
def test_code_managed_migration_preserves_cases_weight_and_combinations(method):
    from go_structural_analysis.model3d import migrate2d
    from go_structural_analysis.thai_code import apply_manager
    d=benchmark(); d.update(cases=['DL','LL'],point_loads=[],distributed_loads=[],self_weight=True,self_weight_case='DL')
    d=apply_manager(d,dict(method=method,bindings={'D':['DL'],'L':['LL']},enabled=['TH2566-'+method+'-01'],custom={}))
    old=solve(d); converted=migrate2d(d); new=solve(converted)
    assert set(converted['combinations'])==set(d['combinations'])
    for case in old['cases']:
        for node,row in old['cases'][case]['nodes'].items():
            assert new['cases'][case]['nodes'][node]['uz']==pytest.approx(row['uz'],abs=1e-10)
            assert new['cases'][case]['nodes'][node]['Fz']==pytest.approx(row['Rz'],abs=1e-8)
    converted['self_weight']=True
    with pytest.raises(ValueError,match='already explicit'): solve(converted)
