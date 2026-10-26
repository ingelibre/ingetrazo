# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Conservative, order-preserving compaction of a recorded GL draw tape.

Only recorded state assignments are considered. Nothing is inferred about the
state on entry, shader sources, visibility, textures or instance overlap.
"""
import numpy as np


def compact_tape(ops, vals):
    """Remove redundant state and join adjacent single-instance triangles.

    Multiple-instance draws must NOT be joined: doing so interleaves their
    primitives in a different order. Triangle strips/fans are not joined either.
    The final state, including texture unbinding, is retained for the next pass.
    """
    if not len(ops) or np.any((ops[:, 0] < 0) | (ops[:, 0] > 11)):
        return ops, vals
    # Renderer tapes use one texture unit/target. Vectorize that common case
    # so a newly recorded 70k-command pass does not replace submission cost
    # with a large Python compaction loop. Multi-unit tapes use the general
    # state tracker below.
    active = np.flatnonzero(ops[:, 0] == 9)
    textures = np.flatnonzero(ops[:, 0] == 10)
    if (len(ops) >= 500 and len(active) and len(textures)
            and active[0] < textures[0]
            and np.all(ops[active, 1] == ops[active[0], 1])
            and np.all(ops[textures, 1] == ops[textures[0], 1])):
        keep = np.ones(len(ops), dtype=bool)
        keep[active[1:]] = False
        culls = np.flatnonzero(ops[:, 0] == 7)
        if len(culls) > 1:
            keep[culls[1:][ops[culls[1:], 1] == ops[culls[:-1], 1]]] = False
        segments = np.cumsum((ops[:, 0] == 0) | (ops[:, 0] == 11))[textures]
        last = np.r_[segments[1:] != segments[:-1], True]
        retained = textures[last]
        keep[textures] = False
        changed = np.r_[True, ops[retained[1:], 2] != ops[retained[:-1], 2]]
        keep[retained[changed]] = True
        return _merge_single_instance(ops[keep], vals[keep])
    bits = vals.view(np.uint32)

    def state_key(row, unit):
        code, a, b, c, d = map(int, row)
        if code in (2, 3, 4): return ('uniform', a)
        if code in (5, 6): return ('cap', a)
        if code == 10:
            return ('texture', unit, a) if unit is not None else None
        return (code,) if code in (1, 7, 8, 9) else None

    def deduplicate(indices):
        state = {}; unit = None; out = []
        for i in indices:
            row = ops[i]; code = int(row[0]); key = state_key(row, unit)
            if code == 9: unit = int(row[1])
            if key is not None:
                value = (tuple(row), tuple(bits[i]))
                if state.get(key) == value: continue
                state[key] = value
            out.append(i)
        return out

    indices = deduplicate(range(len(ops)))
    # Between draws a texture binding overwritten on the SAME unit/target is
    # unobservable. In particular, release(0), uniforms, bind(next) needs only
    # the latter bind. Keep active-unit operations in their original order.
    pending = {}; dropped = set(); unit = None
    for i in indices:
        code = int(ops[i, 0])
        if code in (0, 11): pending.clear()
        elif code == 9: unit = int(ops[i, 1])
        elif code == 10 and unit is not None:
            key = (unit, int(ops[i, 1]))
            if key in pending: dropped.add(pending[key])
            pending[key] = i
    indices = deduplicate(i for i in indices if i not in dropped)
    out = []; floats = []
    for i in indices:
        row = ops[i].copy(); code = int(row[0])
        if (out and code in (0, 11) and row[1] == 4 and row[4] == 1
                and out[-1][0] == code and out[-1][1] == 4
                and out[-1][4] == 1):
            previous = out[-1]
            first, count, stride = (2, 3, 1) if code == 0 else (3, 2, 4)
            if (previous[count] % 3 == 0 and row[count] % 3 == 0
                    and previous[first] + previous[count] * stride == row[first]
                    and previous[count] + row[count] <= 0x7fffffff):
                previous[count] += row[count]
                continue
        out.append(row); floats.append(vals[i])
    return (np.asarray(out, dtype=np.int64).reshape(-1, 5),
            np.asarray(floats, dtype=np.float32).reshape(-1, 4))


def _merge_single_instance(ops, vals):
    if len(ops) < 2:
        return ops, vals
    a, b = ops[:-1], ops[1:]
    join = ((a[:, 0] == b[:, 0]) & ((a[:, 0] == 0) | (a[:, 0] == 11))
            & (a[:, 1] == 4) & (b[:, 1] == 4)
            & (a[:, 4] == 1) & (b[:, 4] == 1))
    arrays = a[:, 0] == 0
    first_a = np.where(arrays, a[:, 2], a[:, 3])
    first_b = np.where(arrays, b[:, 2], b[:, 3])
    count_a = np.where(arrays, a[:, 3], a[:, 2])
    count_b = np.where(arrays, b[:, 3], b[:, 2])
    join &= ((count_a % 3 == 0) & (count_b % 3 == 0)
             & (first_a + count_a * np.where(arrays, 1, 4) == first_b))
    if not join.any():
        return ops, vals
    heads = np.flatnonzero(np.r_[True, ~join]); ends = np.r_[heads[1:], len(ops)]
    out = ops[heads].copy()
    for i in np.flatnonzero(ends - heads > 1):
        column = 3 if out[i, 0] == 0 else 2
        count = int(ops[heads[i]:ends[i], column].sum())
        if count > 0x7fffffff:
            return ops, vals
        out[i, column] = count
    return out, vals[heads]
