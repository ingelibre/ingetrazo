"""Auditable load factors only. No seismic action generation or capacity design."""
import copy
import itertools
import math

PACK={
    'id':'TH-BUILDING-2566','version':'1.0.0','title':'Thailand 2566',
    'source_url':'https://ratchakitcha.soc.go.th/documents/140A054N0000000000400.pdf',
    'publication':'2023-09-06','volume':140,'part':'54 ก','pages':[7,8],
    'source_sha256':'488f6315e12d1ca1913f72960f76a9ef9422619ceaf784df4564351ba70704c9',
    'scope':'Load combination factors, clauses 6 and 7 only',
    'capacity_compliance':'Not Available','earthquake_generation':'Not Available',
}
ACTIONS={
    'D':'Dead load including the configured self-weight',
    'L':'Live load including impact where applicable',
    'W':'Wind action','E':'Earthquake action from a separately verified model',
    'H':'Lateral earth or water pressure','F':'Liquid pressure',
    'T':'Temperature, shrinkage, creep or settlement action',
}
# Formula strings retain original grouping; factors are expanded for the solver.
_ROWS=[
 ('ASD','6(1)','D + L',{'D':1.,'L':1.}),
 ('ASD','6(2)','D + 0.75(L + W)',{'D':1.,'L':.75,'W':.75}),
 ('ASD','6(2)','0.6D + W',{'D':.6,'W':1.}),
 ('ASD','6(3)','D + 0.7E',{'D':1.,'E':.7}),
 ('ASD','6(3)','D + 0.525E + 0.75L',{'D':1.,'E':.525,'L':.75}),
 ('ASD','6(3)','0.6D + 0.7E',{'D':.6,'E':.7}),
 ('ASD','6(4)','D + L + H + F + T',{'D':1.,'L':1.,'H':1.,'F':1.,'T':1.}),
 ('LRFD','7(1)','1.4D + 1.7L',{'D':1.4,'L':1.7}),
 ('LRFD','7(2)','0.75(1.4D + 1.7L) + 1.6W',{'D':1.05,'L':1.275,'W':1.6}),
 ('LRFD','7(2)','0.9D + 1.6W',{'D':.9,'W':1.6}),
 ('LRFD','7(3)','0.75(1.4D + 1.7L) + 1.0E',{'D':1.05,'L':1.275,'E':1.}),
 ('LRFD','7(3)','0.9D + 1.0E',{'D':.9,'E':1.}),
 ('LRFD','7(4)','1.4D + 1.7L + 1.7H',{'D':1.4,'L':1.7,'H':1.7}),
 ('LRFD','7(4)','0.9D + 1.7H',{'D':.9,'H':1.7}),
 ('LRFD','7(4)','1.4D + 1.7L + 1.4F',{'D':1.4,'L':1.7,'F':1.4}),
 ('LRFD','7(4)','0.9D + 1.4F',{'D':.9,'F':1.4}),
 ('LRFD','7(5)','0.75(1.4D + 1.4T + 1.7L)',{'D':1.05,'T':1.05,'L':1.275}),
 ('LRFD','7(5)','1.4D + 1.4T',{'D':1.4,'T':1.4}),
]

def presets(method=None):
    counts={}; rows=[]
    for m,clause,formula,factors in _ROWS:
        counts[m]=counts.get(m,0)+1
        if method is None or method==m:
            rows.append(dict(id=f'TH2566-{m}-{counts[m]:02d}',method=m,clause=clause,
                formula=formula,factors=copy.deepcopy(factors),code_pack=copy.deepcopy(PACK),
                origin='Original statutory formula',editable=False))
    return rows

def assess(preset,model,config):
    warnings=[]; bindings=config.get('bindings',{}); cases=model['cases']; owners={}
    for action in preset['factors']:
        bound=bindings.get(action,[])
        if not isinstance(bound,list) or not bound: warnings.append('Missing Input: '+action); continue
        if len(bound)!=len(set(bound)): warnings.append('Duplicate binding: '+action)
        for case in bound:
            if case not in cases: warnings.append('Missing load case: '+str(case))
            if case in owners and owners[case]!=action: warnings.append('Load case assigned to multiple actions: '+case)
            owners[case]=action
        if action in ('H','F','T'):
            info=config.get('action_verification',{}).get(action,{})
            if not info.get('equivalent_force_model') or not str(info.get('reference','')).strip():
                warnings.append('Disabled: '+action+' requires a reviewed equivalent-force model and reference')
        if action=='E':
            info=config.get('action_verification',{}).get('E',{})
            if not info.get('verified_action') or not str(info.get('reference','')).strip():
                warnings.append('Disabled: earthquake action must be verified separately; combinations do not generate it')
    if model.get('self_weight'):
        sw=model.get('self_weight_case')
        if sw not in bindings.get('D',[]): warnings.append('Self-weight must be assigned once to a bound D case')
        if any(p.get('source')=='self_weight' for name in ('point_loads','distributed_loads') for p in model.get(name,[])):
            warnings.append('Self-weight duplication: explicit self_weight load with automatic self-weight')
    return warnings

def derive(preset,model,config):
    warnings=assess(preset,model,config)
    if warnings: return [],warnings
    bindings=config['bindings']; alternatives=[a for a in preset['factors'] if a in ('W','E')]
    choices=itertools.product(*(bindings[a] for a in alternatives)) if alternatives else [()]
    rows=[]
    for chosen in choices:
        directional=dict(zip(alternatives,chosen)); factors={}
        for action,factor in preset['factors'].items():
            for case in ([directional[action]] if action in directional else bindings[action]):
                factors[case]=factors.get(case,0.)+factor
        name=preset['id']+(' / '+','.join(chosen) if chosen else '')
        rows.append(dict(name=name,factors=factors,method=preset['method'],group=preset['method'],
            preset_id=preset['id'],clause=preset['clause'],formula=preset['formula'],
            origin='Derived directional combination' if chosen else 'Bound statutory formula',
            directions=directional,pack_version=PACK['version'],source_url=PACK['source_url']))
    return rows,[]

def compile_manager(model,config):
    method=config.get('method','Custom')
    if method not in ('ASD','LRFD','Custom'): raise ValueError('Select ASD, LRFD or Custom')
    if config.get('pack_version',PACK['version'])!=PACK['version']: raise ValueError('Unsupported Thai Code Pack version')
    methods=config.get('methods',[method] if method!='Custom' else [])
    if not isinstance(methods,list) or any(m not in ('ASD','LRFD') for m in methods) or len(methods)!=len(set(methods)): raise ValueError('Invalid design methods')
    available={r['id']:r for r in presets() if r['method'] in methods}; combinations={}; metadata={}
    enabled=config.get('enabled',[])
    if not isinstance(enabled,list) or len(enabled)!=len(set(enabled)): raise ValueError('Invalid enabled presets')
    for identifier in enabled:
        if identifier not in available: raise ValueError('Preset does not belong to selected design method: '+identifier)
        rows,warnings=derive(available[identifier],model,config)
        if warnings: raise ValueError(identifier+': '+'; '.join(warnings))
        for row in rows: combinations[row['name']]=row['factors']; metadata[row['name']]=row
    for name,row in config.get('custom',{}).items():
        if not row.get('enabled',True): continue
        factors=row.get('factors',{})
        if not name or name in model['cases'] or name.startswith('TH2566-') or not factors: raise ValueError('Invalid Custom name/factors')
        for case,factor in factors.items():
            if case not in model['cases'] or isinstance(factor,bool) or not isinstance(factor,(float,int)) or not math.isfinite(factor): raise ValueError('Invalid Custom load reference/factor')
        combinations[name]=copy.deepcopy(factors)
        metadata[name]=dict(method='Custom',group='Custom',origin='Custom',cloned_from=row.get('cloned_from'),factors=copy.deepcopy(factors))
    return combinations,metadata

def apply_manager(model,config):
    out=copy.deepcopy(model); config=copy.deepcopy(config); config['pack_version']=PACK['version']
    out['combinations'],out['combination_metadata']=compile_manager(out,config)
    out['combination_manager']=config
    return out

def validate_combinations(model):
    settings=model.get('solver_settings',{})
    if settings and settings!={'analysis':'linear','solver_version':'3.2.0'}: raise ValueError('Unsupported solver settings; use linear PyNiteFEA 3.2.0')
    if model.get('self_weight_case') and model['self_weight_case'] not in model['cases']: raise ValueError('Invalid self-weight case')
    if model.get('self_weight') and any(p.get('source')=='self_weight' for field in ('point_loads','distributed_loads') for p in model.get(field,[])): raise ValueError('Self-weight already explicit; disable automatic self-weight')
    cases=model['cases']; combos=model.get('combinations',{})
    if not isinstance(combos,dict): raise ValueError('Combinations must be a mapping')
    for name,factors in combos.items():
        if not isinstance(name,str) or not name.strip() or name in cases or not isinstance(factors,dict) or not factors: raise ValueError('Invalid combination name/factors')
        for case,factor in factors.items():
            if case not in cases or isinstance(factor,bool) or not isinstance(factor,(float,int)) or not math.isfinite(factor): raise ValueError('Invalid combination load reference/factor')
    if 'combination_manager' in model:
        expected,metadata=compile_manager(model,model['combination_manager'])
        if expected!=combos or metadata!=model.get('combination_metadata'): raise ValueError('Protected preset changed; Clone as Custom to edit')

def clone_custom(preset,name,factors):
    if name.startswith('TH2566-'): raise ValueError('Choose a Custom name outside the protected namespace')
    return dict(factors=copy.deepcopy(factors),cloned_from=preset['id'],method='Custom')
