"""Pure instance dimensions: no library mutation, placement or topology replacement."""
import copy
from . import engine as E,structures as S,path_geometry as G

def editable(kind):
    return {'Footing':('width','depth','height'),'Column':('width','depth','height'),
        'Beam':('depth','height'),'Slab':('height',),'Stair':('width','height','going','risers','waist')}[kind]

def edit_spec(record,values):
    kind=record['kind'];p=copy.deepcopy(record.get('params') or record.get('stair_params'))
    if set(values)!=set(editable(kind)):raise ValueError('Edit fields must match the selected member kind')
    values={k:E.finite(v) for k,v in values.items()}
    if kind=='Stair':
        p.update(values)
        if p.get('stair_schema')==2:
            from .stairs import spec
            return spec(**p)
        return S.stair_spec(**p)
    if p.get('shape')=='polygon':
        from .shape_geometry import slab_spec
        return slab_spec(dict(p,height=values['height']))
    if kind in ('Footing','Column'):
        p['x']+=(p['width']-values['width'])/2;p['y']+=(p['depth']-values['depth'])/2
    elif kind=='Beam':p['y']+=(p['depth']-values['depth'])/2
    p.update(values)
    return E.box_spec(kind,**{k:p[k] for k in ('x','y','z','width','depth','height')})
