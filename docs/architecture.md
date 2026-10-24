# IngeTrazo architecture

This is an early-stage document. Expect it to grow as the codebase does.

## High-level layout

```
ingetrazo/
├── main.py            ← Qt application entry point
├── core/              ← scene graph, camera, geometry primitives, layers
├── views/             ← Qt widgets: main window, viewport, panels
├── tools/             ← built-in modeling tools (line, rectangle, push/pull, ...)
├── plugins/           ← third-party tools, discovered at startup
├── georef/            ← real-world location: tiles, DEM, projections
├── styles/            ← visual style presets (shader modes)
├── materials/         ← material library and editor
├── analysis/          ← (future) 3D-printing checks: manifold, thickness, overhangs
├── formats/           ← import / export for OBJ, COLLADA, glTF, STL, IFC (3MF planned)
├── i18n/              ← UI translations (en, es, ...)
├── resources/         ← shaders, icons, fonts, stylesheets
└── tests/             ← automated tests
```

## Rendering pipeline

The 3D viewport uses **QOpenGLWidget** (PySide6) as the Qt-managed surface and **ModernGL** as the Python-friendly wrapper around OpenGL 3.3+. Shaders live in `resources/shaders/` and are loaded by the `styles/` modules.

## Viewport package

`views/viewport/` holds the `Viewport` widget. `Viewport` is one class, composed of one mixin per job. Import it as `from views.viewport import Viewport`.

| Module | Mixin | Job |
| --- | --- | --- |
| `__init__.py` | `Viewport` | Signals, `__init__`, the document (`set_document`), hover, projection toggles |
| `gl_setup.py` | `GLSetupMixin` | GL context, scene FBO, shader programs, buffers, textures and their release |
| `render.py` | `RenderMixin` | `paintGL`, shading, previews, hidden ghosts, hover and silhouettes |
| `instancing.py` | `InstancingMixin` | Instanced components: placements, prototype draw entries, recorded GL passes |
| `chunks.py` | `ChunkCacheMixin` | Mesh-to-GPU chunks, edge and face sync, the on-disk chunk cache, culling spans |
| `billboards.py` | `BillboardMixin` | Face-me components and billboards |
| `image_planes.py` | `ImagePlaneMixin` | Placed images: drawing, outlines, picking |
| `geo.py` | `GeoMixin` | Base-map tiles, terrain, photo mesh, sky, geo overlays |
| `shadows.py` | `ShadowMixin` | Sun shadows |
| `sections.py` | `SectionPlaneMixin` | Section planes: clipping, cut fill and cut edges, picking |
| `overlay.py` | `OverlayMixin` | The 2D QPainter overlay: snap indicator, guides, labels, dimensions |
| `projection.py` | `ProjectionMixin` | Pixel and world conversions, rays, work planes, depth reads |
| `picking.py` | `PickingMixin` | The pick index, ray hits, the `pick_*` queries |
| `occlusion.py` | `OcclusionMixin` | Screen-depth occlusion for annotations and the snap |
| `snapping.py` | `SnappingMixin` | Snap candidates, centres, inference locks, the snap refresh |
| `clipboard.py` | `ClipboardMixin` | Copy and cut |
| `group_edit.py` | `GroupEditMixin` | Group-edit context and how the rest of the model draws |
| `interaction.py` | `InteractionMixin` | Tools, cursors, navigation, mouse, wheel, keys, focus |
| `value_input.py` | `ValueInputMixin` | The typed value buffer (VCB) |
| `_support.py` | — | Module-level helpers, constants and environment flags |

Put a new method in the mixin that owns its job. A mixin refers to a class attribute of another mixin by that mixin's name (`SnappingMixin.GEDGE_REACH_PX`), not by `Viewport`. The mixins share one object and its attributes. A narrow interface between them is future work.

## Scene graph

To be documented.

## Plugin system

See [plugins.md](plugins.md).
