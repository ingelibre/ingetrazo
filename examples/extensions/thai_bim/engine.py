"""Thai BIM 0.1: deterministic geometry and exports; no Qt/app dependencies."""
import csv
import hashlib
import json
import math
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

VERSION = '0.21.0'


def finite(value):
    v = float(value)
    if not math.isfinite(v):
        raise ValueError('ค่าต้องเป็นตัวเลขที่มีขอบเขต')
    return v


def positive(value, label):
    v = finite(value)
    if v <= 0:
        raise ValueError(label + ' ต้องมากกว่า 0')
    return v


def coordinates(text):
    values = [finite(v.strip()) for v in text.split(',') if v.strip()]
    if not values or len(set(values)) != len(values):
        raise ValueError('พิกัดต้องมีอย่างน้อยหนึ่งค่าและไม่ซ้ำกัน')
    return sorted(values)


def levels(text):
    result = []
    for line in text.splitlines():
        if not line.strip():
            continue
        name, height = line.rsplit('=', 1)
        if not name.strip():
            raise ValueError('กรุณาระบุชื่อระดับ')
        result.append({'name': name.strip(), 'z': finite(height)})
    if not result or len({x['name'] for x in result}) != len(result):
        raise ValueError('ชื่อระดับต้องไม่ซ้ำและมีอย่างน้อยหนึ่งระดับ')
    return result


def add(a, b): return tuple(x+y for x, y in zip(a, b))
def sub(a, b): return tuple(x-y for x, y in zip(a, b))
def mul(a, k): return tuple(x*k for x in a)
def dot(a, b): return sum(x*y for x, y in zip(a, b))
def cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def norm(a): return math.sqrt(dot(a, a))
def unit(a):
    n = positive(norm(a), 'ความยาว')
    return mul(a, 1/n)


def area(poly):
    return abs(sum(p[0]*q[1]-q[0]*p[1] for p,q in zip(poly, poly[1:]+poly[:1])))/2


def extrusion(loop, vec):
    """Outward oriented cap and side polygons, including concave sections."""
    normal = (0., 0., 0.)
    for p,q in zip(loop, loop[1:]+loop[:1]):
        normal = add(normal, cross(p, q))
    if abs(dot(normal, vec)) < 1e-12:
        raise ValueError('หน้าตัดหรือทิศทาง extrusion ไม่ถูกต้อง')
    lo = list(loop) if dot(normal, vec) > 0 else list(reversed(loop))
    hi = [add(p, vec) for p in lo]
    return [list(reversed(lo)), hi] + [[p,q,add(q,vec),add(p,vec)] for p,q in zip(lo,lo[1:]+lo[:1])]


def box_spec(kind, x, y, z, width, depth, height):
    x,y,z = map(finite,(x,y,z))
    w,d,h = positive(width,'กว้าง'),positive(depth,'ลึก'),positive(height,'สูง')
    if min(w,d,h) < .002 or max(w,d,h) > 100:
        raise ValueError('ขนาดชิ้นงานรองรับ 0.002–100 เมตร')
    classes={'Footing':'IfcFooting','Column':'IfcColumn','Beam':'IfcBeam','Slab':'IfcSlab'}
    if kind not in classes: raise ValueError('ชนิดชิ้นงานไม่รองรับ')
    params=dict(kind=kind,x=x,y=y,z=z,width=w,depth=d,height=h)
    loop=[(x,y,z),(x+w,y,z),(x+w,y+d,z),(x,y+d,z)]
    return dict(slot='member',kind=kind,ifc=classes[kind],faces=extrusion(loop,(0,0,h)),
                color=(.58,.61,.63),discipline='Structure',item='RC '+kind,unit='m3',
                quantity=w*d*h,params=params,note='Gross solid volume; intersections not deducted; reinforcement excluded')


def c_profile():
    h,b,t,lip=.125,.05,.0032,.02
    return [(0,-h/2),(b,-h/2),(b,-h/2+lip),(b-t,-h/2+lip),(b-t,-h/2+t),
            (t,-h/2+t),(t,h/2-t),(b-t,h/2-t),(b-t,h/2-lip),(b,h/2-lip),(b,h/2),(0,h/2)]


def strip(points, thickness):
    plus,minus=[],[]
    for i,p in enumerate(points):
        indices=[0] if i==0 else [len(points)-2] if i==len(points)-1 else [i-1,i]
        normals=[]
        for j in indices:
            dx,dy=sub(points[j+1],points[j]); length=math.hypot(dx,dy)
            normals.append((-dy/length,dx/length))
        n=unit(normals[0]) if len(normals)==1 else unit(add(*normals))
        offset=thickness/2/dot(n,normals[0])
        plus.append(add(p,mul(n,offset)));minus.append(sub(p,mul(n,offset)))
    return plus+minus[::-1]


def batten_profile():
    t=.0007; h=.027-t; crown=.020-t/2*(1+math.tan(math.pi/6))
    web=h/math.tan(math.pi/3); foot=(.061-crown-web)/2
    return strip([(-.0305,0),(-.0305+foot,0),(-.0305+foot+web,h),
                  (-.0305+foot+web+crown,h),(-.0305+foot+web+crown,0),(.0305,0)],t)


def stations(length, spacing, inset=0):
    end=length-inset
    if end <= inset: raise ValueError('ความยาวน้อยกว่าระยะเผื่อหัวท้าย')
    count=math.floor((end-inset)/spacing)
    out=[inset+i*spacing for i in range(count+1)]
    if end-out[-1] > 1e-7: out.append(end)
    return out


def section_spec(slot, a, b, normal, poly, item):
    vec=sub(b,a); length=norm(vec); side=unit(cross(unit(vec),normal))
    loop=[add(a,add(mul(side,x),mul(normal,z))) for x,z in poly]
    return dict(slot=slot,kind='Rafter' if slot.startswith('rafter') else 'Batten',ifc='IfcMember',
                faces=extrusion(loop,vec),color=(.56,.62,.68),discipline='Structure',item=item,
                unit='m',quantity=length,axis=[a,b],section_area_m2=area(poly),
                note='Net run; stock cuts, laps, screws and waste excluded')


def roof_specs(x=0,y=0,z=3,width=6,depth=4,pitch=30,overhang=.4,rafter_spacing=1,batten_spacing=.3,cover=.06):
    x,y,z=map(finite,(x,y,z))
    width,depth=positive(width,'กว้าง'),positive(depth,'ลึก')
    pitch=finite(pitch); overhang=finite(overhang)
    rafter_spacing=positive(rafter_spacing,'ระยะจันทัน'); batten_spacing=positive(batten_spacing,'ระยะแป')
    cover=positive(cover,'ความหนาหลังคา')
    if not 5 <= pitch <= 60 or not 0 <= overhang <= 2:
        raise ValueError('มุมหลังคา 5–60 องศา; ชายคา 0–2 เมตร')
    if not .2 <= rafter_spacing <= 3 or not .1 <= batten_spacing <= 1:
        raise ValueError('ระยะจันทัน 0.2–3 เมตร; ระยะแป 0.1–1 เมตร')
    if not 1 <= width <= 40 or not 1 <= depth <= 40 or not .005 <= cover <= .2:
        raise ValueError('อาคารกว้าง/ลึก 1–40 เมตร; ความหนาหลังคา 0.005–0.2 เมตร')
    angle=math.radians(pitch); slope=math.tan(angle); run=width/2+overhang
    length=run/math.cos(angle); ridge=x+width/2; y0=y-overhang; y1=y+depth+overhang
    specs=[]
    for side,sign in [('L',1),('R',-1)]:
        a=(x-overhang if sign==1 else x+width+overhang,y0,z-overhang*slope)
        b=(ridge,y0,z+width/2*slope)
        normal=(-sign*math.sin(angle),0,math.cos(angle))
        loop=[a,(a[0],y1,a[2]),(b[0],y1,b[2]),b]
        specs.append(dict(slot='cover-'+side,kind='Roof cover',ifc='IfcRoof',faces=extrusion(loop,mul(normal,-cover)),
                          color=(.36,.22,.14),discipline='Architecture',item='Roof covering gross area',
                          unit='m2',quantity=length*(y1-y0),note='Continuous roof slab; tile count, overlap and ridge accessories excluded'))
        for i,dy in enumerate(stations(y1-y0,rafter_spacing)):
            aa=add(add(a,(0,dy,0)),mul(normal,-cover-.027-.0625))
            bb=add(add(b,(0,dy,0)),mul(normal,-cover-.027-.0625))
            specs.append(section_spec('rafter-'+side+'-'+str(i),aa,bb,normal,c_profile(),'C125x50x20x3.2 rafter'))
        along=unit(sub(b,a))
        for i,ds in enumerate(stations(length,batten_spacing,.05)):
            aa=add(add(a,mul(along,ds)),mul(normal,-cover-.027))
            bb=add(aa,(0,y1-y0,0))
            sp=section_spec('batten-'+side+'-'+str(i),aa,bb,normal,batten_profile(),'PROFAST ECO0.7 61x27 batten')
            sp['note']+='; gauge must match selected tile; simplified bends/crown; supplier mass not assumed'
            specs.append(sp)
    return specs


def fingerprint(faces):
    rings=[[[round(finite(c),5) for c in p] for p in f] for f in faces]
    return hashlib.sha256(json.dumps(rings,separators=(',',':')).encode()).hexdigest()


def safe_text(value):
    s=str(value if value is not None else '')
    return "'"+s if s.startswith(('=','+','-','@','\t','\r')) else s


HEADERS=['ID','Name','Discipline','Item','Unit','Quantity','Basis','Source','Note']


def tabular(rows):
    return [HEADERS]+[[r.get(k,'') for k in ('id','name','discipline','item','unit','quantity','basis','source','note')] for r in rows]


def aggregate(rows):
    totals=defaultdict(float)
    for r in rows:
        q=r.get('quantity')
        if q is not None: totals[(r['discipline'],r['item'],r['unit'],r['basis'])]+=finite(q)
    return [['Discipline','Item','Unit','Basis','Quantity']]+[[*k,v] for k,v in sorted(totals.items())]


def write_csv(path, rows):
    with open(path,'w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f)
        for row in tabular(rows): writer.writerow([safe_text(v) if not isinstance(v,(int,float)) else v for v in row])


def excel_column(n):
    s=''
    while n:
        n,k=divmod(n-1,26); s=chr(65+k)+s
    return s


def xml_text(s):
    return escape(''.join(c for c in str(s) if c in '\t\n\r' or ord(c)>=32))


def write_xlsx(path, rows=None, issues=(), tables=None):
    """Plain interoperable OOXML, no optional dependencies or executable formulas."""
    sheets=tables if tables is not None else [('Summary',aggregate(rows)),('Elements',tabular(rows)),('Issues',[['Issue']]+[[s] for s in issues])]
    count=len(sheets)
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'+''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,count+1))+'</Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+''.join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_) in enumerate(sheets,1))+'</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,count+1))+f'<Relationship Id="rId{count+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml',f'<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="3"><xf fontId="0" fillId="0" borderId="0" numFmtId="0"/><xf fontId="1" fillId="0" borderId="0" numFmtId="0"/><xf fontId="0" fillId="0" borderId="0" numFmtId="4" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        for i,(_,data) in enumerate(sheets,1):
            body=[]
            for rn,row in enumerate(data,1):
                cells=[]
                for cn,v in enumerate(row,1):
                    ref=f'{excel_column(cn)}{rn}'
                    if v is None: continue
                    if isinstance(v,(int,float)):
                        cells.append(f'<c r="{ref}" s="2"><v>{finite(v)}</v></c>')
                    else:
                        cells.append(f'<c r="{ref}" s="{1 if rn==1 else 0}" t="inlineStr"><is><t xml:space="preserve">{xml_text(v)}</t></is></c>')
                body.append(f'<row r="{rn}">'+''.join(cells)+'</row>')
            last=f'{excel_column(len(data[0]))}{len(data)}'
            z.writestr(f'xl/worksheets/sheet{i}.xml',f'<worksheet xmlns="{ns}"><dimension ref="A1:{last}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols><col min="1" max="{len(data[0])}" width="24" customWidth="1"/></cols><sheetData>'+''.join(body)+f'</sheetData><autoFilter ref="A1:{last}"/></worksheet>')


def clip_intervals(polygon, direction, perpendicular, value):
    """Even-odd line/polygon clipping; supports simple concave footprints."""
    hits=[]
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        av,bv=dot(a,perpendicular),dot(b,perpendicular)
        if av <= value < bv or bv <= value < av:
            t=(value-av)/(bv-av)
            p=add(a,mul(sub(b,a),t));hits.append(dot(p,direction))
    hits.sort()
    if len(hits)%2: raise ValueError('ขอบระนาบไม่สมบูรณ์สำหรับ clipping')
    return [(a,b) for a,b in zip(hits[::2],hits[1::2]) if b-a>.03]


def plane_geometry(vertices):
    pts=[tuple(map(finite,p)) for p in vertices]
    if any(len(p)!=3 for p in pts): raise ValueError('จุดระนาบต้องมี X,Y,Z')
    if len(pts)>3 and norm(sub(pts[0],pts[-1]))<1e-7: pts.pop()
    if len(pts)<3 or len(pts)>100: raise ValueError('ระนาบต้องมี 3–100 จุด')
    if any(abs(c)>10000 for p in pts for c in p) or any(max(p[i] for p in pts)-min(p[i] for p in pts)>200 for i in (0,1)):
        raise ValueError('พิกัดระนาบเกินขอบเขต; ย้าย Origin ใกล้โมเดลหรือแบ่งระนาบ')
    n=(0.,0.,0.)
    for a,b in zip(pts,pts[1:]+pts[:1]): n=add(n,cross(a,b))
    n=unit(n)
    if n[2]<0: n=mul(n,-1)
    if n[2]<.15: raise ValueError('รองรับระนาบหลังคาลาดที่ไม่เกือบตั้งฉาก')
    if any(abs(dot(sub(p,pts[0]),n))>.0002 for p in pts):
        raise ValueError('จุดไม่อยู่ในระนาบเดียวกัน (คลาดเกิน 0.2 mm)')
    gradient=(-n[0]/n[2],-n[1]/n[2]);slope=norm(gradient)
    if slope<.03: raise ValueError('หลังคาแบนต้องระบุทิศทางต่างหาก; รุ่นนี้รองรับหลังคาลาด')
    poly=[p[:2] for p in pts]
    if area(poly)<.01: raise ValueError('ระนาบเล็กเกิน 0.01 m2')
    # Reject crossing/non-adjacent touching edges before even-odd clipping.
    def orient(a,b,c):
        u,v=sub(b,a),sub(c,a);return u[0]*v[1]-u[1]*v[0]
    for i,(a,b) in enumerate(zip(poly,poly[1:]+poly[:1])):
        if norm(sub(b,a))<1e-6: raise ValueError('จุดซ้ำในขอบระนาบ')
        for j in range(i+2,len(poly)):
            if i==0 and j==len(poly)-1: continue
            c,d=poly[j],poly[(j+1)%len(poly)]
            o=[orient(a,b,c),orient(a,b,d),orient(c,d,a),orient(c,d,b)]
            if o[0]*o[1]<=0 and o[2]*o[3]<=0:
                if (max(min(a[0],b[0]),min(c[0],d[0]))<=min(max(a[0],b[0]),max(c[0],d[0]))+1e-8 and
                    max(min(a[1],b[1]),min(c[1],d[1]))<=min(max(a[1],b[1]),max(c[1],d[1]))+1e-8):
                    raise ValueError('ขอบระนาบตัดกันหรือแตะกันเอง')
    intercept=pts[0][2]-dot(pts[0][:2],gradient)
    return poly,gradient,intercept,n


def plane_roof_specs(planes, rafter_spacing=1, batten_spacing=.3, batten_inset=.05, batten_end_inset=None,
                     rafter_offset=.0895, batten_offset=.02665):
    """Clip rafters and battens to each actual roof face; no hip/ridge members."""
    rs,bs=positive(rafter_spacing,'ระยะจันทัน'),positive(batten_spacing,'ระยะแป')
    inset=finite(batten_inset);end_inset=inset if batten_end_inset is None else finite(batten_end_inset)
    ro=finite(rafter_offset);bo=finite(batten_offset)
    if not .2<=rs<=3 or not .1<=bs<=1 or not 0<=inset<=.5 or not 0<=end_inset<=.5 or not 0<=bo<=1 or not 0<=ro<=1:
        raise ValueError('ระยะ/offset อยู่นอกขอบเขตที่รองรับ')
    if not planes or len(planes)>100: raise ValueError('ต้องมีระนาบ 1–100 ระนาบ')
    ids=[str(p['id']) for p in planes]
    if len(ids)!=len(set(ids)): raise ValueError('ID ระนาบซ้ำ')
    specs=[]
    for plane,pid in zip(planes,ids):
        poly,gradient,c,n=plane_geometry(plane['vertices'])
        up=unit(gradient);along=(-up[1],up[0]);factor=math.sqrt(1+dot(gradient,gradient))
        q=[dot(p,along) for p in poly];s=[dot(p,up) for p in poly]
        start=math.ceil((min(q)+1e-7)/rs)*rs
        rvalues=[]
        while start<max(q)-1e-7:
            rvalues.append(start);start+=rs
        if not rvalues: rvalues=[(min(q)+max(q))/2]
        bvalues=[];start=min(s)+inset/factor;end=max(s)-end_inset/factor
        while start<end-1e-8:
            bvalues.append(start);start+=bs/factor
        for kind,values,direction,perp,offset,profile,item in [
            ('rafter',rvalues,up,along,ro,c_profile(),'C125x50x20x3.2 rafter'),
            ('batten',bvalues,along,up,bo,batten_profile(),'PROFAST ECO0.7 61x27 batten')]:
            for index,value in enumerate(values):
                for part,(lo,hi) in enumerate(clip_intervals(poly,direction,perp,value)):
                    endpoints=[]
                    for t in (lo,hi):
                        xy=add(mul(direction,t),mul(perp,value))
                        endpoints.append(sub((*xy,dot(xy,gradient)+c),mul(n,offset)))
                    spec=section_spec(f'{kind}-{pid}-{index}-{part}',*endpoints,n,profile,item)
                    spec.update(plane_id=pid,plane_vertices=plane['vertices'])
                    spec['note']+='; roof-plane clipped; offset/gauge user parameters; hip/ridge/valley/connection members excluded'
                    specs.append(spec)
                    if len(specs)>10000: raise ValueError('แนวโครงหลังคาเกิน 10,000 ชิ้น; แบ่งงานเป็นชุดเล็ก')
    if not specs: raise ValueError('ไม่มีแนวชิ้นงานในระนาบที่เลือก')
    return specs


def stock_cut_plan(runs, stock=6, lap=0, kerf=.003):
    """Best-fit decreasing per material. Material allowance, not joint detailing."""
    stock=positive(stock,'เส้นสต็อก');lap=finite(lap);kerf=finite(kerf)
    if not 0<=lap<stock/2 or not 0<=kerf<.05 or stock<.1:
        raise ValueError('ค่าทาบ/ใบตัด/สต็อกไม่ถูกต้อง')
    if len(runs)>10000: raise ValueError('รองรับแนววัสดุไม่เกิน 10,000 แนว')
    runs=[dict(r,length=positive(r['length'],'ความยาวแนว'),material=str(r['material'])) for r in runs]
    pieces=[];seen=set()
    for run in runs:
        rid=str(run['id'])
        if rid in seen: raise ValueError('ID แนววัสดุซ้ำ')
        seen.add(rid);length=positive(run['length'],'ความยาวแนว')
        if length>1000: raise ValueError('แนววัสดุยาวเกิน 1,000 m')
        n=max(1,math.ceil((length-lap)/(stock-lap)-1e-10))
        total=length+(n-1)*lap
        lengths=[stock]*(n-1)+[total-(n-1)*stock]
        # Avoid a practically tiny tail; rebalance only the final two cuts.
        if n>1 and lengths[-1]<min(.5,stock/2):
            transfer=min(.5,stock/2)-lengths[-1];lengths[-2]-=transfer;lengths[-1]+=transfer
        for index,cut in enumerate(lengths,1):
            pieces.append(dict(run_id=rid,part=index,length=cut,material=run['material'],
                               run_length=length,lap=lap if index>1 else 0))
            if len(pieces)>10000: raise ValueError('รายการตัดเกิน 10,000 ชิ้น; แบ่งงานเป็นชุดเล็ก')
    bins=[]
    for p in sorted(pieces,key=lambda p:(p['material'],-p['length'],p['run_id'],p['part'])):
        options=[]
        for i,b in enumerate(bins):
            if b['material']!=p['material']: continue
            k=min(kerf,max(0.,b['remaining']-p['length']))
            if b['remaining']+1e-8>=p['length']+k:
                options.append((b['remaining']-p['length']-k,i,k))
        if options:
            _,i,k=min(options)
        else:
            bins.append(dict(id=len(bins)+1,material=p['material'],remaining=stock,kerf=0.,pieces=[]))
            i=len(bins)-1;k=min(kerf,max(0.,stock-p['length']))
        b=bins[i];b['remaining']-=p['length']+k;b['kerf']+=k
        p=dict(p,stock_id=b['id'],kerf=k);b['pieces'].append(p)
        if b['remaining']<-1e-7: raise ValueError('แผนตัดเกินความยาวเส้น')
    summaries=[]
    for material in sorted({r['material'] for r in runs}):
        subset=[r for r in runs if r['material']==material];stocks=[b for b in bins if b['material']==material]
        cuts=[p for b in stocks for p in b['pieces']]
        summaries.append(dict(material=material,runs=len(subset),net_m=sum(r['length'] for r in subset),
            lap_m=sum(p['lap'] for p in cuts),cut_m=sum(p['length'] for p in cuts),
            stocks=len(stocks),purchase_m=stock*len(stocks),kerf_m=sum(b['kerf'] for b in stocks),
            offcut_m=sum(b['remaining'] for b in stocks)))
    return dict(stock_m=stock,lap_m=lap,kerf_m=kerf,summary=summaries,stocks=bins,
                notes=['Best-fit decreasing heuristic; not guaranteed minimum stock count',
                       'Material planning only: verify splice locations, supports and lap requirements',
                       'Remaining lengths are reusable offcuts, not automatically discarded waste',
                       'Cutting plan does not add laps/joints to 3D geometry'])


def write_cut_xlsx(path,plan,issues=()):
    summary=[['Material','Runs','Net m','Lap m','Cut m','Stock bars','Purchase m','Kerf m','Offcut m']]
    for r in plan['summary']: summary.append([r[k] for k in ('material','runs','net_m','lap_m','cut_m','stocks','purchase_m','kerf_m','offcut_m')])
    cuts=[['Stock ID','Material','Run ID','Part','Cut length m','Lap allowance m','Kerf m']]
    stocks=[['Stock ID','Material','Stock length m','Cuts','Kerf m','Offcut m']]
    for b in plan['stocks']:
        stocks.append([b['id'],b['material'],plan['stock_m'],len(b['pieces']),b['kerf'],b['remaining']])
        for p in b['pieces']: cuts.append([b['id'],p['material'],p['run_id'],p['part'],p['length'],p['lap'],p['kerf']])
    write_xlsx(path,tables=[('Summary',summary),('Cuts',cuts),('Stock bars',stocks),
                          ('Notes',[['Note']]+[[n] for n in plan['notes']+list(issues)])])
