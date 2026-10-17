import copy
import pytest
pytest.importorskip('PySide6')
from test_qt_v02 import panel,qtapp,run_background
from go_structural_analysis.model3d import cantilever3d
from go_structural_analysis.diagnostics_ui import ModelCheckDialog
from PySide6.QtGui import QImage,QPainter,QColor

def render(panel):
    image=QImage(1000,700,QImage.Format.Format_ARGB32); image.fill(QColor('white')); p=QPainter(image)
    try: panel.paint(panel.app.viewport,p)
    finally: p.end()
    return image

def test_projection_cache_camera_input_and_result_integrity(panel,qtapp):
    panel.put(cantilever3d()); run_background(panel,qtapp); panel.tabs.setCurrentIndex(2); panel.diagram.setCurrentText('Mz'); panel.labels.setChecked(False)
    calls=[]; original=panel.app.world_to_pixels
    panel.app.world_to_pixels=lambda points:(calls.append(len(points)) or original(points))
    snapshot=copy.deepcopy(panel.result); old=render(panel); pool=panel._projection_pool
    calls.clear(); panel.app.viewport.camera.yaw+=.5; new=render(panel)
    assert len(calls)==1 and new!=old and panel._projection_pool is pool
    panel.diagram_scale.setValue(2); render(panel); assert panel._projection_pool is not pool
    assert panel.result==snapshot
    d=copy.deepcopy(panel.model()); d['nodes'][1]['x']=5; panel.put(d); render(panel)
    assert panel.result_status()=='Stale'

def test_selfweight_is_blue_highlight_without_arrows(panel):
    d=cantilever3d(); d.update(self_weight=True,point_loads=[]); panel.put(d); panel.tabs.setCurrentIndex(1); panel.case.setCurrentText('DL'); panel.labels.setChecked(False); panel.local_axes.setChecked(False)
    weighted=render(panel); count=len(panel._projection_pool[1].points)
    d['self_weight']=False; panel.put(d); plain=render(panel)
    assert weighted!=plain and len(panel._projection_pool[1].points)==count

def test_diagnostics_select_and_gate(panel):
    d=cantilever3d(); d['nodes'][0]['support']='Pin'; panel.put(d)
    panel.check_model(); dialog=panel.model_check_dialog
    assert dialog.report['errors']>0 and dialog.table.rowCount()>0
    dialog.select_issue(0,0); assert panel.selected_entity.startswith('node:')
    dialog.run_analysis(); assert panel.thread is None and 'Resolve' in dialog.summary.text(); dialog.close()

def test_canvas_idle_and_compatibility_overlay(panel):
    panel.put(cantilever3d()); panel.canvas.timer.stop(); panel.canvas.sync(); old=panel.canvas._last_frame
    assert panel.canvas.timer.interval()==16
    updates=[]; panel.canvas.update=lambda:updates.append(True)
    panel.canvas.sync(False); assert panel.canvas._last_frame==old and not updates
    panel.app.viewport.camera.yaw+=.1; panel.canvas.sync(False); assert updates
    panel._native_overlay_seen=True; panel.canvas.sync(False); assert panel.canvas.isVisible()

def test_native_callback_does_not_duplicate_canvas_render(panel):
    panel.put(cantilever3d())
    class NativePainter:
        def device(self): return panel.app.viewport
    panel.paint(panel.app.viewport,NativePainter())

def test_cached_projection_respects_front_mask(panel):
    panel.put(cantilever3d()); panel.labels.setChecked(False); panel.legend.setChecked(False); panel.show_loads.setChecked(False)
    visible=render(panel); original=panel.app.world_to_pixels
    def behind(points):
        x,y,f=original(points); f[:]=False; return x,y,f
    panel.app.world_to_pixels=behind
    hidden=render(panel); assert hidden!=visible

def test_2d_batch_and_member_picking(panel):
    from go_structural_analysis.model import benchmark
    from go_structural_analysis.visualization import projected_members
    panel.put(benchmark()); panel.labels.setChecked(False)
    calls=[]; original=panel.app.world_to_pixels
    panel.app.world_to_pixels=lambda points:(calls.append(len(points)) or original(points))
    render(panel); calls.clear(); render(panel); assert len(calls)==1
    plain=render(panel); panel.select_entity('node:'+panel.model()['nodes'][0]['id']); assert render(panel)!=plain
    calls.clear(); members=projected_members(panel)
    assert len(calls)==1 and len(members)==len(panel.model()['members'])
