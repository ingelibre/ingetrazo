# SPDX-License-Identifier: GPL-3.0-or-later
"""SketchUp placement trees, independent of geometry sharing thresholds.

The parser adapter supplies local face loops and one mesh per definition and
inherited material. Every source placement becomes a native nested Group.
Meshing and document metadata still use the ordinary SKP import path.
"""
from __future__ import annotations

def _edge_records(defn):
    """All source edges: retain line-only objects and per-edge display flags."""
    vertices = getattr(defn, 'vertices', {})
    result = []
    for e in getattr(defn, 'edges', {}).values():
        a, b = vertices.get(e.v1_id), vertices.get(e.v2_id)
        if a is None or b is None:
            continue
        result.append({
            'a': [a.x * .0254, a.y * .0254, a.z * .0254],
            'b': [b.x * .0254, b.y * .0254, b.z * .0254],
            'soft': bool(getattr(e, 'soft', False) or getattr(e, 'smooth', False)),
            'hidden': bool(getattr(e, 'hidden', False)),
            'layer': getattr(e, 'layer', None),
            'curve': getattr(e, 'curve_id', None),
        })
    return result


def adapt(model, name, skp_path=None):
    """Return local prototype geometry and the original placement hierarchy."""
    from PySide6.QtGui import QMatrix4x4, QVector3D
    from formats import skp_openskp as a

    definitions = getattr(model, 'definitions', {}) or {}
    by_id = {getattr(d, 'id', None): d for d in definitions.values()}
    root = getattr(model, 'root', None)
    if root is None:
        root = next((d for d in definitions.values() if d.name == 'ROOT_MODEL'), None)
    roots = [root] if root is not None else list(definitions.values())
    attrs, materials = a._material_attrs(model, skp_path or name)
    digits = ''.join(ch for ch in str(getattr(model, 'version', '') or '').lstrip('{')
                     if ch.isdigit() or ch == '.').split('.')[0]
    legacy = digits.isdigit() and int(digits) < 21
    if not legacy:
        for d in roots + list(definitions.values()):
            a._mark_projected_faces(d, attrs)
    identity = QMatrix4x4()

    def geometry(d, inherited):
        faces = []
        if getattr(d, 'is_image', False):
            faces = a._image_quad_faces(d, identity, attrs, inherited)
        else:
            positions, local, meta = a._defn_geom(d)
            points = a._world_points(positions, identity) if meta else []
            for face, s0, s1, holes in meta:
                entry = a._face_entry(face, points, local, s0, s1, holes, attrs, inherited)
                if entry is not None:
                    if getattr(face, 'hidden', False):
                        entry = (entry[0], entry[1], {**(entry[2] or {}), 'hidden': True})
                    faces.append(entry)
        soft = []
        a._soft_edge_segments(d, identity, soft)
        return {'name': getattr(d, 'name', None) or name, 'faces': faces,
                'soft_edges': soft, 'source_edges': _edge_records(d),
                'definition_id': getattr(d, 'id', None)}

    protos, index, building = [], {}, set()

    def placement(ins):
        d = by_id.get(getattr(ins, 'ref_idx', None))
        if d is None:
            raise ValueError(f'SKP instance references missing definition {ins.ref_idx}')
        inherited = getattr(ins, 'material_id', None)
        return d, inherited

    def build(d, inherited, depth):
        if depth > 32:
            raise ValueError('SKP object nesting exceeds the supported 32 levels')
        did = getattr(d, 'id', None)
        key = (did, inherited)
        if did in building:
            raise ValueError(f'Cyclic SKP definition reference: {did}')
        if key in index:
            return index[key]
        idx = index[key] = len(protos)
        protos.append(None)
        building.add(did)
        try:
            pr = geometry(d, inherited)
            children = []
            # Camera-facing artwork is a native sprite. Keep the original
            # sprite aggregate for this specialized representation only.
            if getattr(d, 'always_faces_camera', False):
                flat, soft = [], []
                a._collect(d, identity, by_id, attrs, flat, 0, set(),
                           inherited=inherited, edges_out=soft)
                pr.update(faces=flat, soft_edges=soft, source_edges=[], billboard=True)
            else:
                for ins in getattr(d, 'instances', []) or []:
                    child, material = placement(ins)
                    material = material if material is not None else inherited
                    ci = build(child, material, depth + 1)
                    children.append(descriptor(ins, ci))
            if getattr(d, 'is_image', False):
                image = next((f[2]['texture']['path'] for f in pr['faces']
                              if f[2] and 'texture' in f[2]), None)
                pr['billboard'] = bool(image and a._image_has_cutout(image))
                pr['is_image'] = True
            pr['has_images'] = bool(pr.get('is_image') or
                                    any(protos[c['proto']].get('has_images') for c in children))
            pr.update(children=children, instances=[])
            protos[idx] = pr
        finally:
            building.remove(did)
        return idx

    def descriptor(ins, proto):
        return {'proto': proto, 'xform': a._matrix(ins.matrix),
                'name': getattr(ins, 'name', '') or None,
                'layer': getattr(ins, 'layer', '') or None,
                'hidden': bool(getattr(ins, 'hidden', False)),
                'guid': getattr(ins, 'guid', '') or ''}

    groups, placements = [], []
    for r in roots:
        loose = geometry(r, None)
        if loose['faces'] or loose['source_edges']:
            loose['name'] = name
            groups.append(loose)
        for ins in getattr(r, 'instances', []) or []:
            d, material = placement(ins)
            if getattr(d, 'is_image', False) or getattr(d, 'always_faces_camera', False):
                placed = a._matrix(ins.matrix)
                if getattr(d, 'is_image', False):
                    faces = a._image_quad_faces(d, placed, attrs, material)
                    image = next((f[2]['texture']['path'] for f in faces
                                  if f[2] and 'texture' in f[2]), None)
                    billboard = bool(image and a._image_has_cutout(image) and
                                     not a._rests_on_a_face(roots, by_id, faces[0][0]))
                else:
                    faces = []
                    a._collect(d, placed, by_id, attrs, faces, 0, set(), inherited=material)
                    billboard = True
                if faces:
                    groups.append({'name': getattr(ins, 'name', '') or d.name or name,
                                   'faces': faces, 'billboard': billboard,
                                   'layer': getattr(ins, 'layer', '') or None,
                                   'hidden': bool(getattr(ins, 'hidden', False))})
                continue
            desc = descriptor(ins, build(d, material, 0))
            placements.append(desc)
            # Retain the existing prototype-placement fields for payload
            # consumers. The hierarchy apply path uses the ordered roots.
            pr = protos[desc['proto']]
            pr['instances'].append(desc['xform'])
            pr.setdefault('instance_layers', []).append(desc['layer'])

    def image_modes(desc, parent):
        """Image attachment is per placement, not per shared definition."""
        pr = protos[desc['proto']]
        if not pr.get('has_images'):
            return desc
        world = parent * desc['xform']
        result = dict(desc)
        if pr.get('is_image') and pr.get('billboard') and pr['faces']:
            quad = [world.map(p if hasattr(p, 'x') else QVector3D(*p))
                    for p in pr['faces'][0][0]]
            result['billboard'] = not a._rests_on_a_face(roots, by_id, quad)
        result['children'] = [image_modes(c, world) for c in pr['children']]
        return result

    placements = [image_modes(desc, identity) for desc in placements]
    payload = {'backend': 'openskp', 'groups': groups, 'protos': protos,
               'hierarchy_roots': placements, '_skp_hierarchy': 1}
    if not groups and not protos:
        if not a._is_empty_model(model, skp_path, legacy):
            return None
        payload['empty'] = True
    return a._payload_metadata(model, payload, materials)


def build_groups(payload, native_build, tick):
    """Build real Groups while sharing each definition/material mesh once."""
    import gc
    from PySide6.QtGui import QVector3D, QMatrix4x4
    from core.group import Group
    from core import mesh as mesh_module

    enabled = gc.isenabled()
    gc.disable()
    try:
        def mesh_for(pr):
            mesh = native_build(pr['faces'], pr.get('soft_edges', []))
            for raw in pr.get('source_edges', []):
                a, b = QVector3D(*raw['a']), QVector3D(*raw['b'])
                if (a - b).lengthSquared() < 1e-18:
                    continue
                va, vb = mesh.vertex(a), mesh.vertex(b)
                # Source edges can be shorter than the native weld tolerance.
                # They have no distinct endpoints in this mesh.
                if va is vb:
                    continue
                e = mesh.find_edge(va, vb)
                if e is None:
                    e = mesh.add_edge(a, b)
                e.soft = raw['soft']
                e.hidden = raw['hidden']
                if isinstance(raw.get('layer'), str) and raw['layer']:
                    e.layer = raw['layer']
                if raw.get('curve') is not None:
                    e.curve = raw['curve']
                    if e.curve >= mesh_module._CURVE_COUNTER:
                        mesh_module._CURVE_COUNTER = e.curve + 1
            return mesh

        protos = payload.get('protos', []) or []
        meshes = []
        for pr in protos:
            tick(1)
            meshes.append(mesh_for(pr))
        def place(desc, depth=0):
            if depth > 32:
                raise ValueError('SKP placement nesting exceeds 32 levels')
            tick()
            idx = desc['proto']
            pr = protos[idx]
            g = Group(meshes[idx], name=desc.get('name') or pr['name'])
            g.xform = QMatrix4x4(desc['xform'])
            g.layer = desc.get('layer')
            g.hidden = bool(desc.get('hidden'))
            g.ext = {'skp_source': {'definition': pr.get('definition_id'),
                                     'instance_guid': desc.get('guid', '')}}
            if desc.get('billboard', pr.get('billboard')):
                g.billboard = 'mesh'
            g.adopt(place(kid, depth + 1) for kid in desc.get('children', pr['children']))
            return g
        groups = []
        for pr in payload.get('groups', []) or []:
            tick(1)
            g = Group(mesh_for(pr), name=pr['name'])
            g.layer = pr.get('layer')
            g.hidden = bool(pr.get('hidden'))
            if pr.get('billboard'):
                g.billboard = 'mesh'
            groups.append(g)
        groups.extend(place(desc) for desc in payload.get('hierarchy_roots', []))
        return groups
    finally:
        if enabled:
            gc.enable()
