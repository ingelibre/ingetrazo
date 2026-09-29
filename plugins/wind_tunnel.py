# SPDX-License-Identifier: GPL-3.0-or-later
"""Virtual Wind Tunnel: export and run OpenFOAM, view results with ParaView."""
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import shutil

from PySide6.QtCore import Qt, QProcess, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QDoubleSpinBox, QSpinBox, QLabel, QPushButton, QPlainTextEdit,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox, QLineEdit, QTabWidget,
    QWidget, QApplication)
from tools.base import Tool
from core.wind_tunnel import Settings, generate_case
from core.wind_tunnel_runner import Runner, executable
from core.history import SetPluginDataCommand

KEY = 'virtual_wind_tunnel'


class WindTunnelDialog(QDialog):
    def __init__(self, viewport):
        super().__init__(viewport.window())
        self.vp = viewport
        self.setWindowTitle('Virtual Wind Tunnel')
        self.resize(820, 780)
        self.runner = Runner(self)
        self.runner.output.connect(self.append_log)
        self.runner.stage_changed.connect(self.show_stage)
        self.runner.completed.connect(self.finished_run)
        self.case = None
        self.fields = {}
        layout = QVBoxLayout(self)
        note = QLabel('Steady aircraft or neutral-atmosphere terrain flow. Export a case, mesh and solve with OpenCFD OpenFOAM v2312, then inspect results in ParaView. This is an exploratory setup; validate mesh resolution and convergence before using predictions.')
        note.setWordWrap(True); layout.addWidget(note)
        tabs = QTabWidget(); layout.addWidget(tabs)
        setup, run = QWidget(), QWidget()
        tabs.addTab(setup, 'Model and wind'); tabs.addTab(run, 'Calculation and results')
        config = QVBoxLayout(setup); form = QFormLayout(); config.addLayout(form)
        self.mode = QComboBox(); self.mode.addItem('Aircraft — selected closed groups', 'aircraft'); self.mode.addItem('Terrain — imported DEM + optional obstacle groups', 'terrain')
        form.addRow('Study type', self.mode)
        saved = viewport.scene.plugin_data.get(KEY, {})
        saved_values = saved.get('settings', {})
        defaults = Settings()
        def number(key, label, minimum, maximum, decimals=3):
            box = QSpinBox() if decimals is None else QDoubleSpinBox()
            if decimals is not None:
                box.setDecimals(decimals)
            box.setRange(minimum, maximum)
            box.setValue(saved_values.get(key, getattr(defaults, key)))
            self.fields[key] = box; form.addRow(label, box)
        number('speed', 'Wind speed (m/s)', .01, 100)
        number('heading', 'Flow TOWARDS angle: +X = 0°, +Y = 90°', -360, 360, 1)
        number('alpha', 'Aircraft angle of attack (degrees)', -45, 45, 1)
        number('density', 'Air density (kg/m³)', .01, 10, 4)
        number('viscosity', 'Kinematic viscosity (m²/s)', .0000001, .01, 8)
        number('intensity', 'Aircraft turbulence intensity (fraction)', .0001, .5, 4)
        number('reference_area', 'Aircraft reference wing area (m²)', .000001, 100000, 6)
        number('reference_length', 'Aircraft reference chord (m)', .0001, 10000, 4)
        number('roughness', 'Terrain roughness length (m)', .0001, 10, 4)
        number('reference_height', 'Wind reference height above lowest DEM elevation (m)', .1, 10000, 2)
        number('resolution', 'Background cells per model extent (4 coarse–12 fine)', 4, 12, None)
        number('iterations', 'Maximum steady iterations', 10, 10000, None)
        self.groups = QListWidget(); self.groups.setMaximumHeight(125)
        config.addWidget(QLabel('Include these groups (closed solids; terrain itself comes from the DEM):'))
        config.addWidget(self.groups)
        self.sources = {}
        selected = {g.uid for g in viewport.scene.groups if g in viewport.scene.selection}
        recorded = saved.get('groups', selected)
        for group in viewport.scene.groups:
            if group.billboard or not viewport.scene.entity_visible(group):
                continue
            item = QListWidgetItem(group.name)
            item.setData(Qt.UserRole, group.uid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if group.uid in recorded else Qt.Unchecked)
            self.groups.addItem(item); self.sources[group.uid] = group
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.mode.setCurrentIndex(max(0, self.mode.findData(saved_values.get('mode', 'aircraft'))))
        self.mode_changed()
        export = QPushButton('Export a new wind-tunnel case…'); export.clicked.connect(self.export_case)
        self.export_button = export; config.addWidget(export)
        controls = QVBoxLayout(run); runtime = QFormLayout(); controls.addLayout(runtime)
        self.backend = QComboBox(); self.backend.addItem('Docker — OpenFOAM v2312 (Mac / Linux)', 'docker'); self.backend.addItem('Native OpenFOAM v2312 environment', 'native')
        runtime.addRow('Run using', self.backend)
        self.bashrc = QLineEdit(); self.bashrc.setPlaceholderText('Optional native OpenFOAM …/etc/bashrc')
        runtime.addRow('Native environment file', self.bashrc)
        self.paraview = QLineEdit(executable('paraview') or '')
        if not self.paraview.text():
            matches = sorted(Path('/Applications').glob('ParaView*.app/Contents/MacOS/paraview'))
            if matches:
                self.paraview.setText(str(matches[-1]))
        pvrow = QHBoxLayout(); pvrow.addWidget(self.paraview)
        browse = QPushButton('Browse…'); browse.clicked.connect(self.browse_paraview); pvrow.addWidget(browse)
        runtime.addRow('ParaView executable', pvrow)
        deps = QLabel(('Docker found.' if executable('docker') else 'Docker is not installed on this computer.') +
            ' The Docker backend uses up to 4 CPUs / 6 GB RAM and downloads the OpenFOAM image on first run. Native mode needs OpenFOAM v2312. Exported cases can also be copied to a Linux machine.')
        deps.setWordWrap(True); controls.addWidget(deps)
        links = QLabel('<a href="https://www.openfoam.com/download/openfoam-installation-on-mac-using-docker">OpenFOAM for Mac setup</a> · <a href="https://www.paraview.org/download/">ParaView download</a>')
        links.setOpenExternalLinks(True); controls.addWidget(links)
        self.case_label = QLabel('No case exported yet.'); self.case_label.setWordWrap(True); controls.addWidget(self.case_label)
        controls.addWidget(QLabel('Run uses the exported snapshot. Export a new case after changing the model or wind settings.'))
        row = QHBoxLayout(); controls.addLayout(row)
        self.run_button = QPushButton('Mesh and run'); self.run_button.clicked.connect(self.run_case); row.addWidget(self.run_button)
        self.stop_button = QPushButton('Stop'); self.stop_button.clicked.connect(self.runner.stop); row.addWidget(self.stop_button)
        self.open_button = QPushButton('Open results in ParaView'); self.open_button.clicked.connect(self.open_results); row.addWidget(self.open_button)
        folder = QPushButton('Open case folder'); folder.clicked.connect(self.open_folder); controls.addWidget(folder)
        self.status = QLabel('Export a case to begin.'); self.status.setWordWrap(True); controls.addWidget(self.status)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(2000); controls.addWidget(self.log)
        hint = QLabel('In ParaView: open case.foam, choose latest time → Apply → colour by U Magnitude or p. Use Slice and Stream Tracer. p is kinematic pressure; multiply by density for Pa. Force coefficients and residuals are in postProcessing. Steady iterations are not physical time.')
        hint.setWordWrap(True); controls.addWidget(hint)
        close = QPushButton('Close'); close.clicked.connect(self.reject); layout.addWidget(close)
        path = saved.get('case')
        if path and (Path(path)/'ingetrazo-case.json').is_file():
            self.case = Path(path); self.case_label.setText(str(self.case))
        self.buttons()

    def mode_changed(self):
        terrain = self.mode.currentData() == 'terrain'
        for key in ('alpha', 'intensity', 'reference_area', 'reference_length'):
            self.fields[key].setEnabled(not terrain)
        for key in ('roughness', 'reference_height'):
            self.fields[key].setEnabled(terrain)

    def settings(self):
        values = {k: box.value() for k, box in self.fields.items()}
        values['mode'] = self.mode.currentData()
        if values['mode'] == 'terrain':
            values['alpha'] = 0.
        return Settings(**values)

    def export_case(self):
        parent = QFileDialog.getExistingDirectory(self, 'Choose parent folder for a NEW wind-tunnel case')
        if not parent:
            return
        try:
            groups = [self.sources[self.groups.item(i).data(Qt.UserRole)] for i in range(self.groups.count()) if self.groups.item(i).checkState() == Qt.Checked]
            settings = self.settings()
            path = Path(parent)/('wind-tunnel-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            self.export_button.setEnabled(False)
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                manifest = generate_case(path, groups, settings, self.vp.scene.terrain if settings.mode == 'terrain' else None)
            finally:
                QApplication.restoreOverrideCursor()
                self.export_button.setEnabled(True)
            self.case = path; self.case_label.setText(str(path))
            self.vp.history.execute(SetPluginDataCommand(KEY, dict(settings=asdict(settings), groups=[g.uid for g in groups], case=str(path))))
            self.vp.notify_scene_changed()
            cells = manifest['background_cells']
            self.status.setText(f'Case exported. Background mesh: {cells[0]} × {cells[1]} × {cells[2]} before surface refinement. Not simulated yet.')
            self.log.clear(); self.buttons()
            QMessageBox.information(self, 'Case ready', 'Case exported. Open the Calculation and results tab to run it. Settings and the case path are saved with your model.')
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, 'Wind tunnel', str(exc))

    def buttons(self):
        busy = self.runner.active
        self.run_button.setEnabled(self.case is not None and not busy)
        self.stop_button.setEnabled(busy)
        self.open_button.setEnabled(self.case is not None and not busy)
        self.export_button.setEnabled(not busy)
        self.backend.setEnabled(not busy); self.bashrc.setEnabled(not busy)

    def run_case(self):
        try:
            self.log.clear()
            self.runner.start(self.case, self.backend.currentData(), self.bashrc.text().strip())
            self.buttons()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, 'Solver setup', str(exc))

    def append_log(self, text):
        cursor = self.log.textCursor(); cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text); self.log.setTextCursor(cursor); self.log.ensureCursorVisible()

    def show_stage(self, text):
        self.status.setText(text)

    def finished_run(self, success, message):
        self.status.setText(message); self.buttons()

    def browse_paraview(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose ParaView executable')
        if path:
            self.paraview.setText(path)

    def open_results(self):
        if not self.case:
            return
        if not (self.case/'constant/polyMesh').exists():
            QMessageBox.information(self, 'No computed mesh', 'Mesh and run this case first. No flow results have been calculated yet.')
            return
        program = self.paraview.text().strip()
        if not program or not Path(program).is_file():
            QMessageBox.information(self, 'ParaView needed', 'Install ParaView and choose its executable above. You can also open case.foam manually in ParaView.')
            return
        ok, _ = QProcess.startDetached(program, ['--data='+str(self.case/'case.foam')])
        if not ok:
            QMessageBox.warning(self, 'ParaView', 'Could not start ParaView. Check the selected executable.')

    def open_folder(self):
        if self.case:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.case)))

    def done(self, result):
        if self.runner.active:
            QMessageBox.information(self, 'Calculation running', 'Use Stop and wait for the calculation to stop before closing this window.')
            return
        super().done(result)


class VirtualWindTunnel(Tool):
    name = 'Virtual Wind Tunnel'

    def on_activate(self, viewport):
        if getattr(viewport.scene, '_edit_stack', []):
            QMessageBox.information(viewport.window(), self.name, 'Exit group editing before preparing a wind-tunnel case.')
            return
        WindTunnelDialog(viewport).exec()

    def on_deactivate(self, viewport):
        pass
