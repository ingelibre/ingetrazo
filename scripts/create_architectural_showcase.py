# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ahsan Mehmood — IngeTrazo 3D Architectural Showcase Generator
"""IngeTrazo 3D Architectural Showcase Generator script.

Generates a vibrant multi-story modern pavilion structure featuring:
- Surrounding grass landscape terrain (grass.png)
- Stepped ground terrace base (Concrete & Stone Ashlar textures)
- Perimeter wall structures with brick & concrete textures (IfcWall)
- Matrix of structural steel columns (Metal Brushed texture)
- Translucent blue glass facade curtain wall (Glass Blue texture with opacity=0.5)
- Cantilevered timber roof canopy & pergola beams (Wood Planks Dark & Light textures)
- Organized layers: Slabs, Columns, Walls, Glass, Roof_Canopy, Landscape
- Grouped components & BIM tagging for quantity takeoff showcase

Can be executed inside IngeTrazo via:
  Extensions -> Python Console -> 'Run Script File...'
  Or directly pasted into the Python Console REPL!
"""
from pathlib import Path
from PySide6.QtGui import QVector3D
from core.mesh import Mesh
from core.group import Group
from core.layers import Layer

# Root texture directory
try:
    TEXTURE_DIR = Path(__file__).resolve().parent.parent / "resources" / "textures"
except NameError:
    TEXTURE_DIR = Path("resources/textures").resolve()


def get_tex(rel_path: str, scale_w: float = 2.0, scale_h: float = 2.0) -> dict | None:
    """Helper to locate a texture PNG in resources/textures/."""
    full_p = TEXTURE_DIR / rel_path
    if full_p.exists():
        return {"path": str(full_p), "sw": scale_w, "sh": scale_h}
    return None


def build_box(mesh, p_min: QVector3D, p_max: QVector3D, color=None, texture=None, opacity=1.0, ifc_class=None):
    """Helper to build a 6-sided 3D solid box with colors, textures, and opacity."""
    x0, y0, z0 = p_min.x(), p_min.y(), p_min.z()
    x1, y1, z1 = p_max.x(), p_max.y(), p_max.z()

    # 8 vertices
    v000 = QVector3D(x0, y0, z0)
    v100 = QVector3D(x1, y0, z0)
    v110 = QVector3D(x1, y1, z0)
    v010 = QVector3D(x0, y1, z0)

    v001 = QVector3D(x0, y0, z1)
    v101 = QVector3D(x1, y0, z1)
    v111 = QVector3D(x1, y1, z1)
    v011 = QVector3D(x0, y1, z1)

    # 6 faces with CCW vertex order
    faces_pts = [
        [v000, v010, v110, v100],  # Bottom (-Z)
        [v001, v101, v111, v011],  # Top (+Z)
        [v000, v100, v101, v001],  # Front (-Y)
        [v100, v110, v111, v101],  # Right (+X)
        [v110, v010, v011, v111],  # Back (+Y)
        [v010, v000, v001, v011],  # Left (-X)
    ]

    created_faces = []
    for quad in faces_pts:
        face = mesh.add_face(quad)
        if color:
            # Colors must be floats between 0.0 and 1.0
            face.attrs["color"] = color
        if texture:
            face.attrs["texture"] = texture
        if opacity < 0.999:
            face.attrs["opacity"] = opacity
        if ifc_class:
            face.attrs["ifc_class"] = ifc_class
        created_faces.append(face)

    return created_faces


def generate_architectural_showcase(scene=None, viewport=None):
    """Main generator script."""
    # Resolve live scene/viewport if running inside IngeTrazo console scope
    if viewport is None and "viewport" in globals():
        viewport = globals()["viewport"]
    if scene is None:
        if viewport is not None:
            scene = viewport.scene
        elif "scene" in globals():
            scene = globals()["scene"]

    if scene is None:
        from core.scene import Scene
        scene = Scene()

    print("Building Textured Architectural Showcase Structure...")

    # Define Layers
    layer_names = ["Landscape", "Slabs", "Columns", "Walls", "Glass", "Roof_Canopy"]
    for l_name in layer_names:
        if not scene.layer(l_name):
            scene.layers.append(Layer(l_name))

    # --- 0. Landscape Grass Ground ---
    grass_tex = get_tex("grass.png", scale_w=6.0, scale_h=6.0)
    build_box(scene.mesh, QVector3D(-8, -8, -0.5), QVector3D(20, 16, -0.4),
              color=(0.25, 0.55, 0.20), texture=grass_tex, ifc_class="IfcSite")

    # --- 1. Stepped Ground Terraces (Concrete & Stone Textures) ---
    slab_mesh = Mesh()
    conc_exp = get_tex("library/concrete/concrete_exposed.png", scale_w=3.0, scale_h=3.0)
    conc_smooth = get_tex("library/concrete/concrete_smooth.png", scale_w=3.0, scale_h=3.0)
    stone_tex = get_tex("library/stone/stone_ashlar.png", scale_w=2.0, scale_h=2.0)

    # Base platform
    build_box(slab_mesh, QVector3D(-2, -2, -0.4), QVector3D(14, 10, 0.0),
              color=(0.35, 0.38, 0.42), texture=conc_exp, ifc_class="IfcSlab")

    # Upper terrace
    build_box(slab_mesh, QVector3D(0, 0, 0.0), QVector3D(10, 7, 0.3),
              color=(0.45, 0.48, 0.52), texture=conc_smooth, ifc_class="IfcSlab")

    # Entry steps
    for step in range(4):
        z_base = 0.0 + step * 0.08
        build_box(slab_mesh, QVector3D(-1.0 + step * 0.25, 2.0, z_base), QVector3D(0.0, 5.0, z_base + 0.08),
                  color=(0.55, 0.58, 0.60), texture=stone_tex, ifc_class="IfcSlab")

    slab_group = Group(slab_mesh, name="Ground Terraces & Steps")
    slab_group.layer = "Slabs"
    slab_group.ifc = {"class": "IfcSlab", "name": "Terrace Base Slab"}
    scene.groups.append(slab_group)

    # --- 2. Structural Column Grid (Metal Brushed Texture) ---
    col_mesh = Mesh()
    metal_tex = get_tex("library/metal/metal_brushed.png", scale_w=1.5, scale_h=3.0)
    col_positions = [
        (0.5, 0.5), (4.5, 0.5), (8.5, 0.5),
        (0.5, 6.5), (4.5, 6.5), (8.5, 6.5),
        (0.5, 3.5), (8.5, 3.5),
    ]
    col_size = 0.25
    col_height = 3.2

    for cx, cy in col_positions:
        build_box(col_mesh, QVector3D(cx - col_size/2, cy - col_size/2, 0.3),
                  QVector3D(cx + col_size/2, cy + col_size/2, 0.3 + col_height),
                  color=(0.70, 0.75, 0.80), texture=metal_tex, ifc_class="IfcColumn")

    col_group = Group(col_mesh, name="Structural Column Grid")
    col_group.layer = "Columns"
    col_group.ifc = {"class": "IfcColumn", "name": "Steel Structural Columns"}
    scene.groups.append(col_group)

    # --- 3. Perimeter & Partition Walls (Brick & Concrete Textures) ---
    wall_mesh = Mesh()
    wall_height = 3.2
    brick_clay = get_tex("library/brick/brick_clay.png", scale_w=2.0, scale_h=2.0)
    brick_red = get_tex("library/brick/brick_red.png", scale_w=2.0, scale_h=2.0)
    conc_blocks = get_tex("library/concrete/concrete_blocks.png", scale_w=2.0, scale_h=2.0)

    # Back wall
    build_box(wall_mesh, QVector3D(0.0, 6.6, 0.3), QVector3D(9.0, 6.9, 0.3 + wall_height),
              color=(0.82, 0.65, 0.50), texture=brick_clay, ifc_class="IfcWall")

    # Left wall
    build_box(wall_mesh, QVector3D(0.0, 0.3, 0.3), QVector3D(0.3, 6.6, 0.3 + wall_height),
              color=(0.78, 0.32, 0.22), texture=brick_red, ifc_class="IfcWall")

    # Interior partition wall
    build_box(wall_mesh, QVector3D(4.5, 3.0, 0.3), QVector3D(4.7, 6.6, 0.3 + wall_height),
              color=(0.65, 0.65, 0.65), texture=conc_blocks, ifc_class="IfcWall")

    wall_group = Group(wall_mesh, name="Architectural Walls")
    wall_group.layer = "Walls"
    wall_group.ifc = {"class": "IfcWall", "name": "Exterior & Interior Walls"}
    scene.groups.append(wall_group)

    # --- 4. Glass Curtain Wall Facade (Translucent Glass Blue Texture) ---
    glass_mesh = Mesh()
    glass_tex = get_tex("library/glass/glass_blue.png", scale_w=3.0, scale_h=3.0)

    # Front glass wall with translucency
    build_box(glass_mesh, QVector3D(0.3, 0.5, 0.3), QVector3D(8.7, 0.6, 0.3 + wall_height),
              color=(0.30, 0.65, 0.90), texture=glass_tex, opacity=0.55, ifc_class="IfcWindow")

    # Side glass pane
    build_box(glass_mesh, QVector3D(8.6, 0.6, 0.3), QVector3D(8.7, 3.5, 0.3 + wall_height),
              color=(0.30, 0.65, 0.90), texture=glass_tex, opacity=0.55, ifc_class="IfcWindow")

    glass_group = Group(glass_mesh, name="Glass Facade Panels")
    glass_group.layer = "Glass"
    glass_group.ifc = {"class": "IfcWindow", "name": "Curtain Wall Glazing"}
    scene.groups.append(glass_group)

    # --- 5. Cantilevered Timber Roof Canopy & Pergola (Wood Textures) ---
    roof_mesh = Mesh()
    roof_z = 0.3 + wall_height
    wood_dark = get_tex("library/wood/wood_planks_dark.png", scale_w=3.0, scale_h=3.0)
    wood_light = get_tex("library/wood/wood_planks_light.png", scale_w=3.0, scale_h=3.0)

    # Solid roof slab
    build_box(roof_mesh, QVector3D(-0.5, -0.5, roof_z), QVector3D(9.5, 7.5, roof_z + 0.3),
              color=(0.55, 0.30, 0.15), texture=wood_dark, ifc_class="IfcRoof")

    # Cantilevered pergola beams
    beam_width = 0.12
    beam_height = 0.25
    for i in range(8):
        bx0 = 9.5 + i * 0.4
        bx1 = bx0 + beam_width
        build_box(roof_mesh, QVector3D(bx0, 0.0, roof_z + 0.1), QVector3D(bx1, 7.0, roof_z + 0.1 + beam_height),
                  color=(0.72, 0.48, 0.25), texture=wood_light, ifc_class="IfcBeam")

    roof_group = Group(roof_mesh, name="Timber Roof Canopy & Pergola Beams")
    roof_group.layer = "Roof_Canopy"
    roof_group.ifc = {"class": "IfcRoof", "name": "Cantilevered Timber Roof"}
    scene.groups.append(roof_group)

    # Bump scene version to notify viewport & tray of new geometry
    scene.version += 1

    if viewport:
        # Re-sync GL VBOs and notify all tray docks
        viewport.notify_scene_changed()
        # Zoom camera extents so the entire structure fills the 3D viewport!
        win = viewport.window()
        if hasattr(win, "_on_zoom_extents"):
            win._on_zoom_extents()

    print("Architectural Showcase Generated Successfully!")
    print(f"   Groups Created: {len(scene.groups)}")
    print(f"   Layers Configured: {len(scene.layers)}")


# Execute showcase generation directly upon script run
generate_architectural_showcase()
