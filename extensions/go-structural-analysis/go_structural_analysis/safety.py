"""Result provenance and validation. Display controls never enter solver inputs."""
import copy
import hashlib
import json
import math
from datetime import datetime,timezone

STATES=('Current','Stale','Running','Failed','Not Analyzed')
SAFETY_VERSION=1

def fingerprint(model):
    return hashlib.sha256(json.dumps(model,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def validate_result(result):
    def finite(value):
        if isinstance(value,float) and not math.isfinite(value): raise ValueError('Non-finite solver result')
        if isinstance(value,dict):
            for v in value.values(): finite(v)
        elif isinstance(value,list):
            for v in value: finite(v)
    finite(result)
    if result.get('version')!='3.2.0' or not result.get('cases'): raise ValueError('Invalid solver version or empty results')
    for case,row in result['cases'].items():
        b=row.get('equilibrium',{})
        if not b.get('passed') or not b.get('residual') or len(b['residual'])!=len(b.get('tolerance',[])):
            raise ValueError('Missing/failed global equilibrium: '+case)
        if not all(abs(v)<=t and t>0 for v,t in zip(b['residual'],b['tolerance'])): raise ValueError('Global equilibrium residual exceeds tolerance: '+case)
        if not row.get('nodes') or not row.get('members'): raise ValueError('Empty node/member results')
    return result

def seal(model,result):
    validate_result(result)
    result['model_hash']=fingerprint(model)
    result['input_fingerprint']=result['model_hash']; result['input_model']=copy.deepcopy(model)
    result['safety']=dict(version=SAFETY_VERSION,validated=True,created_utc=datetime.now(timezone.utc).isoformat(),capacity='Not Available',code_compliance='Not Available',serviceability='Not Available')
    return result

def current(model,result):
    try:
        return bool(model and result and result.get('model_hash')==fingerprint(model)
            and result.get('input_fingerprint')==result['model_hash']
            and result.get('result_schema')==(3 if model.get('schema')==2 else 2)
            and result.get('safety',{}).get('version')==SAFETY_VERSION
            and not result.get('safety',{}).get('invalidated_by_failure')
            and not result.get('safety',{}).get('running')
            and result['safety'].get('validated'))
    except (ValueError,KeyError,TypeError): return False

def state(model,result,job=None):
    if job=='Running': return 'Running'
    if job=='Failed': return 'Failed'
    if current(model,result): return 'Current'
    return 'Stale' if result else 'Not Analyzed'

def ensure_exportable(model,result,archived=False):
    if not result: raise ValueError('Not Analyzed: no results to export')
    validate_result(result)
    if not current(model,result) and not archived: raise ValueError('Results out of date; Run Analysis before exporting current results')
    if archived and not result.get('input_model'): raise ValueError('Archived export requires the original input snapshot')
    return copy.deepcopy(result['input_model']) if archived else model

def envelope_groups(result,model):
    cases=result['cases']; groups={}
    for name in model.get('combinations',{}):
        info=model.get('combination_metadata',{}).get(name,{})
        groups.setdefault(info.get('method','Custom'),[]).append(name)
    if not groups: groups['Base cases']=list(model['cases'])
    def build(names):
        out=dict(combinations=names,members={},nodes={})
        first=cases[names[0]]
        for mid,m in first['members'].items():
            out['members'][mid]={}
            for key in m['extrema']:
                values=[dict(v,combination=name) for name in names for v in cases[name]['members'][mid]['extrema'][key].values()]
                out['members'][mid][key]={'min':min(values,key=lambda v:v['value']),'max':max(values,key=lambda v:v['value'])}
        for node,row in first['nodes'].items():
            out['nodes'][node]={}
            for key in row:
                values=[dict(value=cases[name]['nodes'][node][key],combination=name) for name in names]
                out['nodes'][node][key]={'min':min(values,key=lambda v:v['value']),'max':max(values,key=lambda v:v['value'])}
        return out
    result['envelope_groups']={group:build(names) for group,names in groups.items()}
    result['envelope']=build([name for names in groups.values() for name in names])
    result['envelope']['group']=' / '.join(groups)
    return result
