# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Layers / tags (Fase 6): visibility, locking, assignment, persistence."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.layers import DEFAULT_LAYER, Layer, assign_layer, layer_of
from core.scene import Scene
from formats import igz


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _slab(scene, x0=0.0):
    f = scene.mesh.add_face([V(x0, 0), V(x0 + 2, 0), V(x0 + 2, 2), V(x0, 2)])
    return f


def test_entities_default_to_layer_zero():
    scene = Scene()
    f = _slab(scene)
    e = scene.mesh.edges[0]
    assert layer_of(f) == DEFAULT_LAYER
    assert layer_of(e) == DEFAULT_LAYER
    assert scene.entity_visible(f) and scene.entity_selectable(e)


def test_hidden_layer_filters_render_views():
    scene = Scene()
    f1 = _slab(scene, 0)
    f2 = _slab(scene, 5)
    scene.layers.append(Layer("Estructura", visible=False))
    assign_layer(f2, "Estructura")
    for lp in [f2.loop]:
        for i in range(len(lp)):
            e = scene.mesh.find_edge(lp[i], lp[(i + 1) % len(lp)])
            assign_layer(e, "Estructura")
    faces = list(scene.render_faces())
    edges = list(scene.render_edges())
    assert f1 in faces and f2 not in faces
    assert len(edges) == 4                          # only slab 1's edges
    assert not scene.entity_selectable(f2)


def test_locked_layer_visible_but_unselectable():
    scene = Scene()
    f = _slab(scene)
    scene.layers.append(Layer("Fondo", locked=True))
    assign_layer(f, "Fondo")
    assert scene.entity_visible(f)
    assert not scene.entity_selectable(f)


def test_group_layer_hides_whole_group():
    from core.group import Group
    from core.mesh import Mesh
    scene = Scene()
    g = Group(Mesh())
    g.mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    scene.groups.append(g)
    scene.layers.append(Layer("Mobiliario", visible=False))
    assign_layer(g, "Mobiliario")
    assert list(scene.render_faces()) == []
    assert not scene.entity_selectable(g)


def test_layers_and_labels_round_trip_igz(tmp_path):
    scene = Scene()
    f = _slab(scene)
    e = scene.mesh.edges[0]
    scene.layers.append(Layer("Muros", visible=False, locked=True))
    assign_layer(f, "Muros")
    assign_layer(e, "Muros")
    p = tmp_path / "capas.igz"
    igz.save_scene(scene, p)

    scene2 = Scene()
    igz.load_into(scene2, p)
    names = {ly.name: (ly.visible, ly.locked) for ly in scene2.layers}
    assert names[DEFAULT_LAYER] == (True, False)
    assert names["Muros"] == (False, True)
    f2 = scene2.mesh.faces[0]
    assert layer_of(f2) == "Muros"
    tagged = [e2 for e2 in scene2.mesh.edges if layer_of(e2) == "Muros"]
    assert len(tagged) == 1


def test_edge_layer_survives_split_and_snapshot():
    scene = Scene()
    e = scene.mesh.add_edge(V(0, 0), V(4, 0))
    assign_layer(e, "Instalaciones")
    snap = scene.mesh.capture_state()
    mid = scene.mesh.vertex(V(2, 0, 0))
    scene.mesh.split_edge_at(e, mid)
    assert all(layer_of(k) == "Instalaciones" for k in scene.mesh.edges)
    scene.mesh.restore_state(snap)
    assert all(layer_of(k) == "Instalaciones" for k in scene.mesh.edges)


# ---- Annotations on layers (SketchUp tags) ----------------------------------

def test_annotations_take_layers_like_sketchup(tmp_path):
    """Cotas and leader texts are tagged like any entity: default layer when
    born, reassignable, hidden with their layer (so a scene that hides an
    "Anotaciones" layer shows a clean model — no need to duplicate the
    fountain, Marco 2026-09-02), unselectable when locked, and the layer
    survives the .igz round trip."""
    from PySide6.QtGui import QVector3D
    from core.camera import OrbitCamera
    from core.dimension import Dimension
    from core.saved_views import SavedView
    from core.textlabel import TextLabel
    from formats import igz as igz_format

    scene = Scene()
    dim = Dimension(QVector3D(0, 0, 0), QVector3D(2, 0, 0), QVector3D(0, -1, 0))
    lab = TextLabel(QVector3D(1, 0, 0), QVector3D(0.5, 0.5, 1), "Pileta")
    scene.dimensions.append(dim)
    scene.text_labels.append(lab)
    assert layer_of(dim) == DEFAULT_LAYER and layer_of(lab) == DEFAULT_LAYER

    scene.layers.append(Layer("Anotaciones"))
    assign_layer(dim, "Anotaciones")
    assign_layer(lab, "Anotaciones")
    assert (dim.layer, lab.layer) == ("Anotaciones", "Anotaciones")
    assert scene.entity_visible(dim) and scene.entity_selectable(lab)

    scene.layer("Anotaciones").visible = False
    assert not scene.entity_visible(dim) and not scene.entity_visible(lab)
    assert not scene.entity_selectable(dim)

    scene.layer("Anotaciones").visible = True
    scene.layer("Anotaciones").locked = True
    assert scene.entity_visible(lab) and not scene.entity_selectable(lab)
    scene.layer("Anotaciones").locked = False

    # A scene that hides the layer hides the annotations on recall.
    cam = OrbitCamera()
    scene.layer("Anotaciones").visible = False
    limpia = SavedView.capture("Planta limpia", scene, cam)
    scene.layer("Anotaciones").visible = True
    scene.saved_views.append(limpia)
    limpia.apply(scene, cam)
    assert not scene.entity_visible(dim)
    scene.layer("Anotaciones").visible = True

    # The tag travels in the document.
    path = tmp_path / "anotaciones.igz"
    igz_format.save_scene(scene, path)
    fresh = Scene()
    igz_format.load_into(fresh, path)
    assert fresh.dimensions[0].layer == "Anotaciones"
    assert fresh.text_labels[0].layer == "Anotaciones"
    assert fresh.layer("Anotaciones") is not None
    # Back to the default layer = no tag stored.
    assign_layer(fresh.dimensions[0], DEFAULT_LAYER)
    assert fresh.dimensions[0].layer is None


def test_hidden_layer_hides_annotations_from_picks():
    """The pick paths honour the layer: a leader text or a cota on a hidden
    (or locked) layer is not under the cursor, exactly like a face."""
    import os
    from PySide6.QtGui import QFont, QFontMetrics, QVector3D
    from PySide6.QtWidgets import QApplication
    from core.dimension import Dimension
    from core.textlabel import TextLabel
    from views.viewport import Viewport

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QApplication.instance() is None:        # QFontMetrics needs an app
        QApplication([])
    scene = Scene()
    lab = TextLabel(QVector3D(3, 0, 0), QVector3D(-2, 0, 0), "Pileta")
    dim = Dimension(QVector3D(0, 0, 0), QVector3D(2, 0, 0), QVector3D(0, 0, 1))
    scene.text_labels.append(lab)
    scene.dimensions.append(dim)
    scene.layers.append(Layer("Anotaciones"))
    assign_layer(lab, "Anotaciones")
    assign_layer(dim, "Anotaciones")
    font = QFont()
    font.setPointSize(9)
    font.setBold(True)
    w = QFontMetrics(font).horizontalAdvance("Pileta")
    px = {3.0: (300.0, 100.0), 1.0: (100.0, 100.0),
          0.0: (0.0, 200.0), 2.0: (200.0, 200.0)}

    class _VP:
        pick_threshold_px = 8.0
        _text_block_x = staticmethod(Viewport._text_block_x)

        def _world_to_pixel(self, p):
            # dims: a=(0,0,0) b=(2,0,0) and their offsets (z=1) map to y=150
            key = round(p.x(), 6)
            x, y = px[key]
            return (x, 150.0) if p.z() > 0.5 else (x, y)

    vp = _VP()
    vp.scene = scene
    pick_lab = Viewport.pick_text_label.__get__(vp)
    pick_dim = Viewport.pick_dimension.__get__(vp)
    assert pick_lab(100 - 6 - w / 2, 96, rect_only=True) is lab
    assert pick_dim(100, 150) is dim                     # on the dimension line

    scene.layer("Anotaciones").visible = False
    assert pick_lab(100 - 6 - w / 2, 96, rect_only=True) is None
    assert pick_dim(100, 150) is None
    scene.layer("Anotaciones").visible = True
    scene.layer("Anotaciones").locked = True
    assert pick_lab(100 - 6 - w / 2, 96, rect_only=True) is None
    assert pick_dim(100, 150) is None


def test_layers_tray_assigns_and_releases_annotations():
    """Capas ▸ assign moves selected cotas/texts to the current layer, and
    deleting that layer sends them back to the default one."""
    import os
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QVector3D
    from PySide6.QtWidgets import QApplication
    from core.dimension import Dimension
    from core.textlabel import TextLabel
    from views.main_window import MainWindow

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QApplication.instance() is None:
        QApplication([])
    win = MainWindow()
    try:
        scene = win.viewport.scene
        panel = win.tray.layers
        dim = Dimension(QVector3D(0, 0, 0), QVector3D(2, 0, 0),
                        QVector3D(0, -1, 0))
        lab = TextLabel(QVector3D(1, 0, 0), QVector3D(0.5, 0.5, 1), "Pileta")
        scene.dimensions.append(dim)
        scene.text_labels.append(lab)
        scene.layers.append(Layer("Anotaciones"))
        panel.refresh()
        tree = panel.tree
        item = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                    if tree.topLevelItem(i).data(0, Qt.UserRole) == "Anotaciones")
        tree.setCurrentItem(item)
        scene.select([dim, lab])
        panel._on_assign()
        assert layer_of(dim) == "Anotaciones" and layer_of(lab) == "Anotaciones"
        panel._on_delete()
        assert scene.layer("Anotaciones") is None
        assert layer_of(dim) == DEFAULT_LAYER and layer_of(lab) == DEFAULT_LAYER
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
