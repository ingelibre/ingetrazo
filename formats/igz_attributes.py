# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Per-mesh canonical attribute table with checked immutable snapshots.

Only exact builtin simple recipes are memoized. Keys identify retained source
objects, not Python equality: bool/int/float and positive/negative zero cannot
alias. A mutable colour container is checked against its retained scalar
snapshot on EVERY hit, including element identity and length. Replacing an
item invalidates reuse even when Python considers the new value equal.
Unknown/nested/custom recipes use the ordinary projection and JSON encoder.
Nothing is attached to a face, shared across meshes or reused across saves.
"""
_SIMPLE = frozenset(('color', 'mat', 'back', 'layer'))
_SCALARS = (str, int, float, bool, type(None))

class AttributeTable:
    def __init__(self, project, encode):
        self.entries = []
        self.index = {}
        self.recipes = {}
        self.project, self.encode = project, encode

    def add(self, face):
        attrs = face.attrs
        token = color = snapshot = None
        if (type(attrs) is dict and attrs.keys() <= _SIMPLE
                and all(type(k) is str for k in attrs)):
            color = attrs.get('color')
            mat, back, layer = attrs.get('mat'), attrs.get('back'), attrs.get('layer')
            if (color is None or (type(color) in (list, tuple) and len(color) == 3)):
                token = (id(color), id(mat), id(back), id(layer))
                hit = self.recipes.get(token)
                if hit is not None and (color is None or (
                        color[0] is hit[1][0] and color[1] is hit[1][1]
                        and color[2] is hit[1][2])):
                    return hit[-1]
                if (all(type(v) in _SCALARS for v in (mat, layer))
                        and (back is None or type(back) is bool)
                        and (color is None or all(type(v) in _SCALARS for v in color))):
                    snapshot = None if color is None else tuple(color)
                else:
                    token = None
        js = self.project(face) if attrs else None
        if js:
            key = self.encode(js)
            index = self.index.get(key)
            if index is None:
                index = self.index[key] = len(self.entries)
                self.entries.append(js)
        else:
            index = -1
        if token is not None:
            if len(self.recipes) >= 1024:
                self.recipes.clear()
            # Retain every identity used by the key and the colour snapshot;
            # ids cannot be recycled while a cached recipe can be reused.
            self.recipes[token] = (color, snapshot, mat, back, layer, index)
        return index
