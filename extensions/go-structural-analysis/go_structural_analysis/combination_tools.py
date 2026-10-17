"""Combination matrix and reviewed Thai preset generator; no new solver equations."""
import copy,json,math
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QLabel,QPushButton,QTableWidget,QTableWidgetItem,QStyledItemDelegate,QDialog,QComboBox,QCheckBox,QDialogButtonBox
from .combination_ui import FactorInput
from .thai_code import presets,derive,clone_custom
from .theme import apply_style

def formula(factors):
    result=[]
    for case,value in factors.items():
        if value: result.append(('− ' if value<0 else '+ ' if result else '')+f'{abs(value):g} × {case}')
    return ' '.join(result) or 'ยังไม่มีตัวคูณแรง'

class FactorDelegate(QStyledItemDelegate):
    def createEditor(self,parent,option,index):
        editor=FactorInput(parent); editor.setDecimals(15); editor.setRange(-1e100,1e100); editor.setSingleStep(.1); return editor
    def setEditorData(self,editor,index):
        value=index.data(Qt.ItemDataRole.UserRole); editor.setValue(value); editor.setProperty('initial_display',editor.value())
    def setModelData(self,editor,model,index):
        editor.interpretText()
        if editor.value()!=editor.property('initial_display'): model.setData(index,repr(editor.value()),Qt.ItemDataRole.EditRole)

class CombinationOverview(QWidget):
    def __init__(self,manager):
        super().__init__(manager); self.manager=manager; self.rows=[]; self.updating=False; box=QVBoxLayout(self); box.setContentsMargins(0,0,0,0)
        bar=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText('ค้นหา Combination / สูตร…'); self.search.setClearButtonEnabled(True); bar.addWidget(self.search)
        duplicate=QPushButton('ทำสำเนาที่เลือก'); duplicate.clicked.connect(self.duplicate); bar.addWidget(duplicate); box.addLayout(bar)
        self.table=QTableWidget(); self.table.setMinimumHeight(240); self.table.setAlternatingRowColors(True); self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); box.addWidget(self.table)
        self.notice=QLabel('ดับเบิลคลิกตัวคูณเพื่อแก้ไข · 0 = ไม่รวม · ค่าลบ = กลับทิศ · Preset แก้ได้ด้วยสำเนา Custom'); self.notice.setWordWrap(True); box.addWidget(self.notice)
        self.table.itemChanged.connect(self.edit); self.table.currentCellChanged.connect(self.select); self.search.textChanged.connect(self.filter)
        manager.custom.textChanged.connect(self.refresh_if_ready); manager.custom_choice.currentTextChanged.connect(self.select_name); self.refresh()
    def select_name(self,name):
        if self.updating: return
        for i,row in enumerate(self.rows):
            if row['name']==name:
                if self.table.currentRow()!=i: self.table.setCurrentCell(i,1)
                break
    def refresh_if_ready(self):
        if not self.manager.custom_updating: self.refresh()
    def refresh(self):
        if self.updating: return
        m=self.manager; self.updating=True; self.table.blockSignals(True)
        try:
            old=self.rows[self.table.currentRow()]['name'] if 0<=self.table.currentRow()<len(self.rows) else m.custom_choice.currentText()
            self.rows=[dict(name=name,factors=row.get('factors',{}),enabled=row.get('enabled',True),origin='Custom',source=row) for name,row in json.loads(m.custom.toPlainText() or '{}').items()]
            for preset in presets():
                if preset['id'] not in m.enabled: continue
                derived,warnings=derive(preset,m.model(),m.config())
                if not warnings:
                    for row in derived: self.rows.append(dict(row,enabled=True,origin=preset['method']+' · ข้อ '+preset['clause'],preset=preset))
            cases=m.original['cases']; self.table.setColumnCount(len(cases)+4); self.table.setHorizontalHeaderLabels(['ใช้','Combination','ที่มา']+cases+['สูตร']); self.table.setRowCount(len(self.rows))
            self.table.setColumnWidth(0,45); self.table.setColumnWidth(1,210); self.table.setColumnWidth(2,130)
            for col in range(3,3+len(cases)): self.table.setItemDelegateForColumn(col,FactorDelegate(self.table)); self.table.setColumnWidth(col,85)
            self.table.setColumnWidth(3+len(cases),350)
            selected=-1
            for i,row in enumerate(self.rows):
                protected=row['origin']!='Custom'
                origin=row['origin']+(' · clone '+str(row.get('source',{}).get('cloned_from')) if row.get('source',{}).get('cloned_from') else '')
                for col,text in enumerate(['',row['name'],origin]+[repr(row['factors'].get(c,0.)) for c in cases]+[formula(row['factors'])]):
                    item=QTableWidgetItem(text); item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable)
                    if col==0:
                        if not protected: item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                        item.setCheckState(Qt.CheckState.Checked if row['enabled'] else Qt.CheckState.Unchecked)
                    elif 3<=col<3+len(cases):
                        item.setData(Qt.ItemDataRole.UserRole,row['factors'].get(cases[col-3],0.))
                        if not protected: item.setFlags(item.flags()|Qt.ItemFlag.ItemIsEditable)
                    if protected: item.setToolTip('สูตรต้นฉบับตามกฎหมาย — ทำสำเนาเป็น Custom เพื่อแก้ไข')
                    self.table.setItem(i,col,item)
                if row['name']==old: selected=i
            if self.rows: self.table.setCurrentCell(selected if selected>=0 else 0,1)
            self.filter()
        finally: self.table.blockSignals(False); self.updating=False
        self.select(self.table.currentRow())
    def filter(self,*args):
        tokens=self.search.text().casefold().split()
        for i,row in enumerate(self.rows): self.table.setRowHidden(i,not all(t in (row['name']+' '+row['origin']+' '+formula(row['factors'])).casefold() for t in tokens))
    def select(self,row,*args):
        if self.updating or not 0<=row<len(self.rows): return
        entry=self.rows[row]; m=self.manager; editable=entry['origin']=='Custom'
        if editable: m.custom_choice.setCurrentText(entry['name'])
        m.custom_enabled.setEnabled(editable); m.custom_factors.setEnabled(editable); m.rename_custom_button.setEnabled(editable); m.remove_custom_button.setEnabled(editable)
        provenance=entry.get('source',{}).get('cloned_from')
        m.custom_origin.setText(entry['origin']+' · '+entry['name']+(' · clone '+str(provenance) if provenance else '')); m.update_custom_formula(entry['factors'])
        if not editable and hasattr(m,'factor_details'): m.factor_details.toggle.setChecked(False)
    def edit(self,item):
        if self.updating or not 0<=item.row()<len(self.rows): return
        row=self.rows[item.row()]; m=self.manager
        if row['origin']!='Custom': self.refresh(); return
        try:
            custom=json.loads(m.custom.toPlainText()); entry=custom[row['name']]
            if item.column()==0: entry['enabled']=item.checkState()==Qt.CheckState.Checked
            elif 3<=item.column()<3+len(m.original['cases']):
                value=float(item.text())
                if not math.isfinite(value): raise ValueError('ตัวคูณต้องเป็นตัวเลขที่มีค่าจำกัด')
                case=m.original['cases'][item.column()-3]
                if value: entry['factors'][case]=value
                else: entry['factors'].pop(case,None)
                self.updating=True; item.setData(Qt.ItemDataRole.UserRole,value); self.updating=False
            else: return
            m.custom_updating=True; m.custom.setPlainText(json.dumps(custom)); m.custom_updating=False; m.custom_error=None
            row['factors']=entry['factors']; row['enabled']=entry.get('enabled',True)
            self.updating=True; self.table.item(item.row(),self.table.columnCount()-1).setText(formula(row['factors'])); self.updating=False
            m.custom_choice.setCurrentText(row['name']); m.show_custom(); self.select_name(row['name']); self.filter(); self.notice.setText('แก้ไขแล้ว — กดบันทึกเพื่อนำไปใช้; ผลเดิมจะเป็น Stale')
        except Exception as exc:
            m.custom_updating=False; self.updating=False; m.custom_error=str(exc); self.notice.setText(str(exc)); m.warning.setText(str(exc))
            if 3<=item.column()<3+len(m.original['cases']):
                self.updating=True; item.setText(repr(row['factors'].get(m.original['cases'][item.column()-3],0.))); self.updating=False
    def duplicate(self):
        index=self.table.currentRow()
        if not 0<=index<len(self.rows): return
        row=self.rows[index]; custom=json.loads(self.manager.custom.toPlainText()); base=('Custom ' if row['name'].startswith('TH2566-') else '')+row['name']+' copy'; name=base; i=2
        while name in custom or name in self.manager.original['cases']: name=base+' '+str(i); i+=1
        custom[name]=clone_custom(row['preset'],name,row['factors']) if row.get('preset') else copy.deepcopy(custom[row['name']]); custom[name]['enabled']=True
        self.manager.custom.setPlainText(json.dumps(custom)); self.manager.custom_choice.setCurrentText(name); self.refresh(); self.select_name(name)

class LoadingGenerator(QDialog):
    def __init__(self,manager):
        super().__init__(manager); self.manager=manager; self.config=copy.deepcopy(manager.config()); self.data=None; self.refreshing=False
        self.setWindowTitle('Loading Generator — สร้างชุดรวมแรง'); self.resize(850,600); apply_style(self); box=QVBoxLayout(self)
        help=QLabel('1 เลือกวิธีและกรณีแรง → 2 ตรวจสูตรและ Missing Input → 3 เลือกชุดที่ต้องการ\nใช้ Thailand 2566 จาก Code Pack เดิม; ไม่สร้างแรงลม/แผ่นดินไหวหรือ Load Case เปล่าแทนข้อมูลที่ขาด'); help.setWordWrap(True); box.addWidget(help)
        row=QHBoxLayout(); self.method=QComboBox(); self.method.addItems(['ASD','LRFD']); self.method.setCurrentText(manager.method.currentText() if manager.method.currentText()!='Custom' else 'LRFD'); row.addWidget(QLabel('วิธี')); row.addWidget(self.method); self.bindings={}
        for action,title in (('D','Dead Load'),('L','Live Load')):
            control=QComboBox(); control.addItem('— ยังไม่ระบุ —',''); [control.addItem(c,c) for c in manager.original['cases']]
            previous=self.config['bindings'].get(action,[])
            if len(previous)==1: control.setCurrentIndex(control.findData(previous[0]))
            elif len(previous)>1: control.addItem('ใช้ชุดที่ผูกไว้: '+', '.join(previous),tuple(previous)); control.setCurrentIndex(control.count()-1)
            row.addWidget(QLabel(title)); row.addWidget(control); self.bindings[action]=control; control.currentIndexChanged.connect(self.refresh)
        box.addLayout(row); winds=QHBoxLayout(); winds.addWidget(QLabel('Wind — เลือกเป็นทิศทางทางเลือก')); self.winds=[]
        for case in manager.original['cases']:
            if case in self.config['bindings'].get('W',[]) or case in ('WX','WY','WX+','WX-','WY+','WY-','WX−','WY−'):
                check=QCheckBox(case); check.setChecked(case in self.config['bindings'].get('W',[])); check.toggled.connect(self.refresh); winds.addWidget(check); self.winds.append(check)
        box.addLayout(winds); self.table=QTableWidget(0,3); self.table.setHorizontalHeaderLabels(['เลือก','สูตร / ข้อกฎหมาย','สูตรจริง / สถานะ']); self.table.horizontalHeader().setStretchLastSection(True); self.table.setColumnWidth(0,50); self.table.setColumnWidth(1,270); box.addWidget(self.table,1)
        self.summary=QLabel(); self.summary.setWordWrap(True); box.addWidget(self.summary)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel); buttons.button(QDialogButtonBox.StandardButton.Ok).setText('ใช้รายการที่เลือก'); buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('ยกเลิก'); buttons.accepted.connect(self.apply); buttons.rejected.connect(self.reject); box.addWidget(buttons)
        self.method.currentTextChanged.connect(self.refresh); self.table.itemChanged.connect(self.update_summary); self.refresh()
    def draft(self):
        config=copy.deepcopy(self.config); config['method']=self.method.currentText(); config['methods']=sorted(set(config.get('methods',[]))|{self.method.currentText()}); config['enabled']=[]
        for action,control in self.bindings.items():
            value=control.currentData(); config['bindings'][action]=list(value) if isinstance(value,tuple) else [value] if value else []
        config['bindings']['W']=[c.text() for c in self.winds if c.isChecked()]; return config
    def refresh(self,*args):
        if self.refreshing: return
        self.refreshing=True; self.table.blockSignals(True)
        try:
            self.rows=presets(self.method.currentText()); self.table.setRowCount(len(self.rows)); config=self.draft()
            for i,preset in enumerate(self.rows):
                rows,warnings=derive(preset,self.manager.model(),config); item=QTableWidgetItem(); item.setFlags(Qt.ItemFlag.ItemIsSelectable|Qt.ItemFlag.ItemIsUserCheckable|(Qt.ItemFlag.ItemIsEnabled if not warnings else Qt.ItemFlag.NoItemFlags)); item.setCheckState(Qt.CheckState.Checked if not warnings else Qt.CheckState.Unchecked); self.table.setItem(i,0,item)
                for col,text in ((1,preset['formula']+' · ข้อ '+preset['clause']),(2,'; '.join(warnings) if warnings else '\n'.join(formula(r['factors']) for r in rows))):
                    cell=QTableWidgetItem(text); cell.setFlags(cell.flags()&~Qt.ItemFlag.ItemIsEditable); cell.setToolTip(text); self.table.setItem(i,col,cell)
            self.table.resizeRowsToContents()
        finally: self.table.blockSignals(False); self.refreshing=False
        self.update_summary()
    def update_summary(self,*args):
        chosen=sum(self.table.item(i,0).checkState()==Qt.CheckState.Checked for i in range(self.table.rowCount())); self.summary.setText(f'เลือก {chosen} สูตรต้นฉบับ — ทิศทางลมสร้างแยกกัน; Custom เดิมคงไว้\nหากข้อมูลขาด ให้กลับไปเพิ่ม Load Case หรือแก้การผูกประเภทแรงก่อน')
    def apply(self):
        self.data=self.draft(); self.data['enabled']=[p['id'] for i,p in enumerate(self.rows) if self.table.item(i,0).checkState()==Qt.CheckState.Checked and bool(self.table.item(i,0).flags()&Qt.ItemFlag.ItemIsEnabled)]
        if not self.data['enabled']: self.summary.setText('เลือกสูตรที่พร้อมอย่างน้อยหนึ่งรายการ'); return
        other={p['id'] for p in presets() if p['method']!=self.method.currentText()}
        self.data['enabled']=sorted(set(self.data['enabled']) | (set(self.config.get('enabled',[])) & other))
        self.accept()
