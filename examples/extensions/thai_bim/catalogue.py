"""Portable member types: immutable placement snapshots, not shared geometry."""
import copy,json,os,tempfile,uuid
from pathlib import Path
from . import engine as E,structures as S

KINDS=('Footing','Column','Beam','Slab','Stair')
FIELDS={k:('width','depth','height') for k in KINDS[:4]}
FIELDS['Stair']=('width','height','going','risers','waist')
DEFAULTS={'Footing':dict(width=1.2,depth=1.2,height=.4),'Column':dict(width=.25,depth=.25,height=3),
          'Beam':dict(width=3,depth=.2,height=.4),'Slab':dict(width=4,depth=3,height=.15),
          'Stair':dict(width=1,height=3,going=.28,risers=18,waist=.15)}

def member_type(kind,code,name,params,uid=None,revision=1,rebar=None):
    if kind not in KINDS:raise ValueError('Unsupported member kind')
    code=str(code).strip();name=str(name).strip()
    if not code or len(code)>30 or not name or len(name)>80:raise ValueError('Code 1–30; name 1–80 characters')
    if set(params)!=set(FIELDS[kind]):raise ValueError('Type parameters must match the member kind')
    p={k:E.finite(v) for k,v in params.items()}
    if kind=='Stair':S.stair_spec(**p);p['risers']=int(p['risers'])
    else:E.box_spec(kind,0,0,0,**p)
    identity=str(uid or uuid.uuid4());uuid.UUID(identity)
    if isinstance(revision,bool) or int(revision)!=revision or revision<1:raise ValueError('Invalid type revision')
    if rebar is not None:
        from .rebar_recipe import validate as recipe_validate
        rebar=recipe_validate(kind,rebar)
    return dict(id=identity,kind=kind,code=code,name=name,revision=int(revision),params=p,rebar=copy.deepcopy(rebar))

def validate(data):
    if not isinstance(data,dict) or data.get('schema')!=1 or not isinstance(data.get('types'),list):raise ValueError('Invalid type library schema')
    if len(data['types'])>2000:raise ValueError('Library limited to 2000 types')
    rows=[member_type(r['kind'],r['code'],r['name'],r['params'],r['id'],r['revision'],r.get('rebar')) for r in data['types']]
    if len({r['id'] for r in rows})!=len(rows) or len({(r['kind'],r['code'].casefold()) for r in rows})!=len(rows):raise ValueError('Duplicate type ID or code within kind')
    return dict(schema=1,types=rows)

def defaults():
    return dict(schema=1,types=[member_type(k,c,k+' '+c,DEFAULTS[k],str(uuid.uuid5(uuid.NAMESPACE_URL,'thai-bim/type/'+k)))
        for k,c in zip(KINDS,('F1','C1','B1','S1','ST1'))])

def upsert(data,row):
    data=validate(data);old=next((r for r in data['types'] if r['id']==row['id']),None)
    if old and old['kind']!=row['kind']:raise ValueError('Type kind is immutable; create a new type')
    result=copy.deepcopy(data);result['types']=[r for r in result['types'] if r['id']!=row['id']]+[copy.deepcopy(row)]
    return validate(result)

def read(path):
    path=Path(path)
    if path.stat().st_size>4_000_000:raise ValueError('Type library file too large')
    return validate(json.loads(path.read_text(encoding='utf-8-sig')))

def write(path,data):
    data=validate(data);path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    handle,temp=tempfile.mkstemp(prefix='tbim-types-',suffix='.json',dir=path.parent)
    try:
        with os.fdopen(handle,'w',encoding='utf-8') as stream:json.dump(data,stream,ensure_ascii=False,indent=2)
        os.replace(temp,path)
    finally:
        if Path(temp).exists():Path(temp).unlink()

def snapshot(row):return copy.deepcopy(member_type(row['kind'],row['code'],row['name'],row['params'],row['id'],row['revision'],row.get('rebar')))
