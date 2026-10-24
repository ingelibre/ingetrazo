# SPDX-License-Identifier: GPL-3.0-or-later
"""Edge-only selection cues for groups and their nested placements.

Select by placement identity, reuse local prototype edge buffers, and keep
the bounding box. No mesh materialization or duplicate face triangles.
"""
from __future__ import annotations

def _group_selection_plan(vp):
    """Visible placements of the selected objects, with shared LOCAL edges.

    Selection is by placement/owner, never by mesh: selecting one component
    must not light up its other instances. No materialization or face copies.
    """
    from core.group import Group, effective_material
    from PySide6.QtGui import QMatrix4x4
    import numpy as np

    selected = {id(g) for g in vp.scene.selection if isinstance(g, Group)}
    key = (vp._placements_epoch(), vp.scene.version, tuple(sorted(selected)),
           id(vp.scene.mesh), getattr(vp, '_preview_epoch', 0))
    memo = getattr(vp, '_group_selection_plan', None)
    if memo is not None and memo['key'] == key:
        return memo
    runs, groups, bases = {}, [], {}
    if selected:
        preview = getattr(vp, '_preview_groups', None) or ()
        hide_rest = (vp.scene.edit_group is not None
                     and vp._edit_rest_mode == 'hide')
        identity = tuple(QMatrix4x4().data())
        for g in vp._placements():
            if (id(g) not in selected and id(vp._owner_of(g)) not in selected):
                continue
            if (id(g) in preview or not vp.scene.entity_visible(g)
                    or getattr(g, 'billboard', False)
                    or (hide_rest and vp._draws_in_edit_context(g))):
                continue
            groups.append(g)
            mid = id(g.mesh)
            base = bases.get(mid)
            if base is None:
                # Ordinary groups already have a world-space chunk. Instances
                # use their shared local prototype, not a baked world copy.
                base = (vp._proto_base_chunk(g.mesh, effective_material(g))
                        if g.xform is not None else vp._group_chunk(g))
                bases[mid] = base
            if not base['edges']:
                continue
            run = runs.setdefault(mid, {'mesh': g.mesh, 'raw': base['edges'],
                                        'matrices': [], 'groups': []})
            run['matrices'].append(tuple(g.xform.data())
                                   if g.xform is not None else identity)
            run['groups'].append(g)
    for run in runs.values():
        run['matrices'] = np.asarray(run['matrices'], dtype=np.float32).tobytes()
    if len(runs) >= 64:
        joined, parts, members = {}, [], []
        for mid, run in runs.items():
            n = len(run['matrices']) // 64
            if len(run['raw']) // 12 * n > 16384:
                joined[mid] = run
                continue
            pts = np.frombuffer(run['raw'], np.float32).reshape(-1, 3)
            matrices = np.frombuffer(run['matrices'], np.float32).reshape(-1, 4, 4)
            matrices = matrices.transpose(0, 2, 1)
            placed = np.einsum('nij,vj->nvi', matrices[:, :3, :3], pts)
            placed += matrices[:, None, :3, 3]
            parts.append(placed.astype(np.float32).tobytes())
            members.extend(run['groups'])
        if parts:
            joined['small_parts'] = {'mesh': None, 'raw': b''.join(parts),
                                     'groups': members,
                                     'matrices': np.asarray(identity, np.float32).tobytes()}
        runs = joined
    memo = {'key': key, 'runs': runs, 'groups': groups, 'bases': bases}
    vp._group_selection_plan = memo
    return memo


def _destroy_edge_entry(entry):
    for name in ('vao', 'edges', 'matrices'):
        obj = entry.get(name)
        if obj is not None:
            obj.destroy()
            if name == 'vao':
                obj.deleteLater()


def _clear_group_selection(vp, destroy=True):
    entries = getattr(vp, '_group_selection_gl', {})
    profile = getattr(vp, '_group_selection_profile_gl', None)
    current = destroy and (entries or profile) and vp.context() is not None
    if current:
        vp.makeCurrent()
        try:
            for entry in entries.values():
                _destroy_edge_entry(entry)
            if profile is not None:
                _destroy_edge_entry(profile)
        finally:
            vp.doneCurrent()
    vp._group_selection_gl = {}
    vp._group_selection_profile_gl = None
    vp._group_selection_plan = None
    vp._group_selection_profile_key = None
    vp._group_selection_sil_table = None


def _group_edge_entry(vp, run, entry, vm):
    """One edge-only GPU buffer per mesh; only placement matrices vary."""
    from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLVertexArrayObject
    if entry is None:
        vao = QOpenGLVertexArrayObject(vp)
        vao.create()
        edges = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        edges.setUsagePattern(QOpenGLBuffer.StaticDraw)
        edges.create()
        matrices = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        matrices.setUsagePattern(QOpenGLBuffer.DynamicDraw)
        matrices.create()
        vao.bind()
        edges.bind()
        vp._program.enableAttributeArray(vp._loc_pos)
        vp._program.setAttributeBuffer(vp._loc_pos, vm.GL_FLOAT, 0, 3, 12)
        edges.release()
        matrices.bind()
        for i, loc in enumerate(vp._loc_inst):
            vp._program.enableAttributeArray(loc)
            vp._program.setAttributeBuffer(loc, vm.GL_FLOAT, i * 16, 4, 64)
            vp.context().extraFunctions().glVertexAttribDivisor(loc, 1)
        matrices.release()
        vao.release()
        entry = {'vao': vao, 'edges': edges, 'matrices': matrices,
                 'raw': None, 'matrix_raw': None}
    for field, source in (('edges', 'raw'), ('matrices', 'matrices')):
        raw = run[source]
        saved = 'raw' if field == 'edges' else 'matrix_raw'
        if entry[saved] is not raw and entry[saved] != raw:
            entry[field].bind()
            entry[field].allocate(raw, len(raw))
            entry[field].release()
            entry[saved] = raw
    entry['count'] = len(run['raw']) // 12
    entry['instances'] = len(run['matrices']) // 64
    return entry


def _selected_profile_bytes(vp, plan):
    """Only view-dependent silhouettes of selected placements, not seams."""
    import numpy as np
    eye = vp.camera.eye()
    # Keep the normal silhouette pass's table independent of this subset.
    normal_table = getattr(vp, '_sil_table', None)
    vp._sil_table = getattr(vp, '_group_selection_sil_table', None)
    try:
        raw, rest = vp._instanced_silhouettes(plan['groups'], eye, None)
        vp._group_selection_sil_table = vp._sil_table
    finally:
        vp._sil_table = normal_table
    parts = [raw]
    e = np.asarray(eye.toTuple(), dtype=np.float64)
    for g in rest:
        if g.xform is not None:
            raw = vp._instance_silhouette(g, eye, None)
            if raw is not None:
                parts.append(raw)
                continue
        base = vp._group_chunk(g)
        if base['soft_pts'] is None:
            continue
        s0 = np.einsum('ij,ij->i', base['soft_n0'], base['soft_c0'] - e)
        s1 = np.einsum('ij,ij->i', base['soft_n1'], base['soft_c1'] - e)
        mask = base['soft_single'] | ((s0 < 0) != (s1 < 0))
        parts.append(base['soft_pts'][mask].tobytes())
    return b''.join(parts)


def _draw_group_selection(vp, plan, mvp, offsets, vm):
    cache = getattr(vp, '_group_selection_gl', None)
    if cache is None:
        cache = vp._group_selection_gl = {}
    for mid in list(cache):
        if mid not in plan['runs']:
            _destroy_edge_entry(cache.pop(mid))
    for mid, run in plan['runs'].items():
        cache[mid] = _group_edge_entry(vp, run, cache.get(mid), vm)
    profile = getattr(vp, '_group_selection_profile_gl', None)
    profiles = bool(vp._effective_style().profiles and plan['groups'])
    pkey = (plan['key'], tuple(vp.camera.eye().toTuple()), profiles)
    if getattr(vp, '_group_selection_profile_key', None) != pkey:
        raw = _selected_profile_bytes(vp, plan) if profiles else b''
        if raw and profile is None:
            vao, vbo = vp._create_dynamic()
            vp._program.bind()       # _create_dynamic releases the shader
            profile = vp._group_selection_profile_gl = {'vao': vao, 'edges': vbo}
        if profile is not None:
            profile['count'] = len(raw) // 12
            if raw:
                profile['edges'].bind()
                profile['edges'].allocate(raw, len(raw))
                profile['edges'].release()
        vp._group_selection_profile_key = pkey
    draw = vp.context().extraFunctions().glDrawArraysInstanced
    for dx, dy in offsets:
        shifted = vm._shifted_mvp(mvp, dx, dy)
        shifted.setRow(2, shifted.row(2) - shifted.row(3) * 1e-5)
        vp._program.setUniformValue(vp._loc_mvp, shifted)
        for entry in cache.values():
            entry['vao'].bind()
            draw(vm.GL_LINES, 0, entry['count'], entry['instances'])
            entry['vao'].release()
        if profile is not None and profile.get('count', 0):
            profile['vao'].bind()
            vp._gl.glDrawArrays(vm.GL_LINES, 0, profile['count'])
            profile['vao'].release()
