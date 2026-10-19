"""Compact member inspector and modeless result tables."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QDoubleSpinBox,QSlider,QLabel,QPushButton,QDialog,QTabWidget,QTableWidget,QTableWidgetItem,QFileDialog,QCheckBox
from .results import evaluate,is_current,export_csv,export_report,UNITS,tables3d
from .display import format_value
from .theme import ThemeAware,apply_style
from .icons import icon

class Inspector(QWidget):
    def __init__(self,panel):
        super().__init__(panel); self.panel=panel; self.dialog=None; self.last_table_key=None
        box=QVBoxLayout(self); box.setContentsMargins(0,0,0,0); box.setSpacing(6)
        title=QLabel('Result Inspector'); title.setObjectName('goSection'); box.addWidget(title)
        self.member=QComboBox(); self.member.setToolTip('Click a member on the viewport or choose its ID'); box.addWidget(self.member)
        row=QHBoxLayout(); self.ratio=QDoubleSpinBox(); self.ratio.setRange(0,1); self.ratio.setDecimals(4); self.ratio.setSingleStep(0.01); self.ratio.setPrefix('x/L = '); row.addWidget(self.ratio)
        self.side=QComboBox(); self.side.addItems(['right','left']); self.side.setToolTip('Value to the right/left of a load discontinuity'); row.addWidget(self.side); box.addLayout(row)
        self.slider=QSlider(Qt.Orientation.Horizontal); self.slider.setRange(0,1000); box.addWidget(self.slider)
        self.envelope=QCheckBox('Combination envelope at x/L'); self.envelope.toggled.connect(self.update_values); box.addWidget(self.envelope)
        self.values=QLabel('Select a member and Run Analysis'); self.values.setWordWrap(True); box.addWidget(self.values)
        row=QHBoxLayout(); tables=QPushButton('Result Tables…'); tables.clicked.connect(self.show_tables); row.addWidget(tables)
        self.csv=QPushButton('Export CSV…'); self.csv.clicked.connect(self.export); row.addWidget(self.csv); box.addLayout(row)
        self.archive=QPushButton('Export Archived/Stale CSV…'); self.archive.clicked.connect(lambda:self.export(True)); box.addWidget(self.archive)
        self.member.currentTextChanged.connect(self.update_values); self.ratio.valueChanged.connect(self.ratio_changed); self.slider.valueChanged.connect(self.slider_changed); self.side.currentTextChanged.connect(self.update_values)
    def slider_changed(self,value): self.ratio.setValue(value/1000)
    def ratio_changed(self,value):
        self.slider.blockSignals(True); self.slider.setValue(round(value*1000)); self.slider.blockSignals(False); self.update_values()
    def select(self,mid,ratio=None):
        self.member.setCurrentText(mid)
        if ratio is not None: self.ratio.setValue(ratio)
        self.update_values()
    def refresh(self):
        ids=[m['id'] for m in (self.panel.model() or {}).get('members',[])]; old=self.member.currentText()
        if [self.member.itemText(i) for i in range(self.member.count())]!=ids:
            self.member.blockSignals(True); self.member.clear(); self.member.addItems(ids); self.member.setCurrentText(old if old in ids else (ids[0] if ids else '')); self.member.blockSignals(False)
        self.csv.setEnabled(self.panel.results_are_current()); self.archive.setEnabled(bool(self.panel.result and self.panel.result.get('input_model'))); self.update_values()
        if self.dialog and self.dialog.isVisible(): self.populate_tables()
    def update_values(self,*args):
        p=self.panel; mid=self.member.currentText(); case=p.case.currentText()
        if not p.results_are_current(): self.values.setText(p.result_status()+' — Results out of date; Run Analysis' if p.result else p.result_status()+' — Run Analysis to inspect N / V / M / D'); p.app.viewport.update(); return
        m=p.result['cases'].get(case,{}).get('members',{}).get(mid)
        if not m: return
        v=evaluate(m,self.ratio.value()*m['L'],self.side.currentText())
        if self.envelope.isChecked():
                envelope=p.result.get('envelope_groups',{}).get(p.envelope_group.currentText(),p.result['envelope'])
                names=envelope['combinations']; lines=[f'{mid} · {p.envelope_group.currentText()} envelope @ x/L={self.ratio.value():.4f} ({self.side.currentText()})']
                for k in (('N','Vy','Vz','T','My','Mz','D') if (p.model() or {}).get('schema')==2 else ('N','V','M','d')):
                    pairs=[(evaluate(p.result['cases'][name]['members'][mid],self.ratio.value()*m['L'],self.side.currentText())[k],name) for name in names]
                    lo,hi=min(pairs),max(pairs); lines.append(f'{k}: {format_value(lo[0],k,max(abs(lo[0]),abs(hi[0])),p.display_tolerance.value(),p.displacement_mm.isChecked())} ({lo[1]}) … {format_value(hi[0],k,max(abs(lo[0]),abs(hi[0])),p.display_tolerance.value(),p.displacement_mm.isChecked())} ({hi[1]})')
                self.values.setText('\n'.join(lines)); p.app.viewport.update(); return
        if (p.model() or {}).get('schema')==2:
            self.values.setText(f"{mid} · x = {v['x']:.5g} m ({self.side.currentText()})\n"+'\n'.join(f'{k} '+format_value(v[k],k,max(abs(m["extrema"].get(k,{"min":{"value":v[k]},"max":{"value":v[k]}})[t]["value"]) for t in ("min","max")),p.display_tolerance.value(),p.displacement_mm.isChecked()) for k in ('N','Vy','Vz','T','My','Mz','ux','uy','uz','D')))
            p.app.viewport.update(); return
        self.values.setText(f"{mid} · x = {v['x']:.5g} m ({self.side.currentText()})\nN {v['N']:.6g} kN   V {v['V']:.6g} kN\nM {v['M']:.6g} kN·m   D {v['d']*1000:.6g} mm")
        p.app.viewport.update()
    def show_tables(self):
        if self.dialog is None:
            self.dialog=TablesDialog(self); self.dialog.finished.connect(lambda _=0:setattr(self,'last_table_key',None))
        self.populate_tables(); self.dialog.show(); self.dialog.raise_()
    def populate_tables(self):
        p=self.panel; case=p.case.currentText(); r=(p.result or {}).get('cases',{}).get(case)
        self.dialog.notice.setText('Current · Capacity / Code Compliance: Not Available' if p.results_are_current() else p.result_status()+' — ARCHIVED / STALE TABLES; use Archived export only')
        key=(id(p.result),case,p.envelope_group.currentText())
        if self.last_table_key==key: return
        self.last_table_key=key
        if not r:
            for table in self.dialog.tables.values(): table.setRowCount(0)
            return
        snapshot=(p.result.get('input_model') or p.model()) if not p.results_are_current() else p.model()
        if (snapshot or {}).get('schema')==2:
            view=dict(p.result,envelope=p.result.get('envelope_groups',{}).get(p.envelope_group.currentText(),p.result['envelope']))
            for name,(headers,rows) in tables3d(snapshot,view,case).items(): self.dialog.fill(name,headers,rows)
            return
        env=p.result.get('envelope_groups',{}).get(p.envelope_group.currentText(),p.result.get('envelope',{}))
        self.dialog.fill('Member Force Envelope',['Member','Quantity','Type','Value','Unit','x [m]','Side','Governing combination'],[[mid,k,kind,v['value'],UNITS[k],v['x'],v['side'],v['combination']] for mid,row in env.get('members',{}).items() for k,extrema in row.items() for kind,v in extrema.items()])
        self.dialog.fill('Member Diagrams',[],[])
        self.dialog.fill('Node Displacements',['Node','UX [m]','UZ [m]','R_plane [rad]'],[[n,v['ux'],v['uz'],v['rotation']] for n,v in r['nodes'].items()])
        supports={n['id'] for n in (snapshot or {}).get('nodes',[]) if n.get('support','Free')!='Free'}
        self.dialog.fill('Support Reactions',['Node','RX [kN]','RZ [kN]','M_plane [kN·m]'],[[n,v['Rx'],v['Rz'],v['My']] for n,v in r['nodes'].items() if n in supports])
        self.dialog.fill('Member End Forces',['Member','End','FX local [kN]','FY local [kN]','MZ local [kN·m]'],[[mid,end,v['N'],v['V'],v['M']] for mid,m in r['members'].items() for end,v in m.get('end_forces',{}).items()])
        self.dialog.fill('Max / Min',['Member','Quantity','Unit','Type','Value','x [m]','x/L','Side'],[[mid,k,UNITS[k],kind,v['value'],v['x'],v['x']/m['L'],v['side']] for mid,m in r['members'].items() for k,e in m.get('extrema',{}).items() for kind,v in e.items()])
    def export(self,archived=False):
        if not archived and not self.panel.results_are_current(): self.panel.status.setText('Current export disabled — Run Analysis'); return
        directory=QFileDialog.getExistingDirectory(self,'Export result CSV files')
        if not directory: return
        try:
            paths=export_csv(directory,self.panel.model(),self.panel.result,self.panel.case.currentText(),archived=archived); self.panel.status.setText(f'Exported {len(paths)} '+('Archived/Stale ' if archived else 'Current ')+f'CSV files to {directory}')
        except Exception as exc: self.panel.status.setText(str(exc))

class TablesDialog(ThemeAware,QDialog):
    def __init__(self,inspector):
        super().__init__(inspector.panel.app.window); self.setObjectName('goEditor'); apply_style(self); self.setWindowIcon(icon()); self.setWindowTitle('GO Structural Analysis — Result Inspector'); self.resize(760,480); self.setModal(False)
        box=QVBoxLayout(self); self.notice=QLabel(); box.addWidget(self.notice); tabs=QTabWidget(); box.addWidget(tabs); self.tables={}
        for name in ['Node Displacements','Support Reactions','Member End Forces','Max / Min','Member Force Envelope','Member Diagrams']:
            table=QTableWidget(); table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); table.setAlternatingRowColors(True); self.tables[name]=table; tabs.addTab(table,name)
    def fill(self,name,headers,rows):
        t=self.tables[name]; t.setColumnCount(len(headers)); t.setHorizontalHeaderLabels(headers); t.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,value in enumerate(row): t.setItem(i,j,QTableWidgetItem(f'{value:.8g}' if isinstance(value,float) else str(value)))
        t.resizeColumnsToContents()
