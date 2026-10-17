"""Engineering glyphs and world-anchored diagrams projected every frame."""
import math
from PySide6.QtCore import QPointF,QRectF,Qt
from PySide6.QtGui import QPen,QColor,QPolygonF
from .results import is_current,evaluate,pick_member,UNITS,VERSION
from .display import LabelPlacer,watermark,format_value,selected_member,axes_visible
from .diagram_geometry import arrow_geometry,signed_regions,reaction_components,moment_geometry

COLORS={'N':'#ad6ab5','V':'#238a9c','M':'#d56339','d':'#815ad5','Deformed':'#cc553f'}
SIGN_COLORS={1:'#258ac7',-1:'#e37945'}

def projected_members(panel):
    model=panel.model()
    if not model: return []
    nodes={n['id']:n for n in model['nodes']}; out=[]; ids=list(nodes); index={nid:i for i,nid in enumerate(ids)}
    px,py,front=panel.app.world_to_pixels([[nodes[n]['x'],nodes[n].get('y',0),nodes[n]['z']] for n in ids])
    for m in model['members']:
        i,j=index[m['i']],index[m['j']]
        if front[i] and front[j]: out.append((m['id'],(float(px[i]),float(py[i])),(float(px[j]),float(py[j]))))
    return out

def pick(panel,px,py): return pick_member(px,py,projected_members(panel))

def draw(panel,viewport,painter):
    original=panel
    if getattr(panel,'archive_view',None) and panel.archive_view.isChecked() and panel.result and not panel.results_are_current() and panel.result.get('input_model'):
        class Snapshot:
            def __getattr__(self,key): return getattr(original,key)
            def model(self): return original.result['input_model']
            def results_are_current(self): return True
        panel=Snapshot()
    if (panel.model() or {}).get('schema')==2: _draw(panel,viewport,painter)
    else:
        from .projection_cache import batched_draw
        batched_draw(panel,viewport,painter,_draw)
    watermark(original,painter)

def _draw(panel,viewport,painter,project_override=None):
    model=panel.model()
    if not model: return
    if model.get('schema')==2:
        from .visualization3d import draw as draw3d
        return draw3d(panel,viewport,painter)
    nodes={n['id']:n for n in model['nodes']}; case=panel.case.currentText(); mode=panel.diagram.currentText(); key={'N':'N','V':'V','M':'M','D':'d','Deflection':'d'}.get(mode)
    current=panel.results_are_current() if hasattr(panel,'results_are_current') else is_current(model,panel.result); r=panel.result['cases'].get(case) if current else None; labels=panel.labels.isChecked()
    from PySide6.QtGui import QPalette
    ink=panel.palette().color(QPalette.ColorRole.WindowText).name(); painter.setBrush(Qt.BrushStyle.NoBrush)
    placer=LabelPlacer(viewport.width(),viewport.height(),painter.fontMetrics(),panel.label_density.currentText() if hasattr(panel,'label_density') else 'Normal')
    ribbon=getattr(panel,'ribbon',None)
    if ribbon is not None and ribbon.isVisible(): placer.bounds.setTop(min(placer.bounds.bottom(),90+ribbon.height()+10))
    def project(points):
        if project_override is not None: return project_override(points)
        px,py,front=panel.app.world_to_pixels(points); return [(QPointF(float(x),float(y)),bool(f)) for x,y,f in zip(px,py,front)]
    def text(p,label,color=ink,offset=(5,-7)):
        position=placer.place(p,label,offset) if labels else None
        if position is not None: painter.setPen(QColor(color)); painter.drawText(position,label)
    def poly(points,color,width=2):
        pp=project(points); painter.setPen(QPen(QColor(color),width)); painter.setBrush(Qt.BrushStyle.NoBrush)
        visible=[]
        for p,front in pp:
            if front: visible.append(p)
            else:
                if len(visible)>1: painter.drawPolyline(QPolygonF(visible))
                visible=[]
        if len(visible)>1: painter.drawPolyline(QPolygonF(visible))
        return pp
    def arrow(p,vx,vy,label='',color='#934a91',label_offset=(5,-7)):
        geometry=arrow_geometry((p.x(),p.y()),(vx,vy))
        if geometry is None: return
        tail,tip,left,right=[QPointF(*v) for v in geometry]
        painter.setPen(QPen(QColor(color),2)); painter.drawLine(tail,tip)
        painter.setBrush(QColor(color)); painter.drawPolygon(QPolygonF([tip,left,right])); painter.setBrush(Qt.BrushStyle.NoBrush)
        text(tail,label,color,label_offset)
    def force(point,fx,fz,label='',color='#934a91',label_offset=(5,-7)):
        (p,f),=project([point]); (q,g),=project([[point[0]+fx,0,point[2]+fz]])
        if f and g: arrow(p,q.x()-p.x(),q.y()-p.y(),label,color,label_offset)
    def moment(point,value,label,color='#934a91'):
        (p,front),=project([point])
        if not front: return
        geometry=moment_geometry((p.x(),p.y()),value)
        if geometry is None: return
        arc,head=geometry; painter.setPen(QPen(QColor(color),2)); painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF([QPointF(*v) for v in arc]))
        painter.setBrush(QColor(color)); painter.drawPolygon(QPolygonF([QPointF(*v) for v in head])); painter.setBrush(Qt.BrushStyle.NoBrush)
        text(p,label,color,(28,-45))
    if panel.legend.isChecked():
        ribbon=getattr(panel,'ribbon',None); top=ribbon.height()+10 if ribbon is not None and ribbon.isVisible() else 0
        painter.save(); painter.translate(0,top)
        painter.setPen(QColor(ink)); painter.drawText(12,23,f'GO Structural v{VERSION} | XZ | {case} | {mode}')
        legend='N +compression · local V/M · D local y · m, kN, kN·m'
        if key: legend+=f' | scale ×{panel.diagram_scale.value():g} (visual)'
        if mode=='Deformed': legend+=f' | deformation ×{panel.scale.value():g}'
        painter.drawText(12,42,legend)
        if key:
            for sx,sign,label in [(12,1,'Positive (+)'),(135,-1,'Negative (-)')]:
                painter.setPen(Qt.PenStyle.NoPen); swatch=QColor(SIGN_COLORS[sign]); swatch.setAlpha(90); painter.setBrush(swatch); painter.drawRect(QRectF(sx,51,16,10))
                painter.setPen(QColor(ink)); painter.drawText(sx+22,61,label)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        if panel.result and not current: painter.setPen(QColor('#b94a2b')); painter.drawText(12,62,'RESULTS OUT OF DATE — Run Analysis')
        painter.restore()
    peak=max((abs(e[t]['value']) for m in r['members'].values() for k,e in m['extrema'].items() if k==key for t in ['min','max']),default=0) if r and key else 0
    span=max((m['L'] for m in r['members'].values()),default=6) if r else max((math.hypot(nodes[m['j']]['x']-nodes[m['i']]['x'],nodes[m['j']]['z']-nodes[m['i']]['z']) for m in model['members']),default=6)
    factor=span*0.18*panel.diagram_scale.value()/peak if peak>1e-14 else 0
    selected=selected_member(panel)
    for m in model['members']:
        a,b=nodes[m['i']],nodes[m['j']]; base=[[a['x'],0,a['z']],[b['x'],0,b['z']]]; pp=poly(base,'#d79b26' if m['id']==selected else ink,3)
        if axes_visible(panel,m['id']):
            length=math.hypot(b['x']-a['x'],b['z']-a['z']); bx=(b['x']-a['x'])/length; bz=(b['z']-a['z'])/length; center=[(a['x']+b['x'])/2,0,(a['z']+b['z'])/2]
            force(center,bx,bz,'local x','#cf5757'); force(center,-bz,bx,'local y','#388558')
        if all(f for _,f in pp): text((pp[0][0]+pp[1][0])/2,m['id'])
        # Rotation releases are shown at the actual member end, separated from node glyph.
        for end,release in [(0,m.get('release_i',False) or m['type']=='Truss'),(1,m.get('release_j',False) or m['type']=='Truss')]:
            if release and all(f for _,f in pp):
                origin=pp[end][0]; toward=pp[1-end][0]-origin; norm=math.hypot(toward.x(),toward.y())
                p=origin+toward*(10/max(norm,1)); painter.setPen(QPen(QColor(ink),1.5)); painter.setBrush(QColor('#f0f2f4')); painter.drawEllipse(p,4,4); painter.setBrush(Qt.BrushStyle.NoBrush)
        if not r or not (key or mode=='Deformed'): continue
        mr=r['members'][m['id']]; curve=[]
        if key:
            if m['id']==selected and getattr(panel,'diagram_plane',None) and panel.diagram_plane.isChecked():
                plane=project(base+[[b['x']+mr['basis'][1][0]*span*.24,0,b['z']+mr['basis'][1][1]*span*.24],[a['x']+mr['basis'][1][0]*span*.24,0,a['z']+mr['basis'][1][1]*span*.24]])
                if all(f for _,f in plane):
                    fill=QColor('#8999ae'); fill.setAlpha(30); painter.setPen(QPen(QColor('#8999ae'),1,Qt.PenStyle.DashLine)); painter.setBrush(fill); painter.drawPolygon(QPolygonF([p for p,_ in plane])); painter.setBrush(Qt.BrushStyle.NoBrush)
            for sign,cell in signed_regions(mr['plot'],key):
                world=[]
                for position,value in cell:
                    t=position/mr['L']; world.append([a['x']+(b['x']-a['x'])*t+mr['basis'][1][0]*value*factor,0,a['z']+(b['z']-a['z'])*t+mr['basis'][1][1]*value*factor])
                points=project(world)
                if all(front for _,front in points):
                    fill=QColor(SIGN_COLORS[sign]); fill.setAlpha(75); painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(fill); painter.drawPolygon(QPolygonF([p for p,_ in points]))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        for value in mr['plot']:
            t=value['x']/mr['L']; x=a['x']+(b['x']-a['x'])*t; z=a['z']+(b['z']-a['z'])*t
            if mode=='Deformed': x+=value['ux']*panel.scale.value(); z+=value['uz']*panel.scale.value()
            else: x+=mr['basis'][1][0]*value[key]*factor; z+=mr['basis'][1][1]*value[key]*factor
            curve.append([x,0,z])
        poly(curve,COLORS.get(key or mode,'#d56339'))
        # Redraw the baseline above the transparent fill to preserve member visibility.
        poly(base,'#d79b26' if m['id']==selected and panel.tabs.currentIndex()==2 else ink,3)
        if key and labels:
            for kind,e in mr['extrema'][key].items():
                t=e['x']/mr['L']; point=[a['x']+(b['x']-a['x'])*t+mr['basis'][1][0]*e['value']*factor,0,a['z']+(b['z']-a['z'])*t+mr['basis'][1][1]*e['value']*factor]
                (p,f),=project([point])
                value=0. if abs(e['value'])<1e-10 else e['value']
                if f: text(p,f"{kind} {format_value(value,key,peak,panel.display_tolerance.value() if hasattr(panel,'display_tolerance') else 1e-6,getattr(panel,'displacement_mm',panel.labels).isChecked())} @ {e['x']:.4g} m",COLORS[key],(5,-35 if kind=='max' else 20))
    for n in nodes.values():
        point=[n['x'],0,n['z']]; (p,f),=project([point])
        if not f: continue
        node_selected=getattr(panel,'selected_entity',None)=='node:'+n['id']
        painter.setPen(QPen(QColor('#d79b26') if node_selected else QColor(ink),3 if node_selected else 1.5)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawEllipse(p,6 if node_selected else 3,6 if node_selected else 3); text(p,n['id'])
        support=n.get('support','Free')
        if support=='Fixed':
            painter.drawLine(p+QPointF(-13,6),p+QPointF(13,6))
            for x in [-12,-6,0,6,12]: painter.drawLine(p+QPointF(x,6),p+QPointF(x-5,13))
            text(p,'Fixed',ink,(-15,30))
        elif support=='RollerX':
            painter.drawPolygon(QPolygonF([p+QPointF(5,0),p+QPointF(18,-10),p+QPointF(18,10)]))
            for y in [-6,6]: painter.drawEllipse(p+QPointF(22,y),2.5,2.5)
            painter.drawLine(p+QPointF(27,-13),p+QPointF(27,13)); text(p,support,ink,(32,4))
        elif support in ['Pin','Roller']:
            painter.drawPolygon(QPolygonF([p+QPointF(0,5),p+QPointF(-10,18),p+QPointF(10,18)]))
            if support!='Pin':
                for x in [-6,6]: painter.drawEllipse(p+QPointF(x,22),2.5,2.5)
            painter.drawLine(p+QPointF(-13,27 if support!='Pin' else 20),p+QPointF(13,27 if support!='Pin' else 20)); text(p,support,ink,(-15,42))
        if r and mode=='Reaction':
            v=r['nodes'][n['id']]
            for name,fx,fz,value in reaction_components(v['Rx'],v['Rz']):
                force(point,fx,fz,'','#238153')
                text(p,f"{name} {value:.5g} kN",'#238153',(-100,-38) if name=='Rx' else (-100,62))
            moment(point,v['My'],f"M {v['My']:.5g} kN·m",'#238153')
    if mode=='Model' or panel.show_loads.isChecked() or panel.tabs.currentIndex()==1:
        factors=model.get('combinations',{}).get(case,{case:1})
        ms={m['id']:m for m in model['members']}
        for original in model.get('point_loads',[]):
            if original.get('source')=='self_weight':
                if factors.get(original['case'],0):
                    for m in ms.values():
                        if m['id']==original.get('member') or original.get('node') in (m['i'],m['j']):
                            a,b=nodes[m['i']],nodes[m['j']]; poly([[a['x'],0,a['z']],[b['x'],0,b['z']]],'#258ac7',5)
                continue
            factor_case=factors.get(original['case'],0)
            if not factor_case: continue
            load=dict(original,value=original['value']*factor_case)
            if 'node' in load: n=nodes[load['node']]; pt=[n['x'],0,n['z']]
            else:
                m=ms[load['member']]; a,b=nodes[m['i']],nodes[m['j']]; t=load['x']/math.hypot(b['x']-a['x'],b['z']-a['z']); pt=[a['x']+(b['x']-a['x'])*t,0,a['z']+(b['z']-a['z'])*t]
            if load['direction']=='MY':
                moment(pt,load['value'],f"M {load['value']:.4g} kN·m")
            else: force(pt,load['value'] if load['direction']=='FX' else 0,load['value'] if load['direction']=='FZ' else 0,f"{load['value']:.4g} kN")
        distributed=[dict(p,w1=p['w1']*factors.get(p['case'],0),w2=p['w2']*factors.get(p['case'],0),case=case) for p in model.get('distributed_loads',[]) if factors.get(p['case'],0)]
        if model.get('self_weight',False):
            materials={m['id']:m for m in model['materials']}; sections={s['id']:s for s in model['sections']}
            for m in model['members']:
                sw_factor=factors.get(model['self_weight_case'],0) if model.get('self_weight_case') else sum(factors.values())
                weight=materials[m['material']].get('rho',0)*sections[m['section']]['A']*sw_factor
                if weight:
                    a,b=nodes[m['i']],nodes[m['j']]; poly([[a['x'],0,a['z']],[b['x'],0,b['z']]],'#258ac7',5)
            if sw_factor:
                ribbon=getattr(panel,'ribbon',None); top=ribbon.height()+10 if ribbon is not None and ribbon.isVisible() else 0
                painter.setPen(QPen(QColor('#258ac7'),1)); painter.drawText(12,88+top,'Self-weight active: blue members (solver load unchanged)')
        for load in distributed:
            if load.get('source')=='self_weight':
                m=ms[load['member']]; a,b=nodes[m['i']],nodes[m['j']]
                if load['w1'] or load['w2']: poly([[a['x'],0,a['z']],[b['x'],0,b['z']]],'#258ac7',5)
                continue
            if load['case']!=case: continue
            m=ms[load['member']]; a,b=nodes[m['i']],nodes[m['j']]; L=math.hypot(b['x']-a['x'],b['z']-a['z']); x1=load.get('x1',0); x2=load.get('x2',L)
            for i in range(9):
                t=(x1+(x2-x1)*i/8)/L; w=load['w1']+(load['w2']-load['w1'])*i/8; pt=[a['x']+(b['x']-a['x'])*t,0,a['z']+(b['z']-a['z'])*t]
                label=f"{load['w1']:.4g} → {load['w2']:.4g} kN/m"+(' SW' if load.get('self_weight') else '')
                force(pt,w if load['direction']=='FX' else 0,w if load['direction']=='FZ' else 0,label if i==4 else '',label_offset=(5,30) if load.get('self_weight') else (5,12))
    if r and selected in r['members'] and panel.tabs.currentIndex()==2:
        m=next(m for m in model['members'] if m['id']==selected); a,b=nodes[m['i']],nodes[m['j']]; t=panel.inspector.ratio.value(); (p,f),=project([[a['x']+(b['x']-a['x'])*t,0,a['z']+(b['z']-a['z'])*t]])
        if f: painter.setPen(QPen(QColor('#d79b26'),2)); painter.drawEllipse(p,6,6); text(p,f'x/L={t:.4f}','#a97514',(8,30))
