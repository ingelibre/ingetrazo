# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ahsan Mehmood (OpenSKP) — IngeTrazo plugin contribution.
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Console demo: a small pavilion, built through IngeTrazo's REAL APIs.

Run it from Extensions → Python Console → "Run script file…". Everything it
creates arrives as ONE undo step (Ctrl+Z removes the whole pavilion), the
document is marked dirty, and the BIM tab / IFC export actually see the tags
— because it uses the same calls the application itself uses:

- geometry:   mesh.add_face(points)           (the live scope's mesh)
- materials:  face.attrs["color"] = (r, g, b)  floats 0-1, the Paint idiom
- layers:     core.layers.Layer + face.attrs["layer"] / group.layer
- BIM tags:   bim.tag_faces(...) / bim.tag_group(...)  — core.bim

(The original showcase wrote attrs["ifc_class"], a key nothing in IngeTrazo
reads: the model LOOKED tagged in Model Info but exported no BIM objects.)
"""
# The console injects: scene, mesh, QVector3D, Mesh, Group, bim, layers.
from core.layers import Layer

CONCRETE = (0.62, 0.60, 0.58)
GLASS = (0.55, 0.75, 0.85)
TIMBER = (0.55, 0.38, 0.22)

W, D, H = 8.0, 6.0, 3.0          # pavilion footprint and height, metres


def _box(target_mesh, x0, y0, z0, x1, y1, z1, color, layer=None):
    """Six quads of an axis-aligned box; returns the new faces."""
    P = QVector3D
    quads = [
        # Floor wound clockwise seen from above: its outward normal must
        # point DOWN, or the signed-volume sum (core.bim.face_set_volume)
        # counts it backwards and reports wrong m³ for any box whose base
        # is not at z=0 — the bug Marco's first screenshot caught.
        [P(x0, y1, z0), P(x1, y1, z0), P(x1, y0, z0), P(x0, y0, z0)],  # floor
        [P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)],  # top
        [P(x0, y0, z0), P(x1, y0, z0), P(x1, y0, z1), P(x0, y0, z1)],
        [P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)],
        [P(x1, y1, z0), P(x0, y1, z0), P(x0, y1, z1), P(x1, y1, z1)],
        [P(x0, y1, z0), P(x0, y0, z0), P(x0, y0, z1), P(x0, y1, z1)],
    ]
    faces = []
    for q in quads:
        f = target_mesh.add_face(q)
        f.attrs["color"] = color
        if layer:
            f.attrs["layer"] = layer
        faces.append(f)
    return faces


# --- Layers (document data: plain stored names, never translated) ----------
for name in ("Estructura", "Muros"):
    if not any(ly.name == name for ly in scene.layers):
        scene.layers.append(Layer(name))

# --- Floor slab, tagged as ONE IfcSlab across its six faces ----------------
slab = _box(mesh, 0, 0, -0.20, W, D, 0.0, CONCRETE, layer="Estructura")
bim.tag_faces(slab, "IfcSlab", "Losa de piso", bim.next_object_id(scene))

# --- Four corner columns, one tagged group each ----------------------------
for i, (cx, cy) in enumerate(
        [(0.15, 0.15), (W - 0.45, 0.15),
         (0.15, D - 0.45), (W - 0.45, D - 0.45)], start=1):
    g = Group(Mesh(), name=f"Columna {i}")
    _box(g.mesh, cx, cy, 0.0, cx + 0.30, cy + 0.30, H, CONCRETE)
    g.layer = "Estructura"
    bim.tag_group(g, "IfcColumn", f"C-{i}")
    scene.groups.append(g)

# --- Two solid walls + one glazed front ------------------------------------
back = _box(mesh, 0, D - 0.15, 0, W, D, H, CONCRETE, layer="Muros")
side = _box(mesh, 0, 0, 0, 0.15, D, H, CONCRETE, layer="Muros")
bim.tag_faces(back, "IfcWall", "Muro posterior", bim.next_object_id(scene))
bim.tag_faces(side, "IfcWall", "Muro lateral", bim.next_object_id(scene))

front = mesh.add_face([QVector3D(0.6, 0.02, 0.0), QVector3D(W, 0.02, 0.0),
                       QVector3D(W, 0.02, H), QVector3D(0.6, 0.02, H)])
front.attrs["color"] = GLASS
front.attrs["opacity"] = 0.35
front.attrs["layer"] = "Muros"

# --- Timber roof slab ------------------------------------------------------
roof = _box(mesh, -0.30, -0.30, H, W + 0.30, D + 0.30, H + 0.15, TIMBER,
            layer="Estructura")
bim.tag_faces(roof, "IfcRoof", "Cubierta", bim.next_object_id(scene))

objetos = bim.collect_objects(scene)
print(f"Pabellón listo: {len(mesh.faces)} caras sueltas, "
      f"{len(scene.groups)} grupos, {len(objetos)} objetos BIM:")
for o in objetos:
    vol = f", {o['volume']:.2f} m³" if o["volume"] is not None else ""
    print(f"  {o['class']:<10} {o['name']:<16} {o['area']:.1f} m²{vol}")
print("Ctrl+Z deshace todo el pabellón de una vez. F2 lo encuadra.")
