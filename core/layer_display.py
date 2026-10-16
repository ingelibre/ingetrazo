# SPDX-License-Identifier: GPL-3.0-or-later
"""Material-independent geometry for the colour-by-tag display pass."""
from array import array

from core.layers import DEFAULT_LAYER, display_layer_name, default_layer_color


def layer_display_buffers(scene, triangulate, rest_mode="show", suppressed=(),
                          preview_groups=()):
    """Return face/edge positions and (colour, context, start, count) runs.

    Geometry and materials stay untouched. Each placement gets its composed
    world transform and inherits the closest non-default container tag.
    Hidden parents hide their complete subtree; locked tags still draw.
    """
    face_runs, edge_runs = {}, {}
    colors = {layer.name: layer.color for layer in scene.layers}
    editing = scene.edit_group

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

    mesh_buffers(scene.loose_mesh, None, DEFAULT_LAYER, editing is not None)

    def walk(group, parent_matrix=None, inherited=DEFAULT_LAYER, subject=False):
        if not scene.entity_visible(group) or id(group) in preview_groups:
            return
        matrix = group.xform
        if parent_matrix is not None:
            matrix = parent_matrix if matrix is None else parent_matrix * matrix
        name = display_layer_name(group, inherited)
        subject = subject or group is editing
        mesh_buffers(group.mesh, matrix, name, editing is not None and not subject)
        for child in group.children:
            walk(child, matrix, name, subject)

    for group in scene.groups:
        walk(group)

    def pack(runs):
        data, spans = array("f"), []
        for (color, faded), vertices in runs.items():
            spans.append((color, faded, len(data) // 3, len(vertices) // 3))
            data.extend(vertices)
        return data.tobytes(), spans
    return pack(face_runs), pack(edge_runs)
