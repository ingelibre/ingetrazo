"""Presentation only: raw floating-point solver values are never rounded."""
import math
from PySide6.QtCore import QRectF,QPointF

DEFAULTS=dict(labels=True,density='Normal',axes='Selected',diagram_scale=1.,deformation_scale=100.,tolerance=1e-6,displacement_unit='mm',plane=True)

def format_value(value,quantity,scale=1.,tolerance=1e-6,mm=True):
    displacement=quantity in ('d','dy','dz','u','ux','uy','uz','D')
    factor=1000. if displacement and mm else 1.
    threshold=max(1e-12,abs(scale)*tolerance)
    text='≈0' if abs(value)<=threshold else f'{value*factor:.6g}'
    unit='mm' if displacement and mm else 'm' if displacement else 'kN·m' if quantity in ('M','My','Mz','T') else 'kN'
    return text+' '+unit

class LabelPlacer:
    """Greedy screen-space placement with explicit bounds and density limits."""
    def __init__(self,width,height,metrics,density='Normal'):
        self.bounds=QRectF(8,90,max(0,width-16),max(0,height-100)); self.metrics=metrics; self.rects=[]
        self._grid={}; self._boxes=[]
        self.limit={'Sparse':35,'Normal':100,'Dense':300}.get(density,100)
    def place(self,point,text,offset=(5,-7)):
        if len(self.rects)>=self.limit: return None
        width=self.metrics.horizontalAdvance(text)+8; height=self.metrics.height()+4
        px,py=point.x(),point.y(); left,top,right,bottom=self.bounds.left(),self.bounds.top(),self.bounds.right(),self.bounds.bottom()
        for dx,dy in ((offset[0],offset[1]),(8,18),(8,-25),(-width-8,18),(-width-8,-25),(8,40),(8,-45)):
            x,y=px+dx,py+dy-height; x2,y2=x+width,y+height
            if x<left or y<top or x2>right or y2>bottom: continue
            cells=[(i,j) for i in range(math.floor(x/64),math.floor(x2/64)+1) for j in range(math.floor(y/64),math.floor(y2/64)+1)]
            candidates={index for cell in cells for index in self._grid.get(cell,())}
            if any(x<b[2] and x2>b[0] and y<b[3] and y2>b[1] for index in candidates for b in (self._boxes[index],)): continue
            index=len(self.rects); self.rects.append(QRectF(x,y,width,height)); self._boxes.append((x,y,x2,y2))
            for cell in cells: self._grid.setdefault(cell,[]).append(index)
            return QPointF(x+4,y2-3)
        return None

def selected_member(panel):
    selected=getattr(panel,'selected_entity',None)
    if selected and not selected.startswith('node:'): return selected
    return panel.inspector.member.currentText() if hasattr(panel,'inspector') else None

def axes_visible(panel,mid):
    if not panel.local_axes.isChecked(): return False
    mode=panel.axes_mode.currentText() if hasattr(panel,'axes_mode') else 'Selected'
    return mode=='All' or (mode=='Selected' and mid==selected_member(panel))

def watermark(panel,painter):
    status=panel.result_status() if hasattr(panel,'result_status') else 'Current'
    if status=='Current': return
    from PySide6.QtGui import QColor,QPen
    text='RESULTS OUT OF DATE' if panel.result else status.upper()
    if status in ('Running','Failed'): text=status.upper()+' — '+('RESULTS OUT OF DATE' if panel.result else 'NO CURRENT RESULTS')
    if getattr(panel,'archive_view',None) and panel.archive_view.isChecked() and panel.result: text='ARCHIVED / STALE — '+text
    painter.save(); painter.setPen(QPen(QColor('#b85334'))); font=painter.font(); font.setBold(True); font.setPointSize(16); painter.setFont(font); painter.drawText(16,112,text); painter.restore()
