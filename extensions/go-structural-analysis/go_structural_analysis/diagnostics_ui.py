"""Read-only diagnostics; no automatic merge/delete of engineering inputs."""
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QDoubleSpinBox,QPushButton,QTableWidget,QTableWidgetItem,QHeaderView
from .diagnostics import inspect_model
from .theme import ThemeAware,apply_style

class ModelCheckDialog(ThemeAware,QDialog):
    def __init__(self,panel):
        super().__init__(panel); self.panel=panel; apply_style(self); self.setWindowTitle('Model / Stability Check'); self.resize(900,520)
        box=QVBoxLayout(self); row=QHBoxLayout(); row.addWidget(QLabel('Geometry tolerance [m]'))
        self.tolerance=QDoubleSpinBox(); self.tolerance.setDecimals(9); self.tolerance.setRange(1e-9,.1); self.tolerance.setValue(1e-6); row.addWidget(self.tolerance)
        refresh=QPushButton('Check again'); refresh.clicked.connect(self.refresh); row.addWidget(refresh); box.addLayout(row)
        self.summary=QLabel(); self.summary.setWordWrap(True); box.addWidget(self.summary)
        self.table=QTableWidget(0,4); self.table.setHorizontalHeaderLabels(['Status','Issue','Node / Member IDs','Details']); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); box.addWidget(self.table)
        self.table.cellClicked.connect(self.select_issue)
        note=QLabel('Rigid-body screening does not detect every internal mechanism. Run Analysis checks the active stiffness matrix in the background. Buckling / capacity / code compliance: Not Available. Crossing warnings require review of the intended physical joint.'); note.setWordWrap(True); box.addWidget(note)
        run=QPushButton('Run Analysis + stiffness check'); run.clicked.connect(self.run_analysis); box.addWidget(run); self.refresh()
    def refresh(self):
        self.report=inspect_model(self.panel.model(),self.tolerance.value()); r=self.report
        self.summary.setText(f"{r['node_count']} nodes | {r['member_count']} members | {r['components']} components | {r['errors']} Errors | {r['warnings']} Warnings\nInternal stiffness: Not Checked by this precheck. Analysis results: {self.panel.result_status()}")
        self.table.setRowCount(len(r['issues']))
        for i,issue in enumerate(r['issues']):
            for j,value in enumerate((issue['severity'],issue['code'],', '.join(issue['entities']),issue['detail'])): self.table.setItem(i,j,QTableWidgetItem(value))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    def select_issue(self,row,column):
        ids=self.report['issues'][row]['entities']
        if ids: self.panel.select_entity(ids[0]); self.panel.redraw()
    def run_analysis(self):
        self.refresh()
        if self.report['errors']: self.summary.setText(self.summary.text()+'\nResolve geometry/restraint errors before this analysis.'); return
        self.close(); self.panel.run()
