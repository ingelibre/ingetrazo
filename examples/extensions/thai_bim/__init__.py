"""IngeTrazo Extension: Thai BIM Toolkit 0.21.0 (API 2)."""
import copy
import json
import math
import uuid
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QPointF, QUrl
from PySide6.QtGui import QColor, QPen, QDesktopServices, QVector3D,QMatrix4x4
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QFormLayout,QLineEdit,QPlainTextEdit,
    QTabWidget,QComboBox,QDoubleSpinBox,QPushButton,QLabel,QCheckBox,QScrollArea,
    QMessageBox,QFileDialog,QDialog)
from core.mesh import Mesh
from core.group import Group, iter_placements, world_mesh
from core.history import Command
from core.layers import Layer
from core import bim
from . import engine as E
from .visuals import launcher, decorate_multi, decorate_cut
from .builders import add_tools

KEY='thai_bim'
TITLE='Thai BIM 0.21'


class ExchangeGroups(Command):
    """Prepare all geometry before committing. Preserve exact references on Undo."""
    def __init__(self, scene, replacements=(), additions=(), removals=()):
        self.scene=scene
        self.before=list(scene.groups)
        self.selection=set(scene.selection)
        self.old_layers=list(scene.layers)
        replacements=dict(replacements)
        removed=set(removals)
        self.after=[replacements.get(g,g) for g in self.before if g not in removed]+list(additions)
        self.after_selection={replacements.get(g,g) for g in self.selection if g not in removed}
        names={g.layer for g in self.after if g.layer}
        self.new_layers=self.old_layers+[Layer(n) for n in sorted(names-{l.name for l in self.old_layers})]

    def do(self, scene):
        if scene is not self.scene or len(scene.groups)!=len(self.before) or any(a is not b for a,b in zip(scene.groups,self.before)):
            raise ValueError('เอกสารหรือชิ้นงานเปลี่ยนหลังเตรียมคำสั่ง กรุณาสร้างคำสั่งใหม่')
        scene.groups[:]=self.after
        scene.layers[:]=self.new_layers
        scene.selection=set(self.after_selection)
        scene.version+=1

    def undo(self, scene):
        scene.groups[:]=self.before
        scene.layers[:]=self.old_layers
        scene.selection=set(self.selection)
        scene.version+=1


class NormalizeColors(Command):
    def __init__(self, scene):
        self.faces=[];self.materials=[]; seen=set();face_seen=set()
        meshes=[scene.loose_mesh]
        for root in scene.groups:
            for g,_ in iter_placements(root):
                if id(g) in seen: continue
                seen.add(id(g));meshes.append(g.mesh)
                if g.material and len(g.material.get('color',()))==4:
                    self.materials.append((g,copy.deepcopy(g.material)))
        for mesh in meshes:
            for f in mesh.faces:
                if id(f) in face_seen: continue
                face_seen.add(id(f))
                if len(f.attrs.get('color',()))==4:
                    self.faces.append((f,copy.deepcopy(f.attrs)))

    def do(self,scene):
        for f,old in self.faces:
            f.attrs['color']=tuple(old['color'][:3])
            f.attrs.setdefault('opacity',float(old['color'][3]))
        for g,old in self.materials:
            g.material=dict(old,color=tuple(old['color'][:3]))
            g.material.setdefault('opacity',float(old['color'][3]))
        scene.version+=1

    def undo(self,scene):
        for f,old in self.faces: f.attrs.clear();f.attrs.update(copy.deepcopy(old))
        for g,old in self.materials: g.material=copy.deepcopy(old)
        scene.version+=1


def mesh_fingerprint(group):
    # Installed 0.x builds expose either vectors or Vertex objects on faces.
    faces=[[getattr(v,'position',v).toTuple() for v in f.vertices] for f in group.mesh.faces]
    for f in group.mesh.faces:faces.extend([[getattr(v,'position',v).toTuple() for v in hole] for hole in f.holes])
    if group.children:
        for child in group.children:faces.extend([[getattr(v,'position',v).toTuple() for v in f.vertices] for f in world_mesh(child).faces])
    if faces:return E.fingerprint(faces)
    return E.fingerprint([[getattr(v,'position',v).toTuple() for v in (e.a,e.b)] for e in group.mesh.edges])


def make_group(spec, assembly='', previous=None):
    mesh=Mesh()
    for index,ring in enumerate(() if spec.get('components') else spec['faces']):
        face=mesh.add_face([QVector3D(*p) for p in ring],[[QVector3D(*p) for p in hole] for hole in spec.get('face_holes',{}).get(index,[])])
        if face is None: raise ValueError('สร้างผิวชิ้นงานไม่ได้')
        face.attrs['color']=tuple(spec['color'])
    wire=spec.get('representation')=='Centreline' and spec['kind']=='Rebar'
    if wire:
        pts=spec['bar_path'];pairs=list(zip(pts,pts[1:]))
        if spec.get('bar_closed'):pairs.append((pts[-1],pts[0]))
        for a,b in pairs:mesh.add_edge(QVector3D(*a),QVector3D(*b))
    children=[]
    if spec.get('components'):
        for part in spec['components']:
            partmesh=Mesh()
            for ring in part['faces']:partmesh.add_face([QVector3D(*p) for p in ring]).attrs['color']=tuple(spec['color'])
            amount=bim.face_set_volume(list(partmesh.faces))
            if amount is None or amount<=1e-9:raise ValueError('Stair component is not a closed solid: '+part['role'])
            child=Group(partmesh,name=part['role']);bim.tag_group(child,'IfcStairFlight' if part['kind'] in ('Flight','Curved') else 'IfcSlab',child.name);child.ext={'thai_bim_part':dict(role=part['role'],volume_m3=amount)};children.append(child)
        measured=sum(child.ext['thai_bim_part']['volume_m3'] for child in children)
    else:measured=None if wire else bim.face_set_volume(list(mesh.faces))
    if not wire and (measured is None or measured <= 1e-9):
        raise ValueError('ชิ้นงานไม่เป็น solid ปิด: '+spec['slot'])
    g=Group(mesh,name='TBIM '+spec['kind']+' '+spec['slot'])
    if children:g.adopt(children)
    if spec.get('params') and spec['kind'] in ('Footing','Column','Beam','Slab'):
        # Native Move/Rotate composes a pose instead of baking vertices for these hosts.
        g.xform=QMatrix4x4()
    from .management import layer_name
    g.layer=layer_name(spec)
    for child in children:child.layer=g.layer
    bim.tag_group(g,spec['ifc'],g.name)
    rec={k:copy.deepcopy(spec[k]) for k in ('slot','kind','discipline','item','unit','quantity','note')}
    rec.update(id=str(uuid.uuid4()),schema=1,version=E.VERSION,assembly=assembly,
               source='User parameters',volume_m3=measured,params=spec.get('params'),
               axis=spec.get('axis'),roof_params=spec.get('roof_params'),plane_id=spec.get('plane_id'),
               plane_vertices=spec.get('plane_vertices'),fingerprint=mesh_fingerprint(g))
    if children:rec['composite_stair']=True
    g.ext={KEY:rec}
    for k in ('stair_params','bar_path','bar_diameter','bar_closed','bbs','representation','steel'):
        if k in spec:rec[k]=copy.deepcopy(spec[k])
    if previous is not None:
        for k in ('member_type','placement_mode'):
            if k in previous.ext[KEY]:rec[k]=copy.deepcopy(previous.ext[KEY][k])
        g.uid=previous.uid
        g.hidden=previous.hidden
        g.xform=previous.xform
        g.material=copy.deepcopy(previous.material)
        g.ext=copy.deepcopy(previous.ext)
        rec['id']=previous.ext[KEY]['id']
        rec['slot']=previous.ext[KEY]['slot']
        g.ext[KEY]=rec
    if previous is not None and rec.get('member_type'):
        from .type_ui import tag
        tag(g,rec['member_type'])
    rec['native_uid']=g.uid
    return g


def identity_issues(scene):
    ids={}; issues=[]
    for g in scene.groups:
        rec=(g.ext or {}).get(KEY)
        if not rec: continue
        rid=rec.get('id')
        if not rid: issues.append('Missing TBIM ID: '+g.name)
        elif rid in ids: issues.append('Copied TBIM ID: '+g.name+' / '+ids[rid])
        else:
            ids[rid]=g.name
            if rec.get('native_uid') and rec['native_uid']!=g.uid:issues.append('Copied native binding: '+g.name)
    return issues


def bbs_records(scene):
    """Only trusted detailed bars with their original, unchanged host."""
    from .workflow import host_matches
    records=[];issues=identity_issues(scene);host_cache={}
    if issues:return [],issues
    legacy=sum((g.ext or {}).get('family10',{}).get('class')=='IfcReinforcingBar' for g in scene.groups)
    if legacy:issues.append(f'Family10 legacy bars excluded from fabrication BBS: {legacy}; source metadata / nominal paths lack verified hooks, laps and anchorage')
    byuid={g.uid:g for g in scene.groups}
    for g in scene.groups:
        r=(g.ext or {}).get(KEY,{})
        if r.get('kind')!='Rebar':continue
        if not r.get('bbs'):
            issues.append('Legacy / undetailed bar excluded: '+g.name);continue
        host=byuid.get(r.get('host_uid'))
        if not host_matches(g,host,host_cache):
            issues.append('Changed geometry / missing host excluded: '+g.name);continue
        b=r['bbs']
        if abs(E.finite(b['length_m'])-E.finite(r['quantity']))>1e-8:
            issues.append('Inconsistent bar length excluded: '+g.name);continue
        records.append(dict(id=g.uid,host_uid=host.uid,host_name=host.name,bbs=copy.deepcopy(b)))
    return records,issues


def quantity_rows(scene):
    from .workflow import bar_unchanged,host_matches
    rows=[]; issues=identity_issues(scene);host_cache={}
    byuid={g.uid:g for g in scene.groups}
    for g in scene.groups:
        ext=g.ext or {}; ours=ext.get(KEY); legacy=ext.get('family10')
        if not ours and not legacy: continue
        r=ours or legacy
        q=r.get('quantity');basis='Source metadata; not remeasured'
        note=r.get('note','')
        if ours:
            basis='Net centreline from parameters'
            unchanged=mesh_fingerprint(g)==r.get('fingerprint')
            if not unchanged:
                q=None;basis='Unverified edited geometry';issues.append('Recheck quantity: '+g.name)
            elif r['unit']=='m3':
                if r.get('composite_stair'):
                    from .workflow import pose
                    from .placement import rigid_matrix
                    try:
                        rigid_matrix(pose(g));amounts=[bim.face_set_volume(list(world_mesh(child).faces)) for child in g.children]
                        q=sum(amounts) if amounts and all(a is not None for a in amounts) else None;basis='Sum of individually closed stair component volumes; rigid placement'
                    except ValueError:q=None;issues.append('Non-rigid stair placement: '+g.name)
                else:q=bim.face_set_volume(list(world_mesh(g).faces));basis='Measured gross solid volume'
            elif g.xform is not None:
                if r.get('bar_path') and bar_unchanged(g):basis='Analytic bar cut length under tracked rigid placement'
                elif r.get('axis'):
                    a,b=(g.xform.map(QVector3D(*p)) for p in r['axis'])
                    q=(b-a).length();basis='Transformed net centreline'
                else:
                    q=None;basis='Recheck transformed roof area';issues.append('Recheck roof area: '+g.name)
            elif r['unit']=='m2': basis='Gross slope area from parameters'
            if r.get('bar_path') and unchanged and (g.xform is None or bar_unchanged(g)):basis='Analytic detailed bar cut length' if r.get('bbs') else 'Net model bar path; hooks/laps excluded'
            if r.get('host_uid'):
                host=byuid.get(r['host_uid'])
                if not host_matches(g,host,host_cache):
                    q=None;basis='Unverified changed/missing rebar host';issues.append('Recheck reinforcement host: '+g.name)
            if r.get('copy_review_required'):
                q=None;basis='Unverified copied assembly / reinforcement';issues.append('Review copied member: '+g.name)
        if q is not None:
            q=E.finite(q)
            if q < 0: raise ValueError('ปริมาณติดลบ: '+g.name)
        rows.append(dict(id=g.uid,name=g.name,discipline=r.get('discipline','Unclassified'),
                         item=r.get('item',g.name),unit=r.get('unit',''),quantity=q,basis=basis,
                         source=r.get('source',''),note=note))
    skipped=len(scene.groups)-len(rows)
    if skipped: issues.append(f'{skipped} top-level groups have no recognized quantity metadata; excluded')
    return rows,issues


def roof_update(scene, params):
    problems=identity_issues(scene)
    if problems: raise ValueError('\n'.join(problems[:8]))
    old=[g for g in scene.groups if (g.ext or {}).get(KEY,{}).get('assembly')=='gable-roof']
    byslot={g.ext[KEY]['slot']:g for g in old}
    if len(byslot)!=len(old): raise ValueError('หลังคามี slot ซ้ำ กรุณาตรวจรหัสชิ้นงาน')
    for g in old:
        if mesh_fingerprint(g)!=g.ext[KEY]['fingerprint'] or g.xform is not None:
            raise ValueError('หลังคามีชิ้นที่แก้ด้วยมือ/ย้ายแล้ว: '+g.name+'; กรุณาตรวจทานก่อนสร้างใหม่')
    specs=E.roof_specs(**params)
    replacements=[];additions=[]
    for spec in specs:
        spec['roof_params']=copy.deepcopy(params)
        previous=byslot.get(spec['slot']);new=make_group(spec,'gable-roof',previous)
        (replacements if previous is not None else additions).append((previous,new) if previous is not None else new)
    slots={s['slot'] for s in specs}
    removals=[g for g in old if g.ext[KEY]['slot'] not in slots]
    return ExchangeGroups(scene,replacements,additions,removals),len(specs)


class Panel(QWidget):
    def __init__(self, app):
        super().__init__(app.window);self.app=app;self.dock=None
        lay=QVBoxLayout(self)
        intro=QLabel('Thai BIM Toolkit 0.3\nโครงสร้าง • หลังคาหลายระนาบ • แผนตัดสต็อก • QTO')
        intro.setWordWrap(True);lay.addWidget(intro)
        tabs=QTabWidget();lay.addWidget(tabs)
        self.project=self.page(tabs,'โครงการ')
        self.name=QLineEdit();self.project.addRow('ชื่อโครงการ',self.name)
        self.gx=QLineEdit();self.project.addRow('Grid X (m)',self.gx)
        self.gy=QLineEdit();self.project.addRow('Grid Y (m)',self.gy)
        self.lv=QPlainTextEdit();self.lv.setMaximumHeight(125);self.project.addRow('Level: ชื่อ=เมตร',self.lv)
        self.guides=QCheckBox('แสดง Grid / Level');self.project.addRow(self.guides)
        self.button(self.project,'บันทึกค่าประจำโครงการ',self.save_project)
        self.members=self.page(tabs,'โครงสร้าง')
        self.kind=QComboBox();self.kind.addItems(['Footing','Column','Beam','Slab']);self.members.addRow('ชนิด RC',self.kind)
        self.mfields=self.fields(self.members,[('x',0),('y',0),('z',0),('width',.2),('depth',.2),('height',3)])
        self.button(self.members,'สร้างชิ้นใหม่',self.create_member)
        self.button(self.members,'อ่านค่าจากชิ้นที่เลือก',self.pick_member)
        self.button(self.members,'อัปเดตเฉพาะชิ้นที่เลือก',self.update_member)
        self.button(self.members,'สร้างเสาตาม Grid ที่บันทึก',self.grid_columns)
        self.roof=self.page(tabs,'หลังคา')
        self.rfields=self.fields(self.roof,[('x',0),('y',0),('z',3),('width',6),('depth',4),('pitch',30),
            ('overhang',.4),('rafter_spacing',1),('batten_spacing',.3),('cover',.06)])
        note=QLabel('จั่วสันตามแกน Y • จันทัน C125×50×20×3.2\nแป PROFAST 61×27×0.7 mm\nต้องยืนยันระยะแปกับกระเบื้องก่อนใช้งานจริง\nไม่รวมข้อต่อ เหล็กสัน/ตะเข้ และการออกแบบรับแรง')
        note.setWordWrap(True);self.roof.addRow(note)
        self.button(self.roof,'สร้าง / อัปเดตหลังคาจั่ว',self.create_roof)
        self.button(self.roof,'หลังคาหลายระนาบ…',self.open_multi)
        self.qto=self.page(tabs,'QTO / ตรวจ')
        self.button(self.qto,'สรุปปริมาณจากโมเดล',self.show_qto)
        self.button(self.qto,'ส่งออก Excel (.xlsx)',lambda:self.export('xlsx'))
        self.button(self.qto,'ส่งออก CSV สำหรับ Excel',lambda:self.export('csv'))
        self.button(self.qto,'แผนตัดเส้นสต็อก 6 ม.…',self.open_cuts)
        self.button(self.qto,'ตรวจสีและรหัสชิ้นงาน',self.check)
        self.button(self.qto,'แก้สี RGBA สำหรับ Render (Undo ได้)',self.fix_colors)
        self.button(self.qto,'ตั้ง Render: EEVEE / Medium / 1920',self.configure_render)
        self.report=QPlainTextEdit();self.report.setReadOnly(True);self.report.setMinimumHeight(130)
        lay.addWidget(self.report)
        self.refresh();app.on_document_changed(self.refresh)

    def page(self,tabs,title):
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content=QWidget();form=QFormLayout(content)
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        scroll.setWidget(content);tabs.addTab(scroll,title);return form

    def fields(self,form,items):
        labels={'x':'X (m)','y':'Y (m)','z':'Z / ระดับฐาน (m)','width':'กว้าง X (m)','depth':'ลึก Y (m)',
                'height':'สูง Z (m)','pitch':'มุมหลังคา (องศา)','overhang':'ชายคา (m)',
                'rafter_spacing':'ระยะจันทันสูงสุด (m)','batten_spacing':'ระยะแปสูงสุดตามลาด (m)','cover':'ความหนาหลังคา (m)'}
        labels.update(batten_inset='ระยะเริ่มแปจากขอบตามลาด (m)',rafter_offset='ระนาบถึงแกนจันทัน (m)',
                      batten_end_inset='ระยะจบแปจากขอบตามลาด (m)',
                      batten_offset='ระนาบถึงฐานหน้าตัดแป (m)',stock='ความยาวสต็อก (m)',lap='ระยะทาบต่อรอย (m)',kerf='รอยตัด (m)')
        out={}
        for key,value in items:
            box=QDoubleSpinBox();box.setDecimals(6);box.setRange(-10000,10000);box.setValue(value)
            form.addRow(labels[key],box);out[key]=box
        return out

    def button(self,form,title,callback):
        b=QPushButton(title);b.clicked.connect(lambda _=False:self.guard(callback));form.addRow(b)

    def guard(self,callback):
        try: callback()
        except Exception as e:
            self.report.setPlainText('ดำเนินการไม่ได้: '+str(e))
            QMessageBox.warning(self,'Thai BIM',str(e))

    def refresh(self):
        data=self.app.document_data({}) or {}
        defaults={'name':'New project','grid_x':[0,3,6],'grid_y':[0,4],
                  'levels':[{'name':'Ground','z':0},{'name':'Upper FFL','z':3.75},{'name':'Upper structure','z':3.65}],
                  'guides':False}
        data={**defaults,**data}
        self.name.setText(data['name']);self.gx.setText(', '.join(map(str,data['grid_x'])))
        self.gy.setText(', '.join(map(str,data['grid_y'])))
        self.lv.setPlainText('\n'.join(f"{p['name']}={p['z']}" for p in data['levels']))
        self.guides.setChecked(data['guides'])
        roof_data=next(((g.ext or {}).get(KEY,{}) for g in self.app.scene.groups
                        if (g.ext or {}).get(KEY,{}).get('assembly')=='gable-roof'),{})
        if roof_data.get('roof_params'):
            for k,w in self.rfields.items(): w.setValue(roof_data['roof_params'][k])

    def save_project(self):
        d=dict(schema=1,name=self.name.text().strip(),grid_x=E.coordinates(self.gx.text()),
               grid_y=E.coordinates(self.gy.text()),levels=E.levels(self.lv.toPlainText()),guides=self.guides.isChecked())
        if not d['name']: raise ValueError('กรุณาระบุชื่อโครงการ')
        if len(d['grid_x'])*len(d['grid_y'])>400: raise ValueError('Grid รุ่นแรกไม่เกิน 400 จุด')
        self.app.set_document_data(d);self.report.setPlainText('บันทึกโครงการแล้ว (เก็บใน .igz เมื่อ Save)')

    def execute(self,command):
        if self.app.scene.mesh is not self.app.scene.loose_mesh:
            raise ValueError('ออกจากการแก้ไขภายใน Group ก่อนใช้คำสั่ง Thai BIM')
        from .copy_identity import wrap_creation
        self.app.viewport.history.execute(wrap_creation(self.app.scene,command))
        if self.app.viewport.history.last_error:raise ValueError(self.app.viewport.history.last_error)
        self.app.viewport.notify_scene_changed();self.app.viewport.update()

    def spec(self):
        return E.box_spec(self.kind.currentText(),**{k:v.value() for k,v in self.mfields.items()})

    def create_member(self):
        g=make_group(self.spec());self.execute(ExchangeGroups(self.app.scene,additions=[g]))
        self.report.setPlainText('สร้าง '+g.name+' แล้ว')

    def selected(self):
        selected=[g for g in self.app.scene.selection if g in self.app.scene.groups]
        if len(selected)!=1 or not (selected[0].ext or {}).get(KEY,{}).get('params'):
            raise ValueError('เลือกชิ้น RC ที่สร้างด้วย Thai BIM เพียงหนึ่งชิ้น')
        if selected[0].ext[KEY]['params'].get('shape')=='polygon':
            raise ValueError('พื้นหลายจุด: ใช้คลังชนิดเพื่อแก้ความหนา; เครื่องมือสี่เหลี่ยมจะทิ้งขอบเขตเดิม')
        return selected[0]

    def pick_member(self):
        p=self.selected().ext[KEY]['params'];self.kind.setCurrentText(p['kind'])
        for k,w in self.mfields.items(): w.setValue(p[k])
        self.report.setPlainText('อ่านค่าชิ้นที่เลือกแล้ว; พิกัดเป็นค่าตอนสร้างก่อน Transform')

    def update_member(self):
        old=self.selected()
        if old.ext[KEY]['kind']!=self.kind.currentText():
            raise ValueError('ชนิดที่เลือกไม่ตรงกับชิ้นเดิม ใช้สร้างชิ้นใหม่เพื่อเพิ่มชนิดอื่น; อัปเดตใช้ได้เฉพาะชนิดเดิม')
        if identity_issues(self.app.scene): raise ValueError('พบรหัสชิ้นงานซ้ำจาก Copy; ต้องแก้รหัสก่อนอัปเดต')
        new=make_group(self.spec(),old.ext[KEY].get('assembly',''),old)
        self.execute(ExchangeGroups(self.app.scene,replacements=[(old,new)]))
        self.report.setPlainText('อัปเดตเฉพาะชิ้นที่เลือก; Transform เดิมยังอยู่; Undo ได้')

    def grid_columns(self):
        data=self.app.document_data({}) or {}
        if not data: raise ValueError('บันทึก Grid ของโครงการก่อน')
        if identity_issues(self.app.scene): raise ValueError('พบรหัสซ้ำจาก Copy')
        params={k:v.value() for k,v in self.mfields.items()}
        old=[g for g in self.app.scene.groups if (g.ext or {}).get(KEY,{}).get('assembly')=='grid-columns']
        byslot={g.ext[KEY]['slot']:g for g in old};replacements=[];additions=[];slots=set()
        if len(byslot)!=len(old): raise ValueError('Grid column slot ซ้ำ')
        for g in old:
            from .workflow import pose,P
            if mesh_fingerprint(g)!=g.ext[KEY]['fingerprint'] or not P.same_pose(pose(g),None):
                raise ValueError('เสาตาม Grid มีชิ้นที่แก้ด้วยมือ; ตรวจทานก่อนสร้างใหม่')
        for i,x in enumerate(data['grid_x']):
            for j,y in enumerate(data['grid_y']):
                spec=E.box_spec('Column',x-params['width']/2,y-params['depth']/2,params['z'],params['width'],params['depth'],params['height'])
                spec['slot']=f'column-{i}-{j}';slots.add(spec['slot'])
                prev=byslot.get(spec['slot']);g=make_group(spec,'grid-columns',prev)
                (replacements if prev is not None else additions).append((prev,g) if prev is not None else g)
        self.execute(ExchangeGroups(self.app.scene,replacements,additions,[g for g in old if g.ext[KEY]['slot'] not in slots]))
        self.report.setPlainText(f'เสาตาม Grid {len(slots)} ชิ้น; กดซ้ำจะอัปเดตชุดเดิม')

    def create_roof(self):
        command,count=roof_update(self.app.scene,{k:v.value() for k,v in self.rfields.items()})
        self.execute(command);self.report.setPlainText(f'หลังคาจั่ว {count} ชิ้น; กดซ้ำไม่สร้างซ้อน\nระยะแปต้องยืนยันกับกระเบื้อง; ไม่ใช่ผลออกแบบโครงสร้าง')

    def show_qto(self):
        rows,issues=quantity_rows(self.app.scene)
        text='รายการ '+str(len(rows))+' ชิ้น\n'+ '\n'.join(f'{d} | {item}: {q:.3f} {unit} [{basis}]' for d,item,unit,basis,q in E.aggregate(rows)[1:])
        self.report.setPlainText(text+'\n\nข้อสังเกต:\n'+'\n'.join(issues))

    def export(self,fmt):
        rows,issues=quantity_rows(self.app.scene)
        if not rows: raise ValueError('ไม่มีชิ้นงานที่มีข้อมูลปริมาณรองรับ')
        path,_=QFileDialog.getSaveFileName(self,'ส่งออก QTO',str(Path.home()/'Documents'/('Thai-BIM-QTO.'+fmt)),fmt.upper()+' (*.'+fmt+')')
        if not path: return
        path=Path(path)
        if path.suffix.lower()!='.'+fmt: path=path.with_suffix('.'+fmt)
        if fmt=='xlsx': E.write_xlsx(path,rows,issues)
        else:
            E.write_csv(path,rows);path.with_suffix('.issues.txt').write_text('\n'.join(issues),encoding='utf-8')
        self.report.setPlainText('ส่งออกแล้ว: '+str(path)+'\nปริมาณ Family10 อ่าน metadata และแยกฐานการวัดในรายงาน')

    def check(self):
        cmd=NormalizeColors(self.app.scene);issues=identity_issues(self.app.scene)
        self.report.setPlainText(f'RGBA faces: {len(cmd.faces)}\nRGBA group materials: {len(cmd.materials)}\n'+'\n'.join(issues or ['รหัส Thai BIM ไม่ซ้ำ']))

    def fix_colors(self):
        cmd=NormalizeColors(self.app.scene)
        if not cmd.faces and not cmd.materials:
            self.report.setPlainText('สีเป็น RGB แล้ว ไม่ต้องแก้');return
        self.execute(cmd);self.report.setPlainText(f'แก้สี {len(cmd.faces)} ผิว / {len(cmd.materials)} กลุ่ม; รักษา opacity; Undo ได้')

    def configure_render(self):
        from core import render_blender as rb
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        found=rb.find_blender(QSettings().value(rb.SETTINGS_KEY,'') or None)
        if found is None: raise ValueError('ไม่พบ Blender กรุณาติดตั้งหรือเลือกผ่านแผง Render')
        panels=[w for w in QApplication.allWidgets() if type(w).__name__=='RenderPanel']
        if len(panels)!=1: raise ValueError('หาแผง Render ที่เปิดอยู่ไม่ได้')
        p=panels[0]
        if p._proc is not None or p._sync.active: raise ValueError('หยุด Render / Sync ก่อนเปลี่ยนค่า')
        p._found=found;p._update_where()
        p._engine.setCurrentIndex(p._engine.findData('eevee'));p._quality.setCurrentIndex(1)
        p._width.setValue(1920);p._ground.setChecked(True);p._remember_settings()
        self.report.setPlainText('ตั้ง EEVEE / Medium / 1920 px / Ground แล้ว\n'+found.where+'\nเลือกมุมมองแล้วกด Render ในแผง Render')

    def open_multi(self):
        if getattr(self,'_multi_dialog',None) is None: self._multi_dialog=MultiRoofDialog(self)
        self._multi_dialog.show();self._multi_dialog.raise_()

    def open_cuts(self):
        if getattr(self,'_cut_dialog',None) is None: self._cut_dialog=CutDialog(self)
        self._cut_dialog.show();self._cut_dialog.raise_()

    def overlay(self,vp,painter):
        data=self.app.document_data({}) or {}
        if not data.get('guides'): return
        xs,ys=data['grid_x'],data['grid_y'];z=data['levels'][0]['z']
        segments=[]
        for i,x in enumerate(xs): segments.append(((x,min(ys)-1,z),(x,max(ys)+1,z),'X'+str(i+1)))
        for i,y in enumerate(ys): segments.append(((min(xs)-1,y,z),(max(xs)+1,y,z),'Y'+str(i+1)))
        for level in data['levels']:
            segments.append(((min(xs)-1,min(ys)-1,level['z']),(max(xs)+1,min(ys)-1,level['z']),level['name']+f" {level['z']:+.3f}"))
        points=np.asarray([p for a,b,_ in segments for p in (a,b)],dtype=float)
        px,py,front=self.app.world_to_pixels(points)
        painter.setPen(QPen(QColor('#278b9d'),1,Qt.DashLine))
        for i,(_,_,label) in enumerate(segments):
            if front[2*i] and front[2*i+1]:
                a=QPointF(float(px[2*i]),float(py[2*i]));b=QPointF(float(px[2*i+1]),float(py[2*i+1]))
                painter.drawLine(a,b);painter.drawText(a+QPointF(3,-3),label)


def setup(app):
    if app.api_version < 2: raise RuntimeError('Thai BIM ต้องการ IngeTrazo Extension API 2')
    panel=Panel(app);dock=app.add_panel(TITLE,launcher(panel));panel.dock=dock
    app.add_menu_action('Thai BIM Toolkit…',panel.open_workspace,tip='Illustrated dialogs / Project / RC / roof / QTO')
    app.add_overlay(panel.overlay)
    # Keep the Python object alive together with its host widget.
    app.window._thai_bim_panel=panel
    add_tools(panel)
    from .workflow import install
    install(panel)
    from .management import install as install_management
    install_management(panel)
    from .audit import install as install_audit
    install_audit(panel)
    from .drawings import install as install_drawings
    install_drawings(panel)
    from .type_ui import install as install_types
    install_types(panel)
    from .copy_identity import install as install_copies
    install_copies(panel)
    from .analytical_ui import install as install_analytical
    install_analytical(panel)
    from .selected_edit import install as install_selected_edit
    install_selected_edit(panel)
    from .slab_ui import install as install_slab_rebar
    install_slab_rebar(panel)
    from .stairs_ui import install as install_advanced_stairs
    install_advanced_stairs(panel)
    return panel


def selected_assembly(scene,kind,selected=None):
    groups=[g for g in (scene.selection if selected is None else selected) if g in scene.groups]
    if len(groups)!=1 or (groups[0].ext or {}).get(KEY,{}).get('assembly_kind')!=kind:
        raise ValueError('เลือกชิ้นงานหนึ่งชิ้นในชุด '+kind+' ที่สร้างด้วย Thai BIM')
    if groups[0].ext[KEY].get('copy_review_required'):raise ValueError('Copied multi-member assembly needs explicit review; rebuild as a new independent assembly')
    return groups[0]


def assembly_command(scene,specs,kind,params,selected=None):
    if identity_issues(scene):raise ValueError('พบรหัส Thai BIM ซ้ำจาก Copy')
    chosen=selected_assembly(scene,kind,selected) if selected is not None else None
    assembly=chosen.ext[KEY]['assembly'] if chosen else kind+'-'+str(uuid.uuid4())
    return reconcile_specs(scene,specs,assembly,dict(assembly_kind=kind,assembly_params=params))


def reconcile_specs(scene,specs,assembly,metadata,rebar_host=None):
    old=[g for g in scene.groups if (g.ext or {}).get(KEY,{}).get('assembly')==assembly]
    byslot={g.ext[KEY]['slot']:g for g in old}
    if len(byslot)!=len(old):raise ValueError('slot ชุดซ้ำ')
    for g in old:
        from .workflow import bar_unchanged
        valid=bar_unchanged(g) if rebar_host is not None else g.xform is None and mesh_fingerprint(g)==g.ext[KEY]['fingerprint']
        if not valid:
            raise ValueError('ชิ้นในชุดถูกแก้ด้วยมือ/Transform: '+g.name)
    replacements=[];additions=[]
    for spec in specs:
        prev=byslot.get(spec['slot']);new=make_group(spec,assembly,prev)
        new.ext[KEY].update(copy.deepcopy(metadata))
        from .management import layer_name
        new.layer=layer_name(new.ext[KEY])
        if rebar_host is not None:
            from .workflow import pose,matrix
            new.xform=matrix(pose(rebar_host))
        (replacements if prev is not None else additions).append((prev,new) if prev is not None else new)
    slots={s['slot'] for s in specs}
    if len(slots)!=len(specs):raise ValueError('พารามิเตอร์ให้ slot ซ้ำ')
    return ExchangeGroups(scene,replacements,additions,[g for g in old if g.ext[KEY]['slot'] not in slots]),len(specs)


def rebar_command(scene,host,specs,params,expected=None,recipe_source=None):
    if host not in scene.groups or identity_issues(scene):raise ValueError('Host ไม่อยู่ในไฟล์/พบรหัสซ้ำ')
    from .workflow import host_token,pose
    token=host_token(host);rec=host.ext[KEY]
    if expected is not None and token!=expected:raise ValueError('Host changed after preview; review the current host again')
    return reconcile_specs(scene,specs,'rebar-'+host.uid,dict(host_uid=host.uid,host_hash=token[2],host_pose=pose(host),bar_pose=pose(host),
        host_params=copy.deepcopy(rec.get('params') or rec.get('stair_params')),host_kind=rec['kind'],rebar_params=params,
        rebar_recipe_source=__import__(__package__+'.rebar_recipe',fromlist=['provenance']).provenance(rec['kind'],recipe_source,params)),rebar_host=host)


def roof_planes_from_groups(groups, underside=True):
    planes=[]
    for g in groups:
        if (g.ifc or {}).get('class')!='IfcRoof': continue
        candidates=[]
        for f in world_mesh(g).faces:
            if getattr(f,'holes',None): continue
            points=[getattr(v,'position',v).toTuple() for v in f.vertices]
            projected=E.area([p[:2] for p in points])
            if projected>.01:
                try: E.plane_geometry(points)
                except ValueError: continue
                candidates.append((projected,sum(p[2] for p in points)/len(points),points))
        if not candidates: raise ValueError('ไม่พบระนาบลาดเรียบไม่มีรูใน '+g.name)
        maxarea=max(c[0] for c in candidates)
        caps=[c for c in candidates if abs(c[0]-maxarea)<max(.0001,maxarea*1e-5)]
        normals=[E.plane_geometry(c[2])[3] for c in caps]
        if any(E.dot(n,normals[0])<.9999 for n in normals):
            raise ValueError('IfcRoof รวมหลายระนาบใน Group เดียว: แยกเป็น Group ต่อระนาบหรือระบุ JSON')
        chosen=(min if underside else max)(caps,key=lambda c:c[1])
        source_hash=E.fingerprint([[getattr(v,'position',v).toTuple() for v in f.vertices] for f in world_mesh(g).faces])
        planes.append(dict(id=g.uid,name=g.name,source_uid=g.uid,source_geometry_hash=source_hash,vertices=chosen[2]))
    if not planes: raise ValueError('เลือก Group ที่ติด BIM เป็น IfcRoof ก่อน')
    return planes


def multi_roof_update(scene,planes,params):
    if identity_issues(scene): raise ValueError('พบ ID Thai BIM ซ้ำ')
    source_ids={p.get('source_uid') for p in planes}
    sources={g.uid:g for g in scene.groups}
    for p in planes:
        uid=p.get('source_uid')
        if uid:
            if uid not in sources: raise ValueError('ระนาบอ้างอิงไม่อยู่ในไฟล์นี้ กรุณาอ่านระนาบใหม่')
            source=sources[uid]
            current=E.fingerprint([[getattr(v,'position',v).toTuple() for v in f.vertices] for f in world_mesh(source).faces])
            if current!=p.get('source_geometry_hash'):
                raise ValueError('geometry หลังคาอ้างอิงเปลี่ยนแล้ว กรุณาอ่านระนาบใหม่')
    legacy_sources=[g for g in scene.groups if g.uid in source_ids and (g.ext or {}).get('family10')]
    legacy_frames=[g for g in scene.groups if (g.ext or {}).get('family10',{}).get('axis_endpoints')]
    gable_sources=[g for g in scene.groups if g.uid in source_ids and (g.ext or {}).get(KEY,{}).get('assembly')=='gable-roof']
    if legacy_sources and legacy_frames or gable_sources:
        raise ValueError('ระนาบนี้มีโครงหลังคาเดิมแล้ว ใช้ตรวจแผน/ส่งออกก่อน; เครื่องมือไม่สร้างซ้อนกับ Family10 หรือชุดจั่ว')
    old=[g for g in scene.groups if (g.ext or {}).get(KEY,{}).get('assembly')=='multi-roof']
    byslot={g.ext[KEY]['slot']:g for g in old}
    if len(byslot)!=len(old): raise ValueError('slot โครงหลังคาซ้ำ')
    for g in old:
        if mesh_fingerprint(g)!=g.ext[KEY]['fingerprint'] or g.xform is not None:
            raise ValueError('โครงหลายระนาบมีชิ้นที่แก้ด้วยมือ: '+g.name)
    specs=E.plane_roof_specs(planes,**params);replacements=[];additions=[]
    for sp in specs:
        previous=byslot.get(sp['slot']);new=make_group(sp,'multi-roof',previous)
        (replacements if previous is not None else additions).append((previous,new) if previous is not None else new)
    slots={s['slot'] for s in specs}
    return ExchangeGroups(scene,replacements,additions,[g for g in old if g.ext[KEY]['slot'] not in slots]),len(specs)


def cutting_runs(scene, selected_only=False, material='Batten'):
    runs=[];issues=[]
    for g in scene.groups:
        if selected_only and g not in scene.selection: continue
        r=(g.ext or {}).get(KEY) or (g.ext or {}).get('family10')
        if not r: continue
        axis=r.get('axis') or r.get('axis_endpoints')
        item=r.get('item','')
        kind=r.get('kind') or ('Batten' if 'batten' in item.lower() else 'Rafter' if 'C125x50x20x3.2' in item else '')
        if not axis or kind!=material: continue
        a,b=(QVector3D(*p) for p in axis)
        if g.xform is not None: a,b=g.xform.map(a),g.xform.map(b)
        direction=(b-a).normalized()
        projections=[QVector3D.dotProduct(v.position,direction) for v in world_mesh(g).vertices]
        length=max(projections)-min(projections)
        if (g.ext or {}).get(KEY) and mesh_fingerprint(g)!=r.get('fingerprint'):
            issues.append('Excluded manually edited geometry: '+g.name);continue
        if abs(length-(b-a).length())>.0002:
            issues.append('Excluded inconsistent axis/geometry: '+g.name);continue
        runs.append(dict(id=g.uid,length=length,material=r['item'],name=g.name))
    if not runs: raise ValueError('ไม่มีแนววัสดุที่ตรวจความยาวได้ตามตัวเลือก')
    return runs,issues


class MultiRoofDialog(QDialog):
    def __init__(self,panel):
        super().__init__(panel.app.window);self.panel=panel
        self.setWindowTitle('Thai BIM — หลังคาหลายระนาบ');self.resize(780,760)
        lay=QVBoxLayout(self);form=QFormLayout();lay.addLayout(form)
        self.surface=QComboBox();self.surface.addItems(['ใต้แผ่นหลังคา','ผิวบนหลังคา']);form.addRow('ระนาบอ้างอิง',self.surface)
        panel.button(form,'อ่านระนาบจาก IfcRoof ที่เลือก',lambda:self.read(True))
        panel.button(form,'อ่านระนาบ IfcRoof ทั้งโครงการ',lambda:self.read(False))
        self.input=QPlainTextEdit();self.input.setPlaceholderText('[{"id":"plane-1","vertices":[[0,0,3],[3,0,5],[3,4,5],[0,4,3]]}]')
        self.input.setMinimumHeight(150);lay.addWidget(self.input)
        fields=QFormLayout();lay.addLayout(fields)
        self.fields=panel.fields(fields,[('rafter_spacing',1),('batten_spacing',.3),('batten_inset',.05),('batten_end_inset',.05),('rafter_offset',.0895),('batten_offset',.02665)])
        self.output=QPlainTextEdit();self.output.setReadOnly(True);lay.addWidget(self.output)
        panel.button(fields,'ตรวจแผน / ความยาว',self.preview)
        panel.button(fields,'บันทึกระนาบและระยะในโครงการ',self.store)
        panel.button(fields,'สร้าง / อัปเดตโครงหลายระนาบ',self.build)
        data=(panel.app.document_data({}) or {}).get('multi_roof',{})
        if data:
            self.input.setPlainText(json.dumps(data['planes'],ensure_ascii=False,indent=2))
            for k,v in data['params'].items(): self.fields[k].setValue(v)
        decorate_multi(self)

    def config(self):
        planes=json.loads(self.input.toPlainText());params={k:w.value() for k,w in self.fields.items()}
        if not isinstance(planes,list): raise ValueError('JSON ต้องเป็นรายการระนาบ')
        return planes,params

    def read(self,selected):
        scene=self.panel.app.scene
        groups=[g for g in scene.groups if not selected or g in scene.selection]
        planes=roof_planes_from_groups(groups,self.surface.currentIndex()==0)
        self.input.setPlainText(json.dumps(planes,ensure_ascii=False,indent=2));self.preview()

    def preview(self):
        planes,params=self.config();specs=E.plane_roof_specs(planes,**params)
        lines=[]
        for kind in ['Rafter','Batten']:
            subset=[s for s in specs if s['kind']==kind]
            lines.append(f'{kind}: {len(subset)} ชิ้น / {sum(s["quantity"] for s in subset):.3f} m')
        self.output.setPlainText('\n'.join(lines)+'\nระยะและ offset เป็นค่าของผู้ใช้; ยังไม่รวมเหล็กสัน/ตะเข้/ข้อต่อ')
        if hasattr(self,'visual'): self.visual.display('roof',(planes,specs))
        return specs

    def store(self):
        self.preview();planes,params=self.config();data=self.panel.app.document_data({}) or {}
        data['multi_roof']=dict(planes=planes,params=params)
        self.panel.app.set_document_data(data)

    def build(self):
        planes,params=self.config();command,count=multi_roof_update(self.panel.app.scene,planes,params)
        self.panel.execute(command);self.output.setPlainText(f'สร้าง/อัปเดต {count} ชิ้นแล้ว; Undo ได้')


class CutDialog(QDialog):
    def __init__(self,panel):
        super().__init__(panel.app.window);self.panel=panel
        self.setWindowTitle('Thai BIM — แผนตัดสต็อก');self.resize(780,640)
        lay=QVBoxLayout(self);form=QFormLayout();lay.addLayout(form)
        self.material=QComboBox();self.material.addItems(['Batten','Rafter']);form.addRow('วัสดุ',self.material)
        self.selected=QCheckBox('เฉพาะชิ้นที่เลือก');form.addRow(self.selected)
        self.fields=panel.fields(form,[('stock',6),('lap',0),('kerf',.003)])
        note=QLabel('ทาบ 0 เป็นค่าเริ่มต้นสำหรับประมาณวัสดุ ไม่ใช่รายละเอียดรอยต่อ\nแนวเกินสต็อกต้องกำหนดระยะทาบและตรวจจุดรองรับก่อนสั่งซื้อ\nแผนใช้ heuristic; ไม่รับรองจำนวนเส้นต่ำสุด; ไม่เพิ่มรอยต่อในโมเดล')
        note.setWordWrap(True);form.addRow(note)
        panel.button(form,'คำนวณแผนตัด',self.calculate)
        panel.button(form,'ส่งออกแผนตัด Excel',self.export)
        self.output=QPlainTextEdit();self.output.setReadOnly(True);lay.addWidget(self.output)
        data=(panel.app.document_data({}) or {}).get('cutting',{})
        for k,v in data.items():
            if k in self.fields: self.fields[k].setValue(v)
        panel.button(form,'บันทึกค่าตัดในโครงการ',self.store)
        decorate_cut(self)

    def calculate(self):
        runs,issues=cutting_runs(self.panel.app.scene,self.selected.isChecked(),self.material.currentText())
        plan=E.stock_cut_plan(runs,**{k:w.value() for k,w in self.fields.items()})
        if plan['lap_m']==0 and any(r['length']>plan['stock_m'] for r in runs):
            issues.append('มีแนวเกินสต็อกแต่ทาบ=0: ยังไม่รวมระยะทาบที่ต้องยืนยัน')
        self.output.setPlainText('\n'.join(f'{r["material"]}\nสุทธิ {r["net_m"]:.3f} m + ทาบ {r["lap_m"]:.3f} m\nซื้อ {r["stocks"]} เส้น = {r["purchase_m"]:.3f} m\nรอยตัด {r["kerf_m"]:.3f} m / เศษเหลือ {r["offcut_m"]:.3f} m' for r in plan['summary'])+'\n\n'+'\n'.join(issues))
        if hasattr(self,'visual'): self.visual.display('cuts',plan)
        return plan,issues

    def export(self):
        plan,issues=self.calculate()
        path,_=QFileDialog.getSaveFileName(self,'ส่งออกแผนตัด',str(Path.home()/'Documents'/'Thai-BIM-cutting.xlsx'),'Excel (*.xlsx)')
        if path: E.write_cut_xlsx(Path(path).with_suffix('.xlsx'),plan,issues)

    def store(self):
        data=self.panel.app.document_data({}) or {};data['cutting']={k:w.value() for k,w in self.fields.items()}
        E.stock_cut_plan([],**data['cutting']);self.panel.app.set_document_data(data)
