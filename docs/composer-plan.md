# Compositor de láminas — plan C1→C4

> Imprimir el modelo 3D como plano, a escala exacta. El referente de UX es el
> **compositor de impresión de QGIS** (elección de Marco), no SketchUp LayOut:
> LayOut es una app aparte con formato propio (la trampa de scope); QGIS es una
> ventana del mismo programa cuyo lienzo es un `QGraphicsScene` — exactamente
> el framework que ya tenemos debajo. Definido el 2026-08-08.

## La idea en un párrafo

Una **Composición** es una o más páginas de papel (A4…A0) con **items**
encima. El item central es la **VistaModelo**: un marco que referencia una
**Escena** guardada (cámara + capas ocultas — ya existen, panel Escenas) más
una **escala 1:N**, y se rellena renderizando el modelo con cámara ortográfica
por el pipeline real del visor (`render_image`, que ya existe). Los demás
items (texto, cajetín, imagen) son 2D puro. Todo se exporta a PDF con métricas
físicas exactas (`QPdfWriter`) o a la impresora. Las composiciones viven
DENTRO del `.igz`, como QGIS guarda sus layouts en el proyecto.

## El mapeo QGIS → IngeTrazo

| QGIS | IngeTrazo | de dónde sale |
|---|---|---|
| Layout | `Composicion` (core/composition.py) | nuevo |
| `QgsLayoutItemMap` | `MarcoVista` — escena + proyección + escala 1:N | nuevo |
| Map theme | `SavedView` (core/saved_views.py) | ✅ existe |
| Render del marco | `viewport.render_image(w, h, overlays=False)` | ✅ existe (se le agrega alto explícito) |
| Página/export | `QPdfWriter` + `QPrinter` | Qt |
| Lienzo editor | `QGraphicsScene` en **milímetros** | Qt |
| Administrador de layouts | dock con lista de composiciones | C2 |

## La matemática sagrada (la única que no se negocia)

Unidades del modelo: **metros**. Unidades del lienzo compositor: **milímetros
de papel**. Para un marco de alto `H_mm` a escala `1:N`:

    alto_modelo_m  = H_mm × N / 1000
    cam.perspective = False
    cam.distance    = (alto_modelo_m / 2) / tan(rad(cam.fov_deg) / 2)
    # porque la proyección paralela de OrbitCamera deriva su semialto de
    # distance·tan(fov/2)  (core/camera.py:56)
    px = mm / 25.4 × DPI      # raster del marco, DPI = 300

y el aspect de la cámara se fija a `W_px/H_px` durante el render (restaurando
después — el render del compositor **nunca** deja rastro en el estado del
visor: cámara, aspect y visibilidad de capas se capturan y restauran en un
`try/finally`).

**DoD de escala, verificable por máquina:** un cubo de 1 m a 1:100 debe medir
**10.00 mm** sobre el papel. El test rasteriza el PDF exportado a 300 dpi y
cuenta píxeles con tinta de la arista: 10 mm × 300/25.4 = **118 px ± 1**. (La
casa ya aprendió que se mide el resultado final, no el paso intermedio.)

## Decisión: raster primero, HLR después

El marco se rellena **raster a 300 dpi** por el pipeline del visor (un A3
entero son ~3500×4900 px — nítido impreso; QGIS rasteriza igual cuando hace
falta). La eliminación de líneas ocultas **vectorial** (el look plano
delineado puro) es el único problema difícil del proyecto y es C4: proyección
de aristas + test de oclusión contra la malla. No bloquea nada: el flujo
municipal completo funciona con raster.

## Fases

### C1 — El corazón *(esta sesión)*
Ventana **Compositor** (menú Archivo), lienzo `QGraphicsScene` en mm con una
página (A4/A3/A2/A1, vertical/apaisada, sombra y margen), **un** `MarcoVista`
movible ligado a: vista actual, una escena guardada o una vista estándar
(planta/frente/…); escala de lista (1:50/100/200/500/1000 + libre); tamaño del
marco por spinboxes; botón *Exportar PDF*. Sin persistencia ni undo todavía.
- **DoD:** el test del cubo de arriba pasa (118 px ± 1 en el PDF); la ventana
  abre desde el menú y el marco muestra el modelo real; el estado del visor
  queda intacto tras cada render (mismo fingerprint de cámara/capas).

### C2 — Los items y la persistencia
Múltiples `MarcoVista` por página (planta + elevaciones + iso en una lámina),
items de **texto**, **imagen** y **cajetín** (rótulo: proyecto/autor/fecha/
escala/lámina — para el gremio es EL item), manijas de resize, guías con
snapping, administrador de composiciones (N por documento), **persistencia en
el .igz** y undo por Command (invariante de la casa: toda mutación por
Command).
- **DoD:** cerrar y reabrir el .igz conserva la lámina completa; una lámina
  A1 con 4 vistas + cajetín se arma sin tocar código.

### C3 — El estilo plano
Modo de render "técnico" del marco: fondo blanco, solo aristas (+ opción de
caras blancas), respetando planos de sección si existen. Escala gráfica como
item. Título automático del marco («Planta — 1:100»).
- **DoD:** una lámina imprimible que un colega no distingue de un plano CAD a
  primera vista.

### C4 — El lujo (no abrir antes)
HLR vectorial (aristas proyectadas + oclusión → líneas de verdad en el PDF),
**export DXF de las vistas → puente directo a IngeCAD** (IngeTrazo genera el
2D, IngeCAD lo firma e imprime), numeración/atlas de láminas.

## Gotchas conocidos que aplican acá

- `QWidget.grab()` no captura overlays QPainter; el compositor usa
  `render_image` que sí los pinta — pero **con alto explícito los overlays se
  omiten** (`overlays=False`): están calibrados al aspect del widget y
  saldrían corridos. Las cotas sobre la lámina son asunto de C3.
- La vista "planta" usa el preset `top` de `set_view` (pitch ~89°, no 90°) —
  evita la singularidad del lookAt con up=+Z. El error de escala por el
  coseno es 0,015 %: invisible bajo el ± 1 px del DoD.
- Wayland: el render del marco pasa por el mismo FBO propio del visor con su
  workaround de depth — no agregar otro camino GL.
