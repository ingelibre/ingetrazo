"""Run through IngeTrazo MCP; records actual checks in a separate workspace.

exec(Path(...).read_text(), scope); audit = LiveAudit(viewport); audit.start()
After the background worker ends: audit.finish(). Never changes original data.
"""
import copy
import importlib
import json
from pathlib import Path
from PySide6.QtCore import QTimer, QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication


class LiveAudit:
    def __init__(self, viewport):
        self.vp = viewport
        self.panel = viewport.window()._go_structural_panel
        self.app = self.panel.app
        self.out = Path.home() / 'Projects/go-structural-analysis/artifacts/audit-20261009'
        self.out.mkdir(parents=True, exist_ok=True)
        self.checks = {}
        self.ticks = 0
        self.ui = importlib.import_module(self.panel.__module__)
        self.results = importlib.import_module(self.panel.__module__.rsplit('.', 1)[0] + '.results')

    def check(self, name, condition, **details):
        self.checks[name] = {'status': 'Passed' if condition else 'Failed', **details}
        self.write()
        if not condition:
            raise AssertionError(name)

    def write(self):
        (self.out / 'live-tests.json').write_text(json.dumps(self.checks, indent=2), encoding='utf-8')

    def start(self):
        if self.app.workspace() is not None or self.panel.thread is not None:
            raise RuntimeError('Requires idle host with original document active')
        self.original_scene = self.app.scene
        self.original_history = self.vp.history
        self.original_data = copy.deepcopy(self.original_scene.plugin_data)
        self.original_camera = self.camera()
        self.original_tab = self.panel.tabs.currentIndex()
        self.check('plugin_api', self.app.api_version == 2)
        self.check('idempotent_setup', self.ui.setup(self.app) is self.panel)
        self.panel.example()
        self.app.show_panel(self.panel.dock)
        self.timer = QTimer(self.panel)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.panel.run()

    def tick(self):
        if self.panel.thread is not None:
            self.ticks += 1

    def camera(self):
        c = self.vp.camera
        return [list(c.target.toTuple()), c.distance, c.yaw, c.pitch, c.perspective]

    def capture(self, name):
        self.panel.canvas.sync()
        self.vp.repaint()
        QApplication.processEvents()
        self.check('capture_' + name, self.app.window.grab().save(str(self.out / (name + '.png'))))

    def finish(self):
        if self.panel.thread is not None:
            raise RuntimeError('Worker still running; retry finish later')
        self.timer.stop()
        p = self.panel
        try:
            self.check('nonblocking_analysis', self.ticks > 0, gui_ticks=self.ticks)
            self.check('analysis_current', self.results.is_current(p.model(), p.result), message=p.status.text())
            for i, name in enumerate(['model', 'loads', 'results']):
                p.tabs.setCurrentIndex(i)
                p.diagram.setCurrentText('M')
                self.capture(name)
            for mode in ['Model', 'N', 'V', 'M', 'D', 'Reaction', 'Deformed']:
                p.diagram.setCurrentText(mode)
                self.capture('overlay-' + mode)
            p.diagram.setCurrentText('M')
            visual = importlib.import_module(p.__module__.rsplit('.', 1)[0] + '.visualization')
            mid, a, b = visual.projected_members(p)[0]
            point = QPointF((a[0]+b[0])/2, (a[1]+b[1])/2)
            p.last_picked_member = None
            event = QMouseEvent(QEvent.Type.MouseButtonPress, point, point,
                                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(self.vp, event)
            self.check('viewport_selection', p.inspector.member.currentText() == mid
                       and p.last_picked_member == mid)
            p.inspector.slider.setValue(250)
            self.check('inspector_value', 'x = 1.5 m' in p.inspector.values.text(), text=p.inspector.values.text())
            p.tabs.widget(2).ensureWidgetVisible(p.inspector.values)
            self.capture('result-inspector')
            p.inspector.show_tables()
            self.check('result_tables', all(t.rowCount() > 0 for t in p.inspector.dialog.tables.values()))
            self.capture('result-tables')
            self.check('capture_table_dialog', p.inspector.dialog.grab().save(str(self.out / 'table-dialog.png')))
            p.inspector.dialog.hide()
            paths = self.results.export_csv(self.out / 'csv', p.model(), p.result, p.case.currentText())
            self.check('csv_export', len(paths) == 5 and all(Path(v).stat().st_size > 0 for v in paths))
            from formats.igz import save_scene, load_into
            from core.scene import Scene
            path = self.out / 'benchmark.igz'
            save_scene(self.app.scene, path)
            loaded = Scene()
            load_into(loaded, path)
            self.check('save_load', loaded.plugin_data == self.app.scene.plugin_data)
            before = copy.deepcopy(p.data())
            changed = copy.deepcopy(p.model())
            changed['distributed_loads'][0]['w1'] = -11.
            p.put(changed)
            self.check('stale_result', not self.results.is_current(p.model(), p.result) and not p.inspector.csv.isEnabled())
            self.vp.history.undo()
            p.refresh()
            self.check('undo', p.data() == before)
            self.vp.history.redo()
            p.refresh()
            self.check('redo', p.model() == changed)
            self.vp.history.undo()
            p.refresh()
            before_points = visual.projected_members(p)
            self.vp.camera.distance *= .8
            self.vp.camera.target.setX(self.vp.camera.target.x() + .4)
            after_points = visual.projected_members(p)
            _, a, b = after_points[0]
            hit = visual.pick(p, (a[0]+b[0])/2, (a[1]+b[1])/2)
            self.check('zoom_pan_pick', before_points != after_points and hit[0] == mid)
            self.capture('zoom-pan')
        except Exception as exc:
            self.checks['audit_error'] = {'status': 'Failed', 'error': str(exc)}
            self.write()
            raise
        finally:
            ws = self.app.workspace()
            if getattr(ws, 'panel', None) is p:
                ws.saved = copy.deepcopy(self.app.scene.plugin_data.get(self.ui.KEY))
                self.app.leave_workspace()
            p.refresh()
            p.tabs.setCurrentIndex(self.original_tab)
            self.check('original_restored', self.app.scene is self.original_scene
                       and self.vp.history is self.original_history
                       and self.original_scene.plugin_data == self.original_data
                       and self.camera() == self.original_camera)
        return self.checks
