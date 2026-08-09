# IngeTrazo — modelador 3D libre

**Autor:** Marco Sumari Tellez · **Licencia:** GPL-3.0-or-later · **Repo:** `github.com/tuxiasumari/ingetrazo` (público) · **Web:** https://ingetrazo.com (repo `../web`; deploy: `npx wrangler deploy` + git push) · **Manual:** https://ingetrazo-docs.pages.dev (repo `../manual` → github ingelibre/ingetrazo-docs, MkDocs Material espejo de ingepresupuestos-docs; publicar: `venv/bin/mkdocs build` + `npx wrangler pages deploy site --project-name ingetrazo-docs`; dominio docs.ingetrazo.com pendiente de 1 paso en dashboard)

Modelador 3D estilo SketchUp para arquitectura/ingeniería civil e impresión 3D. Linux-first, multiplataforma, PySide6. Hermano open-source de [IngePresupuestos](../ingepresupuestos-pyside6/) — la integración IFC cierra el loop modelo → metrado → presupuesto. *(Se llamó **Wasia** 2026-05-21..23; extensión nativa `.igz`.)*

> **Bitácora:** el registro de *lo hecho* vive en los commits de git y en la historia de este archivo (`git log -p CLAUDE.md` para el detalle de sesiones pasadas). Este archivo guarda el **rumbo**: visión, invariantes, estado, pendientes y gotchas vigentes.

---

## 🧭 Visión y principios (NO negociables)

**El nombre ES la tesis: _trazar como en la vida real_.** Si una decisión de UX mete complejidad de CAD y se aleja de "esto se siente como trazar a mano", es la equivocada. Filtro maestro sobre todos los demás.

**El flujo unificado es el producto** (un solo entorno, no 2D-aparte):
> **terreno (fotogrametría/GPS, georef) → trazar encima → aplicar BIM a lo trazado → .ifc → IngePresupuestos (presupuesto → cronograma → control de obra)**

1. **Freeform al núcleo, BIM como tagging encima.** Sin primitivas rígidas tipo Revit; el BIM son metadatos opcionales sobre geometría seleccionada. Lo taggeado va al IFC/metrado; lo demás es dibujo. Referente: BlenderBIM.
2. **2D = Top View + Parallel + Layers**, no un módulo separado. Output profesional de planos (LayOut-equivalente) diferido a v2.
3. **Scope disciplinado.** No competir feature-por-feature con SketchUp/AutoCAD/Revit. Filtro: "¿le sirve al que modela un edificio chico y saca cantidades?".
4. **`Scene` heterogénea:** malla de referencia (display-only, NUNCA entra al motor de topología), contexto georef, geometría freeform editable (el motor), tags BIM. El terreno/DEM/imports pesados jamás pasan por el weld/heal.
5. **AI-native (invariante, sin construir IA aún):** toda edición ejecutable sin mouse vía capa de acciones explícita (`Tool` + `Command` ya lo cumplen ~70%). La IA será orquestación OPCIONAL sobre el motor determinista — genera *recetas* de acciones, nunca mallas directas; el guard de hermeticidad es el validador del loop agéntico. El moat: API de acciones + semántica de dominio (BIM/IFC/normativa latam/metrado) + flujo unificado + libre/Linux/offline/español — no la generación cruda.
6. **Posicionamiento:** IngePresupuestos = caja a corto plazo; IngeTrazo = moat a largo (motor sólido + IFC, integración fuerte después). IFC bridge por archivos primero; embebido solo con motor maduro y licencia compatible.
7. **Licencia:** GPL-3.0 público desde 2026-07-05. Marco es único titular de copyright → puede re-licenciar (p.ej. Apache 2.0 para el embebido futuro) cuando quiera. Si el norte es "libre para siempre", GPL ya es correcto — decisión abierta, sin urgencia.

**Regla de oro de fases:** una fase no está terminada hasta (1) DoD pasa, (2) commiteada y la app arranca sin regresiones, (3) cero "lo dejo para después". **Dogfooding:** priorizar dibujando un escenario real (la "casita", los archivos del usuario) — los gaps aparecen solos; pedir siempre `.igz`/`.skp` de repro.

---

## 📦 Estado actual (2026-08-08)

**v0.3.0 released 2026-08-08** (tag en `main`, CI Windows + `skp2dae.exe` re-adjuntado): **el release del compositor de láminas** — composer C1–C5 completo (marcos a escala exacta, HLR vectorial, PDF/atlas, DXF a IngeCAD, cotas ancladas al modelo con estilos, formas con polígono/radio/colores, cajetín editable multi-columna, orden Z + bloqueo, zoom QGIS con 100% = tamaño real), G6 fotogrametría, UTM WGS84 en la UI de terreno con selector de marco de coordenadas y pin-origen explícito, fix del deadlock de import .skp e instancia única. Pre-release: review de 5 hallazgos verificados y corregidos (crash por rebuild mid-placement, guard en píxeles obsoletos, captura de re-anclaje, alt al mover origen lejos, clamp de líneas), suites completas verdes (1076 rápidos + 796 slow). Pin de openskp en CI avanzado a la cabeza del fork.

**v0.2.4 released 2026-07-26** (tag `v0.2.4` + CI Windows verde + `skp2dae.exe` re-adjuntado desde v0.2.3): **`.igz` autocontenido** (texturas adentro del documento) + el import `.skp` deja de crear carpetas junto al archivo del usuario; arrastra además todo lo de la sesión 2026-07-24 (capas, escenas, cotas lineales, doble clic para abrir `.skp`, import sin congelar la ventana).

**v0.2.3 released 2026-07-22** (tag + binarios Windows por CI + `skp2dae.exe` re-adjuntado; instalado en la PC del usuario vía `scripts/install_desktop.sh`): **import .skp NATIVO puro-Python de todas las eras** — el build de Windows instala nuestro fork openskp (pineado por SHA en `build-windows.yml`; actualizar el SHA cuando avance la rama `ingetrazo` del fork) con hiddenimports en `ingetrazo.spec`; el fork hizo lazy trimesh/shapely (parse solo necesita numpy). El usuario lo usa como programa normal; las sesiones suelen arrancar con reportes de uso real.

**Sesión 2026-07-24 — fidelidad de import .skp (todo pusheado, fork SHA `3c85b4d`):** se cerraron 3 de los 4 pendientes que quedaban para el "100% fiel a SketchUp": **(1) capas/etiquetas** (asignación por entidad + visibilidad, ambas eras — se llaman **Capas** en la UI, decisión de naming CAD-first), **(2) escenas** (SavedView: cámara + capas ocultas por escena, panel en la bandeja, .igz, import VFF), **(3) cotas lineales** (entidad `5BCC`, extremos resueltos a mundo vía transformación de instancia; validadas con el expediente técnico real). Queda del set original: **texto/etiquetas** (falta repro con entidades Text) + jerarquía de grupos anidados. Método de RE de esta sesión: calibrar contra los `scene_thumbnails/*.png` embebidos en el propio `.skp` (ground truth interno cuando skp2dae/DAE no sirve de oráculo).

**El modelador está MUY completo:** dibujo (línea, rect, rect rotado, círculo, polígono, arcos ×4, offset, sígueme, texto 3D), push/pull robusto con **guard de hermeticidad grado-BIM** (nunca commitea un sólido roto; ops ambiguas se rechazan fail-safe), move/rotar/escala, grupos (v2: entrar con doble clic) + **componentes/instancias compartidas** (proto + xforms, O(1) transformar), materiales + texturas SketchUp-compatible (proyección planar + UVs afines por cara), pintar (B) con eyedropper, **Invertir caras**, cotas + texto guía, capas, **escenas** (SavedView: cámara + visibilidad de capas, panel en la bandeja, .igz, import .skp), bandeja lateral, face culling (dorso azul-gris, color de estilo del archivo), aristas soft/superficies curvas/profiles, **transparencias** (cutout con dither Bayer + materiales translúcidos con pase blend), zoom/zoom ventana, UI bilingüe (`tr()` + `es.json`).

**I/O:** `.igz` (JSON versionado, protos compartidos; **con texturas = contenedor ZIP autocontenido** — ver abajo) · import **`.skp` directo** (ver abajo) · import/export `.dae` COLLADA (export con **geolocalización** para asoleamiento) · import/export OBJ · export STL, **glTF/GLB** (PBR + geolocalización), imagen hi-res del viewport · IFC4 export a mano (STEP sin deps).

**`.igz` autocontenido (2026-07-25):** un documento **sin** texturas sigue siendo JSON plano `igz_format: 1` (diffable, editable a mano, lo abren builds viejos). Apenas hay texturas se guarda como **ZIP `igz_format: 2`**: `document.json` (deflate) + `textures/<sha1-16>-<nombre>` (stored, ya comprimidas), y cada entrada lleva `"embed": "textures/…"` en vez de `"path"` — cero rutas absolutas de la máquina en el archivo. Al abrir, `_unpack_textures` extrae a `<cache>/embedded/` (content-addressed → una sola copia y un solo upload a GPU aunque varios documentos compartan la imagen) y repone `path`, así que renderer/exportadores no se enteran del contenedor. Escritura atómica (`.part` + rename) y timestamps ZIP fijos (1980) → dos guardados del mismo modelo dan bytes idénticos. Imagen ilegible al guardar = se conserva su `path` y `save_scene` la reporta en `{"embedded", "missing"}` (la UI avisa). Medido en `plaza Yanque (1).skp` (1038 grupos, 58 496 caras texturadas, 19 imágenes): **22.8 MB vs 109.6 MB del JSON plano anterior** — el contenedor es 5× más chico *y* además lleva las texturas; guardar 3.4 s, abrir 5.7 s. Pendiente abierto: comprimir también los documentos sin texturas (ganancia ~10× en geometría) a costa de la diffabilidad — decisión del usuario.

**BIM→IFC validado end-to-end:** `.ifc` pasa `ifcopenshell.validate` limpio; cantidades honestas por clase (`Qto_*BaseQuantities`: muro NetSideArea, losa, columna/viga, puerta/ventana, por-metro); puente real con el importador de IngePresupuestos verificado (metrados exactos); "Taggear al dibujar" + push/pull propaga tags. Hallazgos pendientes del lado IngePresupuestos: su `IFC_MAP` pierde `IFCRAILING`/`IFCCOVERING` en silencio; prefiere `max()` de áreas en vez de `Net*` sobre `Gross*`.

**Georref (Track G):** MVP completo — datum local (`SceneDatum`, UTM↔local exacto), teselas XYZ (presets + fuentes custom con nombre persistentes), terreno 3D drapeado (DEM AWS terrarium + mosaico), GeoPath (subsistema propio, NUNCA `Scene.mesh`) con perfil longitudinal vivo + export CSV/PNG, puntos topográficos CSV (P,N,E,Z estación total) con snap bit-exacto. Falta expansión: **G5 curvas de nivel** + DXF.

**G6 — malla fotogramétrica (2026-08-03): HECHO.** `georef/photomesh.py` importa el modelo texturizado de WebODM/ODM como geometría de referencia display-only (invariante #4, arrays NumPy, jamás `Scene.mesh`). Dogfooding con el levantamiento real del usuario (chanchallay, 802×666 m, 362 395 triángulos, 21 atlas): carga 1,12 s, import completo por el menú 2,11 s, guardar 1,80 s → **29,6 MB**, reabrir 2,00 s. Piezas:
- **Coordenadas:** el `_geo.obj` NO es UTM crudo pese al nombre — ODM resta un ancla entera (`odm_georeferencing_model_geo.txt`) y escribe el resto en ±400 m; la Z sí es altitud absoluta. Sin problema de float32, y las versiones recientes ya no exportan el gemelo sin `_geo`.
- **Referencia vertical:** `vertical_origin()` = percentil 1 de las cotas (el **pie** del levantamiento; el mínimo real no sirve, hay picos de reconstrucción — 94 vértices de 222 622 y el más bajo 45 m bajo el p0,1). Se guarda en **`datum.alt`**, así que toda cota se reporta como altitud real. Deriva SOLO del levantamiento: la versión anterior la tomaba del DEM global y mezclaba datums verticales *además* de depender de que hubieran descargado las teselas — el mismo modelo importaba con cotas distintas según la red.
- **Texturas:** ODM emite atlas de hasta 24576², que ninguna GPU acepta. `plan_texture_sizes()` recorta al `GL_MAX_TEXTURE_SIZE` real y luego encoge el mayor hasta caber en un presupuesto de 1 GiB (3,09 → 0,42 GB en la Radeon 780M). Caché en `<texture_cache_root>/odm/`: 8,6 s → 0,6 s.
- **Consulta de superficie:** `height_at(x,y)` con rejilla en planta vectorizada y perezosa — 133 ms de construcción, **21,5 µs por consulta**. En solapes gana la Z más alta. `PhotoMeshSampler` la enchufa a `sample_profile`, así que el perfil longitudinal sale del vuelo propio y no del SRTM de 30 m.
- **Persistencia:** dentro del `.igz` (geometría `.npz` + atlas JPEG ya reescalados). Probado moviendo la carpeta del export de WebODM: el documento abre solo. **La captura del mapa base también se guarda ahora** (`TileLayer.to_dict/from_dict`) — nunca las teselas, que son de un servidor ajeno.
- **Capas:** `PhotoMesh.layer`; el import crea y asigna `SURVEY_LAYER`, para que apagar el levantamiento no se lleve el modelo propio.
- **Trazado:** la herramienta Ruta entra sola en vista superior + paralela (única combinación con paralaje cero sobre relieve) y restaura la cámara al salir; etiqueta en vivo con cota bajo el cursor y, al trazar, longitud · cota · desnivel (pendiente %). Lectura UTM continua en la barra de estado.
- **Ojo con las cotas:** sin GCP, la Z del vuelo es GNSS del dron = elipsoidal, con error de varios metros. El CSV del perfil lo declara en una línea de comentario. El DEM global es ortométrico, así que Terreno 3D y levantamiento muestran un escalón: es real, no un fallo de encaje.
- **Falta:** dibujo directo en 3D sobre la malla (los tools siguen en el plano Z=0; una plataforma dibujada en el origen queda enterrada si el terreno ahí está más alto) y cotas persistentes como anotación.

**Perf:** índice de pick NumPy vectorizado, caras en un draw call (vcolor), chunks por grupo/instancia, hover coalescing — plaza de 394k tris orbita a 60 fps. Pendiente de fondo: import DAE grande ~27 s (ítem "grupos de referencia como arrays NumPy puros").

**Tests: ~963 rápidos + ~800 slow (fuzz 996/1000 limpias, 4 xfail draw-side)** — `python -m pytest tests/ -q -m "not slow"`. CI Windows en tags `v*`.

---

## 🔌 Import SketchUp (.skp) — estrategia OpenSKP

**Decisión 2026-07-21: apoyar de lleno a OpenSKP upstream** (`github.com/iamahsanmehmood/openskp`, MIT, parser clean-room puro-Python) con fork propio como seguro (`tuxiasumari/openskp`, rama `ingetrazo` = main + todos nuestros PRs, instalada editable en el venv). **11 PRs upstream abiertos** (#3–#13): material id, extracción de texturas, material de instancia, UV por cara (matriz 3×3 posicionada/photo-fit), nombres UTF-8, image entities, face-camera behavior, colores de estilo, back material, useTrans, texturas compartidas de materiales colorizados.

- **`formats/skp.py`** = costura: cascada backend openskp → fallback **skp2dae** (satélite Wine + SketchUpAPI.dll del add-on de Blender, proceso separado — la DLL de Trimble JAMÁS entra al árbol GPL; instalador de un clic; `skp2dae.exe` debe re-adjuntarse a CADA release). **HITO 2026-07-22 (palabras del usuario): "el modelo abre fiel a SketchUp, tanto las últimas versiones de skp como las antiguas" — ya NO dependemos del plugin de Blender** (skp2dae queda como fallback de emergencia). **Capas/etiquetas de SketchUp: IMPORTADAS desde 2026-07-24** (ambas eras) — se registran en la bandeja Capas con su visibilidad del archivo (VFF: `8C3C→8E3C` byte hidden; entidad → capa vía `D007→D207`; legacy: db de CEntity + primer byte de flags de CLayer, validado con 'Location Terrain' oculta); decisión de naming: se quedan como **Capas** (público CAD/AutoCAD, no jerga SketchUp 2020+). Instancias top-level → `Group.layer`; instancias anidadas taggeadas se EXTRAEN como grupo propio con la capa (los chunks de referencia no filtran por-cara — y un def con instancias taggeadas en su subtree se excluye de proto-sharing, como los face-me; el hijo taggeado suele re-compartirse un nivel abajo vía `instance_layers` por placement); caras taggeadas → `attrs["layer"]` (gap residual conocido: cara individual taggeada dentro de grupo NO-taggeado no se oculta al toggle — contados ~50 en Toril). **Escenas de SketchUp: IMPORTADAS desde 2026-07-24 (VFF)** — nodo `0702` ▸ `6D60`▸`6D61`▸`7148` por página: `6F54→6F55` nombre, `714A→34BC` cámara (`34BD/34BE/34BF` eye/target/up en pulgadas, `34C4` fov, `34C2` u8 flag PERSPECTIVA — 00 = paralela, calibrado contra los `scene_thumbnails/` del propio ZIP; `34C3` alto visible en paralela), `7150` capas ocultas (runs u8-len + var-int id); llegan como `SavedView` (paralela → distancia derivada del alto orto). Legacy MFC sin escenas aún (CPage sin walker — falta repro con escenas). **Cotas lineales de SketchUp: IMPORTADAS desde 2026-07-24 (VFF)** — entidad `5BCC`: 2 puntos de conexión (`5BCD`/`5BCE`) tipo 1 (punto libre explícito en `520A`) o tipo 2 (conectado a geometría: `520B→53FC→53FD` = id de vértice, `53FE` = id de instancia con prefijo de longitud); el vértice es local → se lleva a mundo con la transformación de la instancia (mapa instancia→xform-mundo componiendo el árbol 6419); `5BD2` = offset. Valor auto-calculado de la distancia (sin texto cacheado). Validado en el expediente técnico real (`plaza Yanque (1).skp`): 6 cotas caen exactas donde el autor las puso (1.87/1.50/1.00 m en la estatua). Falta para el 100%: **texto/etiquetas** (este archivo no tenía entidades Text — falta repro con texto), cotas radiales/angulares, y jerarquía de grupos anidados — planificado para más adelante. **Legacy MFC (≤2020): SOPORTADO nativo desde 2026-07-22** — `openskp/legacy.py` en el fork (rama `ingetrazo` pusheada; upstream PR #14): walker completo del CArchive MFC (store map global, bootstrap de base por el tag del material 2, oráculos parent-de-loop), validado con paridad EXACTA (caras/aristas/área/bbox + fingerprint `skp_diff` idéntico incl. materiales y texturas) en 5 modelos reales v16/v17/v18 vs sus re-guardados VFF de SketchUp Web. Deltas vs la spec pública 2017 (crate Rust `openskp` de hew3d, GPL — usada solo como spec, no su código): vértices ANTES del puntero de curva en CEdge, CLoop +2 bytes de flags, CEdgeUse con preámbulo, back-material antes de los edge-refs redundantes, opacidad gateada por u8 (análogo useTrans), v16 sin pid-mask (CEntity schema 3), flag face-camera en gap[-9] pre-thumbnail. Gaps conocidos: <2 materiales no bootstrapea (cae a skp2dae), CImage/thumbnail doc omitidos, instancias espejadas intercambian lados del material por-cara. Resueltos en dogfooding 2026-07-22: colorizados legacy (flag = blob-u32|alpha + guard _needs_tint), texturas PROYECTADAS (FTC flag bit1, drape en planta), semántica opacidad (trans = transparencia), flags soft/smooth/hidden por arista (D307), material por lado con culling.
- **`formats/skp_openskp.py`** = adapter a payload IngeTrazo: precedencia de materiales SketchUp (cara frontal propia → trasera propia (+flip) → heredado de instancia → estilo), UVs posicionados (receta inversa de la matriz texture→plane), mapeo default en frame LOCAL, colorizados re-tintados (shift/tint HLS, alpha preservado, archivo propio `<mid>_<nombre>`), opacidad, billboards face-me e imágenes, protos por (def, material heredado). **Las imágenes extraídas van a la caché de la app** (`core/texture.py::texture_cache_root` → `<user data>/IngeTrazo/textures/`, subcarpetas `skp/<stem>-<hash de ruta+size+mtime>/` y `embedded/`; override con `$INGETRAZO_TEXTURE_CACHE`, se vacía desde *Archivo ▸ Importar ▸ Limpiar caché de texturas importadas…*) — desde 2026-07-25 el import NUNCA crea carpetas junto al `.skp` del usuario (antes escribía `<stem>/` ahí).
- **Conocimiento del formato TLV** (decodificado acá): cara `AC0D` → `D107` material frontal, `AF0D` trasero, `D007→…→1527` matriz UV 3×3 f64; instancia `6419` (`D107` = pintar componente); `581B→5D1B` = always-face-camera; `8315==2` = image entity; XML: `useTrans` gatea `trans`, `type="2"` = colorizado (imagen compartida cross-carpeta), estilos `4000/4001` = colores frontal/trasero. Detalle en `docs/skp-backend.md` y `docs/openskp-collaboration.md`.
- **`scripts/skp_diff.py`** = harness de paridad (fingerprint por áreas, fusion-invariant) con skp2dae como oráculo caja-negra (límite clean-room: jamás descompilar la DLL).
- **Paridad lograda en archivos reales del usuario** (plaza Yanque, Toril): bbox exacto, área 0.00%, materiales/texturas/grupos/billboards/translucidez al nivel de SketchUp Web.
- Pendientes track: issue upstream por instance-tree misplacement, respuestas del maintainer a #2-#15. **Aportado upstream 2026-07-22 (autorizado por el usuario): PR #14 (parser legacy MFC completo), PR #15 (flags de aristas D307), PR #12 actualizado (semántica trans = transparencia)**; fork pusheado (`ingetrazo` = todo lo nuestro).

---

## Stack

PySide6 6.11 (única dep GUI) · OpenGL 3.3 core vía Qt (QOpenGLShaderProgram/Buffer/VAO) · math QtGui (QMatrix4x4/QVector3D) · NumPy 2.5 (DEM, picks, texturas) · openskp editable desde `~/openskp` · ifcopenshell solo como herramienta de dev (NO en requirements). Python 3.14, venv local.

```bash
cd /home/sumaritux/Proyectos/ingetrazo/app && source venv/bin/activate && python main.py
```

**Portabilidad:** wheels ARM de deps nativas son la fricción real (vigilar ifcopenshell); código propio limpio de asunciones x86. macOS: OpenGL deprecado pero Qt tiene path a Metal.

---

## Arquitectura (mapa)

```
core/     mesh.py (motor: vértices compartidos no-manifold) · scene.py · camera.py ·
          snap.py · topology.py (ciclos/heal) · triangulate.py (earcut) · edits.py ·
          history.py (Command/undo) · orient.py (outward por paridad) ·
          cap_rebuild.py + arrangement.py (rebuild determinista por plano) ·
          group.py (+instancias xform) · bim.py (15 clases IFC + cantidades) ·
          dimension.py · texture.py · text3d.py · textlabel.py · sweep.py · layers.py · i18n.py
views/    main_window.py · viewport.py (render+FBO+picks+VCB+tools dispatch) ·
          tray.py (materiales/cotas/info/capas/BIM/Terreno) · profile_panel.py · icons.py
tools/    base.py (Tool ABC) + select/line/rectangle/circle/arc/move/offset/pushpull/
          paint/dimension/text/geopath/...
formats/  igz.py · skp.py + skp_openskp.py · dae.py · obj.py · stl.py · gltf.py · ifc.py · fuse.py
georef/   datum.py · tiles.py + tile_fetcher.py · dem.py · terrain.py · geopath.py ·
          photomesh.py (malla fotogramétrica ODM, G6) · geoimport.py · surface.py ·
          profile.py · points.py
scripts/  install_desktop.sh · gen_textures/components/doc_icons/app_icon.py · skp_diff.py
docs/     skp-backend.md · openskp-collaboration.md · halfedge-migration-plan.md
```

---

## Convenciones (NO romper)

- **Código/comentarios/commits en inglés**; UI bilingüe vía `core/i18n.py::tr("English source")` + `i18n/es.json` (mapa plano; el inglés es la clave y el fallback). Strings visibles SIEMPRE `tr()`; atributos de tool se traducen en el punto de display, no en la clase. Sin toolchain `.ts`/`.qm`.
- **Z-up** (SketchUp/Blender). X rojo este, Y verde norte, Z azul vertical.
- **Toda mutación pasa por `Command`** (`viewport.history.execute(...)`) — nunca mutar `scene` directo desde un tool.
- **Tools heredan de `tools.base.Tool`**; preview vía `rubber_band_lines()` / `value_label()`; tools de dibujo leen `tool.work_plane` + `plane_axes(normal)` (no hardcodear XY).
- **Identity-equal entities**: `@dataclass(eq=False)` en Edge/Face; la selección guarda referencias.
- Archivos `.igz`/`.skp` de repro del usuario quedan sin trackear en la raíz (scratch).
- Releases: AppId GUID del `.iss` NUNCA cambia; `skp2dae.exe` se re-adjunta a cada release; versión única en `core/version.py`.

---

## Gotchas críticos vigentes (Qt/GL/PySide6)

- **PySide6 bindings:** `QMatrix4x4 * QVector4D` no está bindeado → `mvp.map(...)`. `setUniformValue(loc, 1.0)` rutea el float de Python a la sobrecarga **int** → para uniforms float escalares usar **`setUniformValue1f`** (causó el bug "todo se ve líneas").
- **QOpenGLWidget sin depth real** (PySide6/Mesa/Wayland): el viewport renderea a un FBO propio `CombinedDepthStencil` y blittea. No tocar ese flujo — la regresión es silenciosa (se rompe solo la oclusión). **MSAA va en el FBO de escena**, no en el widget.
- **QPainter contamina el estado GL**: cada `paintGL` re-establece depth test/func/mask, blend, clear color/depth. Y todo `paintGL` debe `glClear` (Wayland estricto).
- **Wayland nativo intercala frames viejos** bajo ráfagas de update (bug del compositor; XWayland perfecto). Decisión del usuario: quedarse en Wayland (multi-monitor DPI mixto). Escape: `QT_QPA_PLATFORM=xcb`.
- **HiDPI:** FBO/viewport/blit en píxeles físicos (`width() * devicePixelRatioF()`).
- **Cutouts + mipmaps:** el discard duro en alpha 0.5 borra texturas caladas al minificar (el promedio cae bajo 0.5) → el shader usa dither Bayer bajo el umbral. Los pases translúcidos (u_opacity<1) van con blend, depth-mask off, después de los opacos.
- **Verificación visual:** `QWidget.grab()` NO captura el overlay QPainter — usar `import -window` (ImageMagick) sobre XWayland, o `viewport.render_image()`. Íconos SIEMPRE validarlos a 24 px reales y en modo oscuro.
- **El ícono de app es un SVG desde el 2026-08-07**, `resources/icons/ingetrazo.svg`, y es la **única fuente de verdad**. Antes el maestro era `ingetrazo_master.png` (816 px) y no había vector: no se podía cambiar la marca sin redibujarla, y 816 px era el techo. La marca se reconstruyó como geometría desde ese raster y se verificó contra él (**96,2 % de solape** en el área azul; lo que faltaba era exactamente el pelo de contorno que el raster llevaba). El diseño vigente (elección de Marco, 2026-08-08, **V11D**) es un **cubo de línea Blueberry-500 `#3689e6` con nodos Orange-100 `#ffc27d` y caras Slate-500/700/Black-900**, sobre la **teja de familia de IngeCAD con su juego de luces exacto**: huella 112 px (rx 24), degradado vertical `#273445`→`#171b21`, keyline negra al 45 % (evita fundirse con docks oscuros — bug cazado por captura) y highlight blanco al 5 %. Todos los colores planos son valores oficiales de la paleta elementary. El recorrido completo y el generador viven en `../icono-propuestas/` (LEEME.md + gen_n6_variantes.py). Al editar el SVG hay que regenerar **en este orden**: `scripts/gen_app_icon.py` (PNG 16..512 + `.ico`) y después `scripts/gen_doc_icons.py`, que compone `ingetrazo_256.png` como insignia de los íconos de documento. El sitio se pone al día con `web/tools/gen-images.py`, y **ojo: el logo de la sección puente de ingecad.org es una copia** (`~/Proyectos/ingecad/web/images/ingetrazo-logo.png`) que hay que regenerar aparte. La geometría vive comentada dentro del propio SVG: un parámetro `t = 0,175` para las aspas y un `CUBE_R = 0,27` deliberadamente mayor para que el cubito se lea a 24 px.
- ⚠️ **(Medido sobre la marca anterior, propuesta3; la keyline de V11D lo mitiga)** El ícono oscuro pierde su silueta sobre las superficies oscuras del PROPIO sitio. Medido: el hexágono contra la cabecera (`--slate-700 #273445`) da **1,46:1**, y contra el fondo del banner OG, 1,47:1 — invisible. Lo que sí se lee son las aspas (3,53:1) y el cubo ámbar (7,97:1), así que a 32 px la marca funciona, solo que como marca y no como insignia. El ícono viejo, con hexágono blanco, daba 12,1:1 ahí. Si algún día molesta, la salida es un logo aparte de hexágono claro para las superficies oscuras del sitio — no cambiar el ícono de la app, que es donde el hexágono oscuro gana (dock, gestor de archivos, fondos claros).
- **Un paquete MIME ajeno rompe `update-mime-database` en esta máquina.** El instalador install4j de PDF Studio 2024 dejó en `~/.local/share/mime/packages/` un archivo con cinco tipos MIME metidos en un solo atributo `type`, que es inválido. Se rechaza en **cada** registro de tipo, de cualquiera de los tres proyectos, así que el error que escupe `install_desktop.sh` no es nuestro. El entry ya no tiene efecto (se descarta), así que borrar ese archivo es inocuo — decisión de Marco, sin hacer.
- **QSettings en scripts sueltos:** fijar `setOrganizationName/setApplicationName` como main.py o escriben a `Unknown Organization`.
- **Wine re-encodea argv** al codepage ANSI → rutas con acentos a skp2dae pasan por temp ASCII.
- **`QOpenGLTexture.destroy()` sin contexto activo** filtra la textura y avisa "Texture has not been destroyed". Envolver siempre en `makeCurrent()/doneCurrent()` como hace `reset_tiles`. Con los 21 atlas de un levantamiento son 0,42 GB de VRAM sin liberar.
- **`signal.connect(lambda…, Qt.QueuedConnection)` sin objeto receptor** ejecuta el slot en el hilo EMISOR — Qt no tiene dónde encolarlo. Síntoma: "QObject::killTimer: Timers cannot be stopped from another thread" al tocar el diálogo de progreso. Hay que conectar a un **método enlazado** de un QObject del hilo de la UI; PySide6 NO acepta la forma de 3 argumentos `connect(contexto, slot, tipo)`. *(`_parse_skp_threaded` tenía este patrón y el 2026-08-08 pasó de warning a DEADLOCK total antes del primer paint — "doble clic en .skp y no abre nada"; arreglado con un QObject relay.)*
- **`QImageReader` rechaza imágenes de más de `allocationLimit()`, 256 MB por defecto**, con un error de "sin memoria" engañoso; hay que ponerlo a 0 y restaurarlo. Y **`setScaledSize` NO evita decodificar un PNG entero** (medido: 7,4 s y 2,5 GB de pico igual con y sin), de ahí la caché de atlas.
- **Un error en Z es INVISIBLE en vista superior.** El mapa base estuvo 1804 m bajo tierra y todas las comprobaciones de encaje en planta salían perfectas. Verificar siempre en vista frontal/lateral además de la superior.
- **`SceneDatum.geodetic_to_local(lat, lon)` sin altitud significa "sobre el plano de referencia"** (Z local = 0), no a nivel del mar. El default de 0.0 metros absolutos hundía todo lo que no lleva elevación propia en cuanto el datum tenía `alt` (teselas del mapa, alineamientos KML).
- **`capture_state` NO sirve para copiar mallas** (preserva identidad y aliasa); copiar = add_face/add_edge profundo.
- **`orient_outward` y glifos:** el probe de centroide falla en caras cóncavas sin huecos — los windings del texto 3D se fijan analíticamente; no tocar el probe.

---

## 🎯 Pendientes (por prioridad tentativa)

1. **Import .skp — completar el "100% fiel" (activo 2026-07-24):** hecho capas + escenas + cotas lineales; **falta (a) TEXTO/etiquetas** (entidad Text — `plaza Yanque (1).skp` no la tenía; pedir repro con texto colocado, calibrar contra su contenido), **(b) cotas radiales/angulares** (otra entidad, sin decodificar), **(c) pulir el lado del offset de la línea de cota** (la dirección perpendicular se deriva, no calca exacto a SketchUp), **(d) jerarquía de grupos anidados**. Aparte: **detalles del render de transparencias** (pendiente viejo) y **optimizaciones**.
2. **Track .skp upstream:** issue instance-tree misplacement (hallado, sin reportar — lo único no reportado); **capas/escenas/cotas parseadas en el fork rama `ingetrazo` (2026-07-24) AÚN sin aportar upstream como PR** (preguntar a Marco — serían PRs nuevos sobre main); legacy MFC **HECHO local** (sin capas/escenas/cotas legacy aún — falta repro); seguimiento de PRs #3–#15 (11/13 mergeados) + issue #2.
3. **Lado IngePresupuestos** (sesión en aquel repo): `IFC_MAP` +RAILING/COVERING, preferir `Net*` sobre `Gross*`, mapear tags→partidas con el RAG "Sugerir partidas".
4. **Flathub** (definido, sin empezar): IngeTrazo + IngeCAD; capturas PNG (videos opcionales WebM <10 MiB sin audio); `appstreamcli validate` fatal; el punto duro es PySide6+Qt6+GL en Flatpak. App-ID: `com.ingetrazo.IngeTrazo`.
5. **Renders:** (2) glTF PBR + "Enviar a Blender" con plantilla → (3) sombras de sol en viewport → (4) AI render opcional. NUNCA motor fotorrealista propio.
6. **Kit restante:** Tape Measure + guías (T) · Eraser (E) por arrastre · Outliner · Texture Position.
7. **Motor (diferido, atacar cuando duela):** iceberg de solapes coplanares (~326/1000 secuencias, invisible al bench; pre-STL/IFC en serio) + los 4 xfail draw-side + rechazos del guard → resultados correctos. La salida de fondo es **A.3: identidad/attrs por REGIÓN a través del rebuild** (el rule-set de declaraciones llegó a su techo). Limitación conocida: `apply_rebuild` disuelve diagonales de usuario en planos tocados por push.
8. **Perf de fondo:** grupos de referencia como arrays NumPy puros (import DAE 27 s → objetivo archivos 80 MB) · edición de mallas 17k+ tris.
9. **Georref expansión:** **G5 curvas de nivel** (siguiente natural: ya hay `photomesh.height_at`) · DXF · G6 y KML/GeoJSON HECHOS. Aparte, lo que pide el flujo del puente: **plano de trabajo que siga al terreno** (hoy los tools dibujan en Z=0 fijo) y **cotas persistentes** como anotación reutilizando `geo_points`.
10. **v2:** planos profesionales (LayOut-equivalente), DWG/DXF (IngeCAD es el hermano 2D), IFC import, plugins públicos.

---

## Memorias de Claude relacionadas

En `~/.claude/projects/-home-sumaritux-ingetrazo/memory/`: filosofía/flujo unificado · casita dogfooding · AI-native · estrategia OpenSKP (`project-skp-import-strategy-openskp`) · skp2dae · sitio web · migración SketchUp · IngeCAD. Del hermano IngePresupuestos: `project_integracion_ingetrazo_flujo` · gotchas Wayland/PySide6 originales.
