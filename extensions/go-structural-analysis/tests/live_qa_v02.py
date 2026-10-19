"""Execute inside installed IngeTrazo through MCP. Never run on a busy workspace."""
import copy
import importlib
import json
import os
from pathlib import Path
from PySide6.QtCore import QTimer,QPointF,QEvent,Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

class LiveQA02:
    def __init__(self,viewport,previous_pid=None):
        self.vp=viewport; self.p=viewport.window()._go_structural_panel; self.app=self.p.app; self.previous_pid=previous_pid
        self.package=self.p.__module__.rsplit('.',1)[0]; self.ui=importlib.import_module(self.p.__module__)
        self.results=importlib.import_module(self.package+'.results'); self.visual=importlib.import_module(self.package+'.visualization')
        self.examples=importlib.import_module(self.package+'.examples3d'); self.model3d=importlib.import_module(self.package+'.model3d')
        self.root=Path.home()/'Projects/go-structural-analysis/artifacts/v0.2/live'; self.root.mkdir(parents=True,exist_ok=True); self.checks={}; self.ticks=0
    def check(self,name,condition,**details):
        self.checks[name]=dict(status='Passed' if condition else 'Failed',**details); self.write()
        if not condition: raise AssertionError(name)
    def write(self): (self.root/'live-results.json').write_text(json.dumps(self.checks,indent=2),encoding='utf-8')
    def camera(self):
        c=self.vp.camera; return [list(c.target.toTuple()),c.distance,c.yaw,c.pitch,c.perspective]
    def capture(self,name):
        self.p.canvas.sync(); self.vp.repaint(); QApplication.processEvents()
        self.check('screenshot_'+name,self.app.window.grab().save(str(self.root/(name+'.png'))))
    def start(self):
        if self.app.workspace() is not None or self.p.thread is not None: raise RuntimeError('Requires idle original document')
        self.original_scene=self.app.scene; self.original_data=copy.deepcopy(self.app.scene.plugin_data); self.original_history=self.vp.history; self.original_camera=self.camera(); self.original_tab=self.p.tabs.currentIndex()
        from formats.igz import save_scene
        save_scene(self.original_scene,self.root/'original-before.igz')
        if self.previous_pid is not None: self.check('cold_process_restart',os.getpid()!=self.previous_pid,pid=os.getpid(),old_pid=self.previous_pid)
        else:
            self.checks['cold_process_restart']=dict(status='Not Tested',reason='Provide the observed previous process PID to verify a cold restart'); self.write()
        self.check('cold_plugin_discovery',self.ui.VERSION=='0.2.3',version=self.ui.VERSION)
        self.check('plugin_api_v2',self.app.api_version==2)
        self.check('idempotent_setup',self.ui.setup(self.app) is self.p)
        self.p.load_example('3d_portal'); self.app.show_panel(self.p.dock)
        self.check('3d_frame_creation',self.p.model()['schema']==2 and any(n['y']!=0 for n in self.p.model()['nodes']))
        self.timer=QTimer(self.p); self.timer.setInterval(10); self.timer.timeout.connect(self.tick); self.timer.start(); self.p.run()
    def tick(self):
        if self.p.thread is not None: self.ticks+=1
    def finish(self):
        if self.p.thread is not None: raise RuntimeError('Worker still running; retry finish')
        self.timer.stop(); p=self.p
        try:
            self.check('background_analysis_nonblocking',self.ticks>0,gui_ticks=self.ticks)
            self.check('analysis_execution',self.results.is_current(p.model(),p.result),message=p.status.text())
            self.check('solver_3_2_0',p.result['version']=='3.2.0')
            for tab,name in enumerate(('Model','Loads','Results')):
                p.tabs.setCurrentIndex(tab); p.diagram.setCurrentText('Model' if tab<2 else 'Mz'); self.capture(name)
            for mode in ('N','Vy','Vz','My','Mz','T','D','Reaction','Deformed'):
                p.diagram.setCurrentText(mode); self.capture(mode)
            p.case.setCurrentText('WX'); before=self.visual.projected_members(p); self.vp.camera.yaw+=.24; self.vp.camera.pitch+=.18; self.vp.camera.distance*=.85; self.vp.camera.target.setY(self.vp.camera.target.y()+.2); p.canvas.sync()
            after=self.visual.projected_members(p); mid,a,b=after[-1]; hit=self.visual.pick(p,(a[0]+b[0])/2,(a[1]+b[1])/2)
            self.check('orbit_pan_zoom_member_pick',before!=after and hit is not None)
            p.last_picked_member=None; pos=QPointF((a[0]+b[0])/2,(a[1]+b[1])/2); event=QMouseEvent(QEvent.Type.MouseButtonPress,pos,pos,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier); QApplication.sendEvent(self.vp,event)
            self.check('interactive_member_selection',p.last_picked_member is not None,selected=p.last_picked_member)
            p.inspector.slider.setValue(371); self.check('result_inspector','Vy ' in p.inspector.values.text() and abs(p.inspector.ratio.value()-.371)<1e-8,text=p.inspector.values.text())
            p.tabs.widget(2).ensureWidgetVisible(p.inspector.values); self.capture('Inspector')
            p.inspector.show_tables(); self.check('result_tables',all(t.rowCount()>0 for t in p.inspector.dialog.tables.values())); self.check('table_dialog_capture',p.inspector.dialog.grab().save(str(self.root/'Result-Tables.png'))); p.inspector.dialog.hide()
            paths=self.results.export_csv(self.root/'csv',p.model(),p.result,'WX'); self.check('csv_3d',len(paths)==6 and all(Path(v).stat().st_size>0 for v in paths))
            from formats.igz import save_scene,load_into
            from core.scene import Scene
            save_scene(self.app.scene,self.root/'3d-frame.igz'); loaded=Scene(); load_into(loaded,self.root/'3d-frame.igz'); self.check('save_load_3d',loaded.plugin_data==self.app.scene.plugin_data)
            old=copy.deepcopy(p.data()); changed=copy.deepcopy(p.model()); changed['point_loads'][0]['value']=-13; p.put(changed)
            self.check('stale_results',not self.results.is_current(p.model(),p.result) and not p.inspector.csv.isEnabled())
            self.vp.history.undo(); p.refresh(); self.check('undo',p.data()==old)
            self.vp.history.redo(); p.refresh(); self.check('redo',p.model()==changed)
            self.vp.history.undo(); p.refresh()
            for theme in ('Light','Dark','System'): p.theme_choice.setCurrentText(theme); QApplication.processEvents(); self.capture('Theme-'+theme)
            self.check('theme_choices',p.theme_choice.currentText()=='System')
            before_geometry=copy.deepcopy(p.data()); self.app.scene.mesh.add_edge(__import__('PySide6.QtGui',fromlist=['QVector3D']).QVector3D(0,0,0),__import__('PySide6.QtGui',fromlist=['QVector3D']).QVector3D(2,0,0)); self.app.scene.selection={self.app.scene.edges[-1]}
            editor=self.ui.Editor
            class CancelPreview(editor):
                def exec(dialog): QTimer.singleShot(0,dialog.reject); return super().exec()
            self.ui.Editor=CancelPreview
            try: p.import_geometry()
            finally: self.ui.Editor=editor
            self.check('geometry_conversion_cancel_preserves_model',p.data()==before_geometry)
        except Exception as exc:
            self.checks['live_error']=dict(status='Failed',error=str(exc)); self.write(); raise
        finally:
            ws=self.app.workspace()
            if getattr(ws,'panel',None) is p:
                ws.saved=copy.deepcopy(self.app.scene.plugin_data.get(self.ui.KEY)); self.app.leave_workspace()
            p.refresh(); p.tabs.setCurrentIndex(self.original_tab)
            self.check('original_model_restored',self.app.scene is self.original_scene and self.vp.history is self.original_history and self.app.scene.plugin_data==self.original_data and self.camera()==self.original_camera)
        return self.checks

    def start_secondary(self,key):
        self.p.enter(); self.p.put(self.examples.example3d(key)); self.p.fit(); self.p.run(); self.secondary_key=key
    def test_orbit_tool(self):
        p=self.p; p.enter(); p.put(self.model3d.cantilever3d()); p.fit(); p.tabs.setCurrentIndex(0)
        w=self.app.window; w._nav_actions['orbit'].trigger()
        self.check('orbit_tool_enabled_3d',w._nav_actions['orbit'].isEnabled())
        self.check('orbit_tool_activated',self.vp.nav_mode=='orbit')
        p.selected_entity=None
        x,y,visible=self.app.world_to_pixels([(0,0,0)])
        pos=QPointF(float(x[0]),float(y[0])); end=pos+QPointF(90,40); before=self.camera()
        for kind,point,buttons in [(QEvent.Type.MouseButtonPress,pos,Qt.LeftButton),(QEvent.Type.MouseMove,end,Qt.LeftButton),(QEvent.Type.MouseButtonRelease,end,Qt.NoButton)]:
            event=QMouseEvent(kind,point,point,Qt.NoButton if kind==QEvent.Type.MouseMove else Qt.LeftButton,buttons,Qt.NoModifier)
            QApplication.sendEvent(self.vp,event)
        p.canvas.sync()
        self.check('orbit_mouse_drag_3d',self.camera()!=before,before=before,after=self.camera())
        self.check('orbit_over_node_bypasses_selection',p.selected_entity is None)
        self.capture('Orbit-tool'); p.put(self.ui.benchmark()); p.canvas.sync()
        self.check('2d_camera_plane_preserved',abs(self.vp.camera.pitch)<1e-9)
        ws=self.app.workspace(); ws.saved=copy.deepcopy(self.app.scene.plugin_data.get(self.ui.KEY)); self.app.leave_workspace(); p.refresh()
        w._tool_actions['select'].trigger()
        self.check('orbit_test_original_restored',self.app.scene is self.original_scene)
    def start_gallery(self,keys):
        self.gallery_keys=list(keys); self.gallery_active=False; self.gallery_timer=QTimer(self.p); self.gallery_timer.setInterval(250)
        def advance():
            if self.p.thread is not None: return
            try:
                if self.gallery_active: self.finish_secondary(); self.gallery_active=False
                if self.gallery_keys: self.start_secondary(self.gallery_keys.pop(0)); self.gallery_active=True
                else: self.gallery_timer.stop(); self.check('live_3d_gallery_completed',True)
            except Exception as exc:
                self.gallery_timer.stop(); self.checks['gallery_error']=dict(status='Failed',error=str(exc)); self.write()
        self.gallery_timer.timeout.connect(advance); self.gallery_timer.start()
    def finish_secondary(self):
        if self.p.thread is not None: raise RuntimeError('Worker still running')
        p=self.p; key=self.secondary_key
        expected_failure=key=='3d_unstable'
        self.check('live_example_'+key,('Analysis failed' in p.status.text()) if expected_failure else self.results.is_current(p.model(),p.result),message=p.status.text())
        if key=='3d_combo':
            p.case.setCurrentText('ULS'); p.inspector.envelope.setChecked(True); self.check('combination_envelope_inspector','Reverse' in p.inspector.values.text()); p.inspector.envelope.setChecked(False); self.capture('Combination-envelope')
            for mode in ('Vy','Vz','My','Mz','D','Deformed','Reaction'):
                p.diagram.setCurrentText(mode); self.capture(mode+'-nonzero')
        if key=='3d_torsion': p.diagram.setCurrentText('T'); self.capture('T-nonzero')
        ws=self.app.workspace(); ws.saved=copy.deepcopy(self.app.scene.plugin_data.get(self.ui.KEY)); self.app.leave_workspace(); p.refresh()
        self.check('secondary_restored_'+key,self.app.scene is self.original_scene and self.app.scene.plugin_data==self.original_data)
    def start_legacy(self):
        from importlib import import_module
        legacy=import_module(self.package+'.examples').example('simple_udl'); self.p.enter(); self.p.put(legacy); self.p.fit(); self.p.run()
    def finish_legacy(self):
        if self.p.thread is not None: raise RuntimeError('Worker still running')
        p=self.p; self.check('live_2d_backward_compatibility',self.results.is_current(p.model(),p.result) and abs(p.result['cases']['LC1']['nodes']['N1']['Rz']-30)<1e-8)
        p.diagram.setCurrentText('M'); self.capture('2D-backward-compatibility'); ws=self.app.workspace(); ws.saved=copy.deepcopy(self.app.scene.plugin_data.get(self.ui.KEY)); self.app.leave_workspace(); p.refresh()
        self.check('final_original_restored',self.app.scene is self.original_scene and self.vp.history is self.original_history and self.app.scene.plugin_data==self.original_data)
