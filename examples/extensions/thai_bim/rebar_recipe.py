"""Portable user detailing, in UI millimetres; fitting requires actual Host review."""
import copy,hashlib,json
from . import engine as E,steel as C

RANGES={'cover':(15,150),'diameter':(4,60),'tie_diameter':(4,60),'spacing':(40,1000),
        'count_x':(2,30),'count_y':(2,30),'layers':(1,2),'inside_radius':(2,250),
        'tie_inside_radius':(2,250),'hook_length':(0,1000),'tie_hook_length':(10,500),
        'lap_length':(0,3000),'extension_start':(0,3000),'extension_end':(0,3000),
        'density':(1000,20000),'hook_ends':(1,2)}
INTEGERS=('count_x','count_y','layers','hook_ends')

def defaults():
    return dict(cover=40.,diameter=12.,tie_diameter=6.,spacing=150.,count_x=3,count_y=3,layers=1,
        inside_radius=24.,tie_inside_radius=12.,hook_length=0.,tie_hook_length=40.,lap_length=0.,
        extension_start=0.,extension_end=0.,density=7850.,hook_ends=2,representation='Lightweight',
        main_steel=C.selection(C.TIS_DB,'DB12','SD40'),tie_steel=C.selection(C.TIS_RB,'RB6','SR24'))

def validate(kind,recipe):
    if kind not in ('Footing','Column','Beam','Slab','Stair'):raise ValueError('Unsupported recipe host kind')
    if not isinstance(recipe,dict) or set(recipe)!=set(defaults()):raise ValueError('Incomplete or unknown reinforcement recipe fields')
    p=copy.deepcopy(recipe)
    for key,(lo,hi) in RANGES.items():
        value=p[key]
        if isinstance(value,bool):raise ValueError('Recipe numeric values cannot be boolean')
        value=E.finite(value)
        if not lo<=value<=hi:raise ValueError('Recipe '+key+' outside supported range')
        if key in INTEGERS:
            if value!=int(value):raise ValueError('Recipe '+key+' must be an integer')
            value=int(value)
        p[key]=value
    if p['representation'] not in ('Lightweight','Centreline','Full'):raise ValueError('Unsupported reinforcement representation')
    for key,diam in (('main_steel','diameter'),('tie_steel','tie_diameter')):
        if p[key] is not None:
            if not isinstance(p[key],dict):raise ValueError('Invalid steel selection')
            try:p[key]=C.validate(p[key],p[diam])
            except (KeyError,TypeError) as error:raise ValueError('Incomplete steel selection') from error
    if kind in ('Footing','Slab') and any(p[k] for k in ('lap_length','extension_start','extension_end')):raise ValueError('Footing / Slab recipes use hooks, not lap or axial extensions')
    if kind in ('Column','Beam') and p['hook_length']:raise ValueError('Column / Beam recipes use axial extensions, not end hooks')
    if kind=='Stair' and (p['lap_length'] or p['layers']!=1):raise ValueError('Stair recipe supports one mat and no lap')
    if kind=='Stair' and p['hook_length'] and (p['extension_start'] or p['extension_end']):raise ValueError('Stair: choose hooks or extensions')
    return p

def source(row):
    recipe=validate(row['kind'],row['rebar'])
    digest=hashlib.sha256(json.dumps(recipe,sort_keys=True).encode('utf-8')).hexdigest()
    return dict(type_id=row['id'],type_code=row['code'],type_revision=row['revision'],recipe_sha256=digest,recipe=recipe)

def provenance(kind,record,params):
    if record is None:return None
    try:
        recipe=validate(kind,record['recipe']);digest=hashlib.sha256(json.dumps(recipe,sort_keys=True).encode('utf-8')).hexdigest()
        if digest!=record['recipe_sha256']:raise ValueError('Recipe provenance checksum mismatch')
        import uuid
        uuid.UUID(record['type_id'])
        if isinstance(record['type_revision'],bool) or int(record['type_revision'])!=record['type_revision'] or record['type_revision']<1:raise ValueError('Invalid recipe type revision')
        if not isinstance(record['type_code'],str) or not record['type_code']:raise ValueError('Invalid recipe type code')
        result={k:copy.deepcopy(record[k]) for k in ('type_id','type_code','type_revision','recipe_sha256','recipe')}
        result['overridden']=validate(kind,params)!=recipe
        return result
    except (KeyError,TypeError) as error:raise ValueError('Invalid recipe provenance') from error
