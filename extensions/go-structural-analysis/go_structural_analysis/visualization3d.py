"""World-space 3D overlays; projection is recomputed for every camera frame."""
import math
from PySide6.QtCore import QPointF,Qt
from PySide6.QtGui import QColor,QPen,QPolygonF,QPalette
from .model3d import xyz,axes,restraints,weight_density,cross,unit
from .results import is_current,UNITS,VERSION
from .display import LabelPlacer,axes_visible,format_value,selected_member
from .diagram_geometry import arrow_geometry,signed_regions

def diagram_axis(key,basis): return basis[2] if key in ('Vz','My','dz') else basis[1]
def diagram_world(a,b,member,key,factor):
    axis=diagram_axis(key,member['basis']); length=member['L']
    return [[a[j]+(b[j]-a[j])*p['x']/length+axis[j]*p[key]*factor for j in range(3)] for p in member['plot']]
def deformed_world(a,b,member,factor):
    return [[a[j]+(b[j]-a[j])*p['x']/member['L']+p[k]*factor for j,k in enumerate(('ux','uy','uz'))] for p in member['plot']]

def draw(panel,viewport,painter):
    from .projection_cache import batched_draw
    return batched_draw(panel,viewport,painter,_draw)

def _draw(panel,viewport,painter,project_override=None):
    model=panel.model(); ns={n['id']:n for n in model['nodes']}; ms={m['id']:m for m in model['members']}
    case=panel.case.currentText(); mode=panel.diagram.currentText(); key=mode if mode in ('N','Vy','Vz','T','My','Mz','D','dy','dz') else None
    r=panel.result['cases'].get(case) if (panel.results_are_current() if hasattr(panel,'results_are_current') else is_current(model,panel.result)) else None
    labels=panel.labels.isChecked(); ink=panel.palette().color(QPalette.ColorRole.WindowText); selected=selected_member(panel)
    placer=LabelPlacer(viewport.width(),viewport.height(),painter.fontMetrics(),panel.label_density.currentText() if hasattr(panel,'label_density') else 'Normal')
    ribbon=getattr(panel,'ribbon',None)
    if ribbon is not None and ribbon.isVisible(): placer.bounds.setTop(min(placer.bounds.bottom(),90+ribbon.height()+10))
    def project(points):
        if project_override is not None: return project_override(points)
        px,py,front=panel.app.world_to_pixels(points)
        return [(QPointF(float(x),float(y)),bool(f)) for x,y,f in zip(px,py,front)]
    def text(p,label,color=None,offset=(5,-8)):
        position=placer.place(p,label,offset) if labels else None
        if position is not None: painter.setPen(color or ink); painter.drawText(position,label)
    def poly(points,color,width=2):
        ps=project(points); painter.setPen(QPen(QColor(color),width)); painter.setBrush(Qt.BrushStyle.NoBrush)
        visible=[]
        for p,front in ps:
            if front: visible.append(p)
            else:
                if len(visible)>1: painter.drawPolyline(QPolygonF(visible))
                visible=[]
        if len(visible)>1: painter.drawPolyline(QPolygonF(visible))
        return ps
    def arrow(point,vector,label,color='#bd65be'):
        (p,f),(q,g)=project([point,[point[j]+vector[j] for j in range(3)]])
        if not f or not g: return
        geom=arrow_geometry((p.x(),p.y()),(q.x()-p.x(),q.y()-p.y()))
        if geom:
            tail,tip,left,right=[QPointF(*v) for v in geom]; painter.setPen(QPen(QColor(color),2)); painter.drawLine(tail,tip)
            painter.setBrush(QColor(color)); painter.drawPolygon(QPolygonF([tip,left,right])); painter.setBrush(Qt.BrushStyle.NoBrush); text(tail,label,QColor(color))
    span=max(math.dist(xyz(ns[m['i']]),xyz(ns[m['j']])) for m in model['members']); symbol=max(.08,span*.075)
    def moment(point,axis,value,label,color='#bd65be'):
        if abs(value)<1e-10: return
        x=unit(axis); seed=[0,0,1] if abs(x[2])<.9 else [0,1,0]; u=unit(cross(x,seed)); v=cross(x,u)
        angles=[(.2+4.6*i/28)*(1 if value>0 else -1) for i in range(29)]
        arc=[[point[j]+symbol*(u[j]*math.cos(t)+v[j]*math.sin(t)) for j in range(3)] for t in angles]
        ps=poly(arc,color); (p,f),(q,g)=ps[-2:]
        if f and g:
            geom=arrow_geometry((q.x(),q.y()),(q.x()-p.x(),q.y()-p.y()))
            if geom:
                _,tip,left,right=[QPointF(*a) for a in geom]; painter.setBrush(QColor(color)); painter.drawPolygon(QPolygonF([tip,left,right])); painter.setBrush(Qt.BrushStyle.NoBrush)
                text(q,label,QColor(color))
    if panel.legend.isChecked():
        ribbon=getattr(panel,'ribbon',None); top=ribbon.height()+10 if ribbon is not None and ribbon.isVisible() else 0
        painter.save(); painter.translate(0,top)
        painter.setPen(ink); painter.drawText(12,23,f'GO Structural v{VERSION} | XYZ / Z up | {case} | {mode}')
        painter.drawText(12,43,'N +compression | right-handed local x/y/z | kN, m, kN·m | blue + / orange −')
        painter.drawText(12,63,f'Diagram ×{panel.diagram_scale.value():g} (visual) | Deformation ×{panel.scale.value():g}')
        if panel.result and not r: painter.setPen(QColor('#e37945')); painter.drawText(12,83,'RESULTS OUT OF DATE — Run Analysis')
        painter.restore()
    peak=max((abs(v['value']) for m in r['members'].values() for v in m['extrema'][key].values()),default=0) if r and key else 0
    factor=span*.18*panel.diagram_scale.value()/peak if peak>1e-14 else 0
    world_key=(getattr(panel,'_projection_pool',(None,))[0],id(model),id(r))
    saved_world=getattr(panel,'_world_geometry',None)
    if saved_world is None or saved_world[0]!=world_key:
        geometry={}
        for mid,m in ms.items():
            a,b=xyz(ns[m['i']]),xyz(ns[m['j']]); basis=axes(a,b,m.get('rotation',0))
            item=dict(a=a,b=b,basis=basis)
            if r and key:
                mr=r['members'][mid]; axis=diagram_axis(key,mr['basis'])
                item['curve']=diagram_world(a,b,mr,key,factor)
                item['cells']=[(sign,[[a[j]+(b[j]-a[j])*position/mr['L']+axis[j]*value*factor for j in range(3)] for position,value in cell]) for sign,cell in signed_regions(mr['plot'],key)]
            if r and mode=='Deformed': item['deformed']=deformed_world(a,b,r['members'][mid],panel.scale.value())
            geometry[mid]=item
        saved_world=(world_key,geometry); panel._world_geometry=saved_world
    geometry=saved_world[1]
    for mid,m in ms.items():
        item=geometry[mid]; a,b,basis=item['a'],item['b'],item['basis']; color=QColor('#d79b26') if mid==selected else ink
        ps=poly([a,b],color,3)
        if all(f for _,f in ps): text((ps[0][0]+ps[1][0])/2,mid)
        if axes_visible(panel,mid):
            origin=[(a[j]+b[j])/2 for j in range(3)]
            for axis,name,axis_color in zip(basis,('x','y','z'),('#e75e5e','#49a575','#638cdd')):
                end=[origin[j]+axis[j]*symbol*2 for j in range(3)]
                poly([origin,end],axis_color); arrow(end,axis,'',axis_color)
                (endpoint,front),=project([end])
                if front: text(endpoint,'local '+name,QColor(axis_color))
        for end in ('i','j'):
            if m.get('release_'+end) or m['type']=='Truss':
                t=.035 if end=='i' else .965; (p,f),=project([[a[j]+(b[j]-a[j])*t for j in range(3)]])
                if f: painter.setPen(QPen(ink,1.5)); painter.setBrush(panel.palette().color(QPalette.ColorRole.Window)); painter.drawEllipse(p,4,4); painter.setBrush(Qt.BrushStyle.NoBrush)
        if not r: continue
        mr=r['members'][mid]; axis=diagram_axis(key,mr['basis']) if key else None
        if key:
            if mid==selected and getattr(panel,'diagram_plane',None) and panel.diagram_plane.isChecked():
                plane=[a,b,[b[j]+axis[j]*span*.24 for j in range(3)],[a[j]+axis[j]*span*.24 for j in range(3)]]
                projected=project(plane)
                if all(f for _,f in projected):
                    color_plane=QColor('#8999ae'); color_plane.setAlpha(30); painter.setPen(QPen(QColor('#8999ae'),1,Qt.PenStyle.DashLine)); painter.setBrush(color_plane); painter.drawPolygon(QPolygonF([p for p,_ in projected])); painter.setBrush(Qt.BrushStyle.NoBrush)
            for sign,points in item['cells']:
                pp=project(points)
                if all(f for _,f in pp):
                    fill=QColor('#258ac7' if sign>0 else '#e37945'); fill.setAlpha(75); painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(fill); painter.drawPolygon(QPolygonF([p for p,_ in pp]))
            painter.setBrush(Qt.BrushStyle.NoBrush); poly(item['curve'],'#59a5cd'); poly([a,b],color,3)
            extrema=mr['extrema'][key]; constant=abs(extrema['max']['value']-extrema['min']['value'])<1e-9
            for kind,e in extrema.items():
                if not labels: break
                if abs(e['value'])<1e-9 or (constant and kind=='min'): continue
                point=[a[j]+(b[j]-a[j])*e['x']/mr['L']+axis[j]*e['value']*factor for j in range(3)]; (p,f),=project([point])
                if f: text(p,f"{'min=max' if constant else kind} {format_value(e['value'],key,peak,panel.display_tolerance.value() if hasattr(panel,'display_tolerance') else 1e-6,getattr(panel,'displacement_mm',panel.labels).isChecked())} @ {e['x']:.4g} m",offset=(5,-22 if kind=='max' else 20))
        if mode=='Deformed': poly(item['deformed'],'#df7d55',2)
    for n in ns.values():
        point=xyz(n); (p,f),=project([point])
        if not f: continue
        node_selected=getattr(panel,'selected_entity',None)=='node:'+n['id']
        painter.setPen(QPen(QColor('#d79b26') if node_selected else ink,3 if node_selected else 1.5)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawEllipse(p,6 if node_selected else 3,6 if node_selected else 3); text(p,n['id'])
        fixed=restraints(n)
        if fixed:
            painter.drawPolygon(QPolygonF([p+QPointF(0,5),p+QPointF(-9,18),p+QPointF(9,18)]))
            if len(fixed)==6:
                for dx in (-9,-3,3,9): painter.drawLine(p+QPointF(dx,21),p+QPointF(dx-4,27))
            elif len(fixed)==1 and fixed[0].startswith('U'):
                painter.drawEllipse(p+QPointF(-5,22),2,2); painter.drawEllipse(p+QPointF(5,22),2,2)
            support_label=('Fixed' if len(fixed)==6 else 'Pin' if set(fixed)=={'UX','UY','UZ'} else 'Roller' if len(fixed)==1 and fixed[0].startswith('U') else 'Custom')+' ['+','.join(fixed)+']'
            text(p,support_label,offset=(8,30))
        if n.get('springs'):
            painter.drawPolyline(QPolygonF([p+QPointF(dx,35+i*3) for i,dx in enumerate((0,-4,4,-4,4,0))])); text(p,'spring '+','.join(n['springs']),offset=(8,53))
        if mode=='Reaction' and r:
            values=r['nodes'][n['id']]
            for j,name in enumerate(('Fx','Fy','Fz')):
                value=values[name]; vector=[0.,0.,0.]; vector[j]=value
                if abs(value)>1e-9: arrow(point,vector,f'{name} {value:.5g} kN','#49a575')
            for j,name in enumerate(('Mx','My','Mz')):
                axis=[0.,0.,0.]; axis[j]=1; moment(point,axis,values[name],f'{name} {values[name]:.5g} kN·m','#49a575')
    if panel.show_loads.isChecked() or panel.tabs.currentIndex()==1:
        factors=model.get('combinations',{}).get(case,{case:1})
        def load_vector(direction,value,member=None):
            index='xyz'.index(direction[1].lower())
            if direction[1].islower(): return [v*value for v in axes(xyz(ns[member['i']]),xyz(ns[member['j']]),member.get('rotation',0))[index]]
            vector=[0.,0.,0.]; vector[index]=value; return vector
        for p in model.get('point_loads',[]):
            value=p['value']*factors.get(p['case'],0)
            if abs(value)<1e-12: continue
            if p.get('source')=='self_weight':
                for member in ms.values():
                    if member['id']==p.get('member') or p.get('node') in (member['i'],member['j']):
                        poly([xyz(ns[member['i']]),xyz(ns[member['j']])],'#258ac7',5)
                continue
            m=ms.get(p.get('member'))
            if 'node' in p: point=xyz(ns[p['node']])
            else:
                a,b=xyz(ns[m['i']]),xyz(ns[m['j']]); t=p['x']/math.dist(a,b); point=[a[j]+(b[j]-a[j])*t for j in range(3)]
            vector=load_vector(p['direction'],1,m)
            if p['direction'].startswith('M'): moment(point,vector,value,f"{p['direction']} {value:.4g} kN·m")
            else: arrow(point,[v*value for v in vector],f"{p['direction']} {value:.4g} kN")
        distributed=list(model.get('distributed_loads',[]))
        if model.get('self_weight') and factors.get(model.get('self_weight_case'),0):
            mats={m['id']:m for m in model['materials']}; secs={s['id']:s for s in model['sections']}
            for m in ms.values():
                if weight_density(mats[m['material']])*secs[m['section']]['A']>0:
                    poly([xyz(ns[m['i']]),xyz(ns[m['j']])],'#258ac7',5)
            ribbon=getattr(panel,'ribbon',None); top=ribbon.height()+10 if ribbon is not None and ribbon.isVisible() else 0
            painter.setPen(QPen(QColor('#258ac7'),1)); painter.drawText(12,88+top,'Self-weight active: blue members (solver load unchanged)')
        for p in distributed:
            if p.get('source')=='self_weight':
                if factors.get(p['case'],0):
                    m=ms[p['member']]; poly([xyz(ns[m['i']]),xyz(ns[m['j']])],'#258ac7',5)
                continue
            factor_case=factors.get(p['case'],0)
            if not factor_case: continue
            m=ms[p['member']]; a,b=xyz(ns[m['i']]),xyz(ns[m['j']]); L=math.dist(a,b); x1=p.get('x1',0); x2=p.get('x2',L)
            for i in range(9):
                t=(x1+(x2-x1)*i/8)/L; point=[a[j]+(b[j]-a[j])*t for j in range(3)]; w=(p['w1']+(p['w2']-p['w1'])*i/8)*factor_case
                arrow(point,load_vector(p['direction'],w,m),f"{p['direction']} {p['w1']*factor_case:.4g} → {p['w2']*factor_case:.4g} kN/m" if i==4 else '')
    if selected in ms:
        member=ms[selected]; poly([xyz(ns[member['i']]),xyz(ns[member['j']])],'#d79b26',3)
    if r and selected in ms and panel.tabs.currentIndex()==2:
        m=ms[selected]; a,b=xyz(ns[m['i']]),xyz(ns[m['j']]); t=panel.inspector.ratio.value(); (p,f),=project([[a[j]+(b[j]-a[j])*t for j in range(3)]])
        if f: painter.setPen(QPen(QColor('#d79b26'),2)); painter.drawEllipse(p,6,6); text(p,f'x/L={t:.4f}',offset=(8,30))
