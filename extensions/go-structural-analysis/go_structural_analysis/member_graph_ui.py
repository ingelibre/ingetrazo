"""Modeless per-member plots. Each member retains its own local axes/signs."""
from PySide6.QtCore import Qt,QTimer,QPointF
from PySide6.QtGui import QPainter,QPainterPath,QPen,QColor
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QScrollArea,QWidget,QDoubleSpinBox
from .theme import ThemeAware,apply_style
from .results import evaluate,UNITS
from .member_geometry import member_length,collinear_members
from .continuous_graph import graph_data,inspect_chain,station

class MemberPlot(QWidget):
    def __init__(self,member,quantity,parent=None,continuous=None,on_station=None):
        super().__init__(parent); self.member=member; self.quantity=quantity; self.continuous=continuous; self.on_station=on_station
        self.setMinimumHeight(360 if continuous else 200)
        if continuous: self.setMinimumWidth(max(700,len(continuous['records'])*220))
    def mousePressEvent(self,event):
        if self.continuous and self.on_station and event.button()==Qt.MouseButton.LeftButton:
            x=max(0.,min(self.continuous['L'],(event.position().x()-65)/max(1,self.width()-90)*self.continuous['L']))
            self.on_station(x); return
        super().mousePressEvent(event)
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        k=self.quantity; m=self.member; factor=1000 if k in ('d','D') else 1; unit='mm' if factor==1000 else UNITS[k]
        series=[]
        if self.continuous:
            series=[[(x,value*factor) for x,value in row] for row in self.continuous['series']]
        else:
            for seg in m['segments']:
                points=[(seg['x1']+(seg['x2']-seg['x1'])*i/48) for i in range(49)]
                series.append([(x,evaluate(m,x,'left' if i==48 else 'right')[k]*factor) for i,x in enumerate(points)])
        peak=max((abs(v) for row in series for x,v in row),default=0)
        ext=m.get('extrema',{}).get(k,{})
        peak=max([peak]+[abs(e['value']*factor) for e in ext.values()]); scale=(self.height()-(150 if self.continuous else 85))/2/(peak or 1)
        left=65; width=max(1,self.width()-90); base=(self.height()+20)/2
        point=lambda x,v:QPointF(left+x/m['L']*width,base-v*scale)
        p.setPen(QPen(self.palette().color(self.palette().ColorRole.Mid),1)); p.drawLine(QPointF(left,base),QPointF(left+width,base))
        if self.continuous:
            p.setPen(QPen(self.palette().color(self.palette().ColorRole.Mid),1,Qt.PenStyle.DashLine))
            records=self.continuous['records']
            for record in records:
                x=point(record['start'],0).x(); p.drawLine(QPointF(x,85),QPointF(x,self.height()-48))
            p.setPen(self.palette().color(self.palette().ColorRole.Text))
            for record in records:
                middle=point((record['start']+record['end'])/2,0).x()
                p.drawText(int(middle)-50,82,f'{record["id"]} · {record["end"]-record["start"]:.5g} m')
                p.drawText(int(point(record['start'],0).x())-12,self.height()-28,f'{record["left_node"]} · {record["start"]:.5g} m')
            end=records[-1]; p.drawText(left+int(width)-90,self.height()-28,f'{end["right_node"]} · {end["end"]:.5g} m')
        if self.continuous:
            for previous,next_row in zip(series,series[1:]):
                if abs(previous[-1][0]-next_row[0][0])<1e-8:
                    p.setPen(QPen(self.palette().color(self.palette().ColorRole.Text),1,Qt.PenStyle.DashLine))
                    p.drawLine(point(*previous[-1]),point(*next_row[0]))
        for row in series:
            for (x,v),(nx,nv) in zip(row,row[1:]):
                pieces=[((x,v),(nx,nv))]
                if v*nv<0:
                    zero=x+(nx-x)*abs(v)/(abs(v)+abs(nv)); pieces=[((x,v),(zero,0)),((zero,0),(nx,nv))]
                for (a,b),(c,d) in pieces:
                    color=QColor('#2684d9' if b+d>=0 else '#df7246'); fill=QColor(color); fill.setAlpha(65)
                    path=QPainterPath(point(a,0)); path.lineTo(point(a,b)); path.lineTo(point(c,d)); path.lineTo(point(c,0)); path.closeSubpath()
                    p.fillPath(path,fill); p.setPen(QPen(color,1.6)); p.drawLine(point(a,b),point(c,d))
        p.setPen(self.palette().color(self.palette().ColorRole.Text)); p.drawText(12,20,f'{k} [{unit}] · + blue / − orange · '+('common axes · click graph to inspect station s' if self.continuous else 'local x: i → j'))
        p.drawText(left,self.height()-8,'0'); p.drawText(left+int(width)-55,self.height()-8,f'{m["L"]:.5g} m')
        if self.continuous:
            for line,(kind,value) in enumerate(ext.items()):
                p.drawText(12,40+line*18,f'{kind}: {value["value"]*factor:.6g} {unit} @ s={value["x"]:.5g} m · {value["member"]} local x={value["local_x"]:.5g} m ({value["side"]})')
        else: p.drawText(12,40,'   '.join(f'{kind}: {value["value"]*factor:.6g} {unit} @ x={value["x"]:.5g} m ({value.get("side","right")})' for kind,value in ext.items()))

class MemberGraphDialog(ThemeAware,QDialog):
    def __init__(self,panel,identifier):
        super().__init__(panel.app.window); self.panel=panel; self.identifier=identifier; self.setModal(False); self.setObjectName('goEditor'); apply_style(self)
        self.setWindowTitle('GO — Member diagrams / กราฟสมาชิก'); self.resize(900,650)
        box=QVBoxLayout(self); self.notice=QLabel(); self.notice.setWordWrap(True); box.addWidget(self.notice)
        row=QHBoxLayout(); self.scope=QComboBox(); self.scope.addItems(['Selected member / สมาชิกเดียว','Connected collinear / สมาชิกต่อกันแนวเดียวกัน']); row.addWidget(self.scope)
        self.case=QComboBox(); row.addWidget(self.case); self.quantity=QComboBox(); row.addWidget(self.quantity); box.addLayout(row)
        sample=QHBoxLayout(); self.member=QComboBox(); sample.addWidget(self.member); self.ratio=QDoubleSpinBox(); self.ratio.setRange(0,1); self.ratio.setDecimals(4); self.ratio.setPrefix('x/L = '); sample.addWidget(self.ratio)
        self.side=QComboBox(); self.side.addItems(['right','left']); sample.addWidget(self.side); box.addLayout(sample)
        self.values=QLabel(); self.values.setWordWrap(True); box.addWidget(self.values)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); self.body=QWidget(); self.graphs=QVBoxLayout(self.body); scroll.setWidget(self.body); box.addWidget(scroll)
        self.scope.currentIndexChanged.connect(self.refresh); self.case.currentTextChanged.connect(self.refresh); self.quantity.currentTextChanged.connect(self.refresh)
        self.member.currentTextChanged.connect(self.inspect); self.ratio.valueChanged.connect(self.inspect); self.side.currentTextChanged.connect(self.inspect)
        self.chain_data=None; self.timer=QTimer(self); self.timer.setInterval(300); self.timer.timeout.connect(self.refresh); self.timer.start(); self.stamp=None; self.refresh()
    def refresh(self,*args):
        p=self.panel; model=p.model() or {}; current=p.results_are_current()
        stamp=(id(p.result),repr(model),current,self.scope.currentIndex(),self.case.currentText(),self.quantity.currentText())
        if stamp==self.stamp: return
        self.stamp=stamp
        self.chain_data=None
        self.body.setMinimumWidth(0)
        while self.graphs.count():
            item=self.graphs.takeAt(0)
            if item.widget():
                item.widget().hide(); item.widget().deleteLater()
        exists=any(m['id']==self.identifier for m in model.get('members',[]))
        if not current or not exists:
            self.notice.setText(p.result_status()+' — RESULTS OUT OF DATE / Run Analysis' if exists else 'Member removed — select again')
            self.values.clear(); self.member.clear(); return
        names=list(p.result['cases']); old=self.case.currentText() or p.case.currentText()
        if [self.case.itemText(i) for i in range(self.case.count())]!=names:
            self.case.blockSignals(True); self.case.clear(); self.case.addItems(names); self.case.setCurrentText(old); self.case.blockSignals(False)
        quantities=['N','Vy','Vz','T','My','Mz','D'] if model.get('schema')==2 else ['N','V','M','d']
        if [self.quantity.itemText(i) for i in range(self.quantity.count())]!=quantities:
            self.quantity.blockSignals(True); self.quantity.clear(); self.quantity.addItems(quantities); self.quantity.blockSignals(False)
        ids=collinear_members(model,self.identifier) if self.scope.currentIndex() else [self.identifier]
        self.member.blockSignals(True); old=self.member.currentText(); self.member.clear(); self.member.addItems(ids); self.member.setCurrentText(old if old in ids else self.identifier); self.member.blockSignals(False)
        metadata=model.get('combination_metadata',{}).get(self.case.currentText(),{})
        self.notice.setText('Current · '+self.case.currentText()+' · '+metadata.get('method','Load Case')+'\nEach plot uses that member’s local i → j axes; separate plots retain signs. Capacity / Code Compliance: Not Available.')
        members=p.result['cases'].get(self.case.currentText(),{}).get('members',{})
        if self.scope.currentIndex():
            try:
                self.chain_data=graph_data(model,members,self.identifier,self.quantity.currentText())
                data=self.chain_data
                self.body.setMinimumWidth(max(700,len(data['records'])*220)+24)
                self.notice.setText('Current · '+self.case.currentText()+' · '+metadata.get('method','Load Case')+f'\nContinuous beam · total L={data["L"]:.8g} m · common axes = {self.identifier} i → j; section forces converted to common cut direction. Capacity / Code Compliance: Not Available.')
                self.graphs.addWidget(MemberPlot(dict(L=data['L'],extrema={self.quantity.currentText():data['extrema']}),self.quantity.currentText(),self.body,continuous=data,on_station=self.select_station))
            except (ValueError,KeyError) as exc:
                self.notice.setText('Cannot display continuous graph: '+str(exc)); self.values.clear(); return
        else:
            for mid in ids:
                m=next(m for m in model['members'] if m['id']==mid); self.graphs.addWidget(QLabel(f'{mid} · {m["i"]} → {m["j"]} · L = {member_length(model,mid):.8g} m'))
                if mid in members: self.graphs.addWidget(MemberPlot(members[mid],self.quantity.currentText(),self.body))
        self.graphs.addStretch(); self.inspect()
    def inspect(self,*args):
        if not self.panel.results_are_current(): self.values.clear(); return
        m=(self.panel.result or {}).get('cases',{}).get(self.case.currentText(),{}).get('members',{}).get(self.member.currentText())
        if not m: self.values.clear(); return
        local_side=self.side.currentText()
        record=next((r for r in self.chain_data['records'] if r['id']==self.member.currentText()),None) if self.chain_data else None
        if record and not record['forward']: local_side='left' if local_side=='right' else 'right'
        v=evaluate(m,self.ratio.value()*m['L'],local_side); keys=['N','Vy','Vz','T','My','Mz','D'] if 'D' in v else ['N','V','M','d']
        prefix=f'{self.member.currentText()} · local x={v["x"]:.8g} m · '
        if self.chain_data:
            reference=self.chain_data['reference']
            prefix+=f's={station(record,m,v["x"]):.8g} m · common axes · '
            v.update({k:inspect_chain(m,reference,k,v['x'],local_side) for k in keys})
        self.values.setText(prefix+'   '.join(f'{k}={v[k]*(1000 if k in ("D","d") else 1):.8g} '+('mm' if k in ('D','d') else UNITS[k]) for k in keys))
    def select_station(self,value):
        if not self.chain_data or not self.panel.results_are_current(): return
        records=self.chain_data['records']; candidates=[r for r in records if r['start']-1e-9<=value<=r['end']+1e-9]
        if not candidates: return
        record=candidates[0] if self.side.currentText()=='left' else candidates[-1]
        length=record['end']-record['start']; ratio=max(0.,min(1.,(value-record['start'])/length))
        self.member.setCurrentText(record['id']); self.ratio.setValue(ratio if record['forward'] else 1-ratio); self.inspect()
    def closeEvent(self,event):
        self.timer.stop(); super().closeEvent(event)
    def showEvent(self,event):
        self.timer.start(); self.refresh(); super().showEvent(event)

def show_member_graph(panel):
    mid=panel.selected_entity
    if not mid or mid.startswith('node:') or not panel.results_are_current(): return
    previous=getattr(panel,'member_graph_dialog',None)
    if previous: previous.close(); previous.deleteLater()
    panel.member_graph_dialog=MemberGraphDialog(panel,mid); panel.member_graph_dialog.show(); panel.member_graph_dialog.raise_()
