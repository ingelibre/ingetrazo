# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Last-use bookkeeping for an adapter-owned OpenSKP model's geometry."""
from collections import Counter


class PrototypeGeometry:
    """Release source geometry only after every prototype needing it is built.

    Construct after flattened groups, tagged groups and image attachment tests
    have finished. The remaining reads follow _collect's prototype boundaries,
    inherited materials, depth limit and cycle guard. Planning walks instance
    metadata only; it never copies or materializes geometry.
    """

    def __init__(self, by_id, proto_ids, proto_uses, roots, max_depth):
        self.definitions = {id(d): d for d in by_id.values()}
        self.protected = {id(d) for d in roots}
        self.reads = {}
        self.remaining = Counter()
        pending = list(proto_uses)

        def visit(d, inherited, depth, stack, reads):
            oid = id(d)
            if depth > max_depth or oid in stack:
                return
            reads.add(oid)
            stack = stack | {oid}
            for ins in getattr(d, "instances", ()):
                child = by_id.get(getattr(ins, "ref_idx", None))
                if child is None:
                    continue
                inh = getattr(ins, "material_id", None) or inherited
                if getattr(child, "is_image", False):
                    # _collect emits the quad directly, before proto dispatch.
                    reads.add(id(child))
                elif getattr(child, "id", None) in proto_ids:
                    pending.append((child.id, inh))
                else:
                    visit(child, inh, depth + 1, stack, reads)

        while pending:
            key = pending.pop()
            if key in self.reads:
                continue
            reads = self.reads[key] = set()
            d = by_id.get(key[0])
            if d is not None:
                visit(d, key[1], 0, set(), reads)
            self.remaining.update(reads)
        for oid in self.definitions.keys() - self.remaining.keys():
            self._drop(oid)

    def _drop(self, oid):
        d = self.definitions.pop(oid, None)
        if d is None or oid in self.protected:
            return
        _drop_geometry(d)

    def release(self, key):
        """A complete _collect has copied everything this prototype needs."""
        for oid in self.reads.pop(key):
            self.remaining[oid] -= 1
            if not self.remaining[oid]:
                del self.remaining[oid]
                self._drop(oid)


def _drop_geometry(definition):
    # Replace rather than clear: separate definitions can alias tables.
    # Keep instance and non-geometry metadata for traversal and payloads.
    for attr in ("faces", "edges", "vertices"):
        setattr(definition, attr, {})
    for attr in ("_geom", "_soft_arr", "_face_boxes"):
        if hasattr(definition, attr):
            delattr(definition, attr)


class FlatGeometry:
    """Last-use release for non-prototype geometry with an exact census.

    The census counts expanded placements. Only use it when its depth/cycle
    guards cannot truncate any path. The caller must finish global image
    attachment decisions before releasing the first definition.
    """

    def __init__(self, by_id, proto_ids, uses, roots, max_depth):
        self.remaining = {}
        heights = {}
        reachable = {}

        def height(d, stack):
            oid = id(d)
            if oid in stack:
                raise ValueError("cyclic definition graph")
            if oid in heights:
                return heights[oid]
            if len(stack) > max_depth:
                raise ValueError("geometry needed beyond the flat census")
            reachable[oid] = d
            heights[oid] = 1 + max((height(child, stack | {oid})
                                   for ins in getattr(d, "instances", ())
                                   if (child := by_id.get(getattr(ins, "ref_idx", None)))
                                   is not None), default=-1)
            return heights[oid]

        try:
            if any(height(root, set()) > max_depth for root in roots):
                return
        except ValueError:
            return
        protected = {id(d) for d in roots}
        pending = [by_id[did] for did in proto_ids if did in by_id]
        visited = set()
        while pending:
            d = pending.pop()
            if id(d) in visited:
                continue
            visited.add(id(d))
            protected.add(id(d))
            pending.extend(child for ins in getattr(d, "instances", ())
                           if (child := by_id.get(getattr(ins, "ref_idx", None))) is not None)
        self.remaining = {oid: uses[d.id] for oid, d in reachable.items()
                          if oid not in protected and uses.get(getattr(d, "id", None), 0)}

    def release(self, definition):
        """Called once this occurrence's own faces and soft edges are copied."""
        oid = id(definition)
        if oid in self.remaining:
            self.remaining[oid] -= 1
            if not self.remaining[oid]:
                del self.remaining[oid]
                _drop_geometry(definition)


class SoftSegments:
    """Ordered endpoint pairs backed by float32 chunks, with Python-float reads.

    Import coordinates are already quantized to float32. Keeping that storage
    avoids six Python floats and three tuples per soft edge. Iteration and repr
    preserve the former tuple/list representation used by prototype deduplication.
    """

    def __init__(self):
        self.chunks = []
        self.size = 0

    def add(self, points):
        points = points.reshape(-1, 2, 3)
        points.setflags(write=False)
        self.chunks.append(points)
        self.size += len(points)

    def __len__(self):
        return self.size

    def __iter__(self):
        for chunk in self.chunks:
            for pair in chunk:
                yield tuple(pair[0].tolist()), tuple(pair[1].tolist())

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(self.size)[index]]
        if index < 0:
            index += self.size
        if index < 0 or index >= self.size:
            raise IndexError(index)
        for chunk in self.chunks:
            if index < len(chunk):
                pair = chunk[index]
                return tuple(pair[0].tolist()), tuple(pair[1].tolist())
            index -= len(chunk)
        raise IndexError(index)

    def __repr__(self):
        return "[" + ", ".join(map(repr, self)) + "]"

    def __eq__(self, other):
        if isinstance(other, (list, SoftSegments)):
            return list(self) == list(other)
        return NotImplemented
