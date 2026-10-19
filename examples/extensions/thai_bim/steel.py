"""Nominal bar catalogue; geometry is smooth, grade is specified metadata."""
import copy,hashlib,json,math

TIS_RB='TIS 20-2559 / RB'
TIS_DB='TIS 24-2559 / DB'
ASTM_SI='ASTM A615/A615M / SI'
ASTM_IN='ASTM A615/A615M / inch'
CUSTOM='Custom / unspecified'
CATALOGUES=(TIS_DB,TIS_RB,ASTM_SI,ASTM_IN,CUSTOM)
SOURCES={TIS_RB:'https://www.tisi.go.th/data/standard/fulltext/TIS-20-2559p.pdf',
         TIS_DB:'https://www.tisi.go.th/data/standard/fulltext/TIS-24-2559p.pdf',
         ASTM_SI:'https://www.crsi.org/wp-content/uploads/CRSI_MSP_29th_Ed_Errata-Nov2019.pdf',
         ASTM_IN:'https://www.crsi.org/wp-content/uploads/CRSI_MSP_29th_Ed_Errata-Nov2019.pdf'}
RB=(6,8,9,10,12,15,19,22,25,28,34)
DB=(6,8,10,12,16,20,22,25,28,32,36,40)
# #9 onward use published nominal dimensions, not designation / 8.
US=((3,10,.375,9.5),(4,13,.500,12.7),(5,16,.625,15.9),(6,19,.750,19.1),
    (7,22,.875,22.2),(8,25,1.,25.4),(9,29,1.128,28.7),(10,32,1.270,32.3),
    (11,36,1.410,35.8),(14,43,1.693,43.0),(18,57,2.257,57.3))

def entries(catalogue):
    if catalogue in (TIS_RB,TIS_DB):
        prefix='RB' if catalogue==TIS_RB else 'DB'
        return [dict(size=f'{prefix}{d}',diameter_mm=float(d),diameter_in=None,metric_designation=str(d)) for d in (RB if prefix=='RB' else DB)]
    if catalogue in (ASTM_SI,ASTM_IN):
        return [dict(size=f'#{n}',diameter_mm=mm if catalogue==ASTM_SI else inch*25.4,
            diameter_in=inch,metric_designation=f'No.{metric}') for n,metric,inch,mm in US]
    if catalogue==CUSTOM:return []
    raise ValueError('Unknown steel catalogue')

def selection(catalogue,size,grade):
    row=next((v for v in entries(catalogue) if v['size']==size),None)
    if row is None:raise ValueError('Bar size is not in the selected catalogue')
    grade=str(grade).strip()
    allowed=('SR24',) if catalogue==TIS_RB else (('SD30','SD40','SD50') if catalogue==TIS_DB else ('Grade 60 [420]','Grade 80 [550]','Grade 100 [690]','Grade 40 [280]'))
    if grade not in allowed:raise ValueError('Unsupported grade designation')
    if catalogue in (ASTM_SI,ASTM_IN) and grade=='Grade 40 [280]' and int(size[1:])>6:
        raise ValueError('Grade 40 preset supports #3–#6; select a different grade for larger bars')
    return dict(catalogue=catalogue,**row,grade=grade,surface='Plain' if catalogue==TIS_RB else 'Deformed',
        source=SOURCES[catalogue],basis='Nominal catalogue; specified grade, not product certification')

def validate(record,diameter_mm):
    expected=selection(record['catalogue'],record['size'],record['grade'])
    if not math.isfinite(diameter_mm) or abs(expected['diameter_mm']-diameter_mm)>1e-6:
        raise ValueError('Diameter differs from the selected RB / DB / ASTM size')
    return expected

def tag(spec,record):
    if not record:return spec
    spec['steel']=copy.deepcopy(record)
    spec['item']=f"{record['size']} {record['grade']} ({record['catalogue']}) "+spec.get('bbs',{}).get('shape','net path')
    if spec.get('bbs'):
        b=spec['bbs'];b['steel']=copy.deepcopy(record)
        b['mark']='B-'+hashlib.sha256(json.dumps([b['mark'],record],sort_keys=True).encode()).hexdigest()[:12].upper()
    return spec
