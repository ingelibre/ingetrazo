# Wasia — modelador 3D libre

**Autor:** Marco Sumari Tellez · **Licencia:** GPL-3.0-or-later · **Repo:** `/home/sumaritux/wasia/` (local, sin pushear todavía a github.com/tuxiasumari/wasia)

Modelador 3D estilo SketchUp orientado a arquitectura, ingeniería civil e impresión 3D. Multiplataforma (Linux / Windows / macOS) sobre PySide6. Hermano open-source de [IngePresupuestos](../ingepresupuestos-pyside6/) — la integración IFC entre los dos cierra el loop modelo → metrado → presupuesto.

---

## Estado / Roadmap

### ✅ Sesión inaugural 2026-05-21
1. **Repo + esqueleto + GPL-3.0** (`ac278d6`) — carpetas en inglés, README/CONTRIBUTING/CODE_OF_CONDUCT, .wasia format placeholder, main.py runnable con ventana vacía.
2. **Viewport: cámara orbital + grid + ejes XYZ** (`860a6b6`) — `OrbitCamera` Z-up estilo SketchUp/Blender, navegación middle-drag (orbit) / Shift+MMB-drag (pan) / wheel (zoom) / P (perspectiva ↔ paralela). Shaders `basic.vert`/`basic.frag`. **Wayland nativo OK** (vía `paintGL` que limpia explícitamente — ver `[[feedback-wayland-paintgl-explicito]]` en memoria de Claude).
3. **Tools (Line + Select) con SketchUp-style inferencing** (`1c454c9`):
   - Snap engine: endpoint, origin, close-polygon, axis_inference (auto, dentro de 3°), reference parallel/perpendicular.
   - LineTool: chain drawing + auto-close + rubber band naranja.
   - SelectTool: edge picking screen-space + Shift+click aditivo + Delete.
   - Axis lock con arrow keys: →=X, ←=Y, ↑=Z (toggle off pulsando la misma flecha).
   - **Down (↓)** = cycle parallel/perpendicular a una arista de referencia (capturada por hover).
   - **Shift** = lock contextual (locks la inferencia auto activa).
   - **VCB** (Value Control Box): tipear número → Enter → longitud exacta.
   - Camera-aware line projection (line-line closest a la ray) — Z lock funciona.
4. **Save/Open `.wasia`** (`3f7248d`) — JSON versioned, File menu (New/Open/Save/Save As), título dinámico con `*` dirty marker, prompt antes de descartar cambios.
5. **Undo/Redo** (`6379191`) — `core/history.py` con `Command` ABC, `History` stack, `AddEdgeCommand`/`DeleteEdgesCommand`/`AddFaceCommand`/`CompoundCommand`. Tools usan `viewport.history.execute(cmd)` siempre. Edit menu con Undo (Ctrl+Z) / Redo (Ctrl+Y o Ctrl+Shift+Z). Cada rectángulo / extrusión cuenta como **un solo paso atómico** vía `CompoundCommand`.
6. **Rectangle tool (R)** (`db41965`) — 2 clics → 4 aristas + 1 cara. Tools exponen `rubber_band_lines() -> list[(a,b)]` que el viewport renderiza genéricamente.
7. **Zoom Extents (F2) + Standard Views** (`f29224e`) — `Camera.fit_to(min,max)` + `Camera.set_view("top"/"front"/"right"/"iso"/...)` + `Scene.bounds()`. Menú View → Standard Views.
8. **Faces + Push/Pull (U)** (`e352688`) — `Face` con Newell-normal + centroide. Auto-cara cuando un polígono cierra (≥3 vértices). PushPullTool: hover → click cara → drag o VCB → commit con CompoundCommand (top edges + verticales + top face + N side faces). Render con polygon offset para no z-fighting con aristas.
9. **Adaptive work plane + VCB 3D** (`0f78087`) — `_world_from_pixel` raycastea al plano `Z = start_point.z` cuando hay tool activa con start_point a altura ≠ 0. VCB acepta `5;3;2` como delta XYZ; `LineTool.on_value` recibe float (longitud) o tuple (delta 3D).

### ✅ Sesión 2026-05-22 — hidden line removal
10. **Fix hidden line removal** — bug raíz **doble**:
    - **(a) FBO sin depth attachment**: en PySide6 6.11 + Mesa + Wayland, `QOpenGLWidget` ignora `setFormat(depthBufferSize=24)`; el default FB termina sin depth (verificado: `defaultFramebufferObject()=0`, `glReadPixels(DEPTH)` tras `glClearDepthf(0.5)` devuelve 0.0). Workaround: render en `views/viewport.py` a un `QOpenGLFramebufferObject` propio con `CombinedDepthStencil`, luego `glBlitFramebuffer` del color al default FBO del widget.
    - **(b) QPainter del overlay deshabilita `GL_DEPTH_TEST`** y el estado se hereda en el siguiente `paintGL` — confirmado con `glIsEnabled(GL_DEPTH_TEST)` que devuelve `0` en el frame 2. Por eso, aunque pongamos `glEnable(GL_DEPTH_TEST)` en `initializeGL`, las caras dejan de ocluir aristas después del primer overlay. Fix: re-establecer **todo** el estado GL relevante (`glEnable(GL_DEPTH_TEST)`, `glDepthFunc(GL_LEQUAL)`, `glDepthMask(GL_TRUE)`, `glEnable(GL_BLEND)`, blend func, `glClearDepthf(1.0)`, `glClearColor`) al inicio de cada `paintGL`.
    - Adicional: `glDepthMask(GL_FALSE)` en el grid (no debe ocluir geometría), polygon offset (1,1) sobre caras como cinturón+tirantes para aristas coplanares, request de OpenGL 3.3 Core en `main.py` + en el widget.

### ✅ Sesión 2026-05-22 (continuación) — UX de dibujo y topología
11. **HiDPI / device pixel ratio** — el FBO se creaba con tamaño lógico (`self.width()`) mientras el framebuffer del widget está en píxeles físicos (lógico × DPR). Consecuencia: el render se blitteaba al 1/DPR² del widget y el cursor quedaba desplazado del trazado. Fix: usar `int(self.width() * self.devicePixelRatioF())` para viewport, FBO y blit en `paintGL`/`resizeGL`.
12. **Adaptive work plane según cámara** — `_world_from_pixel` ahora elige el plano de trabajo según la orientación de la cámara. Si `|forward.z| ≥ sin(15°)` (top/iso/arquitectónica), plano horizontal a través de `start_point`. Si la cámara está casi al horizonte, plano vertical (XZ o YZ, el más perpendicular a la vista). Resuelve el problema de "dibujo aparente OK pero la línea cae al suelo" cuando se rota la cámara cerca del horizonte. Threshold de 15° elegido tras probar — más estricto rompía rectángulos en iso, más laxo molestaba en arquitectura.
13. **Auto-detección de polígonos** (`core/topology.py`, nuevo) — `find_smallest_cycle_through(edges, a, b)` hace BFS en el grafo de aristas (dedup por posición con tolerancia ≈ 0.1 mm) para encontrar el ciclo más chico que pasaría por la nueva arista. `is_planar` + `face_exists` filtran lo válido. `LineTool._commit_edge` lo usa: si dibujás 2 líneas que cierran un triángulo usando una arista del cubo, la cara aparece automáticamente. Estilo SketchUp.
14. **UX del snap** — tres ajustes encadenados:
    - Threshold de point snaps bajó de 12 → 9 px (estaba mushy: en aristas cortas el endpoint disparaba a lo largo de toda la línea).
    - Indicador continuo de axis lock (círculo 4×4 siguiendo el cursor) eliminado. El estado de lock se comunica sólo con el color del rubber-band, como SketchUp.
    - Con axis lock activo, `compute_snap` ahora dispara `endpoint` (cuadrado verde) cuando el cursor cae cerca de un vértice que **está sobre la línea de lock** — así podés clavarte exactamente en vértices existentes sin perder el lock.
15. **Orden de render** — ejes XYZ ahora se dibujan ANTES de las aristas del usuario, así una línea sobre el eje Z queda visible por encima del color del eje (`GL_LEQUAL` deja ganar al segundo draw en depths iguales). Rubber-band sigue al final, sin depth-test, encima de todo.

### 🐛 Conocidos sin resolver
- **Fan triangulation rompe para polígonos cóncavos** — funciona para rectángulos y convexos. Una L o cualquier no-convexo se triangula mal. Solución: ear-clipping.
- **Sin face culling** — ambos lados de cada cara se renderizan con el mismo color crema. Front/back vs SketchUp: front cream, back azul-grisáceo. Pendiente.
- **Sin merge de geometría coincidente** — dos rectángulos que comparten arista crean aristas duplicadas. SketchUp auto-suelda.
- **Sin face-plane inference** — el plano de trabajo se adapta a la cámara y al `start_point.z`, pero no a una cara hovereada. Es el siguiente nivel de naturalidad.
- **Auto-polígono encuentra UN solo ciclo** — si una arista cierra múltiples polígonos (clásico: diagonal en cuadrado → 2 triángulos), sólo crea uno (el primero que BFS encuentra). SketchUp crea ambos.

### 🚧 Próxima sesión — prioridades (decididas 2026-05-22)
**Refinar lo que ya existe ANTES de tools nuevas.** El motor básico es ~70%, pero la calidad de la selección y el manejo de polígonos define la experiencia.
1. **Pulir auto-detección de polígonos** — detectar TODOS los ciclos chicos que cierra una arista nueva (no sólo el primero), evitar caras duplicadas con orientación opuesta, considerar el caso de aristas que dividen una cara existente (split de face), y ear-clipping para soportar cóncavos.
2. **Selección sólida** — hoy sólo se seleccionan aristas. Falta: seleccionar caras (con click sobre la cara), seleccionar al hacer rubber-band con drag, double-click para seleccionar todo lo conectado, triple-click para todo el sólido, hover highlighting.
3. **Después de eso** sigue Move/Rotate/Erase + face-plane inference + auto-merge + face culling (en ese orden).

### 🔮 Roadmap v0.1 (versión inicial usable real)

### 🔮 Roadmap v0.1 (versión inicial usable real)
- Groups / Components (encapsulación de geometría reutilizable).
- Tape Measure + Guide Lines (líneas de construcción que no son geometría real).
- Layers / Tags (visibilidad / lock por capa).
- Materials (color sólido + textura por cara).
- IFC import/export (gancho clave con IngePresupuestos).
- STL/3MF export (para impresión 3D).
- Geo-referenciación (terreno DEM + ortofoto). Carpeta `georef/` ya esqueleteada.
- Plugin system público — el patrón `Tool` + auto-discovery en `plugins/` ya está armado, falta documentar y publicar API.
- Sistema de licencia y release (portear desde IngePresupuestos: `core/update_manager.py`, `release.sh`, GitHub Actions, distribución vía R2).

---

## Stack

| Capa | Librería |
|------|----------|
| UI | **PySide6 6.11** (Qt 6) — la única dep "GUI" |
| Render 3D | **QOpenGLShaderProgram + QOpenGLBuffer + QOpenGLVertexArrayObject** bundleados en PySide6. `moderngl` planeado pero **NO instalado todavía** (glcontext requiere `libx11-dev` para compilar en Python 3.14 — pendiente apt install) |
| Math 3D | **QMatrix4x4 + QVector3D + QVector4D** de QtGui (NO numpy, NO pyrr) |
| Empaquetado de vértices | **`array` stdlib** (sin numpy) |
| Snap fuzzy / inference | propio en `core/snap.py` |

**Sin** numpy, ifcopenshell, trimesh, manifold3d, pyassimp aún — esos llegan cuando se necesiten (probablemente IFC el primero).

```bash
cd /home/sumaritux/wasia
source venv/bin/activate
python main.py
```

Python 3.14.4 · venv local en `/home/sumaritux/wasia/venv/` (gitignored).

---

## Arquitectura

```
wasia/
├── main.py                    ← entry point Qt
├── CLAUDE.md                  ← este archivo
├── LICENSE                    ← GPL-3.0 verbatim
├── README.md / CONTRIBUTING.md / CODE_OF_CONDUCT.md
├── core/
│   ├── camera.py              ← OrbitCamera (Z-up, lookAt, perspective/ortho, fit_to, set_view)
│   ├── geometry.py            ← Edge (eq=False, identity-hashable) + Face (Newell normal + centroid)
│   ├── scene.py               ← Scene (edges, faces, selection, version, bounds)
│   ├── snap.py                ← compute_snap(...) — 7 tipos de snap con resolver callbacks
│   └── history.py             ← Command ABC + History (undo/redo) + Add/DeleteEdge/AddFace/Compound
├── views/
│   ├── main_window.py         ← QMainWindow + menús (File/Edit/View/Tools) + toolbar + status bar
│   └── viewport.py            ← QOpenGLWidget — render + paintGL + tools dispatch + VCB + overlays
├── tools/
│   ├── base.py                ← Tool ABC + ToolContext (viewport, world, screen, modifiers, snap)
│   ├── select.py              ← SelectTool (pick edge + Shift-add + Delete)
│   ├── line.py                ← LineTool (chain + auto-close + VCB float/tuple)
│   ├── rectangle.py           ← RectangleTool (4 edges + 1 face CompoundCommand)
│   └── pushpull.py            ← PushPullTool (face hover + drag → extrude)
├── formats/
│   └── wasia.py               ← save_scene / load_into (JSON, schema versionado)
├── plugins/                   ← carpeta para complementos de terceros (vacía + README)
├── georef/                    ← stubs para tiles/DEM/projections (a llenar)
├── resources/
│   ├── shaders/basic.vert + basic.frag
│   ├── icons/ (vacío)
│   ├── fonts/ (vacío — usaremos Inter cuando importemos)
│   └── styles/main.qss (comentado)
├── i18n/
│   ├── en.json
│   └── es.json
├── docs/
│   ├── architecture.md
│   ├── plugins.md
│   └── development.md
├── tests/
└── .github/workflows/ (vacío)
```

---

## Convenciones (NO romper)

- **Idioma**: TODO el código, comentarios, docstrings, commit messages y nombres de carpeta en **inglés** (decidido en sesión inaugural para atraer contributors). UI bilingüe via `i18n/{en,es}.json`. Es **lo opuesto a IngePresupuestos** (que es 100% español por ser closed-source).
- **Z-up**: convención SketchUp/Blender/FreeCAD/CAD. X rojo (este), Y verde (norte), Z azul (vertical). NO mezclar con Y-up de juegos.
- **Identity-equal entities**: `@dataclass(eq=False)` en Edge y Face. Esto las hace hashables (set/dict OK) y dos instancias con mismos valores se tratan como distintas. La selection set se llena con referencias.
- **Toda mutación pasa por Command**: nunca llamar `scene.edges.append(...)` directo desde un tool. Usá `viewport.history.execute(AddEdgeCommand(...))`. Así undo/redo siempre funciona.
- **Tools heredan de `tools.base.Tool`**: implementan al menos `on_activate`/`on_deactivate`. Spatial tools sobrescriben `on_click`/`on_hover`/`on_cancel`/`on_value` recibiendo `ToolContext`. Para preview gráfico, override `rubber_band_lines()` devolviendo lista de segmentos. Para label flotante custom, override `value_label() -> (text, world_pos)`.
- **Cualquier `QOpenGLWidget` debe `glClear` en `paintGL`** — Wayland es estricto, no perdona buffers no inicializados. Ver memoria `[[feedback-wayland-paintgl-explicito]]`.
- **`QMatrix4x4 * QVector4D` no está bindeado** en PySide6 6.11 — usar `mvp.map(QVector4D(x,y,z,1))`. Ver memoria `[[feedback-pyside6-matrix-vector-mul]]`.

---

## Gotchas críticos descubiertos

- **Z lock pre-refactor**: proyectar candidate (que venía del raycast Z=0) sobre el eje Z daba el mismo `start_point`. Fix: `_project_to_lock_line` con closest-point line-to-ray usando el rayo de la cámara (`views/viewport.py`). Mismo fix vale para reference lock con dirección 3D.
- **Adaptive work plane** (Fix 1 de la sesión 9): sin esto, después de subir con Z lock no podías dibujar al nivel del techo — el cursor caía al suelo. Solución: `_current_work_plane_z()` que usa `start_point.z()` cuando hay tool activa.
- **Polygon offset** activado solo para faces (`GL_POLYGON_OFFSET_FILL` con factor 1, units 1) — empuja las caras "atrás" en depth para que aristas coincidentes se vean limpias encima. Combinado con `glDepthFunc(GL_LEQUAL)` cubre todos los casos de aristas coplanares con caras.
- **Rubber band depth-test off**: el rubber-band naranja se pinta SIEMPRE encima de cualquier cosa, sin importar profundidad. Lo logramos con `glDisable(GL_DEPTH_TEST)` antes del draw, `glEnable` después.
- **QOpenGLWidget sin depth buffer real**: en esta combinación PySide6/Mesa/Wayland, el default FB del widget llega sin depth attachment aunque `setFormat(depthBufferSize=24)` y `context().format()` mientan diciendo que sí lo tiene. Por eso `Viewport.paintGL` renderea a su propio `QOpenGLFramebufferObject` (creado en `_ensure_scene_fbo` con `CombinedDepthStencil`) y blittea el color al final. **No tocar este flujo sin verificar que el depth buffer sobreviva** — la regresión es silenciosa: la app sigue funcionando, sólo se rompe la oclusión.
- **QPainter contamina el estado GL** entre frames. Cada `paintGL` debe re-establecer `GL_DEPTH_TEST`, `glDepthFunc`, `glDepthMask`, `GL_BLEND`, blend func y clear color/depth. No alcanza con setearlos una vez en `initializeGL`. La regresión típica es: hidden-line removal funciona en el primer frame y se rompe en todos los siguientes.

---

## Tests + CI

- `tests/` existe pero está vacía. Pytest planeado, sin tests escritos aún.
- GitHub Actions en `.github/workflows/` vacío (pendiente de portar el setup desde IngePresupuestos cuando empecemos a empaquetar releases).

---

## Memorias de Claude relacionadas (en `~/.claude/projects/-home-sumaritux-ingepresupuestos-pyside6/memory/`)

- `project_wasia_iniciado.md` — decisiones estratégicas del proyecto (GPL-3.0, idioma inglés, monetización via integración con IngePresupuestos).
- `feedback_wayland_paintgl_explicito.md` — Wayland exige `glClear` en `paintGL`.
- `feedback_pyside6_matrix_vector_mul.md` — `QMatrix4x4 * QVector4D` no bindea; usar `.map()`.
