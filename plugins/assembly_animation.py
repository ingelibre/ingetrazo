# SPDX-License-Identifier: GPL-3.0-or-later
"""Simple parented animation with hinges and bounded straight travel."""
import copy
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QComboBox, QLineEdit, QDoubleSpinBox, QLabel, QPushButton, QSlider,
    QListWidget, QDialogButtonBox, QMessageBox)
from tools.base import Tool
from core.assembly_animation import KEY, joint, solve, packed, matrix, AnimationCommand


class AssemblyDialog(QDialog):
    def __init__(self, viewport):
        super().__init__(viewport.window())
        self.setWindowTitle('Assembly Animation')
        self.resize(580, 640)
        self.vp = viewport
        self.groups = list(viewport.scene.groups)
        self.before = {g.uid: (packed(g.xform), g.component) for g in self.groups}
        self.joints = copy.deepcopy(viewport.scene.plugin_data.get(KEY, []))
        layout = QVBoxLayout(self)
        help_text = QLabel('Position your parts in their starting assembly first. Attach a moving part to a parent; choose World to ground it. Joints constrain motion during this animation. Coordinates are world millimetres at the starting pose.')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        form = QFormLayout()
        layout.addLayout(form)
        self.child, self.parent, self.kind = QComboBox(), QComboBox(), QComboBox()
        self.parent.addItem('World (stationary)', None)
        for g in self.groups:
            label = f'{g.name} [{g.uid[:6]}]'
            self.child.addItem(label, g.uid)
            self.parent.addItem(label, g.uid)
        for label, key in [('Fixed attachment', 'fixed'), ('Hinge rotation', 'hinge'), ('Straight slot / travel line', 'slide')]:
            self.kind.addItem(label, key)
        self.anchor = QLineEdit('0, 0, 0')
        self.axis = QLineEdit('0, 0, 1')
        self.start, self.end = QDoubleSpinBox(), QDoubleSpinBox()
        for box, value in [(self.start, 0), (self.end, 90)]:
            box.setRange(-100000, 100000)
            box.setDecimals(3)
            box.setValue(value)
        for name, widget in [('Moving part', self.child), ('Parent part', self.parent), ('Joint', self.kind), ('Hinge anchor X, Y, Z (mm)', self.anchor), ('Axis / travel direction X, Y, Z', self.axis), ('Start (degrees or mm)', self.start), ('End (degrees or mm)', self.end)]:
            form.addRow(name, widget)
        edge_button = QPushButton('Use selected edge as hinge axis / travel line')
        edge_button.clicked.connect(self.use_edge)
        layout.addWidget(edge_button)
        note = QLabel('For a slot, position the pin centre at the safe start, then set travel to the safe end. Allow for pin radius at both ends. The centre stays on this straight line and cannot pass its limits. Shape collisions and linked crank mechanisms are not solved.')
        note.setWordWrap(True)
        layout.addWidget(note)
        add = QPushButton('Add / replace joint for moving part')
        add.clicked.connect(self.add_joint)
        layout.addWidget(add)
        self.list = QListWidget()
        layout.addWidget(self.list)
        remove = QPushButton('Remove selected joint')
        remove.clicked.connect(self.remove_joint)
        layout.addWidget(remove)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.valueChanged.connect(self.preview)
        layout.addWidget(self.slider)
        row = QHBoxLayout()
        self.position = QLabel('0%')
        self.play = QPushButton('Play')
        self.play.clicked.connect(self.toggle_play)
        reset = QPushButton('Return to original pose')
        reset.clicked.connect(self.reset)
        row.addWidget(self.position); row.addWidget(self.play); row.addWidget(reset)
        layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('Keep pose and joints')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        self.list.clear()
        names = {g.uid: g.name for g in self.groups}
        for j in self.joints:
            self.list.addItem(f"{names.get(j['child'], 'Missing part')} → {names.get(j['parent'], 'World')} : {j['kind']} ({j['start']:g} to {j['end']:g})")

    def restore(self):
        for g in self.groups:
            value, component = self.before[g.uid]
            g.xform = matrix(value) if value is not None else None
            g.component = component

    def redraw(self):
        self.vp.scene.version += 1
        self.vp.scene.view_version += 1
        self.vp.notify_scene_changed()

    def reset(self):
        self.timer.stop(); self.play.setText('Play')
        self.slider.blockSignals(True); self.slider.setValue(0); self.slider.blockSignals(False)
        self.position.setText('Original pose')
        self.restore(); self.redraw()

    def preview(self):
        try:
            self.restore()
            poses = solve(self.groups, self.joints, self.slider.value()/1000)
            for g in self.groups:
                if g.uid in poses:
                    if g.xform is None:
                        g.component = False
                    g.xform = poses[g.uid]
            self.position.setText(f'{self.slider.value()/10:g}%')
            self.redraw()
        except (ValueError, KeyError, TypeError) as exc:
            self.reset()
            QMessageBox.warning(self, 'Animation', str(exc))

    def add_joint(self):
        try:
            def vector(text):
                values = [float(v.strip()) for v in text.split(',')]
                if len(values) != 3:
                    raise ValueError('Enter three numbers separated by commas.')
                return values
            self.reset()
            lookup = {g.uid: g for g in self.groups}
            child = lookup[self.child.currentData()]
            parent = lookup.get(self.parent.currentData())
            j = joint(child, parent, self.kind.currentData(),
                      [v/1000 for v in vector(self.anchor.text())],
                      vector(self.axis.text()), self.start.value(), self.end.value())
            proposed = [r for r in self.joints if r['child'] != child.uid] + [j]
            solve(self.groups, proposed, 0)
            self.joints = proposed
            self.refresh()
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, 'Joint', str(exc))

    def remove_joint(self):
        index = self.list.currentRow()
        if index >= 0:
            self.reset()
            del self.joints[index]
            self.refresh()

    def use_edge(self):
        from core.mesh import Edge
        edges = [e for e in self.vp.scene.selection if isinstance(e, Edge)]
        if len(edges) != 1:
            QMessageBox.information(self, 'Travel line', 'Before opening Animation, select one loose edge in the model. Its first endpoint defines the hinge anchor; its direction defines the axis.')
            return
        e = edges[0]
        a, b = e.v0.position, e.v1.position
        d = QVector3D(b) - QVector3D(a)
        self.anchor.setText(', '.join(f'{v*1000:g}' for v in (a.x(), a.y(), a.z())))
        self.axis.setText(', '.join(f'{v:g}' for v in (d.x(), d.y(), d.z())))
        if self.kind.currentData() == 'slide':
            self.start.setValue(0); self.end.setValue(d.length()*1000)

    def toggle_play(self):
        if self.timer.isActive():
            self.timer.stop(); self.play.setText('Play')
        else:
            if self.slider.value() == 1000:
                self.slider.setValue(0)
            self.timer.start(); self.play.setText('Pause')

    def tick(self):
        self.slider.setValue(min(1000, self.slider.value()+7))
        if self.slider.value() == 1000:
            self.timer.stop(); self.play.setText('Play')

    def done(self, result):
        self.timer.stop()
        after = {g.uid: (packed(g.xform), g.component) for g in self.groups}
        self.restore()
        if result == QDialog.Accepted:
            self.vp.history.execute(AnimationCommand(self.groups, self.before, after, self.joints))
        self.redraw()
        super().done(result)


class AssemblyAnimation(Tool):
    name = 'Assembly Animation'

    def on_activate(self, viewport):
        if getattr(viewport.scene, '_edit_stack', []):
            QMessageBox.information(viewport.window(), self.name, 'Exit group editing before animating the assembly.')
            return
        if not viewport.scene.groups:
            QMessageBox.information(viewport.window(), self.name, 'Create separate groups for the parts first.')
            return
        # Recovery must never capture a temporary animation preview.
        autosave = getattr(viewport.window(), '_autosave_timer', None)
        was_active = autosave is not None and autosave.isActive()
        if was_active:
            autosave.stop()
        dialog = None
        try:
            dialog = AssemblyDialog(viewport)
            dialog.exec()
        finally:
            if dialog is not None:
                dialog.timer.stop()
            if was_active:
                autosave.start()

    def on_deactivate(self, viewport):
        pass
