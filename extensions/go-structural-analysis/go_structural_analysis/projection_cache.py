"""Batch host API projection. Cache world points, never camera-space coordinates."""
from PySide6.QtCore import QPointF
from .safety import fingerprint

class Collector:
    def __init__(self): self.index={}; self.points=[]
    def __call__(self,points):
        out=[]
        for point in points:
            key=tuple(point)
            if key not in self.index:
                self.index[key]=len(self.points); self.points.append(key)
            out.append((QPointF(float(point[0]),float(point[1])),True))
        return out

class NullPainter:
    def __init__(self,painter): self.painter=painter
    def fontMetrics(self): return self.painter.fontMetrics()
    def __getattr__(self,name): return lambda *args,**kwargs:None

def signature(panel):
    def value(name,method,default=None):
        control=getattr(panel,name,None)
        return getattr(control,method)() if control is not None else default
    return (fingerprint(panel.model()),id(panel.result),panel.results_are_current(),
        value('case','currentText'),value('diagram','currentText'),panel.tabs.currentIndex(),
        value('diagram_scale','value'),value('scale','value'),value('show_loads','isChecked'),
        value('local_axes','isChecked'),value('axes_mode','currentText'),value('diagram_plane','isChecked'),
        value('labels','isChecked'),
        getattr(panel,'selected_entity',None),getattr(panel,'last_picked_member',None),
        panel.inspector.ratio.value() if getattr(panel,'inspector',None) else None)

def batched_draw(panel,viewport,painter,draw):
    key=signature(panel); cache=getattr(panel,'_projection_pool',None)
    if cache is None or cache[0]!=key:
        collect=Collector(); panel._projection_pool=(key,collect)
        draw(panel,viewport,NullPainter(painter),collect)
        # A single active pool keeps memory bounded even with many result cases.
        cache=(key,collect); panel._projection_pool=cache
    collect=cache[1]
    if not collect.points: return
    px,py,front=panel.app.world_to_pixels(collect.points)
    pixels=getattr(collect,'pixels',None)
    if pixels is None or len(pixels)!=len(collect.points):
        pixels=[[QPointF(),False] for _ in collect.points]; collect.pixels=pixels
    for pixel,x,y,f in zip(pixels,px,py,front):
        pixel[0].setX(float(x)); pixel[0].setY(float(y)); pixel[1]=bool(f)
    def project(points):
        keys=[tuple(p) for p in points]
        if any(k not in collect.index for k in keys):
            # Screen-dependent glyph branches may request extra points. Keep
            # correctness and add them for the next frame, without caching pixels.
            ax,ay,af=panel.app.world_to_pixels(points)
            out=[(QPointF(float(x),float(y)),bool(f)) for x,y,f in zip(ax,ay,af)]
            for k,pixel in zip(keys,out):
                if k not in collect.index:
                    collect.index[k]=len(collect.points); collect.points.append(k); pixels.append(pixel)
            return out
        return [pixels[collect.index[k]] for k in keys]
    draw(panel,viewport,painter,project)
