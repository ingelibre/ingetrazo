"""Reviewed statutory presets and explicitly labelled Custom combinations."""
import copy
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPlainTextEdit,QTableWidget,QTableWidgetItem,QPushButton,QDialogButtonBox,QLineEdit,QCheckBox,QScrollArea,QWidget,QTabWidget,QToolButton,QMenu,QDoubleSpinBox
from PySide6.QtGui import QAction
from .thai_code import PACK,ACTIONS,presets,derive,apply_manager,clone_custom
from .model import validate
from .theme import apply_style

class FactorInput(QDoubleSpinBox):
    def textFromValue(self,value):
        return format(value,'.15f').rstrip('0').rstrip('.') if value else '0'

class CombinationManager(QDialog):
    def __init__(self,model,parent=None):
        super().__init__(parent); self.original=copy.deepcopy(model); self.data=None
        self.setWindowTitle('Load Combinations — รวมกรณีแรง'); self.resize(920,760); apply_style(self)
        box=QVBoxLayout(self); heading=QLabel('Load Combination — รวมกรณีแรงด้วยตัวคูณ'); box.addWidget(heading)
        link=QLabel('<a href="'+PACK['source_url']+'">Thailand 2566 · Gazette 6 September 2566 · clauses 6–7 · pack '+PACK['version']+'</a>'); link.setOpenExternalLinks(True); box.addWidget(link)
        self.code_link=link
        box.addWidget(QLabel('Load factors only. Capacity / code compliance: Not Available. Earthquake actions require separate verification.'))
        config=model.get('combination_manager',{})
        self.method=QComboBox(); self.method.addItems(['ASD','LRFD','ASD + LRFD','Custom']); self.method.setCurrentText('ASD + LRFD' if set(config.get('methods',[]))=={'ASD','LRFD'} else config.get('method','Custom')); self.method.setToolTip('Custom = กำหนดเอง | ASD / LRFD = Preset Thailand 2566'); box.addWidget(self.method)
        box.addWidget(QLabel('Action bindings — choose actual cases; W/E entries are alternatives, not simultaneous.'))
        self.bindings=QTableWidget(7,2); self.bindings.setHorizontalHeaderLabels(['Action / ความหมาย','เลือก Load Case']); self.bindings.horizontalHeader().setStretchLastSection(True)
        defaults={'D':['DL'] if 'DL' in model['cases'] else [],'L':['LL'] if 'LL' in model['cases'] else [],'W':[c for c in model['cases'] if c in ('WX','WY','WX+','WX-','WY+','WY-','WX−','WY−')],'E':[]}
        for i,(action,meaning) in enumerate(ACTIONS.items()):
            item=QTableWidgetItem(action+' — '+meaning); item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable); self.bindings.setItem(i,0,item)
            self.bindings.setItem(i,1,QTableWidgetItem(', '.join(config.get('bindings',defaults).get(action,[]))))
        self.bindings.setColumnWidth(0,450); self.bindings.setMaximumHeight(210); box.addWidget(self.bindings)
        self.binding_choices={}
        for i,action in enumerate(ACTIONS):
            button=QToolButton(); button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup); menu=QMenu(button); choices=[]
            selected=config.get('bindings',defaults).get(action,[])
            for case in model['cases']:
                option=QAction(case,menu); option.setCheckable(True); option.setChecked(case in selected); menu.addAction(option); choices.append(option)
                option.toggled.connect(lambda checked,a=action,row=i,b=button:self.update_binding(a,row,b))
            button.setMenu(menu); self.binding_choices[action]=choices; self.bindings.setCellWidget(i,1,button); button.setText(', '.join(c.text() for c in choices if c.isChecked()) or 'เลือก Load Case…')
        self.verification=QTableWidget(4,3); self.verification.setHorizontalHeaderLabels(['Action review','Confirmed','Independent reference / source']); self.verification.setMaximumHeight(145); self.verification.horizontalHeader().setStretchLastSection(True); self.review_fields={}
        for i,action in enumerate('EHFT'):
            info=config.get('action_verification',{}).get(action,{})
            self.verification.setItem(i,0,QTableWidgetItem(action+' — '+('seismic action verified separately' if action=='E' else 'reviewed equivalent-force model')))
            self.verification.item(i,0).setFlags(self.verification.item(i,0).flags()&~Qt.ItemFlag.ItemIsEditable)
            check=QCheckBox(); check.setChecked(info.get('verified_action' if action=='E' else 'equivalent_force_model',False)); self.verification.setCellWidget(i,1,check)
            reference=QLineEdit(str(info.get('reference',''))); self.verification.setCellWidget(i,2,reference); self.review_fields[action]=(check,reference)
        self.verification.setColumnWidth(0,330); box.addWidget(self.verification)
        sw=QHBoxLayout(); sw.addWidget(QLabel('Automatic self-weight case (must belong to D)')); self.sw_case=QComboBox(); self.sw_case.addItems(model['cases']); self.sw_case.setCurrentText(model.get('self_weight_case','DL')); sw.addWidget(self.sw_case); box.addLayout(sw)
        self.table=QTableWidget(0,4); self.table.setHorizontalHeaderLabels(['Enable','Clause / Formula','Availability','Derived directions']); self.table.horizontalHeader().setStretchLastSection(True); box.addWidget(self.table,1)
        self.preview=QLabel(); self.preview.setWordWrap(True); self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); box.addWidget(self.preview)
        row=QHBoxLayout(); self.custom_name=QLineEdit(); self.custom_name.setPlaceholderText('Custom combination name'); row.addWidget(self.custom_name); clone=QPushButton('Clone selected as Custom'); clone.clicked.connect(self.clone); row.addWidget(clone); box.addLayout(row)
        self.custom=QPlainTextEdit(); self.custom.setMaximumHeight(95)
        initial=config.get('custom',{}) or {name:dict(factors=f,method='Custom') for name,f in model.get('combinations',{}).items() if not name.startswith('TH2566-')}
        self.custom.setPlainText(json.dumps(initial,indent=2)); box.addWidget(QLabel('Combinations — Custom แก้ไขได้; ASD / LRFD เป็นต้นฉบับ Read-only')); box.addWidget(self.custom)
        self.warning=QLabel(); self.warning.setWordWrap(True); box.addWidget(self.warning)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept_model); buttons.rejected.connect(self.reject); box.addWidget(buttons)
        self.enabled=set(config.get('enabled',[])); self.refreshing=False
        self.method.currentTextChanged.connect(self.rebuild); self.bindings.itemChanged.connect(self.rebuild); self.sw_case.currentTextChanged.connect(self.rebuild)
        for check,reference in self.review_fields.values(): check.toggled.connect(self.rebuild); reference.textChanged.connect(self.rebuild)
        self.table.currentCellChanged.connect(self.show_preview); self.table.itemChanged.connect(self.toggle)
        # Keep the formula list usable on a laptop; input review and Custom editing
        # have their own pages rather than squeezing 11 combinations into one row.
        items=[]
        while box.count()>4: items.append(box.takeAt(4))
        self.pages=QTabWidget(); box.addWidget(self.pages,1)
        for title,indexes in [('Inputs / action review',(0,1,2,3)),('Statutory presets',(4,5,6)),('Custom factors',(7,8))]:
            page=QWidget(); page_box=QVBoxLayout(page); self.pages.addTab(page,title)
            for index in indexes:
                item=items[index]
                if item.widget(): page_box.addWidget(item.widget(),1 if index==4 else 0)
                elif item.layout(): item.layout().setParent(None); page_box.addLayout(item.layout())
            if title!='Statutory presets': page_box.addStretch()
        box.addWidget(self.warning); box.addWidget(buttons); self.pages.setCurrentIndex(1)
        self.table.setMinimumHeight(260)
        self.factor_table=QTableWidget(1,7); self.factor_table.setHorizontalHeaderLabels(list(ACTIONS)); self.factor_table.setVerticalHeaderLabels(['Factor']); self.factor_table.setMaximumHeight(80)
        self.pages.widget(1).layout().insertWidget(2,self.factor_table)
        custom_box=self.pages.widget(2).layout(); self.custom.hide(); self.custom_updating=False; self.custom_error=None
        toolbar=QHBoxLayout(); self.custom_choice=QComboBox(); self.custom_choice.setMinimumWidth(170); toolbar.addWidget(self.custom_choice)
        self.custom_enabled=QCheckBox('ใช้งาน'); toolbar.addWidget(self.custom_enabled)
        self.new_custom_name=QLineEdit(); self.new_custom_name.setPlaceholderText('ชื่อ Combination เช่น Gravity ULS'); toolbar.addWidget(self.new_custom_name)
        add_custom=QPushButton('+ เพิ่ม Combination'); add_custom.clicked.connect(self.add_custom); toolbar.addWidget(add_custom); custom_box.insertLayout(1,toolbar)
        rename_custom=QPushButton('เปลี่ยนชื่อ'); rename_custom.clicked.connect(self.rename_custom); toolbar.addWidget(rename_custom)
        remove_custom=QPushButton('ลบ'); remove_custom.clicked.connect(self.remove_custom); toolbar.addWidget(remove_custom)
        self.rename_custom_button=rename_custom; self.remove_custom_button=remove_custom
        self.custom_factors=QTableWidget(0,2); self.custom_factors.setHorizontalHeaderLabels(['Load Case / กรณีแรง','ตัวคูณแรง']); self.custom_factors.setMinimumHeight(260); self.custom_factors.setColumnWidth(0,230); self.custom_factors.horizontalHeader().setStretchLastSection(True); custom_box.insertWidget(2,self.custom_factors)
        self.custom_origin=QLabel(); custom_box.insertWidget(3,self.custom_origin)
        self.custom_formula=QLabel(); self.custom_formula.setWordWrap(True); custom_box.insertWidget(4,self.custom_formula)
        custom_box.insertWidget(0,QLabel('เลือก Combination → กรอกตัวคูณของแต่ละ Load Case เช่น DL = 1.4, LL = 1.7\nตัวคูณ 0 หมายถึงไม่รวมกรณีแรงนั้น; ตัวคูณติดลบใช้กลับทิศแรง'))
        self.custom.textChanged.connect(self.refresh_custom); self.custom_choice.currentTextChanged.connect(self.show_custom); self.custom_factors.itemChanged.connect(self.edit_custom_factor); self.custom_enabled.toggled.connect(self.edit_custom_enabled)
        self.refresh_custom()
        self.rebuild()
        self.pages.setCurrentIndex(2 if self.method.currentText()=='Custom' else 1)
        self.method.currentTextChanged.connect(lambda method:self.pages.setCurrentIndex(2 if method=='Custom' else 1))
        link.setVisible(self.method.currentText()!='Custom'); self.method.currentTextChanged.connect(lambda method:link.setVisible(method!='Custom'))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('บันทึก'); buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('ยกเลิก')
        from .combination_tools import CombinationOverview
        from .workspace_ui import Section
        position=custom_box.indexOf(self.custom_factors); custom_box.removeWidget(self.custom_factors)
        self.overview=CombinationOverview(self); custom_box.insertWidget(position,self.overview,1)
        self.factor_details=Section('รายละเอียดตัวคูณของ Combination ที่เลือก',self); self.factor_details.layout.addWidget(self.custom_factors); self.factor_details.toggle.setChecked(False); custom_box.insertWidget(position+1,self.factor_details)
        self.generator_button=QPushButton('Loading Generator… — สร้าง Preset'); self.generator_button.clicked.connect(self.open_generator); box.insertWidget(4,self.generator_button)
        self.pages.setTabText(2,'Combinations / ตารางตัวคูณ')
        self.new_custom_name.returnPressed.connect(self.add_custom)
        self.pages.setCurrentIndex(2)
    def open_generator(self):
        from .combination_tools import LoadingGenerator
        dialog=LoadingGenerator(self)
        if dialog.exec():
            config=dialog.data; self.enabled=set(config['enabled'])
            self.method.blockSignals(True); self.method.setCurrentText(config['method']); self.method.blockSignals(False)
            self.code_link.setVisible(config['method']!='Custom')
            for i,action in enumerate(ACTIONS):
                button=self.bindings.cellWidget(i,1)
                for option in self.binding_choices[action]:
                    option.blockSignals(True); option.setChecked(option.text() in config['bindings'].get(action,[])); option.blockSignals(False)
                self.bindings.blockSignals(True); self.update_binding(action,i,button); self.bindings.blockSignals(False)
            self.rebuild(); self.pages.setCurrentIndex(2)
    def update_binding(self,action,row,button):
        text=', '.join(c.text() for c in self.binding_choices[action] if c.isChecked()); button.setText(text or 'เลือก Load Case…'); self.bindings.item(row,1).setText(text)
    def rename_custom(self):
        name=self.new_custom_name.text().strip(); old=self.custom_choice.currentText(); custom=json.loads(self.custom.toPlainText() or '{}')
        if not old or not name or name in custom or name in self.original['cases'] or name.startswith('TH2566-'): self.warning.setText('เลือก Combination และกรอกชื่อใหม่ที่ไม่ซ้ำ'); return
        custom[name]=custom.pop(old); self.custom.setPlainText(json.dumps(custom)); self.custom_choice.setCurrentText(name)
    def remove_custom(self):
        custom=json.loads(self.custom.toPlainText() or '{}'); name=self.custom_choice.currentText()
        if name in custom: del custom[name]; self.custom.setPlainText(json.dumps(custom))
    def config(self):
        selected=self.method.currentText()
        methods={r['method'] for r in presets() if r['id'] in self.enabled}
        methods.update(['ASD','LRFD'] if selected=='ASD + LRFD' else [selected] if selected!='Custom' else [])
        return dict(method='ASD' if selected=='ASD + LRFD' else selected,methods=sorted(methods),pack_version=PACK['version'],bindings={a:[option.text() for option in self.binding_choices[a] if option.isChecked()] for a in ACTIONS},action_verification={a:{'verified_action' if a=='E' else 'equivalent_force_model':check.isChecked(),'reference':reference.text().strip()} for a,(check,reference) in self.review_fields.items()},enabled=sorted(self.enabled),custom=json.loads(self.custom.toPlainText() or '{}'))
    def model(self):
        model=copy.deepcopy(self.original)
        if model.get('self_weight'): model['self_weight_case']=self.sw_case.currentText()
        return model
    def rebuild(self,*args):
        if self.refreshing: return
        self.refreshing=True
        try:
            config=self.config(); self.rows=presets() if self.method.currentText()=='ASD + LRFD' else presets(self.method.currentText()); self.table.setRowCount(len(self.rows))
            for i,preset in enumerate(self.rows):
                derived,warnings=derive(preset,self.model(),config); enabled=not warnings
                check=QTableWidgetItem(); check.setFlags(Qt.ItemFlag.ItemIsUserCheckable|Qt.ItemFlag.ItemIsSelectable|(Qt.ItemFlag.ItemIsEnabled if enabled else Qt.ItemFlag.NoItemFlags)); check.setCheckState(Qt.CheckState.Checked if preset['id'] in self.enabled and enabled else Qt.CheckState.Unchecked)
                if not enabled: self.enabled.discard(preset['id'])
                self.table.setItem(i,0,check)
                for j,text in enumerate((preset['clause']+' · '+preset['formula'],'Ready' if enabled else '; '.join(warnings),str(len(derived))),1):
                    item=QTableWidgetItem(text); item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable); self.table.setItem(i,j,item)
            self.table.resizeColumnsToContents(); self.table.setColumnWidth(2,300); self.warning.setText('กรอกตัวคูณแล้วกดบันทึก; สูตรนี้เป็น Custom ที่ผู้ใช้กำหนด' if self.method.currentText()=='Custom' else 'Preset factors are read-only. Clone to edit. Choose a reviewed envelope group in Results.')
        except Exception as exc: self.warning.setText('Invalid input: '+str(exc))
        finally: self.refreshing=False
        self.show_preview()
        if hasattr(self,'overview'): self.overview.refresh()
    def toggle(self,item):
        if self.refreshing or item.column()!=0: return
        identifier=self.rows[item.row()]['id']
        if item.checkState()==Qt.CheckState.Checked: self.enabled.add(identifier)
        else: self.enabled.discard(identifier)
        self.show_preview()
        if hasattr(self,'overview'): self.overview.refresh()
    def show_preview(self,*args):
        i=self.table.currentRow()
        if i<0 and getattr(self,'rows',[]): i=0
        if i<0 or i>=len(getattr(self,'rows',[])): self.preview.setText('Custom method: editable factors below'); return
        p=self.rows[i]
        self.preview.setText(p['formula']+'\nFactor table: '+', '.join(f'{a} × {f:g}' for a,f in p['factors'].items())+'\nClause '+p['clause']+' · '+p['method']+' · Original statutory formula')
        if hasattr(self,'factor_table'):
            for j,action in enumerate(ACTIONS):
                item=QTableWidgetItem(str(p['factors'][action]) if action in p['factors'] else '—'); item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable); self.factor_table.setItem(0,j,item)
    def refresh_custom(self):
        if self.custom_updating: return
        try:
            custom=json.loads(self.custom.toPlainText() or '{}'); old=self.custom_choice.currentText(); self.custom_choice.blockSignals(True); self.custom_choice.clear(); self.custom_choice.addItems(custom); self.custom_choice.setCurrentText(old if old in custom else (next(iter(custom)) if custom else '')); self.custom_choice.blockSignals(False); self.show_custom()
        except Exception as exc: self.custom_error=str(exc); self.warning.setText(str(exc))
    def show_custom(self,*args):
        self.custom_updating=True
        try:
            row=json.loads(self.custom.toPlainText() or '{}').get(self.custom_choice.currentText(),{}); self.custom_factors.setRowCount(len(self.original['cases']))
            self.custom_factors.setEnabled(bool(self.custom_choice.currentText())); self.custom_enabled.setEnabled(bool(self.custom_choice.currentText()))
            self.custom_enabled.setChecked(row.get('enabled',True)); self.custom_origin.setText('Custom · cloned from '+str(row.get('cloned_from','user-defined')))
            for i,case in enumerate(self.original['cases']):
                item=QTableWidgetItem(case); item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable); self.custom_factors.setItem(i,0,item); self.custom_factors.setItem(i,1,QTableWidgetItem(str(row.get('factors',{}).get(case,0))))
                factor=FactorInput(); factor.setDecimals(15); factor.setRange(-1e100,1e100); factor.setSingleStep(.1); factor.setValue(row.get('factors',{}).get(case,0)); factor.setToolTip('ตัวคูณแรง: 0 = ไม่รวม, ค่าลบ = กลับทิศ'); factor.valueChanged.connect(lambda value,r=i:self.custom_factors.item(r,1).setText(repr(value))); self.custom_factors.setCellWidget(i,1,factor)
            self.update_custom_formula(row.get('factors',{}))
        finally: self.custom_updating=False
    def update_custom_formula(self,factors):
        parts=[]
        for case,value in factors.items():
            if not value: continue
            parts.append(('− ' if value<0 else '+ ' if parts else '')+f'{abs(value):g} × {case}')
        self.custom_formula.setText('สูตร: '+(' '.join(parts) or 'ยังไม่ได้เลือกกรณีแรง — กรอกตัวคูณอย่างน้อยหนึ่งรายการ'))
    def add_custom(self):
        name=self.new_custom_name.text().strip(); custom=json.loads(self.custom.toPlainText() or '{}')
        if not name or name in custom or name in self.original['cases'] or name.startswith('TH2566-'): self.warning.setText('กรอกชื่อ Combination ที่ไม่ซ้ำกับ Load Case / Combination'); return
        custom[name]=dict(factors={self.original['cases'][0]:1.},enabled=True); self.custom.setPlainText(json.dumps(custom)); self.custom_choice.setCurrentText(name)
        if hasattr(self,'overview'): self.overview.select_name(name)
        self.pages.setCurrentIndex(2)
    def edit_custom_factor(self,item):
        if self.custom_updating or item.column()!=1: return
        try:
            import math
            custom=json.loads(self.custom.toPlainText() or '{}'); name=self.custom_choice.currentText()
            if not name: raise ValueError('Add or clone a Custom combination first')
            factors={}
            for i,case in enumerate(self.original['cases']):
                value=float(self.custom_factors.item(i,1).text())
                if not math.isfinite(value): raise ValueError('Factors must be finite')
                if value: factors[case]=value
            custom[name]['factors']=factors; self.custom_error=None; self.custom_updating=True; self.custom.setPlainText(json.dumps(custom)); self.warning.setText('Custom factors edited; original statutory factors unchanged')
            self.update_custom_formula(factors)
        except Exception as exc: self.custom_error=str(exc); self.warning.setText(str(exc))
        finally: self.custom_updating=False
        if hasattr(self,'overview'): self.overview.refresh()
    def edit_custom_enabled(self,enabled):
        if self.custom_updating: return
        custom=json.loads(self.custom.toPlainText() or '{}'); name=self.custom_choice.currentText()
        if name: custom[name]['enabled']=enabled; self.custom_updating=True; self.custom.setPlainText(json.dumps(custom)); self.custom_updating=False
        if hasattr(self,'overview'): self.overview.refresh()
    def clone(self):
        try:
            i=max(0,self.table.currentRow()); p=self.rows[i]; rows,warnings=derive(p,self.model(),self.config())
            if warnings: raise ValueError('; '.join(warnings))
            name=self.custom_name.text().strip()
            if not name: raise ValueError('Enter a Custom name')
            custom=json.loads(self.custom.toPlainText() or '{}'); created=[]
            for n,row in enumerate(rows):
                label=name if len(rows)==1 else name+' / '+','.join(row['directions'].values())
                if label in custom: raise ValueError('Custom name already exists')
                custom[label]=clone_custom(p,label,row['factors'])
                created.append(label)
            self.custom.setPlainText(json.dumps(custom,indent=2)); self.warning.setText('Cloned into Custom. The statutory formula remains unchanged.')
            if created:
                self.custom_choice.setCurrentText(created[0])
                if hasattr(self,'overview'): self.overview.select_name(created[0])
            self.pages.setCurrentIndex(2)
        except Exception as exc: self.warning.setText(str(exc))
    def accept_model(self):
        try:
            if self.custom_error: raise ValueError(self.custom_error)
            self.data=validate(apply_manager(self.model(),self.config())); self.accept()
        except Exception as exc: self.warning.setText('Cannot apply: '+str(exc))
