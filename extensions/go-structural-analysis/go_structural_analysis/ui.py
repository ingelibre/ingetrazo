import copy
import json
import math
from pathlib import Path
from PySide6.QtCore import Qt, QObject, Signal, Slot, QThread, QPointF, QTimer, QEvent, QSize, QRectF
from PySide6.QtGui import QColor, QPen, QVector3D, QPainter, QPalette
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QDoubleSpinBox,QCheckBox,
    QDialog,QDialogButtonBox,QTabWidget,QTableWidget,QTableWidgetItem,QFileDialog,QMessageBox,QPlainTextEdit,QHeaderView,
    QRadioButton,QButtonGroup,QGridLayout,QScrollArea,QFrame,QToolButton,QLineEdit)
from .model import benchmark,validate
from .client import analyze
from .icons import icon,pixmap

from .theme import ThemeAware, apply_style
from .results import VERSION,is_current,export_report
from .safety import state,validate_result,fingerprint
from .combination_ui import CombinationManager
from .workspace_ui import Section,QuickControls
from .inspector import Inspector
from . import visualization
from .examples import CATALOG, example as example_model
from .materials import PRESETS, NOTES, material_preset
from .model3d import cantilever3d, migrate2d, from_lines, DOFS, GLOBAL, LOCAL
from .examples3d import CATALOG3D, example3d
from .house_example import BUILDING_CATALOG

KEY='go_structural_analysis'
FIELDS={
 'nodes':['id','x','z','support'], 'members':['id','i','j','type','material','section','release_i','release_j'],
 'materials':['id','E','G','nu','rho'], 'sections':['id','A','Iy','Iz','J'],
 'point_loads':['node','member','direction','value','x','case'],
 'distributed_loads':['member','direction','w1','w2','x1','x2','case']}
NUMERIC={'x','z','E','G','nu','rho','A','Iy','Iz','J','value','w1','w2','x1','x2'}
CHOICES={'support':['Free','Fixed','Pin','Roller','RollerX'],'type':['Beam','Frame','Truss'],'direction':['FX','FZ','MY']}
CHOICES.update(release_i=['','False','True'],release_j=['','False','True'])

class Editor(ThemeAware,QDialog):
    def __init__(self,data,parent):
        super().__init__(parent); self.setObjectName('goEditor'); apply_style(self); self.setWindowIcon(icon()); self.setWindowTitle('Structural model — m, kN'); self.resize(850,560)
        self.data=copy.deepcopy(data); self.tables={}; box=QVBoxLayout(self)
        self.is3d=data.get('schema')==2; self.fields=copy.deepcopy(FIELDS); self.choices=copy.deepcopy(CHOICES)
        if self.is3d:
            self.fields['nodes']=['id','x','y','z','support','restraints','springs']
            self.fields['members']+=['rotation']
            self.choices.update(support=['Free','Fixed','Pin','Roller','RollerX','RollerY','Custom','Spring'],type=['Beam','Column','Frame','Truss'],direction=list(GLOBAL+LOCAL))
            self.choices.pop('release_i'); self.choices.pop('release_j')
        info=QLabel('XZ plane • E/G: kN/m² • A: m² • Iy/Iz/J: m⁴ • Iz: in-plane bending\nPin restrains X/Z; Roller restrains Z; RollerX restrains X. Truss loads at nodes.'); info.setWordWrap(True); box.addWidget(info)
        if self.is3d: info.setText('XYZ • Global Z up • right-handed local axes • rotation [deg]\nrestraints / releases: JSON ["UX","UY","UZ","RX","RY","RZ"] (global supports / local releases).\nsprings: JSON {"UZ":1000} — kN/m or kN·m/rad. rho is WEIGHT density [kN/m³].\nGlobal loads uppercase FX…MZ; local member loads Fx…Mz. Truss loads at nodes.')
        tabs=QTabWidget(); self.tabs=tabs; box.addWidget(tabs)
        for key,fields in self.fields.items():
            page=QWidget(); layout=QVBoxLayout(page); table=QTableWidget(0,len(fields)); table.setHorizontalHeaderLabels(fields)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            self.tables[key]=table; layout.addWidget(table)
            if key=='materials':
                presets=QHBoxLayout(); self.material_presets=QComboBox(); self.material_presets.addItems(PRESETS)
                self.add_material_button=QPushButton('Add preset'); presets.addWidget(self.material_presets); presets.addWidget(self.add_material_button); layout.addLayout(presets)
                self.material_note=QLabel(NOTES['Steel']+' E/G: kN/m²; rho: kN/m³.'); self.material_note.setWordWrap(True); layout.addWidget(self.material_note)
                self.material_presets.currentTextChanged.connect(lambda name:self.material_note.setText(NOTES[name]+' E/G: kN/m²; rho: kN/m³.'))
                self.add_material_button.clicked.connect(self.add_material_preset)
            if key=='distributed_loads':
                self.load_extent=QLabel('เลือกแถวแรงกระจายเพื่อดูความยาวสมาชิก [m]; x1/x2 วัดจากปลาย i → j')
                self.load_extent.setWordWrap(True); layout.addWidget(self.load_extent)
                self.full_length=QPushButton('Full member / ใส่แรงตลอดสมาชิก (x1=0, x2=L)'); layout.addWidget(self.full_length)
                self.full_length.clicked.connect(self.fill_load_length)
                table.itemSelectionChanged.connect(self.update_load_extent); table.itemChanged.connect(self.update_load_extent)
            for row in data.get(key,[]): self.add_row(key,row)
            buttons=QHBoxLayout(); add=QPushButton('Add'); remove=QPushButton('Delete selected'); buttons.addWidget(add); buttons.addWidget(remove); layout.addLayout(buttons)
            add.clicked.connect(lambda _=False,k=key:self.add_row(k,{}))
            remove.clicked.connect(lambda _=False,t=table:self.remove_rows(t))
            tabs.addTab(page,key.replace('_',' ').title())
        self.tables['nodes'].itemChanged.connect(self.update_load_extent)
        self.tables['members'].itemChanged.connect(self.update_load_extent)
        self.tables['materials'].itemChanged.connect(lambda _=None:self.refresh_material_choices())
        self.cases=QPlainTextEdit('\n'.join(data['cases'])); self.cases.hide()
        self.case_button=QPushButton('Load Cases… — เพิ่ม / เปลี่ยนชื่อกรณีแรง'); self.case_button.clicked.connect(self.edit_cases); box.addWidget(self.case_button)
        self.combination_data=copy.deepcopy(data.get('combinations',{}))
        self.combinations=QPlainTextEdit(json.dumps(self.combination_data)); self.combinations.setReadOnly(True); self.combinations.hide()
        self.combination_button=QPushButton('Load Combinations… — เลือกกรณีแรงและกรอกตัวคูณ'); self.combination_button.clicked.connect(self.edit_combinations); box.addWidget(self.combination_button)
        self.weight=QCheckBox('Self-weight in every case (rho in kN/m³)'); self.weight.setChecked(data.get('self_weight',False)); box.addWidget(self.weight)
        if self.is3d:
            self.weight.setText('Automatic self-weight in one case only')
            self.weight_case=QComboBox(); self.weight_case.setEditable(True); self.weight_case.addItems(data['cases']); self.weight_case.setCurrentText(data.get('self_weight_case',data['cases'][0])); box.addWidget(QLabel('Self-weight case')); box.addWidget(self.weight_case)
        self.error=QLabel(); self.error.setWordWrap(True); box.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept_model); buttons.rejected.connect(self.reject); box.addWidget(buttons)
    def add_row(self,key,row):
        t=self.tables[key]; i=t.rowCount(); t.insertRow(i)
        for j,k in enumerate(self.fields[key]):
            if k=='case':
                w=QComboBox(); w.addItems(self.data['cases']); value=str(row.get(k,self.data['cases'][0]))
                if value not in self.data['cases']: w.addItem(value); w.setToolTip('Missing Load Case — เพิ่มกรณีแรงก่อนบันทึก')
                w.setCurrentText(value); t.setCellWidget(i,j,w)
            elif k=='material':
                w=QComboBox(); w.setEditable(True); w.addItems([m['id'] for m in self.data['materials']]); w.setCurrentText(str(row.get(k,self.data['materials'][0]['id']))); t.setCellWidget(i,j,w)
            elif k in self.choices:
                w=QComboBox(); w.addItems(self.choices[k]); w.setCurrentText(str(row.get(k,self.choices[k][0]))); t.setCellWidget(i,j,w)
            else: t.setItem(i,j,QTableWidgetItem((json.dumps(row[k]) if isinstance(row.get(k),(list,dict)) else str(row[k])) if k in row else ''))
    def edited_geometry(self):
        out={}
        for key in ('nodes','members'):
            t=self.tables[key]; fields=self.fields[key]; rows=[]
            for i in range(t.rowCount()):
                row={}
                for k in ('id','x','y','z') if key=='nodes' else ('id','i','j'):
                    if k not in fields: continue
                    item=t.item(i,fields.index(k)); value=item.text().strip() if item else ''
                    row[k]=float(value) if k in ('x','y','z') else value
                rows.append(row)
            out[key]=rows
        return out
    def selected_load_length(self):
        from .member_geometry import member_length
        t=self.tables['distributed_loads']; i=t.currentRow()
        if i<0: raise ValueError('เลือกแถวแรงกระจายก่อน')
        item=t.item(i,self.fields['distributed_loads'].index('member')); mid=item.text().strip() if item else ''
        return i,mid,member_length(self.edited_geometry(),mid)
    def update_load_extent(self,*args):
        if not hasattr(self,'load_extent'): return
        try:
            i,mid,length=self.selected_load_length()
            self.load_extent.setText(f'{mid} ? L = {length:.10g} m ? x1/x2 measured from local i ? j ? load: kN/m')
            self.full_length.setEnabled(length>0)
        except (ValueError,KeyError,StopIteration):
            self.load_extent.setText('เลือกแถวและระบุ Member ที่มีอยู่ เพื่อดู L [m] · x1/x2 วัดจากปลาย i → j')
            self.full_length.setEnabled(False)
    def fill_load_length(self):
        try:
            i,mid,length=self.selected_load_length(); t=self.tables['distributed_loads']
            for k,value in (('x1',0.),('x2',length)): t.setItem(i,self.fields['distributed_loads'].index(k),QTableWidgetItem(repr(value)))
            self.update_load_extent()
        except (ValueError,KeyError,StopIteration): self.update_load_extent()
    def remove_rows(self,t):
        for i in sorted({v.row() for v in t.selectedIndexes()},reverse=True): t.removeRow(i)
        if t is self.tables['materials']: self.refresh_material_choices()
    def refresh_material_choices(self):
        table=self.tables['materials']; ids=[table.item(i,0).text().strip() for i in range(table.rowCount()) if table.item(i,0) and table.item(i,0).text().strip()]
        members=self.tables['members']; column=FIELDS['members'].index('material')
        for i in range(members.rowCount()):
            combo=members.cellWidget(i,column); old=combo.currentText(); combo.blockSignals(True); combo.clear(); combo.addItems(ids); combo.setCurrentText(old); combo.blockSignals(False)
    def add_material_preset(self):
        name=self.material_presets.currentText(); table=self.tables['materials']
        for i in range(table.rowCount()):
            if table.item(i,0) and table.item(i,0).text().strip()==name:
                table.selectRow(i); self.material_note.setText(name+' already exists; its edited values are preserved.'); return
        self.add_row('materials',material_preset(name)); self.refresh_material_choices(); table.selectRow(table.rowCount()-1)
    def edit_combinations(self):
        try:
            dialog=CombinationManager(self.collect_data(),self)
            if dialog.exec():
                self.data=dialog.data; self.combination_data=dialog.data['combinations']
                if self.is3d: self.weight_case.setCurrentText(dialog.data.get('self_weight_case',''))
        except Exception as exc: self.error.setText(str(exc))
    def edit_cases(self):
        from .load_case_ui import LoadCaseManager
        try:
            dialog=LoadCaseManager(self.collect_data(),self)
            if dialog.exec():
                self.data=dialog.data; self.combination_data=dialog.data.get('combinations',{}); self.cases.setPlainText('\n'.join(dialog.data['cases']))
                for key in self.fields:
                    self.tables[key].setRowCount(0)
                    for row in dialog.data.get(key,[]): self.add_row(key,row)
                if self.is3d:
                    self.weight_case.clear(); self.weight_case.addItems(dialog.data['cases']); self.weight_case.setCurrentText(dialog.data.get('self_weight_case',dialog.data['cases'][0]))
        except Exception as exc: self.error.setText(str(exc))
    def accept_model(self):
        try:
            self.data=validate(self.collect_data()); self.accept()
        except Exception as exc: self.error.setText(str(exc))
    def collect_data(self):
        d=copy.deepcopy(self.data); d.update(schema=1,self_weight=self.weight.isChecked(),cases=[c.strip() for c in self.cases.toPlainText().splitlines() if c.strip()],combinations=self.combination_data)
        if self.is3d: d.update(schema=2,dimension='3D',self_weight_case=self.weight_case.currentText())
        for key,fields in self.fields.items():
            rows=[]
            for i in range(self.tables[key].rowCount()):
                row={}; t=self.tables[key]
                for j,k in enumerate(fields):
                    w=t.cellWidget(i,j); item=t.item(i,j); v=w.currentText() if w else (item.text().strip() if item else '')
                    if v:
                        if self.is3d and k in ('restraints','springs','release_i','release_j'): row[k]=json.loads(v)
                        else: row[k]=(v=='True') if k in ('release_i','release_j') else (float(v) if k in NUMERIC or k in ('y','rotation') else v)
                if row:
                    original=next((v for v in self.data.get(key,[]) if row.get('id') and v.get('id')==row['id']),{})
                    if not row.get('id') and i<len(self.data.get(key,[])): original=self.data[key][i]
                    rows.append(dict(original,**row))
            d[key]=rows
        return d

class SolverTask(QObject):
    done=Signal(object)
    def __init__(self,model): super().__init__(); self.model=model
    @Slot()
    def run(self):
        try: payload={'ok':True,'result':analyze(self.model)}
        except Exception as exc: payload={'ok':False,'error':str(exc)}
        self.done.emit(payload)

class Workspace:
    allowed_tools={'select','pan','zoom'}
    def __init__(self,panel,data=None):
        from core.scene import Scene
        from core.history import History
        self.panel=panel; self.scene=Scene(); self.history=History(self.scene); self.path=None; self.saved=None
        if data: self.scene.plugin_data[KEY]=copy.deepcopy(data)
        self.camera={'target':[3,0,0],'distance':14,'yaw':-math.pi/2,'pitch':0,'perspective':False}
    def title(self): return 'GO Structural Analysis v'+VERSION+' — '+(self.path.name if self.path else 'Untitled')
    def is_dirty(self): return self.scene.plugin_data.get(KEY)!=self.saved
    def save(self):
        if self.path is None: return self.save_as()
        from formats.igz import save_scene
        try:
            save_scene(self.scene,self.path); self.saved=copy.deepcopy(self.scene.plugin_data.get(KEY)); return True
        except Exception as exc: QMessageBox.warning(self.panel,'Save failed',str(exc)); return False
    def save_as(self):
        path,_=QFileDialog.getSaveFileName(self.panel,'Save structural document','','IngeTrazo (*.igz)')
        if not path: return False
        self.path=Path(path).with_suffix('.igz'); return self.save()
    def confirm_leave(self):
        if self.panel.thread is not None:
            QMessageBox.information(self.panel,'Analysis running','Wait for the solver to finish.'); return False
        if not self.is_dirty(): return True
        choice=QMessageBox.question(self.panel,'Unsaved analysis','Save the structural workspace before leaving?',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel)
        return self.save() if choice==QMessageBox.StandardButton.Save else choice==QMessageBox.StandardButton.Discard
    def left(self): self.panel.refresh()

class OverlayCanvas(QWidget):
    """Compatibility canvas: installed frozen builds may omit extension overlays.

    A transparent child of the viewport paints only this extension's data.
    No host methods are patched; the native API overlay remains registered.
    """
    def __init__(self,panel):
        super().__init__(panel.app.viewport); self.panel=panel
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(panel.app.viewport.rect()); panel.app.viewport.installEventFilter(self)
        self._last_frame=None
        self.timer=QTimer(self); self.timer.setInterval(16); self.timer.timeout.connect(lambda:self.sync(False)); self.timer.start(); self.show(); self.raise_()
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.Resize: self.setGeometry(obj.rect())
        if event.type() in (QEvent.Type.MouseMove,QEvent.Type.Wheel): self.update()
        if getattr(obj,'nav_mode',None) is not None: return False
        if event.type()==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton and self.panel.tabs.currentIndex()==0:
            entity=self.panel.native_pick(event.position().x(),event.position().y())
            if entity:
                self.panel.select_entity(entity); return True
        if event.type()==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton and self.panel.tabs.currentIndex()==2:
            hit=visualization.pick(self.panel,event.position().x(),event.position().y())
            if hit:
                self.panel.select_member(*hit); return True
        return False
    def sync(self,force=True):
        ws=self.panel.app.workspace(); cam=self.panel.app.viewport.camera
        if (self.panel.model() or {}).get('schema')!=2 and getattr(ws,'panel',None) is self.panel and (cam.pitch!=0 or cam.yaw!=-math.pi/2 or cam.perspective):
            cam.pitch=0.0; cam.yaw=-math.pi/2; cam.perspective=False; self.panel.app.viewport.update()
        self.setVisible(bool(self.panel.model()))
        if not self.isVisible(): return
        stamp=(id(self.panel.last_data),id(self.panel.result),self.panel.job,cam.yaw,cam.pitch,cam.distance,cam.perspective,tuple(cam.target.toTuple()),self.width(),self.height(),self.panel.inspector.ratio.value())
        if force or stamp!=self._last_frame:
            self._last_frame=stamp; self.raise_(); self.update()
            for name in ('quick','ribbon'):
                control=getattr(self.panel,name,None)
                if control is not None: control.raise_()
    def paintEvent(self,event):
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try: self.panel.paint(self.panel.app.viewport,painter)
        except Exception as exc: self.panel.status.setText('Diagram failed: '+str(exc))
        finally: painter.end()

class ModelRadio(QRadioButton):
    """Keep the reference's circular selector on Windows native Qt styles."""
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); cy=self.height()/2
        palette=self.palette(); text=palette.color(QPalette.ColorRole.WindowText); background=palette.color(QPalette.ColorRole.Window)
        p.setPen(QPen(text if self.isChecked() else palette.color(QPalette.ColorRole.PlaceholderText),1.3)); p.setBrush(text if self.isChecked() else background); p.drawEllipse(QPointF(11,cy),10,10)
        if self.isChecked():
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(background); p.drawEllipse(QPointF(11,cy),3,3)
        p.setFont(self.font()); p.setPen(text); p.drawText(QRectF(34,0,self.width()-34,self.height()),Qt.AlignmentFlag.AlignVCenter,self.text()); p.end()

class Panel(ThemeAware,QWidget):
    def __init__(self,app):
        super().__init__(); self.app=app; self.thread=None; self.task=None; self.result=None; self.last_data=None; self.job=None; self.result_error=None
        self.setMinimumWidth(310); self.setMaximumWidth(640)
        self.setObjectName('goPanel'); apply_style(self); self.setWindowIcon(icon()); self.pending_type='Beam'
        layout=QVBoxLayout(self); layout.setContentsMargins(14,14,14,12); layout.setSpacing(12)
        header=QHBoxLayout(); logo=QLabel(); logo.setProperty('go_icon','extension'); logo.setProperty('go_icon_size',32); logo.setPixmap(pixmap('extension',32)); header.addWidget(logo)
        heading=QLabel('GO Structural Analysis'); heading.setObjectName('goTitle'); heading.setWordWrap(True); header.addWidget(heading,1)
        badge=QLabel('v'+VERSION); badge.setObjectName('goBadge'); header.addWidget(badge); layout.addLayout(header)
        self.tabs=QTabWidget(); self.tabs.setDocumentMode(True); self.tabs.setUsesScrollButtons(False); self.tabs.tabBar().setDrawBase(False); self.tabs.tabBar().setExpanding(True); layout.addWidget(self.tabs,1)
        self.tab_layouts=[]
        for title in ['Model','Loads','Results']:
            scroll=QScrollArea(); scroll.setWidgetResizable(True); page=QWidget(); page.setObjectName('goPage'); content=QVBoxLayout(page); content.setContentsMargins(0,12,0,8); content.setSpacing(10); scroll.setWidget(page); self.tabs.addTab(scroll,title); self.tab_layouts.append(content)
        model_box,loads_box,results_box=self.tab_layouts
        self.sections={}
        for parent,names in ((model_box,('Model Tree','Section / Material','Supports')),(loads_box,('Load Cases','Load Combinations')),(results_box,('Display Settings','Result Inspector','Result Tables'))):
            for name in names:
                section=Section(name,self); parent.addWidget(section); self.sections[name]=section
        model_box=self.sections['Model Tree'].layout; loads_box=self.sections['Load Cases'].layout; results_box=self.sections['Display Settings'].layout
        from PySide6.QtWidgets import QTreeWidget,QTreeWidgetItem
        self.tree_search=QLineEdit(); self.tree_search.setPlaceholderText('ค้นหา Node / Member / พิกัด…'); self.tree_search.setClearButtonEnabled(True); model_box.addWidget(self.tree_search)
        from .command_ui import filter_model_tree
        self.tree_search.textChanged.connect(lambda text:filter_model_tree(self,text))
        self.model_tree=QTreeWidget(); self.model_tree.setHeaderLabels(['Analytical Model','Coordinates / type']); self.model_tree.setMaximumHeight(190); model_box.addWidget(self.model_tree)
        self.model_tree.itemClicked.connect(lambda item,column:self.select_entity(item.data(0,Qt.ItemDataRole.UserRole)) if item.data(0,Qt.ItemDataRole.UserRole) else None)
        self.check_model_button=QPushButton('Check Model / Stability…'); self.check_model_button.clicked.connect(self.check_model); model_box.addWidget(self.check_model_button)
        self.dimension=QComboBox(); self.dimension.addItems(['2D','3D']); model_box.addWidget(QLabel('Workspace')); model_box.addWidget(self.dimension); self.dimension.currentTextChanged.connect(self.switch_dimension)
        self.theme_choice=QComboBox(); self.theme_choice.addItems(['System','Light','Dark']); self.theme_choice.currentTextChanged.connect(self.apply_theme); model_box.addWidget(QLabel('Extension theme')); model_box.addWidget(self.theme_choice)
        self.geometry_button=QPushButton('Preview selected edges → analytical model…'); self.geometry_button.clicked.connect(self.import_geometry); model_box.addWidget(self.geometry_button)
        selection_row=QHBoxLayout(); edit_selected=QPushButton('Edit selected…'); delete_selected=QPushButton('Delete selected'); edit_selected.clicked.connect(self.edit_selected); delete_selected.clicked.connect(self.delete_selected); selection_row.addWidget(edit_selected); selection_row.addWidget(delete_selected); model_box.addLayout(selection_row); self.selected_entity=None
        title=QLabel('Model Type'); title.setObjectName('goSection'); model_box.addWidget(title)
        self.types=QButtonGroup(self); self.type_buttons={}
        for kind in ['Beam','Frame','Truss']:
            radio=ModelRadio('2D '+kind); self.types.addButton(radio); self.type_buttons[kind]=radio; model_box.addWidget(radio)
            radio.clicked.connect(lambda _=False,k=kind:self.choose_type(k))
        self.type_buttons['Beam'].setChecked(True)
        cards=QGridLayout(); cards.setSpacing(9); model_box.addLayout(cards)
        for i,(title,subtitle,glyph,key) in enumerate([('Nodes','Create / Edit','nodes','nodes'),('Members','Beam / Frame / Truss','members','members'),('Sections','Area / Inertia','sections','sections'),('Supports','Fixed / Pin / Roller','supports','nodes')]):
            button=self.card(title,subtitle,glyph,lambda k=key:self.edit_section(k))
            if title in ('Sections','Supports'): self.sections['Section / Material' if title=='Sections' else 'Supports'].layout.addWidget(button)
            else: cards.addWidget(button,0,i)
        for text,glyph,fn in [('Materials · E / G / Density','materials',lambda:self.edit_section('materials'))]:
            button=QPushButton(text); button.setProperty('go_icon',glyph); button.setIcon(icon(glyph)); button.clicked.connect(fn); self.sections['Section / Material'].layout.addWidget(button)
        self.add_examples_controls(model_box)
        self.model_info=QLabel('No structural model yet'); self.model_info.setObjectName('goMuted'); self.model_info.setWordWrap(True); model_box.addWidget(self.model_info); model_box.addStretch()
        title=QLabel('Load Definition'); title.setObjectName('goSection'); loads_box.addWidget(title)
        load_cards=QGridLayout(); load_cards.setSpacing(9); loads_box.addLayout(load_cards)
        for i,(title,subtitle,glyph,key) in enumerate([('Point Loads','Node / Member','point','point_loads'),('Distributed','Uniform / Varying','distributed','distributed_loads'),('Load Cases','Manage cases','cases','cases')]):
            load_cards.addWidget(self.card(title,subtitle,glyph,lambda k=key:self.edit_section(k)),i//2,i%2)
        self.weight=QCheckBox('Include self-weight'); self.weight.clicked.connect(self.set_weight); loads_box.addWidget(self.weight)
        combo_button=QPushButton('Load Combinations… — จัดชุดรวมแรง'); combo_button.clicked.connect(self.open_combinations); self.sections['Load Combinations'].layout.addWidget(combo_button)
        self.combo_notice=QLabel('No Code Pack selected · Custom combinations'); self.combo_notice.setWordWrap(True); self.sections['Load Combinations'].layout.addWidget(self.combo_notice)
        note=QLabel('m · kN · kN/m\nSelf-weight uses material density in kN/m³ and applies to every case.'); self.load_note=note; note.setObjectName('goMuted'); note.setWordWrap(True); loads_box.addWidget(note); loads_box.addStretch()
        results_box.addWidget(QLabel('Load Case')); self.case=QComboBox(); self.case.currentTextChanged.connect(self.redraw); results_box.addWidget(self.case)
        results_box.addWidget(QLabel('Viewport Diagram')); self.diagram=QComboBox(); self.diagram.addItems(['Model','N','V','M','D','Reaction','Deformed']); self.diagram.currentTextChanged.connect(self.redraw); results_box.addWidget(self.diagram)
        self.diagram_scale=QDoubleSpinBox(); self.diagram_scale.setRange(0.01,100); self.diagram_scale.setValue(1); self.diagram_scale.setPrefix('Diagram × '); self.diagram_scale.valueChanged.connect(self.redraw); results_box.addWidget(self.diagram_scale)
        self.scale=QDoubleSpinBox(); self.scale.setRange(0.001,1e6); self.scale.setValue(100); self.scale.setPrefix('Deformation × '); self.scale.valueChanged.connect(self.redraw); results_box.addWidget(self.scale)
        visibility=QHBoxLayout(); self.labels=QCheckBox('Labels'); self.legend=QCheckBox('Legend'); self.show_loads=QCheckBox('Loads')
        for check in [self.labels,self.legend,self.show_loads]: check.setChecked(check is not self.show_loads); check.toggled.connect(self.redraw); visibility.addWidget(check)
        results_box.addLayout(visibility)
        self.local_axes=QCheckBox('Local axes x / y / z'); self.local_axes.setChecked(True); self.local_axes.toggled.connect(self.redraw); results_box.addWidget(self.local_axes)
        self.axes_mode=QComboBox(); self.axes_mode.addItems(['Selected','All','None']); self.axes_mode.currentTextChanged.connect(self.redraw); results_box.addWidget(self.axes_mode)
        self.label_density=QComboBox(); self.label_density.addItems(['Sparse','Normal','Dense']); self.label_density.setCurrentText('Normal'); self.label_density.currentTextChanged.connect(self.redraw); results_box.addWidget(self.label_density)
        self.display_tolerance=QDoubleSpinBox(); self.display_tolerance.setDecimals(9); self.display_tolerance.setRange(0,0.01); self.display_tolerance.setValue(1e-6); self.display_tolerance.setPrefix('Display tolerance × peak: '); self.display_tolerance.valueChanged.connect(self.redraw); results_box.addWidget(self.display_tolerance)
        self.displacement_mm=QCheckBox('Displacement in mm'); self.displacement_mm.setChecked(True); self.displacement_mm.toggled.connect(self.redraw); results_box.addWidget(self.displacement_mm)
        self.diagram_plane=QCheckBox('Visible diagram plane'); self.diagram_plane.setChecked(True); self.diagram_plane.toggled.connect(self.redraw); results_box.addWidget(self.diagram_plane)
        self.archive_view=QCheckBox('Show Archived/Stale snapshot explicitly'); self.archive_view.toggled.connect(self.redraw); results_box.addWidget(self.archive_view)
        defaults=QPushButton('Restore Display Defaults'); defaults.clicked.connect(self.restore_display); results_box.addWidget(defaults)
        self.envelope_group=QComboBox(); self.envelope_group.currentTextChanged.connect(self.redraw); results_box.addWidget(QLabel('Envelope group / design method')); results_box.addWidget(self.envelope_group)
        self.inspector=Inspector(self); self.sections['Result Inspector'].layout.addWidget(self.inspector)
        self.summary=QPlainTextEdit(); self.summary.setReadOnly(True); self.summary.setPlaceholderText('Run Analysis to view reactions and member results.'); self.summary.setMinimumHeight(80); self.summary.setMaximumHeight(130); self.sections['Result Tables'].layout.addWidget(self.summary)
        self.report_button=QPushButton('Export Current Engineering Report…'); self.report_button.clicked.connect(self.export_engineering_report); self.sections['Result Tables'].layout.addWidget(self.report_button)
        self.capacity_notice=QLabel('Capacity / Code Compliance / Serviceability: Not Available'); self.capacity_notice.setWordWrap(True); self.sections['Result Tables'].layout.addWidget(self.capacity_notice)
        self.run_button=QPushButton('Run Analysis'); self.run_button.setObjectName('goRun'); self.run_button.setProperty('go_icon','run'); self.run_button.setIcon(icon('run')); self.run_button.clicked.connect(self.run); layout.addWidget(self.run_button)
        self.status=QLabel('PyNite solver ready · 2D XZ · m / kN'); self.status.setObjectName('goStatus'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.state_badge=QLabel('Not Analyzed'); layout.addWidget(self.state_badge)
        from PySide6.QtWidgets import QProgressBar
        self.progress=QProgressBar(); self.progress.setRange(0,0); self.progress.hide(); layout.addWidget(self.progress)
        actions=QHBoxLayout(); actions.setSpacing(7)
        for text,glyph,tip,fn in [('Workspace','workspace','Enter the 2D XZ workspace',self.enter),('Return','back','Return to the parked model',self.leave),('Save','save','Save the structural .igz document',self.save)]:
            b=QPushButton(text); b.setProperty('go_icon',glyph); b.setIcon(icon(glyph)); b.setToolTip(tip); b.clicked.connect(fn); actions.addWidget(b)
        layout.addLayout(actions)
        store=QPushButton('Store analysis in current document'); store.setToolTip('Explicitly copy workspace analysis data to the original model'); store.clicked.connect(self.store); layout.addWidget(store)
        app.on_document_changed(self.refresh); app.add_overlay(self.paint); self.refresh()
        self.canvas=OverlayCanvas(self)
        self.quick=QuickControls(self)
        from .command_ui import CommandRegistry
        self.commands=CommandRegistry(self)
        self.model_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.model_tree.customContextMenuRequested.connect(self.commands.tree_context)
        from .ribbon_ui import WorkspaceRibbon
        self.ribbon=WorkspaceRibbon(self)
        app.add_pickable(lambda vp,x,y:self.native_pick(x,y),on_select=lambda mid:self.select_entity(mid) if mid is not None else None,delete=lambda mid:self.delete_selected(mid))
    def result_status(self):
        if getattr(self,'_paint_status',None) is not None: return self._paint_status
        if self.job not in ('Running','Failed') and self.result and self.result.get('geometry_fingerprint') and self.result['geometry_fingerprint']!=self.geometry_token(): return 'Stale'
        return state(self.model(),self.result,'Failed' if self.result_error else self.job)
    def results_are_current(self): return self.result_status()=='Current'
    def record_failure(self,error):
        self.job='Failed'; d=copy.deepcopy(self.data()); d['analysis_state']=dict(state='Failed',error=str(error),input_fingerprint=fingerprint(d.get('model')))
        if d.get('result'): d['result'].setdefault('safety',{})['invalidated_by_failure']=True
        self.app.set_document_data(d); self.status.setText('Analysis failed: '+str(error)); self.redraw()
    def open_combinations(self):
        if not self.model(): self.status.setText('Create a model before configuring combinations'); return
        dialog=CombinationManager(self.model(),self)
        if dialog.exec(): self.put(dialog.data)
    def check_model(self):
        if not self.model(): self.status.setText('Create a model before checking'); return
        from .diagnostics_ui import ModelCheckDialog
        self.model_check_dialog=ModelCheckDialog(self); self.model_check_dialog.show()
    def restore_display(self):
        self.labels.setChecked(True); self.legend.setChecked(True); self.local_axes.setChecked(True); self.axes_mode.setCurrentText('Selected'); self.label_density.setCurrentText('Normal'); self.diagram_scale.setValue(1); self.scale.setValue(100); self.display_tolerance.setValue(1e-6); self.displacement_mm.setChecked(True); self.diagram_plane.setChecked(True); self.archive_view.setChecked(False)
    def export_engineering_report(self):
        if not self.results_are_current(): self.status.setText('No Current results; Run Analysis first'); return
        path,_=QFileDialog.getSaveFileName(self,'Current Engineering Analysis Report','','JSON (*.json)')
        if path:
            try: export_report(path,self.model(),self.result); self.status.setText('Current report exported; capacity/code compliance Not Available')
            except Exception as exc: self.status.setText(str(exc))
    def geometry_token(self):
        scene=self.app.scene
        def point(v): return list(getattr(v,'position',v).toTuple())
        def mesh_data(mesh):
            return dict(points=[point(v) for v in getattr(mesh,'vertices',[])],edges=[(point(e.a),point(e.b)) for e in getattr(mesh,'edges',[])],faces=[dict(outer=[point(v) for v in f.vertices],holes=[[point(v) for v in hole] for hole in getattr(f,'holes',[])]) for f in getattr(mesh,'faces',[])])
        def group_data(g):
            return dict(name=getattr(g,'name',''),mesh=mesh_data(getattr(g,'mesh',None)),transform=[list(g.xform.row(i).toTuple()) for i in range(4)] if getattr(g,'xform',None) is not None else None,children=[group_data(child) for child in getattr(g,'children',[])])
        return fingerprint(dict(mesh=mesh_data(getattr(scene,'mesh',scene)),groups=[group_data(g) for g in getattr(scene,'groups',[])]))
    def native_pick(self,x,y):
        if self.tabs.currentIndex()==0 and self.model():
            nodes=self.model()['nodes']; px,py,front=self.app.world_to_pixels([[n['x'],n.get('y',0),n['z']] for n in nodes])
            hits=[(math.hypot(x-float(a),y-float(b)),n['id']) for n,a,b,f in zip(nodes,px,py,front) if f and math.hypot(x-float(a),y-float(b))<9]
            if hits: return 'node:'+min(hits)[1]
        hit=visualization.pick(self,x,y); return hit[0] if hit else None
    def apply_theme(self,name):
        if name=='System': self.setPalette(QPalette())
        else:
            palette=QPalette(); dark=name=='Dark'
            for role,color in ((QPalette.ColorRole.Window,'#202630' if dark else '#f1f4f7'),(QPalette.ColorRole.Base,'#2b3440' if dark else '#ffffff'),(QPalette.ColorRole.Button,'#303b49' if dark else '#e7edf2'),(QPalette.ColorRole.AlternateBase,'#242d38' if dark else '#f4f7fa')): palette.setColor(role,QColor(color))
            for role in (QPalette.ColorRole.WindowText,QPalette.ColorRole.Text,QPalette.ColorRole.ButtonText): palette.setColor(role,QColor('#e7edf5' if dark else '#23364d'))
            palette.setColor(QPalette.ColorRole.Highlight,QColor('#358dba')); self.setPalette(palette)
        apply_style(self); self.redraw()
    def select_entity(self,mid):
        self.selected_entity=mid
        if mid.startswith('node:'): self.status.setText('Selected '+mid[5:]+' — Edit selected / Delete selected'); self.redraw(); return
        if self.tabs.currentIndex()==0: self.status.setText('Selected member '+mid+' — Edit selected / Delete selected'); self.redraw(); return
        self.select_member(mid)
    def edit_selected(self):
        if not self.selected_entity: self.status.setText('Select a node or member in Model viewport first'); return
        key='nodes' if self.selected_entity.startswith('node:') else 'members'; identifier=self.selected_entity[5:] if key=='nodes' else self.selected_entity
        dialog=Editor(self.model(),self); dialog.tabs.setCurrentIndex(list(dialog.fields).index(key))
        for i,n in enumerate(self.model()[key]):
            if n['id']==identifier: dialog.tables[key].selectRow(i)
        if dialog.exec(): self.put(dialog.data); self.fit()
    def delete_selected(self,identifier=None):
        identifier=identifier if isinstance(identifier,str) else self.selected_entity
        if not identifier or not self.model() or self.thread is not None: return
        model=copy.deepcopy(self.model()); node=identifier[5:] if identifier.startswith('node:') else None
        removed={m['id'] for m in model['members'] if (node in (m['i'],m['j']) if node else m['id']==identifier)}
        model['members']=[m for m in model['members'] if m['id'] not in removed]; used={n for m in model['members'] for n in (m['i'],m['j'])}
        model['nodes']=[n for n in model['nodes'] if n['id'] in used]
        model['point_loads']=[p for p in model.get('point_loads',[]) if p.get('member') not in removed and (p.get('node') is None or p['node'] in used)]
        model['distributed_loads']=[p for p in model.get('distributed_loads',[]) if p['member'] not in removed]
        try:
            if not model['members']: self.app.set_document_data({'version':VERSION,'model':None,'result':None}); self.refresh()
            else: self.put(model)
            self.selected_entity=None
        except Exception as exc: self.status.setText('Delete rejected: '+str(exc))
    def switch_dimension(self,dimension):
        if self.thread is not None: return
        current=self.model()
        if current and (current.get('schema')==2)==(dimension=='3D'): return
        if dimension=='2D' and current and current.get('schema')==2:
            self.dimension.blockSignals(True); self.dimension.setCurrentText('3D'); self.dimension.blockSignals(False)
            self.status.setText('Choose a 2D example or open a legacy .igz to return to 2D; 3D geometry is never flattened silently.'); return
        if dimension=='3D':
            candidate=migrate2d(current) if current else cantilever3d()
            dialog=Editor(candidate,self)
            if dialog.exec(): self.put(dialog.data); self.fit()
            else:
                self.dimension.blockSignals(True); self.dimension.setCurrentText('2D'); self.dimension.blockSignals(False)
    def import_geometry(self):
        try:
            lines=[(list(e.a.toTuple()),list(e.b.toTuple())) for e in self.app.scene.selection if hasattr(e,'a') and hasattr(e,'b')]
            if not lines: raise ValueError('Select straight edges in IngeTrazo first. Groups/faces/curves are not automatically interpreted as structural members.')
            candidate=from_lines(lines,cantilever3d()); dialog=Editor(candidate,self)
            dialog.setWindowTitle('Preview geometry conversion — set supports and review before confirming')
            if dialog.exec():
                if self.app.workspace() is None: self.enter()
                self.put(dialog.data); self.fit()
        except Exception as exc: self.status.setText(str(exc))
    def select_member(self,mid,ratio=None):
        self.last_picked_member=mid; self.tabs.setCurrentIndex(2); self.inspector.select(mid,ratio)
    def card(self,title,subtitle,glyph,fn):
        b=QPushButton(); b.setObjectName('goCard'); b.setAccessibleName(title); b.setToolTip(title+' — '+subtitle)
        box=QVBoxLayout(b); box.setContentsMargins(12,10,8,10); box.setSpacing(5)
        image=QLabel(); image.setProperty('go_icon',glyph); image.setProperty('go_icon_size',21); image.setPixmap(pixmap(glyph,21)); text=QLabel(title); text.setStyleSheet('font-weight: 600;'); detail=QLabel(subtitle); detail.setObjectName('goMuted'); detail.setWordWrap(True)
        for label in [image,text,detail]: label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents); box.addWidget(label)
        b.clicked.connect(lambda _=False:fn()); return b
    def choose_type(self,kind):
        self.pending_type=kind
        m=self.model()
        if m:
            m=copy.deepcopy(m)
            for member in m['members']: member['type']=kind
            try: self.put(m)
            except Exception as exc: self.status.setText(str(exc)); self.refresh_types()
    def refresh_types(self):
        model=self.model(); kinds={m['type'] for m in model['members']} if model else set()
        for kind,radio in self.type_buttons.items():
            radio.blockSignals(True); radio.setChecked(kind==(next(iter(kinds)) if len(kinds)==1 else self.pending_type)); radio.blockSignals(False)
    def set_weight(self,checked):
        m=self.model()
        if not m: self.weight.setChecked(False); self.status.setText('Create a model before enabling self-weight.'); return
        m=copy.deepcopy(m); m['self_weight']=checked
        if m.get('schema')==2 and not m.get('self_weight_case'): m['self_weight_case']=m['cases'][0]
        try: self.put(m)
        except Exception as exc: self.status.setText('Self-weight rejected: '+str(exc)); self.refresh()
    def edit_section(self,key): self.edit(key)
    def data(self): return self.app.document_data({}) or {}
    def model(self): return (self.last_data if self.last_data is not None else self.data()).get('model')
    def refresh(self):
        d=self.data()
        ws=self.app.workspace()
        if ws is not None and getattr(ws,'panel',None) is self:
            allowed={'select','pan','zoom'}
            if (d.get('model') or {}).get('schema')==2: allowed.add('orbit')
            if ws.allowed_tools!=allowed:
                ws.allowed_tools=allowed
                setter=getattr(self.app.window,'set_tool_filter',None)
                if callable(setter): setter(allowed)
        if d!=self.last_data:
            self.last_data=copy.deepcopy(d); self.result=d.get('result'); cases=list((d.get('model') or {}).get('cases',[]))+list((d.get('model') or {}).get('combinations',{}))
            self.result_error=None
            attempt=d.get('analysis_state',{})
            if attempt.get('state')=='Failed' and attempt.get('input_fingerprint')==fingerprint(d.get('model')): self.job='Failed'
            elif attempt.get('state')=='Running' and self.job!='Running': self.job='Failed'; self.result_error='Previous analysis interrupted; Run Analysis again'
            elif self.job!='Running': self.job=None
            if self.result:
                try: validate_result(self.result)
                except Exception as exc: self.result_error=str(exc)
            if hasattr(self,'model_tree'):
                from PySide6.QtWidgets import QTreeWidgetItem
                self.model_tree.clear(); model=d.get('model') or {}; nodes=QTreeWidgetItem(self.model_tree,['Nodes','']); members=QTreeWidgetItem(self.model_tree,['Members',''])
                for n in model.get('nodes',[]):
                    item=QTreeWidgetItem(nodes,[n['id'],', '.join(f'{n.get(k,0):g}' for k in ('x','y','z'))]); item.setData(0,Qt.ItemDataRole.UserRole,'node:'+n['id'])
                for m in model.get('members',[]):
                    item=QTreeWidgetItem(members,[m['id'],m['type']+' '+m['i']+' → '+m['j']]); item.setData(0,Qt.ItemDataRole.UserRole,m['id'])
                nodes.setExpanded(True); members.setExpanded(True)
                from .command_ui import filter_model_tree
                filter_model_tree(self,self.tree_search.text())
            old=self.case.currentText(); self.case.blockSignals(True); self.case.clear(); self.case.addItems(cases); self.case.setCurrentText(old if old in cases else (cases[0] if cases else '')); self.case.blockSignals(False)
        self.redraw()
        if hasattr(self,'combo_notice'):
            cm=(d.get('model') or {}).get('combination_manager',{}); self.combo_notice.setText('Thailand 2566 · '+cm.get('method','Custom')+' · '+str(len((d.get('model') or {}).get('combinations',{})))+' combinations\nCapacity / Code Compliance: Not Available')
        if hasattr(self,'envelope_group'):
            groups=list((self.result or {}).get('envelope_groups',{})); old=self.envelope_group.currentText(); self.envelope_group.blockSignals(True); self.envelope_group.clear(); self.envelope_group.addItems(groups); self.envelope_group.setCurrentText(old if old in groups else (groups[0] if groups else '')); self.envelope_group.blockSignals(False)
        if hasattr(self,'type_buttons'):
            self.refresh_types(); self.weight.setChecked((d.get('model') or {}).get('self_weight',False))
            if hasattr(self,'diagram'):
                is3d=bool(d.get('model') and d['model'].get('schema')==2); choices=['Model','N','Vy','Vz','My','Mz','T','D','dy','dz','Reaction','Deformed'] if is3d else ['Model','N','V','M','D','Reaction','Deformed']
                if [self.diagram.itemText(i) for i in range(self.diagram.count())]!=choices:
                    old=self.diagram.currentText(); self.diagram.blockSignals(True); self.diagram.clear(); self.diagram.addItems(choices); self.diagram.setCurrentText(old if old in choices else 'Model'); self.diagram.blockSignals(False)
            m=d.get('model'); self.model_info.setText(f"{len(m['nodes'])} nodes · {len(m['members'])} members · XZ plane" if m else 'No structural model yet')
            if hasattr(self,'dimension'):
                dim='3D' if m and m.get('schema')==2 else '2D'; self.dimension.blockSignals(True); self.dimension.setCurrentText(dim); self.dimension.blockSignals(False)
                for kind,radio in self.type_buttons.items(): radio.setText(dim+' '+kind)
                if m and dim=='3D': self.model_info.setText(f"{len(m['nodes'])} nodes · {len(m['members'])} members · XYZ / Z up")
                self.load_note.setText('m · kN · kN/m · kN·m\nGlobal FX/FY/FZ/MX/MY/MZ; member-local Fx/Fy/Fz/Mx/My/Mz.\n3D self-weight uses rho [kN/m³] in one selected case only.' if dim=='3D' else 'm · kN · kN/m\n2D legacy self-weight applies to every case; rho [kN/m³].')
                if dim=='2D' and m and m.get('self_weight_case'): self.load_note.setText('m · kN · kN/m\nSelf-weight uses rho [kN/m³] once, in '+m['self_weight_case'])
    def put(self,model,result=None):
        self.job=None
        previous=self.data().get('result')
        self.app.set_document_data({'version':VERSION,'model':validate(model),'result':result if result is not None else previous}); self.refresh()
        if self.result and not is_current(self.model(),self.result): self.status.setText('Results out of date — Run Analysis required')
    def enter(self):
        if self.app.workspace() is not None: self.status.setText('A workspace is already active.'); return
        ws=Workspace(self,self.data() or None)
        if self.app.enter_workspace(ws): self.refresh(); self.status.setText(self.dimension.currentText()+' workspace active; original model parked.'); self.fit()
    def leave(self): self.app.leave_workspace(); self.refresh()
    def edit(self,key=None):
        if self.thread is not None: return
        model=self.model() or (cantilever3d() if self.dimension.currentText()=='3D' else benchmark())
        if key=='cases':
            from .load_case_ui import LoadCaseManager
            dialog=LoadCaseManager(model,self)
            if dialog.exec(): self.put(dialog.data)
            return
        if not self.model():
            model['members'][0]['type']=self.pending_type
            if self.pending_type=='Truss': model['distributed_loads']=[]
        dialog=Editor(model,self)
        if key in FIELDS: dialog.tabs.setCurrentIndex(list(FIELDS).index(key))
        elif key=='cases': dialog.cases.setFocus()
        if dialog.exec(): self.put(dialog.data); self.fit()
    def example(self):
        return self.load_example('simple_udl')
    def add_examples_controls(self,box):
        box.addWidget(QLabel('Engineering Examples / Benchmarks'))
        self.examples=QComboBox()
        self.example_catalog=CATALOG+CATALOG3D+BUILDING_CATALOG
        for key,title,description in self.example_catalog: self.examples.addItem(title,key)
        box.addWidget(self.examples)
        self.example_note=QLabel(); self.example_note.setWordWrap(True); self.example_note.setObjectName('goMuted'); box.addWidget(self.example_note)
        self.examples.currentIndexChanged.connect(lambda _=0:self.example_note.setText(self.example_catalog[self.examples.currentIndex()][2]))
        self.example_note.setText(CATALOG[0][2])
        self.example_button=QPushButton('Load selected example'); self.example_button.clicked.connect(lambda _=False:self.load_example(self.examples.currentData())); box.addWidget(self.example_button)
    def load_example(self,key):
        if self.thread is not None: return
        model=example3d(key) if key.startswith('3d_') else example_model(key)
        if self.app.workspace() is None: self.enter()
        ws=self.app.workspace()
        if getattr(ws,'panel',None) is self:
            if self.model() and ws.is_dirty():
                choice=QMessageBox.question(self,'Replace structural example?','The current structural workspace has unsaved changes. Replace it with the selected example?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
                if choice!=QMessageBox.StandardButton.Yes: return
            self.put(model); self.fit(); self.tabs.setCurrentIndex(0)
            self.status.setText('Example loaded — Run Analysis. '+next(row[2] for row in self.example_catalog if row[0]==key))
    def store(self):
        # User-requested explicit commit only; never done by installation/tests.
        ws=self.app.workspace()
        if getattr(ws,'panel',None) is not self: self.status.setText('Changes are already stored in the current .igz document.'); return
        d=copy.deepcopy(self.data())
        if self.app.leave_workspace(): self.app.set_document_data(d); self.status.setText('Analysis data stored in model; save .igz to persist.')
    def save(self):
        ws=self.app.workspace()
        if getattr(ws,'panel',None) is self: ws.save_as()
        else: self.status.setText('Use IngeTrazo File → Save to save current document data.')
    def fit(self):
        m=self.model()
        if not m: return
        xs=[n['x'] for n in m['nodes']]; zs=[n['z'] for n in m['nodes']]
        cam=self.app.viewport.camera; cam.target=QVector3D((min(xs)+max(xs))/2,0,(min(zs)+max(zs))/2)
        cam.yaw=-math.pi/2; cam.pitch=0.0; cam.perspective=False; cam.distance=max(max(xs)-min(xs),max(zs)-min(zs),2)*2.5; self.app.viewport.update()
        if m.get('schema')==2:
            ys=[n['y'] for n in m['nodes']]; cam.target=QVector3D((min(xs)+max(xs))/2,(min(ys)+max(ys))/2,(min(zs)+max(zs))/2)
            cam.yaw=-.8; cam.pitch=.45; cam.distance=max(max(xs)-min(xs),max(ys)-min(ys),max(zs)-min(zs),2)*2.5; self.app.viewport.update()
    def run(self):
        if self.thread is not None: return
        try: model=validate(self.model()); self.analysis_model=copy.deepcopy(model); self.analysis_scene=self.app.scene
        except Exception as exc: self.record_failure(exc); return
        self.job='Running'; self.analysis_geometry=self.geometry_token()
        running_data=copy.deepcopy(self.data()); running_data['analysis_state']=dict(state='Running',input_fingerprint=fingerprint(model))
        if running_data.get('result'): running_data['result'].setdefault('safety',{})['running']=True
        self.app.set_document_data(running_data); self.redraw(); self.progress.show()
        self.status.setText('Analyzing with PyNite worker…'); self.run_button.setEnabled(False)
        self.thread=QThread(self); self.task=SolverTask(model); self.task.moveToThread(self.thread)
        self.thread.started.connect(self.task.run); self.task.done.connect(self.complete,Qt.ConnectionType.QueuedConnection)
        self.task.done.connect(self.thread.quit); self.thread.finished.connect(self.task.deleteLater); self.thread.finished.connect(self.finished); self.thread.start()
    @Slot(object)
    def complete(self,payload):
        self.job=None
        if self.app.scene is not self.analysis_scene or self.data().get('model')!=self.analysis_model or self.geometry_token()!=self.analysis_geometry:
            self.status.setText('Document changed; stale solver results discarded.'); return
        if not payload['ok']: self.record_failure(payload['error']); return
        try: validate_result(payload['result'])
        except Exception as exc: self.record_failure('Safety validation: '+str(exc)); return
        payload['result']['geometry_fingerprint']=self.analysis_geometry
        self.put(self.analysis_model,payload['result']); self.status.setText('Analysis complete — PyNiteFEA '+payload['result']['version'])
        self.tabs.setCurrentIndex(2)
    @Slot()
    def finished(self):
        self.thread.deleteLater(); self.thread=None; self.task=None; self.run_button.setEnabled(True); self.progress.hide(); self.redraw()
    def redraw(self,*args):
        self.app.viewport.update()
        if hasattr(self,'canvas'): self.canvas.update()
        if hasattr(self,'state_badge'):
            status=self.result_status(); self.state_badge.setText(status+' · Capacity / Code Compliance: Not Available'); self.report_button.setEnabled(status=='Current')
        if hasattr(self,'quick'): self.quick.refresh()
        if hasattr(self,'inspector'): self.inspector.refresh()
        if getattr(self,'commands',None) is not None: self.commands.refresh()
        if hasattr(self,'ribbon'): self.ribbon.refresh()
        summary_key=(id(self.result),self.case.currentText(),self.result_status())
        if getattr(self,'_summary_key',None)==summary_key: return
        self._summary_key=summary_key
        if not self.results_are_current() or self.case.currentText() not in self.result['cases']:
            self.summary.setPlainText('RESULTS OUT OF DATE — Run Analysis' if self.result else ''); return
        r=self.result['cases'][self.case.currentText()]; lines=['Reactions (kN; kN·m)']
        for n,v in r['nodes'].items():
            if self.model().get('schema')==2: lines.append(n+': '+', '.join(f'{k}={v[k]:.5g}' for k in ('Fx','Fy','Fz','Mx','My','Mz')))
            else: lines.append(f"{n}: Rx={v['Rx']:.5g}, Rz={v['Rz']:.5g}, My={v['My']:.5g}")
        for mid,v in r['members'].items():
            for key,extrema in v['extrema'].items():
                from .results import UNITS
                units=UNITS[key]
                lines.append(f"{mid} {key}: min {extrema['min']['value']:.6g}, max {extrema['max']['value']:.6g} {units}")
        self.summary.setPlainText('\n'.join(lines))
    def paint(self,viewport,painter):
        if painter.device() is viewport:
            # Some installed host builds invoke the native callback before their
            # GL pass overwrites it. Keep the visible compatibility canvas as the
            # single renderer instead of treating callback delivery as proof.
            if hasattr(self,'canvas'): return
        self._paint_status=self.result_status()
        try: visualization.draw(self,viewport,painter)
        finally: self._paint_status=None

def setup(app):
    if getattr(app,'api_version',0)!=2: raise RuntimeError('GO Structural Analysis requires IngeTrazo Plugin API v2')
    existing=getattr(app.window,'_go_structural_panel',None)
    if existing is not None: return existing
    panel=Panel(app); dock=app.add_panel('GO Structural',panel); dock.setWindowIcon(icon())
    action=app.add_menu_action('GO Structural Analysis v'+VERSION,lambda:app.show_panel(dock),tip='2D / 3D beam, frame and truss analysis')
    if action is not None: action.setIcon(icon())
    panel.menu_action=action; panel.dock=dock
    app.window._go_structural_panel=panel
    return panel
