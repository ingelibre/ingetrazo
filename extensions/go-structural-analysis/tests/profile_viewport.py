"""Run in installed MCP for comparable orbit repaint measurements."""
import json,time,statistics
from pathlib import Path
from PySide6.QtGui import QImage,QPainter,QColor

def profile(panel,name,frames=4,labels=False):
    app=panel.app; vp=app.viewport; original=app.world_to_pixels
    saved=(panel.tabs.currentIndex(),panel.diagram.currentText(),panel.show_loads.isChecked(),panel.labels.isChecked(),vp.camera.yaw)
    rows=[]; counters={}
    def projected(points):
        counters['calls']+=1; counters['points']+=len(points)
        return original(points)
    app.world_to_pixels=projected
    try:
        panel.labels.setChecked(labels)
        for tab,mode in ((0,'Model'),(1,'Model'),(2,'Mz'),(2,'Deformed')):
            panel.tabs.setCurrentIndex(tab); panel.diagram.setCurrentText(mode); panel.show_loads.setChecked(tab==1)
            assert panel.diagram.currentText()==mode, 'Requested diagram was not selected'
            if tab==2: assert panel.results_are_current(), 'Cannot benchmark missing/stale result diagrams'
            values=[]; calls=[]; points=[]
            for i in range(frames+1):
                vp.camera.yaw=saved[-1]+i*.025; counters.update(calls=0,points=0)
                image=QImage(vp.width(),vp.height(),QImage.Format.Format_ARGB32); image.fill(QColor('white'))
                p=QPainter(image); t=time.perf_counter()
                try: panel.paint(vp,p)
                finally: p.end()
                assert panel.diagram.currentText()==mode
                elapsed=(time.perf_counter()-t)*1000
                if i: values.append(elapsed); calls.append(counters['calls']); points.append(counters['points'])
            rows.append(dict(tab=tab,diagram=mode,actual_diagram=panel.diagram.currentText(),result_status=panel.result_status(),case=panel.case.currentText(),labels=labels,frames=frames,frame_times_ms=values,mean_ms=statistics.mean(values),max_ms=max(values),projection_calls=statistics.mean(calls),projected_points=statistics.mean(points)))
    finally:
        app.world_to_pixels=original; panel.tabs.setCurrentIndex(saved[0]); panel.diagram.setCurrentText(saved[1]); panel.show_loads.setChecked(saved[2]); panel.labels.setChecked(saved[3]); vp.camera.yaw=saved[4]
    root=Path.home()/'Projects/go-structural-analysis/artifacts/viewport-performance'; root.mkdir(exist_ok=True)
    (root/(name+'.json')).write_text(json.dumps(rows,indent=2),encoding='utf-8')
    return rows
