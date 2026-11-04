# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Edge display data, independent of the camera and of OpenGL.

One local-coordinate stream is shared by every instance of a prototype.
Soft edges carry adjacent face normals so silhouettes are decided on the
GPU; deferred meshes are read from their plan without building topology.
"""
from __future__ import annotations

import numpy as np

from core.layers import DEFAULT_LAYER, LINETYPES

# Per vertex: position, material RGB, normals of two adjacent faces,
# soft flag, boundary flag, dash count, and up to eight dash lengths.
EDGE_FLOATS = 23
AXIS_COLORS = ((0.85, 0.20, 0.20), (0.20, 0.65, 0.25), (0.20, 0.35, 0.90))


def needs_edge_renderer(style, scene) -> bool:
    """Keep the original fast path for an unchanged, solid-color style."""
    return (style.edge_color_mode != "same" or style.depth_cue
            or style.extensions or style.endpoints
            or (style.profiles and (style.profile_width != 1
                                    or style.profile_cap != "butt" or not style.edges))
            or (style.dashes and any(layer.linetype != "continuous"
                                     for layer in scene.layers)))


def axis_color(direction, fallback, axes=None):
    """Axis-aligned edges use the drawing axes; diagonal edges keep fallback."""
    vector = np.asarray(direction, dtype=float)
    size = np.linalg.norm(vector)
    if size < 1e-12:
        return fallback
    basis = np.eye(3) if axes is None else np.asarray(axes, dtype=float)
    dots = np.abs(basis @ (vector / size))
    axis = int(np.argmax(dots))
    return AXIS_COLORS[axis] if dots[axis] >= 1.0 - 1e-6 else fallback


def marker_candidates(data, transform, style, mode, eye, forward, perspective):
    """World-space endpoints of drawn edges, before deduplicating junctions.

    Match the geometry shader's soft-edge and silhouette rules, so a hidden
    soft edge cannot own (and thereby suppress) another edge's marker.
    """
    linear = transform[:3, :3]
    normal = (np.linalg.inv(linear).T if abs(np.linalg.det(linear)) > 1e-12
              else np.eye(3))
    world = data.copy()
    world[:, :3] = data[:, :3] @ linear.T + transform[:3, 3]
    world[:, 6:9] = data[:, 6:9] @ normal.T
    world[:, 9:12] = data[:, 9:12] @ normal.T
    pairs = world.reshape((-1, 2, EDGE_FLOATS))
    toward = (eye - pairs[:, :, :3].mean(axis=1) if perspective
              else np.broadcast_to(-forward, (len(pairs), 3)))
    first = pairs[:, 0]
    profile = ((first[:, 13] > 0.5)
               | (np.sum(first[:, 6:9] * toward, axis=1)
                  * np.sum(first[:, 9:12] * toward, axis=1) < 0))
    silhouettes = style.profiles & profile
    shown = ((first[:, 12] < 0.5) | silhouettes)
    shown &= (style.edges or mode == "wireframe") | silhouettes
    return np.ascontiguousarray(pairs[shown].reshape((-1, EDGE_FLOATS)))


def _paint_color(attrs, average):
    color = attrs.get("color")
    texture = attrs.get("texture")
    if color is not None and len(color) >= 3:
        return tuple(color[:3])
    if texture and texture.get("path") and average is not None:
        return average(texture["path"])
    return None


def _plan_arrays(mesh, plan):
    """Positions, normals, materials and adjacency without materializing a mesh."""
    ring_start = np.r_[0, np.cumsum(plan.ring_sizes)]
    first_ring = np.r_[0, np.cumsum(plan.ring_counts)[:-1]]
    normals = np.zeros((plan.nfaces, 3))
    if plan.nfaces:
        # Newell's sum is stable even when the first three corners are collinear.
        nxt = np.arange(len(plan.corners)) + 1
        nxt[ring_start[1:] - 1] = ring_start[:-1]
        points = plan.pos[plan.corners]
        crossed = np.cross(points, points[nxt])
        ring_normals = np.add.reduceat(crossed, ring_start[:-1])
        normals = ring_normals[first_ring]
        lengths = np.linalg.norm(normals, axis=1)
        normals = normals / np.maximum(lengths[:, None], 1e-15)
    return plan.pos[plan.edges], normals, plan.ef_start, plan.ef_face


def edge_vertices(mesh, scene, paint=None, inherited_layer=None, average=None) -> np.ndarray:
    """Build a packed line stream including profiles, materials and tag dashes.

    An unpainted edge inherits its container's material. Missing paint is
    a sentinel, resolved by the
    shader to the style's fallback color rather than a baked black.
    """
    from core.lazy_mesh import plan_of
    plan = plan_of(mesh)
    if plan is not None:
        points, normals, starts, incident = _plan_arrays(mesh, plan)
        from formats.igz import _edge_material_map
        from core.mesh import edge_material_key
        paints = _edge_material_map(mesh.__dict__["_deferred_source"]["meta"])
        materials = ([paints.get(edge_material_key(a, b)) for a, b in points]
                     if paints else [None] * len(points))
        soft = plan.soft
        hidden = plan.hidden
        layers = plan.layer
    else:
        edges, faces = mesh.edges, mesh.faces
        points = np.asarray([[e.a.toTuple(), e.b.toTuple()] for e in edges], dtype=float)
        points = points.reshape((-1, 2, 3))
        normals = np.asarray([face.normal().toTuple() for face in faces]).reshape((-1, 3))
        materials = [edge.material for edge in edges]
        face_ids = {id(face): i for i, face in enumerate(faces)}
        incident_lists = [[face_ids[id(face)] for face in edge.faces
                           if id(face) in face_ids] for edge in edges]
        starts = np.r_[0, np.cumsum([len(items) for items in incident_lists])]
        incident = np.asarray([i for items in incident_lists for i in items], dtype=int)
        soft = np.asarray([edge.soft for edge in edges])
        hidden = np.asarray([edge.hidden or not scene.entity_visible(edge) for edge in edges])
        layers = [edge.layer for edge in edges]
    count = len(points)
    data = np.zeros((count, 2, EDGE_FLOATS), dtype=np.float32)
    data[:, :, :3] = points
    data[:, :, 3:6] = -1.0
    data[:, :, 12] = np.asarray(soft)[:, None]
    lengths = starts[1:] - starts[:-1]
    data[:, :, 13] = (lengths != 2)[:, None]
    inherited = _paint_color(paint or {}, average)
    keep = ~np.asarray(hidden, dtype=bool)
    layer_map = {layer.name: layer for layer in scene.layers}
    for i in range(count):
        faces = incident[starts[i]:starts[i + 1]]
        if len(faces):
            data[i, :, 6:9] = normals[faces[0]]
            data[i, :, 9:12] = normals[faces[1] if len(faces) > 1 else faces[0]]
        color = _paint_color(materials[i] or {}, average) or inherited
        if color is not None:
            data[i, :, 3:6] = color
        name = layers[i]
        if not name or name == DEFAULT_LAYER:
            name = inherited_layer or DEFAULT_LAYER
        layer = layer_map.get(name)
        if layer is not None:
            keep[i] &= layer.visible
            pattern = LINETYPES.get(layer.linetype, ())
            data[i, :, 14] = len(pattern)
            # The layer stores millimeters on paper. Four screen pixels per
            # millimeter keeps its pattern legible at every model zoom.
            data[i, :, 15:15 + len(pattern)] = np.asarray(pattern) * 4.0
    keep &= np.isfinite(points).all(axis=(1, 2))
    keep &= np.linalg.norm(points[:, 1] - points[:, 0], axis=1) > 1e-12
    return np.ascontiguousarray(data[keep].reshape((-1, EDGE_FLOATS)))
