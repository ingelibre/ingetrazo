"""Executed by MCP: visual-only preview, preserves scene/history/workspace."""
import copy
import importlib
import json
from pathlib import Path
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

def verify_visuals(viewport):
    p=viewport.window()._go_structural_panel
    if p.thread is not None: raise RuntimeError('Wait for active analysis')
    module=importlib.import_module(p.__module__.rsplit('.',1)[0]+'.visualization')
    importlib.reload(module)
    out=Path.home()/'Projects/go-structural-analysis/artifacts/visual-update'
    fixtures=json.loads((out/'fixtures.json').read_text(encoding='utf-8'))
    scene=p.app.scene; history=viewport.history; workspace=p.app.workspace()
    original_data=copy.deepcopy(scene.plugin_data)
    c=viewport.camera; camera=(QVector3D(c.target),c.distance,c.yaw,c.pitch,c.perspective)
    controls=(p.tabs.currentIndex(),p.case.currentText(),p.diagram.currentText(),p.show_loads.isChecked())
    checks=[]
    try:
        for fixture in fixtures:
            p.last_data={'model':fixture['model'],'result':fixture['result']}; p.result=fixture['result']
            p.case.blockSignals(True); p.case.clear(); p.case.addItems(fixture['model']['cases']); p.case.blockSignals(False)
            p.inspector.refresh(); p.fit()
            for mode in ['Model','Reaction','V','M','N']:
                if fixture['key']!='simple_udl' and mode=='V': continue
                p.tabs.setCurrentIndex(1 if mode=='Model' else 2)
                p.diagram.setCurrentText(mode); p.show_loads.setChecked(mode=='Model')
                p.canvas.sync(); viewport.repaint(); QApplication.processEvents()
                name=fixture['key']+'-'+mode+'.png'
                ok=p.app.window.grab().save(str(out/name))
                checks.append({'file':name,'status':'Passed' if ok else 'Failed'})
    finally:
        c.target,c.distance,c.yaw,c.pitch,c.perspective=camera
        p.last_data=None; p.refresh(); p.case.setCurrentText(controls[1]); p.diagram.setCurrentText(controls[2]); p.show_loads.setChecked(controls[3]); p.tabs.setCurrentIndex(controls[0]); p.canvas.sync(); viewport.update()
        restored=p.app.scene is scene and viewport.history is history and p.app.workspace() is workspace and scene.plugin_data==original_data
        checks.append({'check':'original_model_workspace_preserved','status':'Passed' if restored else 'Failed'})
        (out/'live-results.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    return checks
