"""Project readiness report; quantities retain their declared measurement basis."""
import json,collections
from pathlib import Path
from . import engine as E

def summarize(elements,layer_states):
    counts=collections.Counter();native=collections.Counter();legacy=collections.Counter();layers=collections.Counter();issues=[];uids=set();ids=set()
    for entry in elements:
        uid=entry['uid'];r=entry.get('record') or {};origin=entry.get('origin');cls=r.get('class',r.get('kind','Unclassified'))
        if uid in uids:issues.append('Duplicate native UID: '+uid)
        uids.add(uid);rid=r.get('id')
        if rid and (origin,rid) in ids:issues.append('Duplicate metadata ID: '+str(rid))
        if rid:ids.add((origin,rid))
        layers[entry.get('layer') or 'Layer 0']+=1
        if origin=='family10':legacy[cls]+=1
        elif origin=='thai_bim':native[cls]+=1
        if origin:counts[(r.get('discipline','Unclassified'),r.get('item','Unclassified'))]+=1
        if origin and (entry.get('layer') or 'Layer 0') not in layer_states:issues.append('Missing layer: '+str(entry.get('layer')))
    return dict(total_groups=len(elements),tagged=sum(native.values())+sum(legacy.values()),untagged=len(elements)-sum(native.values())-sum(legacy.values()),
        legacy_classes=dict(legacy),toolkit_kinds=dict(native),layers=[dict(name=n,count=c,visible=layer_states.get(n)) for n,c in sorted(layers.items())],
        quantities_by_item=[dict(discipline=d,item=i,count=c) for (d,i),c in sorted(counts.items())],issues=issues,
        legacy_rebar_count=legacy.get('IfcReinforcingBar',0),
        status='Model review: source completeness and LOD350 require drawing coordination')

def project_report(scene):
    from . import quantity_rows,bbs_records
    from .workflow import host_notices
    entries=[]
    for g in scene.groups:
        ext=g.ext or {};origin='thai_bim' if ext.get('thai_bim') else ('family10' if ext.get('family10') else None)
        entries.append(dict(uid=g.uid,origin=origin,record=ext.get(origin,{}) if origin else {},layer=g.layer))
    report=summarize(entries,{l.name:l.visible for l in scene.layers})
    rows,qissues=quantity_rows(scene);bars,bissues=bbs_records(scene)
    report.update(qto=E.aggregate(rows)[1:],qto_rows=len(rows),qto_unverified=sum(r['quantity'] is None for r in rows),
        qto_issues=qissues,bbs_bars=len(bars),bbs_issues=bissues,hosts=host_notices(scene),
        mesh_faces=sum(len(g.mesh.faces) for g in scene.groups),mesh_edges=sum(len(g.mesh.edges) for g in scene.groups))
    if report['legacy_rebar_count']:report['issues'].append('Family10 bars retain original estimated kg; legacy paths are not a fabrication BBS or eligible for toolkit-host regeneration')
    return report

def report_tables(report):
    return [('Overview',[['Check','Value'],['Groups',report['total_groups']],['Tagged elements',report['tagged']],['Untagged groups',report['untagged']],['Mesh faces',report['mesh_faces']],['Mesh edges',report['mesh_edges']],['Validated detailed BBS bars',report['bbs_bars']],['Legacy rebar excluded from fabrication BBS',report['legacy_rebar_count']],['QTO rows missing / invalid quantity',report['qto_unverified']],['Status',report['status']]]),
        ('Layers',[['Layer','Elements','Visible']]+[[x['name'],x['count'],str(x['visible'])] for x in report['layers']]),
        ('QTO summary',[['Discipline','Item','Unit','Measurement basis','Quantity']]+report['qto']),
        ('Issues',[['Review issue']]+[[x] for x in report['issues']+report['qto_issues']+report['bbs_issues']])]

def open_audit(panel):
    from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPushButton,QFileDialog,QTabWidget,QTableWidget,QTableWidgetItem
    from .builders import icon
    old=getattr(panel,'audit_dialog',None)
    if old is not None:old.close();old.deleteLater()
    dialog=QDialog(panel.app.window);dialog.setWindowTitle('Thai BIM — ตรวจทั้งโครงการ / Family10');dialog.setWindowIcon(icon('QTO'));dialog.resize(1100,720);layout=QVBoxLayout(dialog)
    report=project_report(panel.app.scene);layout.addWidget(QLabel(f"ชิ้นติดข้อมูล {report['tagged']} / ทั้งหมด {report['total_groups']} • BBS รายละเอียด {report['bbs_bars']} เส้น"))
    tabs=QTabWidget();layout.addWidget(tabs)
    for label,(_,rows) in zip(('ภาพรวม','Layer','ปริมาณแยกงาน','รายการต้องตรวจ'),report_tables(report)):
        table=QTableWidget(len(rows)-1,len(rows[0]));table.setHorizontalHeaderLabels(rows[0]);table.setEditTriggers(QTableWidget.NoEditTriggers)
        for i,row in enumerate(rows[1:]):
            for j,value in enumerate(row):table.setItem(i,j,QTableWidgetItem(str(value)))
        table.resizeColumnsToContents();table.horizontalHeader().setStretchLastSection(True);tabs.addTab(table,label)
    def export():
        path,_=QFileDialog.getSaveFileName(dialog,'ส่งออกผลตรวจโครงการ','','Excel (*.xlsx)')
        if path:E.write_xlsx(Path(path).with_suffix('.xlsx'),tables=report_tables(report))
    b=QPushButton('ส่งออกผลตรวจนี้ / Layer / QTO / Issues เป็น Excel');b.clicked.connect(lambda _:panel.guard(export));layout.addWidget(b)
    layout.addWidget(QLabel('รายงานนี้เป็น snapshot ตอนเปิดหน้าต่าง; เปิดใหม่หลังแก้โมเดล • Source metadata ไม่ใช่ปริมาณที่วัด geometry ใหม่'))
    panel.audit_dialog=dialog;dialog.show();return dialog

def install(panel):
    if getattr(panel,'_audit_tools',False):return
    from .builders import icon
    panel._audit_tools=True;a=panel.toolbar.addAction(icon('QTO'),'ตรวจทั้งโครงการ / Family10');a.triggered.connect(lambda _:panel.guard(lambda:open_audit(panel)))
