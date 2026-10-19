"""Identify copied business IDs without modifying native instance/type identity."""
import copy,uuid

def repaired(rows):
    if len({uid for uid,r in rows})!=len(rows):raise ValueError('Duplicate native UID; native instances must be repaired first')
    grouped={};referenced={r.get('host_uid') for uid,r in rows if r.get('host_uid')}
    for uid,r in rows:
        if r.get('id'):grouped.setdefault(r['id'],[]).append((uid,r))
    owners={}
    for rid,items in grouped.items():
        declared=[uid for uid,r in items if r.get('native_uid')==uid]
        linked=[uid for uid,r in items if uid in referenced]
        owners[rid]=(declared or linked or [items[0][0]])[0]
    result=[]
    for uid,old in rows:
        r=copy.deepcopy(old);rid=r.get('id');copied=bool(rid and owners[rid]!=uid or r.get('native_uid') and r['native_uid']!=uid)
        if copied or not rid:
            r['id']=str(uuid.uuid4());r['copied_from_id']=rid
            # Detached assemblies cannot overwrite the original's members.
            if r.get('assembly'):r['assembly']='copy-'+uid
            if r.get('kind')=='Rebar' or r.get('kind') not in ('Footing','Column','Beam','Slab','Stair'):
                r['copy_review_required']=True
                if r.get('kind')=='Rebar':
                    r['copied_from_host_uid']=r.get('host_uid');r['host_uid']='unverified-copy-'+uid
        r['native_uid']=uid
        result.append((uid,r))
    return result
