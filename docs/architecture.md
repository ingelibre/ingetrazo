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

The 3D viewport uses **QOpenGLWidget** (PySide6) as the Qt-managed surface
with direct OpenGL 3.3 Core calls (`QOpenGLShaderProgram`, `QOpenGLBuffer`,
VAOs). Shaders live in `resources/shaders/`.

## Viewport package

`views/viewport/` holds the `Viewport` widget: one class, made of one mixin per job (#901). Import it as `from views.viewport import Viewport`.

| Module | Mixin | Job |
| --- | --- | --- |
| `__init__.py` | `Viewport` | The class: its Qt signals, `__init__`, the document (`set_document`), hover and the projection toggles |
| `interaction.py` | `InteractionMixin` | Input: tools, cursors, navigation, mouse, wheel, keys and focus. |
| `value_input.py` | `ValueInputMixin` | The typed value buffer (VCB): key handling and value parsing. |
| `snapping.py` | `SnappingMixin` | Snapping and inference: candidate edges and points, centres, locks and the snap refresh. |
| `picking.py` | `PickingMixin` | Picking: the pick index, ray hits and the pick_* queries. |
| `occlusion.py` | `OcclusionMixin` | Screen-depth occlusion for the overlay's annotations and the snap. |
| `projection.py` | `ProjectionMixin` | Pixel and world conversions, rays, work planes and depth reads. |
| `group_edit.py` | `GroupEditMixin` | Group-edit context: entering and leaving a group and how the rest of the model draws. |
| `clipboard.py` | `ClipboardMixin` | Copy, cut and the prototype chunks a clip carries. |
| `overlay.py` | `OverlayMixin` | The 2D QPainter overlay: snap indicator, guides, labels, dimensions and text. |
| `sections.py` | `SectionPlaneMixin` | Section planes: clipping, the cut fill and edges, plane frames and picking. |
| `render.py` | `RenderMixin` | Frame rendering: the paintGL passes, shading, previews, hidden ghosts, hover and silhouettes. |
| `instancing.py` | `InstancingMixin` | Instanced component drawing: placements, prototype draw entries, recorded GL passes. |
| `billboards.py` | `BillboardMixin` | Face-me components and billboards: orientation, meshes, drawing and outlines. |
| `chunks.py` | `ChunkCacheMixin` | Mesh-to-GPU chunk caches: edge and face sync, fingerprints, on-disk cache, culling spans. |
| `image_planes.py` | `ImagePlaneMixin` | Image planes: drawing, outlines and picking of placed images. |
| `geo.py` | `GeoMixin` | Geo-referenced content: base-map tiles, terrain, photo mesh, sky and the geo overlays. |
| `shadows.py` | `ShadowMixin` | Sun shadows: the light frustum, the shadow map and the shadow ground. |
| `gl_setup.py` | `GLSetupMixin` | GL context lifecycle: scene FBO, shader programs, buffers, textures and their release. |
| `_support.py` | — | Module-level helpers, constants and flags shared by the viewport mixins. |

Put a new method in the mixin that owns its job. The mixins share one object and its attributes; a narrow interface between them is future work.

Two things keep the package working as the one module it was:

- A method may name the class itself (`Viewport.painting += 1`, `Viewport._paint_frame(self)`): each part that does has a `Viewport = None` placeholder that `__init__.py` sets to the class once it exists, so these read and write the real class and a test that patches `Viewport.X` still reaches them.
- `views.viewport` is still the module the tests and the switches know: a name set on it (`monkeypatch.setattr(views.viewport, "_NO_SNAP_FAST", True)`) is set in every part that holds it, and a name read off it that `__init__.py` does not hold is read live from the part that does.

`scripts/split_viewport.py` made the split from the single `views/viewport.py`, and `scripts/split_viewport.py --check` verifies it against that file (each member verbatim, the same code objects, the same `dir(Viewport)`).

## Scene graph

The scene is a flat list of primitives (edges, faces, groups) managed by
`core/scene.py`. Groups and components provide hierarchy; editing a group
swaps the active mesh context. The topology layer (`core/topology.py`) keeps
the shared-vertex mesh consistent, and the hermeticity guard in Push/Pull
refuses to commit a broken solid.

## Plugin system

See [plugins.md](plugins.md).
