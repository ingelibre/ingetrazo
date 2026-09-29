# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic, bounded tree joints. All anchors are in reference-world metres."""
import copy
import math
from PySide6.QtGui import QMatrix4x4, QVector3D
from core.history import Command

KEY = 'assembly_animation'


def matrix(value):
    return QMatrix4x4(*value) if value is not None else QMatrix4x4()


def packed(value):
    return list(value.copyDataTo()) if value is not None else None


def joint(child, parent, kind, anchor, axis, start, end):
    return dict(child=child.uid, parent=parent.uid if parent else None,
                kind=kind, anchor=list(anchor), axis=list(axis), start=start, end=end,
                base=packed(child.xform), parent_base=packed(parent.xform) if parent else None)


def solve(groups, joints, progress):
    """Return matrices without mutation; reject cycles and missing references."""
    if not math.isfinite(progress):
        raise ValueError('Animation position must be finite.')
    progress = max(0., min(1., progress))
    lookup = {g.uid: g for g in groups}
    rules = {}
    for j in joints:
        uid = j['child']
        if uid in rules:
            raise ValueError('Each moving part can have only one parent joint.')
        if uid not in lookup or (j['parent'] is not None and j['parent'] not in lookup):
            raise ValueError('A joint refers to a removed part. Remove that joint and recreate it.')
        if j['kind'] not in ('fixed', 'hinge', 'slide'):
            raise ValueError('Unknown joint type.')
        numbers = [*j['anchor'], *j['axis'], j['start'], j['end']]
        if len(j['anchor']) != 3 or len(j['axis']) != 3 or not all(math.isfinite(v) for v in numbers):
            raise ValueError('Joint coordinates must be finite.')
        if QVector3D(*j['axis']).length() < 1e-8:
            raise ValueError('Choose a nonzero joint axis.')
        rules[uid] = j
    result, visiting = {}, set()
    def visit(uid):
        if uid in result:
            return result[uid]
        if uid in visiting:
            raise ValueError('Joint loop: a part cannot be its own ancestor.')
        if uid not in rules:
            return matrix(packed(lookup[uid].xform))
        visiting.add(uid)
        j = rules[uid]
        parent = j['parent']
        delta = QMatrix4x4()
        if parent is not None:
            inverse, ok = matrix(j['parent_base']).inverted()
            if not ok:
                raise ValueError('Parent transform cannot have zero scale.')
            delta = visit(parent) * inverse
        motion = QMatrix4x4()
        amount = j['start'] + progress * (j['end'] - j['start'])
        axis = QVector3D(*j['axis']).normalized()
        if j['kind'] == 'hinge':
            pivot = QVector3D(*j['anchor'])
            motion.translate(pivot)
            motion.rotate(amount, axis)
            motion.translate(-pivot)
        elif j['kind'] == 'slide':
            motion.translate(axis * (amount / 1000.))
        result[uid] = delta * motion * matrix(j['base'])
        visiting.remove(uid)
        return result[uid]
    for uid in rules:
        visit(uid)
    return result


class AnimationCommand(Command):
    """Commit configuration and pose together as one undo step."""
    def __init__(self, groups, before, after, joints):
        self.groups = list(groups)
        self.before = before
        self.after = after
        self.joints = copy.deepcopy(joints)
        self.old_data = None

    def do(self, scene):
        self.old_data = copy.deepcopy(scene.plugin_data.get(KEY))
        scene.plugin_data[KEY] = copy.deepcopy(self.joints)
        self._apply(scene, self.after)

    def undo(self, scene):
        if self.old_data is None:
            scene.plugin_data.pop(KEY, None)
        else:
            scene.plugin_data[KEY] = copy.deepcopy(self.old_data)
        self._apply(scene, self.before)

    def _apply(self, scene, values):
        for group in self.groups:
            value, component = values[group.uid]
            group.xform = matrix(value) if value is not None else None
            group.component = component
        scene.version += 1
