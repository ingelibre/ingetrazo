"""Compact workspace ribbon; commands delegate to the existing panel workflows."""
from PySide6.QtCore import Qt,QEvent
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QTabBar,QStackedWidget,QScrollArea,QToolButton,QLabel,QFrame
from .icons import icon
from .theme import apply_style

class WorkspaceRibbon(QWidget):
    def __init__(self,panel):
        super().__init__(panel.app.viewport); self.panel=panel; self.setObjectName('goRibbon'); self.setAutoFillBackground(True)
        self.buttons={}; self.requires_model=[]; self._syncing=False
        layout=QVBoxLayout(self); layout.setContentsMargins(6,4,6,4); layout.setSpacing(3)
        header=QHBoxLayout(); title=QLabel('GO'); title.setObjectName('goTitle'); header.addWidget(title)
        self.add_button(header,'save','บันทึก','save',lambda:panel.commands.execute('save'),'บันทึกโมเดลวิเคราะห์เป็นไฟล์ .igz')
        self.add_button(header,'run','วิเคราะห์','run',lambda:panel.commands.execute('run'),'Run Analysis ด้วย Background Worker')
        self.add_button(header,'search','ค้นหา','sections',panel.commands.show_search,'ค้นหาคำสั่ง · Ctrl+K')
        self.tabs=QTabBar(); self.tabs.setExpanding(False); self.tabs.setUsesScrollButtons(True)
        for name in ('Model','Loads','Analysis','Results','Display'): self.tabs.addTab(name)
        header.addWidget(self.tabs,1)
        self.status=QLabel(); header.addWidget(self.status)
        self.collapse=QToolButton(); self.collapse.setText('พับ'); self.collapse.setCheckable(True); self.collapse.setToolTip('พับกลุ่มคำสั่งเพื่อเพิ่มพื้นที่โมเดล'); header.addWidget(self.collapse); layout.addLayout(header)
        self.pages=QStackedWidget(); layout.addWidget(self.pages)
        groups=[
            [('Geometry',[('nodes','Nodes','nodes','edit_section','nodes'),('members','Members','members','edit_section','members')]),
             ('Properties',[('materials','Materials','materials','edit_section','materials'),('sections','Sections','sections','edit_section','sections'),('supports','Supports','supports','edit_section','nodes')]),
             ('Selection',[('edit_selected','แก้ไขที่เลือก','members','edit_selected',None),('geometry','จาก Geometry','workspace','import_geometry',None)])],
            [('Cases / Combinations',[('cases','Load Cases','point','edit','cases'),('combinations','Combinations','distributed','open_combinations',None)]),
             ('Applied loads',[('point_loads','Point / Moment','point','edit_section','point_loads'),('distributed_loads','Distributed','distributed','edit_section','distributed_loads')])],
            [('Validation',[('check','Check Model','supports','check_model',None)]),
             ('Solver',[('analysis_run','Run Analysis','run','run',None)])],
            [('Inspect',[('inspector','Result Inspector','members','show_inspector',None),('tables','Result Tables','sections','show_tables',None)]),
             ('Export',[('csv','CSV','save','export_csv',None),('report','Engineering Report','save','export_engineering_report',None)])],
            [('Display',[('display','Diagram / Labels','workspace','show_display',None),('defaults','Restore Defaults','back','restore_display',None)]),
             ('Workspace',[('panel','Panel','workspace','toggle_panel',None),('return','กลับโมเดลเดิม','back','leave',None)])]
        ]
        for page_groups in groups:
            scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame); scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            body=QWidget(); row=QHBoxLayout(body); row.setContentsMargins(0,0,0,0); row.setSpacing(12)
            for title,commands in page_groups:
                group=QWidget(); box=QVBoxLayout(group); box.setContentsMargins(3,0,3,0); box.setSpacing(2); actions=QHBoxLayout(); actions.setSpacing(5); box.addLayout(actions)
                for key,text,glyph,method,arg in commands:
                    self.add_button(actions,key,text,glyph,lambda k=key:panel.commands.execute(k),text+' — '+title)
                    if key not in ('defaults','display','panel','return'): self.requires_model.append(key)
                label=QLabel(title); label.setObjectName('goMuted'); box.addWidget(label); row.addWidget(group)
            row.addStretch(); scroll.setWidget(body); self.pages.addWidget(scroll)
        self.pages.setFixedHeight(70)
        self.tabs.currentChanged.connect(self.select_tab); self.collapse.toggled.connect(self.set_collapsed)
        panel.tabs.currentChanged.connect(self.follow_panel)
        panel.app.viewport.installEventFilter(self); apply_style(self); self.refresh()
    def add_button(self,layout,key,text,glyph,callback,tooltip):
        button=QToolButton(); button.setText(text); button.setProperty('go_icon',glyph); button.setIcon(icon(glyph)); button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon); button.setToolTip(tooltip); button.clicked.connect(lambda checked=False:callback()); layout.addWidget(button); self.buttons[key]=button
    def invoke(self,method,arg):
        self.panel.commands.invoke(method,arg)
    def select_tab(self,index):
        self.pages.setCurrentIndex(index)
        if not self._syncing:
            self._syncing=True
            try: self.panel.tabs.setCurrentIndex({0:0,1:1,2:0,3:2,4:2}[index])
            finally: self._syncing=False
    def follow_panel(self,index):
        if self._syncing: return
        self._syncing=True
        try:
            target={0:0,1:1,2:3}[index]
            if self.tabs.currentIndex() not in ({0,2} if index==0 else {3,4} if index==2 else {1}): self.tabs.setCurrentIndex(target)
        finally: self._syncing=False
    def set_collapsed(self,collapsed):
        self.pages.setVisible(not collapsed); self.collapse.setText('ขยาย' if collapsed else 'พับ'); self.position()
    def position(self):
        self.setFixedWidth(max(100,self.panel.app.viewport.width()-20)); self.adjustSize(); self.move(10,10); self.raise_()
    def eventFilter(self,obj,event):
        if obj is self.panel.app.viewport and event.type()==QEvent.Type.Resize: self.position()
        return super().eventFilter(obj,event)
    def refresh(self):
        p=self.panel
        for key,button in self.buttons.items():
            if key in p.commands.commands:
                reason=p.commands.disabled_reason(key); button.setEnabled(not reason); button.setToolTip(reason or p.commands.commands[key].title)
        self.status.setText(p.state_badge.text().split(' · ',1)[0]); self.status.setToolTip(p.state_badge.text()); self.setPalette(p.palette()); self.follow_panel(p.tabs.currentIndex()); self.position(); self.show()
