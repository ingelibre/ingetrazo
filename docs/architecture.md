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
├── analysis/          ← 3D-printing checks (manifold, thickness, overhangs)
├── formats/           ← import / export for OBJ, COLLADA, glTF, STL, 3MF, IFC
├── i18n/              ← UI translations (en, es, ...)
├── resources/         ← shaders, icons, fonts, stylesheets
└── tests/             ← automated tests
```

## Rendering pipeline

The 3D viewport uses **QOpenGLWidget** (PySide6) as the Qt-managed surface
with direct OpenGL 3.3 Core calls (`QOpenGLShaderProgram`, `QOpenGLBuffer`,
VAOs). Shaders live in `resources/shaders/` and are selected by the `styles/`
modules (Default, Architectural, Shaded, Hidden Line, Monochrome, Wireframe,
X-ray).

## Scene graph

The scene is a flat list of primitives (edges, faces, groups) managed by
`core/scene.py`. Groups and components provide hierarchy; editing a group
swaps the active mesh context. The topology layer (`core/topology.py`) keeps
the shared-vertex mesh consistent, and the hermeticity guard in Push/Pull
refuses to commit a broken solid.

## Plugin system

See [plugins.md](plugins.md).
