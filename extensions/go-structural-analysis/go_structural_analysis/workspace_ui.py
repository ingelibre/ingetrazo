from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QToolButton,QLabel,QComboBox,QDoubleSpinBox,QCheckBox,QPushButton

class Section(QWidget):
    def __init__(self,title,parent=None):
        super().__init__(parent); box=QVBoxLayout(self); box.setContentsMargins(0,0,0,0); box.setSpacing(6)
        self.toggle=QToolButton(); self.toggle.setText(title); self.toggle.setCheckable(True); self.toggle.setChecked(True); self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon); self.toggle.setArrowType(Qt.ArrowType.DownArrow); box.addWidget(self.toggle)
        self.body=QWidget(); self.layout=QVBoxLayout(self.body); self.layout.setContentsMargins(3,3,3,8); box.addWidget(self.body)
        self.toggle.toggled.connect(self.set_expanded)
    def set_expanded(self,expanded): self.body.setVisible(expanded); self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

class QuickControls(QWidget):
    def __init__(self,panel):
        super().__init__(panel.app.viewport); self.panel=panel; self.setObjectName('goQuickControls'); self.setAutoFillBackground(True)
        box=QHBoxLayout(self); box.setContentsMargins(6,4,6,4); self.mode=QComboBox(); self.mode.addItems(['Model','Loads','Results']); self.mode.currentIndexChanged.connect(panel.tabs.setCurrentIndex); box.addWidget(self.mode)
        self.diagram=QComboBox(); self.case=QComboBox()
        for control,target in ((self.diagram,panel.diagram),(self.case,panel.case)):
            control.setMinimumWidth(75); control.setMaximumWidth(165); control.currentTextChanged.connect(target.setCurrentText); box.addWidget(control)
        self.scale=QDoubleSpinBox(); self.scale.setRange(.001,1e6); self.scale.setPrefix('D × '); self.scale.setMaximumWidth(110); self.scale.valueChanged.connect(panel.scale.setValue); box.addWidget(self.scale)
        self.labels=QCheckBox('Labels'); self.labels.toggled.connect(panel.labels.setChecked); box.addWidget(self.labels)
        self.axes=QComboBox(); self.axes.addItems(['Selected','All','None']); self.axes.currentTextChanged.connect(panel.axes_mode.setCurrentText); self.axes.setMaximumWidth(90); box.addWidget(self.axes)
        self.hide_button=QPushButton('Panel'); self.hide_button.clicked.connect(self.toggle_panel); box.addWidget(self.hide_button); self.refresh()
    def toggle_panel(self):
        dock=getattr(self.panel,'dock',None)
        if dock: dock.setVisible(not dock.isVisible())
    def refresh(self):
        p=self.panel
        for control,target in ((self.diagram,p.diagram),(self.case,p.case)):
            items=[target.itemText(i) for i in range(target.count())]; control.blockSignals(True)
            if [control.itemText(i) for i in range(control.count())]!=items: control.clear(); control.addItems(items)
            control.setCurrentText(target.currentText()); control.setToolTip(target.currentText()); control.blockSignals(False)
        for control,value,setter in ((self.scale,p.scale.value(),'setValue'),(self.labels,p.labels.isChecked(),'setChecked'),(self.axes,p.axes_mode.currentText(),'setCurrentText'),(self.mode,p.tabs.currentIndex(),'setCurrentIndex')):
            control.blockSignals(True); getattr(control,setter)(value); control.blockSignals(False)
        self.setPalette(p.palette()); self.adjustSize(); self.setMaximumWidth(max(200,p.app.viewport.width()-20)); self.move(10,max(130,p.app.viewport.height()-self.height()-12)); self.show(); self.raise_()
