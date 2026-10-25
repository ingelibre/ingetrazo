# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Read-only packed coordinate protocol for the internal SKP payload."""

class PointRows:
    """List-compatible coordinate rows sharing one packed float32 array.

    Faces keep slices of the transformed array instead of allocating a list
    and three Python floats per corner. Reading a row returns the same Python
    float values as the former float32 → float64 → tolist conversion. Repr
    deliberately remains the list repr used by prototype deduplication.
    """

    __slots__ = ("_array", "_indices")

    def __init__(self, array, indices=None):
        self._array = array.view()
        self._array.setflags(write=False)
        self._indices = range(len(array)) if indices is None else indices

    def _coordinate_span(self):
        """Borrow read-only rows in this exact order; no Python float expansion."""
        return self._array, self._indices

    def __len__(self):
        return len(self._indices)

    def __getitem__(self, key):
        indices = self._indices[key]
        if isinstance(key, slice):
            result = object.__new__(PointRows)
            result._array, result._indices = self._array, indices
            return result
        return self._array[indices].tolist()

    def __iter__(self):
        for i in self._indices:
            yield self._array[i].tolist()

    def __repr__(self):
        return repr(list(self))

    def __eq__(self, other):
        if isinstance(other, (list, PointRows)):
            return list(self) == list(other)
        return NotImplemented


def flatten_rings(rings, size):
    """Copy payload rings to weld input without expanding packed rows.

    Internal providers expose ``_coordinate_span() -> (array, range)``. The
    source is borrowed read-only and never mutated; reverse/strided ranges
    retain their exact order. Adjacent spans of one array are copied together.
    Ordinary list and QVector3D rings keep their existing interpretation.
    Only the large-mesh route uses this function: small meshes still replay
    scalar welding, whose vertex order can differ from bulk welding.
    """
    import numpy as np
    out = np.empty((size, 3), dtype=np.float32)
    offset = 0
    source = span = None

    def copy_span():
        nonlocal offset
        n = len(span)
        # range.stop may be -1 for a reversed span: slice(None) is needed
        # because an ndarray interprets literal -1 relative to its end.
        stop = None if span.step < 0 and span.stop < 0 else span.stop
        out[offset:offset + n] = source[span.start:stop:span.step]
        offset += n

    for ring in rings:
        if not len(ring):
            continue
        provider = getattr(ring, "_coordinate_span", None)
        if provider is not None:
            array, indices = provider()
            if (source is array and span.step == indices.step
                    and span.start + len(span) * span.step == indices.start):
                span = range(span.start, indices.stop, span.step)
            else:
                if source is not None:
                    copy_span()
                source, span = array, indices
        else:
            if source is not None:
                copy_span()
                source = span = None
            n = len(ring)
            if hasattr(ring[0], "x"):
                ring = [p.toTuple() for p in ring]
            out[offset:offset + n] = ring
            offset += n
    if source is not None:
        copy_span()
    return out
