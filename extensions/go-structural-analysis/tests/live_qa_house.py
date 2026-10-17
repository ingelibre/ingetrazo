"""Installed-host MCP QA for the house demo; never replaces the parked document."""
import copy
import json
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

class HouseQA:
    def __init__(self,viewport):
        self.vp=viewport; self.p=viewport.window()._go_structural_panel; self.app=self.p.app
        self.root=Path.home()/'Projects/go-structural-analysis'
        self.out=self.root/'artifacts/house'; self.out.mkdir(exist_ok=True)
        self.checks={}; self.ticks=0
    def check(self,name,ok,**details):
        self.checks[name]=dict(status='Passed' if ok else 'Failed',**details)
        (self.out/'live-results.json').write_text(json.dumps(self.checks,indent=2),encoding='utf-8')
        if not ok: raise AssertionError(name)
    def capture(self,name):
        self.p.canvas.sync(); self.vp.repaint(); QApplication.processEvents()
        self.check('capture_'+name,self.app.window.grab().save(str(self.out/(name+'.png'))))
    def start(self):
        if self.app.workspace() is not None or self.p.thread is not None:
            raise RuntimeError('Requires an idle original document')
        from formats.igz import save_scene
        self.original=self.app.scene; self.original_data=copy.deepcopy(self.original.plugin_data); self.original_history=self.vp.history
        save_scene(self.original,self.root/'backups/house-phetnaray-before-20261010/cold-open-model-before.igz')
        index=self.p.examples.findData('3d_house_phetnaray')
        self.check('cold_catalog_entry',index>=0)
        self.p.examples.setCurrentIndex(index); self.p.example_button.click()
        self.check('example_button_load',len(self.p.model()['nodes'])==146 and len(self.p.model()['members'])==255)
        self.app.show_panel(self.p.dock); self.p.labels.setChecked(False); self.p.tabs.setCurrentIndex(0); self.p.fit()
        self.capture('House-Model')
        self.timer=QTimer(self.p); self.timer.setInterval(10); self.timer.timeout.connect(self.tick); self.timer.start(); self.p.run()
        self.check('background_started',self.p.result_status()=='Running')
    def tick(self):
        if self.p.thread is not None: self.ticks+=1
    def finish(self):
        if self.p.thread is not None: raise RuntimeError('Worker still running')
        self.timer.stop()
        self.check('current_analysis',self.p.results_are_current(),message=self.p.status.text())
        self.check('background_gui_responsive',self.ticks>0,ticks=self.ticks)
        self.check('all_cases_equilibrium',len(self.p.result['cases'])==10 and all(c['equilibrium']['passed'] for c in self.p.result['cases'].values()))
        self.p.case.setCurrentText('DEMO Gravity'); self.p.tabs.setCurrentIndex(1); self.capture('House-Loads')
        self.p.tabs.setCurrentIndex(2)
        for diagram in ('Mz','N','Deformed','Reaction'):
            self.p.diagram.setCurrentText(diagram); self.capture('House-'+diagram)
        from formats.igz import save_scene,load_into
        from core.scene import Scene
        path=self.root/'examples/house/Phetnaray-RC-Steel-Roof.igz'
        save_scene(self.app.scene,path); loaded=Scene(); load_into(loaded,path)
        self.check('igz_save_load',loaded.plugin_data==self.app.scene.plugin_data,file=str(path))
        old=copy.deepcopy(self.p.model()); changed=copy.deepcopy(old); changed['materials'][0]['E']*=.95
        self.p.put(changed); self.check('edit_stale',self.p.result_status()=='Stale')
        self.vp.history.undo(); self.p.refresh(); self.check('undo_current',self.p.results_are_current())
        ws=self.app.workspace()
        # Use the same document key as the installed panel rather than assumptions.
        import importlib
        key=importlib.import_module(self.p.__module__).KEY
        ws.saved=copy.deepcopy(self.app.scene.plugin_data.get(key)); self.app.leave_workspace(); self.p.refresh()
        self.check('original_document_restored',self.app.scene is self.original and self.original.plugin_data==self.original_data and self.vp.history is self.original_history)
        return path
