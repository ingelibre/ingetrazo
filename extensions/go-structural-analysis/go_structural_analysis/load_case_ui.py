"""Named load cases with reference-safe rename/removal."""
import copy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QPushButton,QDialogButtonBox
from .model import validate
from .theme import apply_style

def remap_cases(model,names):
    d=copy.deepcopy(model); old=d['cases']
    values=list(names.values())
    if not values or any(not n.strip() for n in values) or len(values)!=len(set(values)): raise ValueError('กรุณาตั้งชื่อ Load Case ให้ครบและไม่ซ้ำกัน')
    if set(values)&set(d.get('combinations',{})): raise ValueError('ชื่อ Load Case ต้องไม่ซ้ำกับ Load Combination')
    used={p['case'] for key in ('point_loads','distributed_loads') for p in d.get(key,[])}
    used.update(c for factors in d.get('combinations',{}).values() for c in factors)
    cfg=d.get('combination_manager',{})
    used.update(c for cases in cfg.get('bindings',{}).values() for c in cases)
    used.update(c for row in cfg.get('custom',{}).values() for c in row.get('factors',{}))
    if d.get('self_weight') and d.get('self_weight_case'): used.add(d['self_weight_case'])
    removed=set(old)-set(names)
    if removed&used: raise ValueError('ลบไม่ได้: '+', '.join(sorted(removed&used))+' ยังถูกใช้งานในโหลด / Combination / Self-weight')
    d['cases']=values
    for key in ('point_loads','distributed_loads'):
        for p in d.get(key,[]): p['case']=names.get(p['case'],p['case'])
    def factors(f): return {names.get(k,k):v for k,v in f.items()}
    d['combinations']={k:factors(f) for k,f in d.get('combinations',{}).items()}
    for a,cases in cfg.get('bindings',{}).items(): cfg['bindings'][a]=[names.get(c,c) for c in cases]
    for row in cfg.get('custom',{}).values(): row['factors']=factors(row.get('factors',{}))
    if d.get('self_weight_case'):
        d['self_weight_case']=values[0] if d['self_weight_case'] in removed else names.get(d['self_weight_case'],d['self_weight_case'])
    if cfg:
        from .thai_code import apply_manager
        d=apply_manager(d,cfg)
    return validate(d)

class LoadCaseManager(QDialog):
    def __init__(self,model,parent=None):
        super().__init__(parent); apply_style(self); self.original=copy.deepcopy(model); self.data=None; self.counter=0
        self.setWindowTitle('Load Cases — กรณีแรง'); self.resize(720,480); box=QVBoxLayout(self)
        hint=QLabel('Load Case คือแรงหนึ่งชุด เช่น DL = น้ำหนักคงที่, LL = แรงจร, WX+ = ลมแกน X ทิศบวก\nตั้งชื่อในตารางได้โดยตรง การเปลี่ยนชื่อจะอัปเดตโหลดและ Combination ที่อ้างอิงให้ด้วย'); hint.setWordWrap(True); box.addWidget(hint)
        row=QHBoxLayout()
        for name in ('DL','LL','WX+','WX-','WY+','WY-'):
            button=QPushButton('+ '+name); button.setToolTip({'DL':'Dead Load — น้ำหนักคงที่','LL':'Live Load — แรงจร'}.get(name,'Wind — ลมตามแกนและเครื่องหมายที่ระบุ')); button.clicked.connect(lambda checked=False,n=name:self.add(n)); row.addWidget(button)
        box.addLayout(row); self.table=QTableWidget(0,2); self.table.setHorizontalHeaderLabels(['ชื่อ Load Case','โหลดที่ใช้งาน']); self.table.horizontalHeader().setStretchLastSection(True); box.addWidget(self.table)
        for case in model['cases']: self.add(case,case)
        row=QHBoxLayout(); add=QPushButton('+ เพิ่มกรณีแรง'); add.clicked.connect(lambda:self.add('CASE')); remove=QPushButton('ลบแถวที่เลือก'); remove.clicked.connect(self.remove); row.addWidget(add); row.addWidget(remove); box.addLayout(row)
        self.error=QLabel(); self.error.setWordWrap(True); box.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.apply); buttons.rejected.connect(self.reject); box.addWidget(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('บันทึก'); buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('ยกเลิก')
    def add(self,name,original=None):
        existing={self.table.item(i,0).text() for i in range(self.table.rowCount())}; label=name; index=2
        while label in existing: label=name+str(index); index+=1
        i=self.table.rowCount(); self.table.insertRow(i); item=QTableWidgetItem(label)
        self.counter+=1; item.setData(Qt.ItemDataRole.UserRole,original if original is not None else -self.counter); self.table.setItem(i,0,item)
        count=sum(p.get('case')==original for key in ('point_loads','distributed_loads') for p in self.original.get(key,[]))
        combos={k for k,f in self.original.get('combinations',{}).items() if original in f}|{k for k,r in self.original.get('combination_manager',{}).get('custom',{}).items() if original in r.get('factors',{})}
        actions=[a for a,cases in self.original.get('combination_manager',{}).get('bindings',{}).items() if original in cases]
        usage=f'โหลด {count} รายการ · Combination {len(combos)} ชุด'
        if original and self.original.get('self_weight') and self.original.get('self_weight_case')==original: usage+=' · Self-weight'
        if actions: usage+=' · ประเภท '+', '.join(actions)
        note=QTableWidgetItem(usage); note.setFlags(note.flags()&~Qt.ItemFlag.ItemIsEditable); self.table.setItem(i,1,note); self.table.setCurrentCell(i,0)
    def remove(self):
        if self.table.currentRow()>=0: self.table.removeRow(self.table.currentRow())
    def apply(self):
        try:
            names={self.table.item(i,0).data(Qt.ItemDataRole.UserRole):self.table.item(i,0).text().strip() for i in range(self.table.rowCount())}
            self.data=remap_cases(self.original,names); self.accept()
        except Exception as exc: self.error.setText(str(exc))
