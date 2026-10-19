"""Portable schema-2 RC stair types; immutable snapshots, no instance propagation."""
import copy,json,os,tempfile,uuid
from pathlib import Path
from . import stairs as S

def stair_type(code,name,params,rebar,uid=None,revision=1):
    code=str(code).strip();name=str(name).strip()
    if not 1<=len(code)<=30 or not 1<=len(name)<=80:raise ValueError('Code 1–30; name 1–80 characters')
    if type(revision) is not int or revision<1:raise ValueError('Invalid stair type revision')
    if not isinstance(params,dict) or set(params)!=set(S.defaults()):raise ValueError('Stair type requires complete schema 2 geometry')
    if any(type(params[k]) is not bool for k in ('bottom_landing','top_landing')):raise ValueError('Landing switches must be boolean')
    if any(isinstance(v,bool) for k,v in params.items() if k not in ('bottom_landing','top_landing')):raise ValueError('Numeric geometry cannot be boolean')
    p=S.validated(copy.deepcopy(params))
    if not isinstance(rebar,dict) or set(rebar)!=set(S.rebar_defaults()):raise ValueError('Stair type requires complete reinforcement settings')
    q=json.loads(json.dumps(rebar,allow_nan=False));rep=q['representation']
    if rep not in ('Centreline','Lightweight','Full'):raise ValueError('Invalid representation')
    if type(q['mats']) is not int:raise ValueError('Mat count must be integer')
    for k in ('cover','diameter','distribution_diameter','spacing','distribution_spacing','inside_radius','connection'):
        if isinstance(q[k],bool):raise ValueError('Numeric reinforcement cannot be boolean')
        q[k]=float(q[k])
    if not isinstance(q['extra_connections'],list):raise ValueError('Connection patterns must be a list')
    for r in q['extra_connections']:
        if not isinstance(r,dict) or set(r)!=set(('name','x','y','z','angle','length','leg','count','spacing')):raise ValueError('Invalid connection fields')
        if not isinstance(r['name'],str) or not r['name'].strip() or len(r['name'])>80:raise ValueError('Connection name 1–80 characters')
        if any(isinstance(v,bool) for k,v in r.items() if k!='name'):raise ValueError('Numeric connection cannot be boolean')
    # Validate actual geometric fit without expensive tubular visualization.
    S.reinforcement(p,dict(q,representation='Centreline'))
    identity=str(uuid.UUID(str(uid or uuid.uuid4())))
    return dict(id=identity,kind='AdvancedRCStair',code=code,name=name,revision=revision,params=p,rebar=copy.deepcopy(q))

def snapshot(row):
    if not isinstance(row,dict) or set(row)!=set(('id','kind','code','name','revision','params','rebar')) or row['kind']!='AdvancedRCStair':raise ValueError('Invalid advanced stair type')
    return stair_type(row['code'],row['name'],row['params'],row['rebar'],row['id'],row['revision'])

def validate(data):
    if not isinstance(data,dict) or set(data)!=set(('schema','types')) or type(data['schema']) is not int or data['schema']!=1 or not isinstance(data['types'],list):raise ValueError('Invalid advanced stair library schema')
    if len(data['types'])>500:raise ValueError('Stair library limited to 500 types')
    rows=[snapshot(r) for r in data['types']]
    if len({r['id'] for r in rows})!=len(rows) or len({r['code'].casefold() for r in rows})!=len(rows):raise ValueError('Duplicate stair type ID or code')
    return dict(schema=1,types=rows)

def defaults():
    rows=[]
    for i,layout in enumerate(S.LAYOUTS,1):
        p=S.defaults();p['layout']=layout;q=S.rebar_defaults()
        if layout in ('Spiral','Circular'):q['connection']=0
        if layout=='Circular':p.update(inner_radius=1.5,sweep=180)
        rows.append(stair_type('ST-'+str(i).zfill(2),layout+' RC example',p,q,str(uuid.uuid5(uuid.NAMESPACE_URL,'thai-bim/advanced-stair/'+layout))))
    return dict(schema=1,types=rows)

def upsert(data,row):
    data=validate(data);row=snapshot(row);old=next((r for r in data['types'] if r['id']==row['id']),None)
    if old and row['revision']!=old['revision']+1:raise ValueError('Revision must advance once; read current saved type')
    if not old and row['revision']!=1:raise ValueError('New type starts at revision 1')
    return validate(dict(schema=1,types=[r for r in data['types'] if r['id']!=row['id']]+[row]))

def read(path):
    p=Path(path)
    if p.stat().st_size>4_000_000:raise ValueError('Stair library file too large')
    return validate(json.loads(p.read_text(encoding='utf-8-sig')))

def write(path,data):
    data=validate(data);p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    handle,temp=tempfile.mkstemp(prefix='tbim-stairs-',suffix='.json',dir=p.parent)
    try:
        with os.fdopen(handle,'w',encoding='utf-8') as stream:json.dump(data,stream,ensure_ascii=False,indent=2,allow_nan=False)
        os.replace(temp,p)
    finally:
        if Path(temp).exists():Path(temp).unlink()
