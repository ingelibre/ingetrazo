"""Run inside actual installed IngeTrazo MCP; preserve the user's document."""
import copy,importlib,json,os
from pathlib import Path
from PySide6.QtCore import QTimer,QPointF,QEvent,Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

class LiveQA024:
    def __init__(self,viewport,old_pid):
        self.vp=viewport; self.p=viewport.window()._go_structural_panel; self.app=self.p.app; self.old_pid=old_pid
        self.package=self.p.__module__.rsplit('.',1)[0]
        for name in ('ui','thai_code','model3d','results','visualization','combination_ui','examples3d'):
            setattr(self,name,importlib.import_module(self.package+'.'+name))
        self.root=Path.home()/'Projects/go-structural-analysis/artifacts/v0.2.4'
        self.checks=json.loads((self.root/'live-results.json').read_text()) if (self.root/'live-results.json').exists() else {}
        self.ticks=0
    def check(self,name,passed,**details):
        self.checks[name]=dict(status='Passed' if passed else 'Failed',**details)
        (self.root/'live-results.json').write_text(json.dumps(self.checks,indent=2),encoding='utf-8')
        if not passed: raise AssertionError(name)
    def capture(self,name):
        self.p.canvas.sync(); self.vp.repaint(); QApplication.processEvents(); self.check('capture_'+name,self.app.window.grab().save(str(self.root/(name+'.png'))))
    def start(self):
        if self.app.workspace() is not None or self.p.thread is not None: raise RuntimeError('Requires an idle original document')
        self.original=self.app.scene; self.original_data=copy.deepcopy(self.original.plugin_data); self.original_history=self.vp.history
        self.check('final_cold_restart',os.getpid()!=self.old_pid and self.ui.VERSION=='0.2.4',pid=os.getpid(),old_pid=self.old_pid)
        self.check('plugin_api_v2',self.app.api_version==2)
        self.app.show_panel(self.p.dock); d=self.model3d.cantilever3d(); d['cases']=['DL','LL','WX+','WX-','WY+','WY-']
        d['point_loads'] += [dict(node='N2',direction='FX' if case.startswith('WX') else 'FY',value=7 if case.endswith('+') else -7,case=case) for case in d['cases'][2:]]
        config=dict(method='LRFD',bindings={'D':['DL'],'L':['LL'],'W':d['cases'][2:]},enabled=['TH2566-LRFD-01','TH2566-LRFD-02','TH2566-LRFD-03'],custom={})
        self.p.enter(); self.p.put(self.thai_code.apply_manager(d,config)); self.p.fit()
        self.timer=QTimer(self.p); self.timer.setInterval(10); self.timer.timeout.connect(self.tick); self.timer.start(); self.p.run()
        self.check('running_progress_and_export_gate',self.p.result_status()=='Running' and not self.p.inspector.csv.isEnabled() and not self.p.report_button.isEnabled() and self.p.progress.isVisible())
    def tick(self):
        if self.p.thread is not None: self.ticks+=1
    def finish(self):
        if self.p.thread is not None: raise RuntimeError('Wait for background worker')
        self.timer.stop(); p=self.p
        self.check('background_gui_ticks',self.ticks>0,ticks=self.ticks)
        self.check('analysis_current',p.result_status()=='Current' and len(p.result['cases'])==15)
        self.check('solver_version',p.result['version']=='3.2.0')
        self.check('current_export_enabled',p.inspector.csv.isEnabled() and p.report_button.isEnabled())
        p.case.setCurrentText('TH2566-LRFD-02 / WY+'); p.diagram.setCurrentText('Mz'); p.inspector.select('B1',.37)
        for tab,name in enumerate(('After-Model','After-Loads','After-Results')): p.tabs.setCurrentIndex(tab); self.capture(name)
        dialog=self.combination_ui.CombinationManager(p.model(),p); dialog.show(); QApplication.processEvents()
        self.check('manager_missing_input',not dialog.table.item(3,0).flags()&Qt.ItemFlag.ItemIsEnabled)
        self.check('manager_readonly_factors',not dialog.factor_table.item(0,0).flags()&Qt.ItemFlag.ItemIsEditable)
        for index,name in ((0,'Combination-Inputs'),(1,'Combination-Manager-Final')):
            dialog.pages.setCurrentIndex(index); QApplication.processEvents(); self.check('capture_'+name,dialog.grab().save(str(self.root/(name+'.png'))))
        dialog.table.setCurrentCell(0,1); dialog.custom_name.setText('Reviewed Custom'); dialog.clone(); dialog.custom_factors.item(0,1).setText('1.2'); dialog.accept_model()
        self.check('clone_edit_custom',dialog.result()==1 and dialog.data['combinations']['Reviewed Custom']['DL']==1.2 and dialog.data['combinations']['TH2566-LRFD-01']['DL']==1.4)
        dialog.close()
        old=copy.deepcopy(p.model()); changed=copy.deepcopy(old); changed['nodes'][1]['y']=.4; p.put(changed)
        self.check('stale_node_change',p.result_status()=='Stale')
        self.check('stale_current_export_blocked',not p.inspector.csv.isEnabled() and not p.report_button.isEnabled())
        p.legend.setChecked(False); self.capture('Stale-Watermark-Legend-Off'); p.archive_view.setChecked(True); self.capture('Archived-Snapshot')
        paths=self.results.export_csv(self.root/'archive-csv',p.model(),p.result,p.case.currentText(),archived=True)
        self.check('archive_csv_status',all('Archived/Stale' in Path(v).read_text(encoding='utf-8-sig') for v in paths))
        self.vp.history.undo(); p.refresh(); self.check('undo_current_inputs',p.results_are_current())
        self.vp.history.redo(); p.refresh(); self.check('redo_stale_inputs',p.result_status()=='Stale')
        self.vp.history.undo(); p.refresh(); p.restore_display()
        from formats.igz import save_scene,load_into
        from core.scene import Scene
        save_scene(self.app.scene,self.root/'thai-combinations.igz'); loaded=Scene(); load_into(loaded,self.root/'thai-combinations.igz')
        self.check('save_load_codepack',loaded.plugin_data==self.app.scene.plugin_data)
        self.results.export_report(self.root/'current-engineering-report.json',p.model(),p.result)
        self.check('report_capacity_unavailable',json.loads((self.root/'current-engineering-report.json').read_text())['code_compliance']=='Not Available')
        p.envelope_group.setCurrentText('LRFD'); p.inspector.envelope.setChecked(True)
        self.check('governing_inspector','TH2566-LRFD' in p.inspector.values.text())
        p.sections['Display Settings'].toggle.setChecked(False); p.sections['Result Tables'].toggle.setChecked(False); self.capture('After-Inspector')
        p.inspector.show_tables(); self.check('governing_tables',p.inspector.dialog.tables['Member Force Envelope'].rowCount()>0)
        self.check('capture_Result-Tables',p.inspector.dialog.grab().save(str(self.root/'Result-Tables.png'))); p.inspector.dialog.hide(); p.inspector.envelope.setChecked(False)
        for perspective in (False,True):
            for angle in (-1.3,-.4,.6):
                self.vp.camera.perspective=perspective; self.vp.camera.yaw=angle; self.vp.camera.pitch=.35; self.vp.camera.distance*=.97; self.vp.camera.target.setZ(self.vp.camera.target.z()+.01); p.canvas.sync()
                mid,a,b=self.visualization.projected_members(p)[0]; hit=self.visualization.pick(p,(a[0]+b[0])/2,(a[1]+b[1])/2)
                self.check('perspective_orbit_pan_zoom_pick_'+str(perspective)+'_'+str(angle),hit is not None and hit[0]==mid)
                self.app.window._tool_actions['select'].trigger(); pos=QPointF((a[0]+b[0])/2,(a[1]+b[1])/2)
                QApplication.sendEvent(self.vp,QMouseEvent(QEvent.Type.MouseButtonPress,pos,pos,Qt.LeftButton,Qt.LeftButton,Qt.NoModifier))
                self.check('qt_member_press_'+str(perspective)+'_'+str(angle),p.last_picked_member==mid)
        self.capture('Perspective-Diagram'); model_snapshot=copy.deepcopy(p.model()); result_snapshot=copy.deepcopy(p.result)
        for mode in ('N','Vy','Vz','My','Mz','T','D','Deformed','Reaction'): p.diagram.setCurrentText(mode); self.capture('After-'+mode)
        self.check('display_does_not_change_solver',p.model()==model_snapshot and p.result==result_snapshot)
        for theme in ('Light','Dark','System'): p.theme_choice.setCurrentText(theme); self.capture('Theme-'+theme)
        before=copy.deepcopy(p.data()); p.quick.toggle_panel(); QApplication.processEvents(); self.check('hide_panel_preserves_state',p.data()==before); p.quick.toggle_panel(); self.app.show_panel(p.dock)
        self.restore()
    def restore(self):
        ws=self.app.workspace()
        if ws is not None: ws.saved=copy.deepcopy(self.app.scene.plugin_data.get(self.ui.KEY)); self.app.leave_workspace()
        self.p.refresh(); self.check('original_model_restored',self.app.scene is self.original and self.original.plugin_data==self.original_data and self.vp.history is self.original_history)
    def start_legacy(self):
        self.p.enter(); d=self.ui.benchmark(); d['cases']=['DL','LL']; d['distributed_loads'][0]['case']='DL'
        c=dict(method='ASD',bindings={'D':['DL'],'L':['LL']},enabled=['TH2566-ASD-01'],custom={})
        self.p.put(self.thai_code.apply_manager(d,c)); self.p.fit(); self.p.run()
    def finish_legacy(self):
        if self.p.thread is not None: raise RuntimeError('Wait for legacy worker')
        self.check('live_2d_combination',self.p.results_are_current() and abs(self.p.result['cases']['TH2566-ASD-01']['nodes']['N1']['Rz']-30)<1e-8)
        self.p.case.setCurrentText('TH2566-ASD-01'); self.p.diagram.setCurrentText('M'); self.capture('After-2D-ASD'); self.restore()
    def start_unstable(self):
        self.p.enter(); self.p.put(self.examples3d.example3d('3d_unstable')); self.p.fit(); self.p.run()
    def finish_unstable(self):
        if self.p.thread is not None: raise RuntimeError('Wait for unstable worker')
        self.check('live_failed_unstable',self.p.result_status()=='Failed' and not self.p.report_button.isEnabled() and not self.p.inspector.csv.isEnabled(),error=self.p.status.text())
        self.capture('Failed-Unstable'); self.restore()
