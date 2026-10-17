"""Shared command routing, searchable actions and analytical selection menus."""
from dataclasses import dataclass
from PySide6.QtCore import Qt,QObject,QEvent
from PySide6.QtGui import QAction,QShortcut,QKeySequence,QColor
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLineEdit,QTreeWidget,QTreeWidgetItem,QLabel,QPushButton,QMenu,QMessageBox
from .icons import icon
from .theme import apply_style

@dataclass(frozen=True)
class Command:
    key:str
    title:str
    group:str
    glyph:str
    method:str
    argument:object=None
    keywords:str=''
    needs_model:bool=True
    selected:bool=False
    current:bool=False
    allow_running:bool=False

COMMANDS=(
    Command('member_graph','Member Graphs / กราฟสมาชิก…','Results','members','show_member_graph',keywords='graph collinear คานแนวเดียวกัน กราฟ',selected=True,current=True),
    Command('save','บันทึกโมเดล / Save','Project','save','save'),
    Command('run','Run Analysis / วิเคราะห์','Analysis','run','run',keywords='solver pynite คำนวณ'),
    Command('analysis_run','Run Analysis','Analysis','run','run',keywords='solver'),
    Command('nodes','Nodes / จุดต่อ','Model','nodes','edit_section','nodes',keywords='node coordinate xyz พิกัด'),
    Command('members','Members / สมาชิก','Model','members','edit_section','members',keywords='member beam column truss คาน เสา'),
    Command('materials','Materials / วัสดุ','Model','materials','edit_section','materials',keywords='concrete steel wood E G คอนกรีต เหล็ก ไม้'),
    Command('sections','Sections / หน้าตัด','Model','sections','edit_section','sections',keywords='area inertia Iy Iz J'),
    Command('supports','Supports / จุดรองรับ','Model','supports','edit_section','nodes',keywords='pin roller fixed spring support'),
    Command('edit_selected','แก้ไขที่เลือก / Properties','Selection','members','edit_selected',keywords='edit property node member',selected=True),
    Command('delete_selected','ลบที่เลือก / Delete','Selection','back','confirm_delete',keywords='remove node member',selected=True),
    Command('geometry','Preview Geometry → Analytical Model','Model','workspace','import_geometry',keywords='import edges แปลง',needs_model=False),
    Command('cases','Load Cases / กรณีแรง','Loads','point','edit','cases',keywords='case DL LL wind ลม'),
    Command('combinations','Load Combinations / ชุดรวมแรง','Loads','distributed','open_combinations',keywords='combination factor ASD LRFD ตัวคูณ'),
    Command('point_loads','Point Load / Moment','Loads','point','edit_section','point_loads',keywords='node member force แรง โมเมนต์'),
    Command('distributed_loads','Distributed Load','Loads','distributed','edit_section','distributed_loads',keywords='udl แรงกระจาย'),
    Command('check','Check Model / Stability','Analysis','supports','check_model',keywords='duplicate connectivity singular ตรวจ ซ้ำ เสถียรภาพ'),
    Command('inspector','Result Inspector','Results','members','show_inspector',keywords='N V M D T x/L ตรวจผล'),
    Command('tables','Result Tables / ตารางผล','Results','sections','show_tables',keywords='reaction displacement end force ปฏิกิริยา'),
    Command('csv','Export Current CSV','Results','save','export_csv',keywords='export ส่งออก',current=True),
    Command('report','Current Engineering Report','Results','save','export_engineering_report',keywords='report รายงาน',current=True),
    Command('display','Diagram / Labels','Display','workspace','show_display',keywords='diagram labels scale กราฟ ป้าย',needs_model=False,allow_running=True),
    Command('defaults','Restore Display Defaults','Display','back','restore_display',keywords='reset คืนค่า',needs_model=False,allow_running=True),
    Command('panel','Show / Hide Panel','Display','workspace','toggle_panel',keywords='panel ซ่อน',needs_model=False,allow_running=True),
    Command('return','Return to Original Model','Project','back','leave',keywords='workspace กลับ',needs_model=False),
)

class CommandRegistry(QObject):
    def __init__(self,panel):
        super().__init__(panel); self.panel=panel; self.commands={c.key:c for c in COMMANDS}; self.dialog=None; self.menu=None
        panel.app.viewport.installEventFilter(self)
        self.shortcut=QShortcut(QKeySequence('Ctrl+K'),panel.app.window); self.shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut); self.shortcut.activated.connect(self.show_search)
    def valid_selection(self):
        p=self.panel; entity=p.selected_entity; model=p.model() or {}
        if not entity: return False
        key,identifier=('nodes',entity[5:]) if entity.startswith('node:') else ('members',entity)
        return any(row['id']==identifier for row in model.get(key,[]))
    def disabled_reason(self,key):
        c=self.commands[key]; p=self.panel
        if not c.allow_running and (p.job=='Running' or p.thread is not None): return 'กำลังวิเคราะห์ — รอให้ Solver ทำงานเสร็จ'
        if c.needs_model and not p.model(): return 'ยังไม่มีโมเดล — เปิดตัวอย่างหรือสร้างโมเดลก่อน'
        if key=='member_graph' and p.selected_entity and p.selected_entity.startswith('node:'): return 'เลือก Member ก่อน'
        if c.selected and not self.valid_selection(): return 'เลือก Node หรือ Member ก่อน'
        if c.current and not p.inspector.csv.isEnabled(): return 'ผลยังไม่เป็น Current — Run Analysis ก่อนส่งออก'
        return ''
    def execute(self,key):
        reason=self.disabled_reason(key)
        if self.commands[key].current and not self.panel.results_are_current(): reason='ผลยังไม่เป็น Current — Run Analysis ก่อนส่งออก'
        if reason: self.panel.status.setText(reason); return False
        c=self.commands[key]; self.invoke(c.method,c.argument); return True
    def invoke(self,method,arg=None):
        p=self.panel
        if method in ('show_inspector','show_display'):
            p.tabs.setCurrentIndex(2); p.app.show_panel(p.dock)
            section=p.sections['Result Inspector' if method=='show_inspector' else 'Display Settings']; section.toggle.setChecked(True); section.set_expanded(True); p.tabs.widget(2).ensureWidgetVisible(section)
            if method=='show_inspector' and self.valid_selection() and not p.selected_entity.startswith('node:'): p.inspector.select(p.selected_entity)
        elif method=='show_member_graph':
            from .member_graph_ui import show_member_graph
            show_member_graph(p)
        elif method=='show_tables': p.inspector.show_tables()
        elif method=='export_csv': p.inspector.export()
        elif method=='toggle_panel': p.quick.toggle_panel()
        elif method=='confirm_delete': self.confirm_delete()
        else:
            callback=getattr(p,method); callback(arg) if arg is not None else callback()
    def confirm_delete(self):
        p=self.panel; entity=p.selected_entity; model=p.model(); node=entity[5:] if entity.startswith('node:') else None
        members={m['id'] for m in model['members'] if (node in (m['i'],m['j']) if node else m['id']==entity)}
        used={n for m in model['members'] if m['id'] not in members for n in (m['i'],m['j'])}
        nodes={n['id'] for n in model['nodes'] if n['id'] not in used}
        loads=sum(row.get('member') in members or row.get('node') in nodes for kind in ('point_loads','distributed_loads') for row in model.get(kind,[]))
        text=f'{entity}\nจะลบ Member {len(members)} รายการ, Node ที่ไม่มีสมาชิก {len(nodes)} รายการ และโหลด {loads} รายการ\nผลวิเคราะห์เดิมจะไม่เป็นปัจจุบัน'
        if QMessageBox.question(p,'ยืนยันการลบ',text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes: p.delete_selected(entity)
    def show_search(self):
        if self.dialog is None: self.dialog=CommandSearch(self)
        self.dialog.setPalette(self.panel.palette()); self.dialog.refresh(); self.dialog.show(); self.dialog.raise_(); self.dialog.search.setFocus(); self.dialog.search.selectAll()
    def refresh(self):
        p=self.panel; stamp=(id(p.model()),p.job,p.thread is not None,p.selected_entity,p.inspector.csv.isEnabled())
        if stamp==getattr(self,'_status_stamp',None): return
        self._status_stamp=stamp
        if self.dialog and self.dialog.isVisible(): self.dialog.refresh()
        if self.menu and self.menu.isVisible():
            for action in self.menu.actions():
                key=action.data()
                if key in self.commands:
                    reason=self.disabled_reason(key); action.setEnabled(not reason); action.setToolTip(reason or self.commands[key].title)
    def make_context_menu(self,entity=None):
        p=self.panel
        if entity: p.select_entity(entity)
        menu=QMenu(p); menu.setPalette(p.palette()); title=menu.addAction(entity or 'GO Structural Analysis'); title.setEnabled(False); menu.addSeparator()
        keys=['edit_selected','delete_selected'] if entity else []
        if entity and not entity.startswith('node:'): keys+=['inspector','member_graph']
        keys+=['check','cases','combinations','tables','run']
        for key in keys:
            c=self.commands[key]; action=QAction(icon(c.glyph),c.title,menu); action.setData(key); reason=self.disabled_reason(key); action.setEnabled(not reason); action.setToolTip(reason or c.title); action.triggered.connect(lambda checked=False,k=key,target=entity:self.execute_context(k,target)); menu.addAction(action)
        menu.setToolTipsVisible(True); return menu
    def execute_context(self,key,entity):
        if entity and key in ('edit_selected','delete_selected','inspector','member_graph'):
            model=self.panel.model() or {}; kind,identifier=('nodes',entity[5:]) if entity.startswith('node:') else ('members',entity)
            if not any(row['id']==identifier for row in model.get(kind,[])):
                self.panel.status.setText('รายการในเมนูไม่มีอยู่แล้ว — เลือกใหม่'); return False
            self.panel.select_entity(entity)
        return self.execute(key)
    def tree_context(self,position):
        tree=self.panel.model_tree; item=tree.itemAt(position); entity=item.data(0,Qt.ItemDataRole.UserRole) if item else None
        if item: tree.setCurrentItem(item)
        if self.menu: self.menu.close(); self.menu.deleteLater()
        self.menu=self.make_context_menu(entity); self.menu.popup(tree.viewport().mapToGlobal(position))
    def eventFilter(self,obj,event):
        if obj is self.panel.app.viewport and event.type()==QEvent.Type.ContextMenu and self.panel.model():
            ws=self.panel.app.workspace()
            if ws is not None and getattr(ws,'panel',None) is not self.panel: return False
            position=event.pos(); entity=self.panel.selected_entity if event.reason()==event.Reason.Keyboard and self.valid_selection() else self.panel.native_pick(position.x(),position.y())
            if self.menu: self.menu.close(); self.menu.deleteLater()
            self.menu=self.make_context_menu(entity); self.menu.popup(event.globalPos()); event.accept(); return True
        return super().eventFilter(obj,event)

class CommandSearch(QDialog):
    def __init__(self,registry):
        super().__init__(registry.panel); self.registry=registry; self.setWindowTitle('GO — ค้นหาคำสั่ง'); self.resize(680,460); apply_style(self)
        layout=QVBoxLayout(self); self.search=QLineEdit(); self.search.setPlaceholderText('ค้นหา เช่น node, combination, ตรวจ, CSV · Ctrl+K'); layout.addWidget(self.search)
        self.list=QTreeWidget(); self.list.setHeaderLabels(['คำสั่ง','กลุ่ม / สถานะ']); self.list.setColumnWidth(0,340); layout.addWidget(self.list)
        self.notice=QLabel(); self.notice.setWordWrap(True); layout.addWidget(self.notice)
        self.execute_button=QPushButton('เรียกใช้คำสั่ง'); layout.addWidget(self.execute_button)
        self.search.textChanged.connect(self.refresh); self.list.currentItemChanged.connect(self.selection_changed); self.list.itemDoubleClicked.connect(lambda item,column:self.activate()); self.search.returnPressed.connect(self.activate); self.execute_button.clicked.connect(self.activate)
    def refresh(self,*args):
        selected=self.list.currentItem().data(0,Qt.ItemDataRole.UserRole) if self.list.currentItem() else None
        tokens=self.search.text().casefold().split(); self.list.clear(); candidate=None
        for c in self.registry.commands.values():
            if c.key=='analysis_run': continue
            if not all(t in f'{c.title} {c.group} {c.key} {c.keywords}'.casefold() for t in tokens): continue
            reason=self.registry.disabled_reason(c.key); item=QTreeWidgetItem(self.list,[c.title,reason or c.group]); item.setData(0,Qt.ItemDataRole.UserRole,c.key); item.setIcon(0,icon(c.glyph)); item.setToolTip(1,reason or c.group)
            if reason:
                color=self.palette().color(self.palette().ColorRole.PlaceholderText)
                item.setForeground(0,color)
            if c.key==selected or candidate is None and not reason: candidate=item
        self.list.setCurrentItem(candidate or self.list.topLevelItem(0)); self.selection_changed()
    def selection_changed(self,*args):
        item=self.list.currentItem(); reason=self.registry.disabled_reason(item.data(0,Qt.ItemDataRole.UserRole)) if item else 'ไม่พบคำสั่งที่ตรงกัน'
        self.notice.setText(reason or 'Enter หรือดับเบิลคลิกเพื่อเรียกใช้คำสั่ง'); self.execute_button.setEnabled(item is not None and not reason)
    def activate(self):
        item=self.list.currentItem()
        if not item: return
        key=item.data(0,Qt.ItemDataRole.UserRole); reason=self.registry.disabled_reason(key)
        if reason: self.notice.setText(reason); self.execute_button.setEnabled(False); return
        self.hide(); self.registry.execute(key)

def filter_model_tree(panel,text):
    tokens=text.casefold().split(); tree=panel.model_tree
    for i in range(tree.topLevelItemCount()):
        group=tree.topLevelItem(i); visible=False
        for j in range(group.childCount()):
            item=group.child(j); haystack=(group.text(0)+' '+item.text(0)+' '+item.text(1)).casefold(); match=all(t in haystack for t in tokens); item.setHidden(not match); visible|=match
        group.setHidden(not visible); group.setExpanded(True)
