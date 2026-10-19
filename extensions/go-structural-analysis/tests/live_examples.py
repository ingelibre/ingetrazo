"""MCP entry: gallery = ExampleGallery(viewport); gallery.start()."""
import copy
import importlib
import json
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


class ExampleGallery:
    def __init__(self,viewport):
        self.vp=viewport; self.panel=viewport.window()._go_structural_panel
        self.app=self.panel.app
        self.module=importlib.import_module(self.panel.__module__.rsplit('.',1)[0]+'.examples')
        self.out=Path.home()/'Projects/go-structural-analysis/artifacts/examples-v0.1.3'
        self.out.mkdir(parents=True,exist_ok=True)
        self.checks=[]; self.index=0; self.waiting=False

    def start(self):
        if self.app.workspace() is not None or self.panel.thread is not None: raise RuntimeError('Host must be idle')
        self.original=self.app.scene; self.history=self.vp.history
        self.data=copy.deepcopy(self.original.plugin_data)
        c=self.vp.camera; self.camera=[list(c.target.toTuple()),c.distance,c.yaw,c.pitch,c.perspective]
        self.panel.enter(); self.app.show_panel(self.panel.dock)
        self.timer=QTimer(self.panel); self.timer.setInterval(150); self.timer.timeout.connect(self.step); self.timer.start()

    def record(self):
        (self.out/'live-results.json').write_text(json.dumps(self.checks,indent=2),encoding='utf-8')

    def grab(self,name):
        self.panel.canvas.sync(); self.vp.repaint(); QApplication.processEvents()
        if not self.app.window.grab().save(str(self.out/(name+'.png'))): raise RuntimeError('Capture failed')

    def step(self):
        self.timer.stop()
        try:
            p=self.panel
            if self.waiting:
                if p.thread is not None: self.timer.start(); return
                key,title,_=self.module.CATALOG[self.index]
                expected_failure=key.startswith('unstable')
                current=importlib.import_module(p.__module__.rsplit('.',1)[0]+'.results').is_current(p.model(),p.result)
                passed=('Analysis failed:' in p.status.text() and not current) if expected_failure else current
                item={'key':key,'title':title,'status':'Passed' if passed else 'Failed','expected':'unstable rejection' if expected_failure else 'successful analysis','message':p.status.text()}
                self.checks.append(item); self.record()
                if not passed: raise AssertionError(title+': '+p.status.text())
                p.tabs.setCurrentIndex(1); self.grab(key+'-loads')
                p.tabs.setCurrentIndex(2); p.diagram.setCurrentText('N' if key.startswith('truss') or key=='axial' else 'M'); self.grab(key+'-results')
                if not expected_failure:
                    p.diagram.setCurrentText('Deformed'); self.grab(key+'-deformed')
                self.index+=1; self.waiting=False
            if self.index>=len(self.module.CATALOG): self.cleanup(); return
            key,title,_=self.module.CATALOG[self.index]
            ws=self.app.workspace(); ws.saved=copy.deepcopy(self.app.scene.plugin_data.get('go_structural_analysis'))
            p.examples.setCurrentIndex(self.index)
            # Exercise the actual button route instead of inserting model directly.
            p.example_button.click()
            assert p.model()==self.module.example(key)
            assert p.result is None or not importlib.import_module(p.__module__.rsplit('.',1)[0]+'.results').is_current(p.model(),p.result)
            p.tabs.widget(0).ensureWidgetVisible(p.examples)
            self.grab(key+'-model')
            p.run_button.click(); self.waiting=True; self.timer.start()
        except Exception as exc:
            self.checks.append({'status':'Failed','error':str(exc)}); self.record(); self.cleanup()

    def cleanup(self):
        self.timer.stop()
        ws=self.app.workspace()
        if getattr(ws,'panel',None) is self.panel and self.panel.thread is None:
            ws.saved=copy.deepcopy(self.app.scene.plugin_data.get('go_structural_analysis')); self.app.leave_workspace()
        c=self.vp.camera
        restored=self.app.scene is self.original and self.vp.history is self.history and self.original.plugin_data==self.data and self.camera==[list(c.target.toTuple()),c.distance,c.yaw,c.pitch,c.perspective]
        self.checks.append({'key':'original_restored','status':'Passed' if restored else 'Failed'}); self.record()
