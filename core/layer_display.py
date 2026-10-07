# SPDX-License-Identifier: GPL-3.0-or-later
"""Material-independent geometry for the colour-by-tag display pass."""
from array import array

from core.layers import DEFAULT_LAYER, display_layer_name, default_layer_color, layer_of


def _display_meshes(scene, rest_mode, preview_groups):
    """Visible meshes with composed transforms and inherited container tags."""
    editing = scene.edit_group
    if editing is None or rest_mode != "hide":
        yield scene.loose_mesh, None, DEFAULT_LAYER, editing is not None

    def walk(group, parent_matrix=None, inherited=DEFAULT_LAYER, subject=False):
        if not scene.entity_visible(group) or id(group) in preview_groups:
            return
        matrix = group.xform
        if parent_matrix is not None:
            matrix = parent_matrix if matrix is None else parent_matrix * matrix
        name = display_layer_name(group, inherited)
        subject = subject or group is editing
        context = editing is not None and not subject
        if not context or rest_mode != "hide":
            yield group.mesh, matrix, name, context
        for child in group.children:
            yield from walk(child, matrix, name, subject)

    for group in scene.groups:
        yield from walk(group)


def _transformed_vertices(vertices, matrix):
    """Transform a shared local buffer in one NumPy operation per placement."""
    import numpy as np
    if matrix is None:
        return vertices.tobytes()
    if not matrix.isAffine():
        from PySide6.QtGui import QVector3D
        return np.array([tuple(matrix.map(QVector3D(*point)).toTuple())
                         for point in vertices], dtype=np.float32).tobytes()
    transform = np.asarray(matrix.data(), dtype=np.float32).reshape(4, 4, order="F")
    return (vertices @ transform[:3, :3].T + transform[:3, 3]).astype(np.float32).tobytes()


def layer_line_buffers(scene, default_color, rest_mode="show", preview_groups=()):
    """Hard edges grouped by effective colour, line pattern and edit context.

    Each shared mesh is read once; placements transform its local buffers.
    This replaces the ordinary hard-edge pass when overrides exist, so gaps
    in dashed/dotted lines never expose a solid line underneath them.
    """
    import numpy as np
    runs, meshes = {}, {}
    settings = {layer.name: (
        scene.layer_setting(layer.name, "edge_color", tuple(default_color)),
        scene.layer_setting(layer.name, "line_style", "solid"))
        for layer in scene.layers}
    for mesh, matrix, inherited, context in _display_meshes(
            scene, rest_mode, preview_groups):
        if id(mesh) not in meshes:
            local = {}
            for edge in mesh.edges:
                if (not scene.entity_visible(edge) or getattr(edge, "soft", False)
                        or getattr(edge, "hidden", False)):
                    continue
                local.setdefault(layer_of(edge), []).extend((edge.a.toTuple(), edge.b.toTuple()))
            meshes[id(mesh)] = {name: np.asarray(points, dtype=np.float32)
                                for name, points in local.items()}
        for tag, vertices in meshes[id(mesh)].items():
            name = inherited if tag == DEFAULT_LAYER else tag
            color, pattern = settings.get(name, (tuple(default_color), "solid"))
            key = (color, pattern, context and rest_mode == "fade")
            runs.setdefault(key, array("f")).frombytes(_transformed_vertices(vertices, matrix))
    data, spans = array("f"), []
    for (color, pattern, faded), vertices in runs.items():
        spans.append((color, pattern, faded, len(data) // 3, len(vertices) // 3))
        data.extend(vertices)
    return data.tobytes(), spans


def layer_display_buffers(scene, triangulate, rest_mode="show", suppressed=(),
                          preview_groups=()):
    """Return face/edge positions and (colour, context, start, count) runs.

    Geometry and materials stay untouched. Each placement gets its composed
    world transform and inherits the closest non-default container tag.
    Hidden parents hide their complete subtree; locked tags still draw.
    """
    face_runs, edge_runs = {}, {}
    colors = {layer.name: layer.color for layer in scene.layers}

    def mesh_buffers(mesh, matrix, inherited, context):
        if context and rest_mode == "hide":
            return
        def key(entity):
            name = display_layer_name(entity, inherited)
            return (colors.get(name, colors.get(DEFAULT_LAYER,
                                                default_layer_color(DEFAULT_LAYER))),
                    context and rest_mode == "fade")
        def append(buf, point):
            p = matrix.map(point) if matrix is not None else point
            buf.extend((p.x(), p.y(), p.z()))
        for face in mesh.faces:
            if face in suppressed or not scene.entity_visible(face):
                continue
            buf = face_runs.setdefault(key(face), array("f"))
            for tri in triangulate(face):
                for point in tri:
                    append(buf, point)
        for edge in mesh.edges:
            if (not scene.entity_visible(edge) or getattr(edge, "soft", False)
                    or getattr(edge, "hidden", False)):
                continue
            buf = edge_runs.setdefault(((0.0, 0.0, 0.0),
                                        context and rest_mode == "fade"), array("f"))
            append(buf, edge.a)
            append(buf, edge.b)

    for mesh, matrix, name, context in _display_meshes(scene, rest_mode, preview_groups):
        mesh_buffers(mesh, matrix, name, context)

    def pack(runs):
        data, spans = array("f"), []
        for (color, faded), vertices in runs.items():
            spans.append((color, faded, len(data) // 3, len(vertices) // 3))
            data.extend(vertices)
        return data.tobytes(), spans
    return pack(face_runs), pack(edge_runs)


def layer_face_buffers(scene, triangulate, *, tint=False, rest_mode="show",
                       suppressed=(), preview_groups=()):
    """Tag-coloured faces or material-preserving tints, with folder opacity.

    Repeated components share local triangles. Colour and opacity remain
    per placement, without triangulating or mapping every face again.
    """
    import numpy as np
    settings = {layer.name: (scene.layer_setting(layer.name, "tint_color")
                             if tint else layer.color)
                for layer in scene.layers}
    runs, meshes, opacities = {}, {}, {}
    for mesh, matrix, inherited, context in _display_meshes(scene, rest_mode, preview_groups):
        if id(mesh) not in meshes:
            local = {}
            for face in mesh.faces:
                if face in suppressed or not scene.entity_visible(face):
                    continue
                points = local.setdefault(layer_of(face), [])
                for tri in triangulate(face):
                    points.extend(point.toTuple() for point in tri)
            meshes[id(mesh)] = {name: np.asarray(points, dtype=np.float32).reshape(-1, 3)
                                for name, points in local.items()}
        for tag, vertices in meshes[id(mesh)].items():
            name = inherited if tag == DEFAULT_LAYER else tag
            color = settings.get(name, settings.get(DEFAULT_LAYER))
            if color is None or not len(vertices):
                continue
            opacity_key = (name, inherited)
            if opacity_key not in opacities:
                opacities[opacity_key] = scene.layer_opacity(name, inherited)
            opacity = opacities[opacity_key] * (.24 if tint else 1.)
            if opacity <= 0:
                continue
            key = (color, opacity, context and rest_mode == "fade")
            runs.setdefault(key, array("f")).frombytes(_transformed_vertices(vertices, matrix))
    data, spans = array("f"), []
    # Opaque surfaces establish depth before any translucent ones draw.
    for (color, opacity, faded), vertices in sorted(runs.items(), key=lambda item: item[0][1] < .999):
        spans.append((color, opacity, faded, len(data) // 3, len(vertices) // 3))
        data.extend(vertices)
    return data.tobytes(), spans
