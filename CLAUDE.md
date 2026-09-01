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

## 📦 Estado actual (2026-08-31) — imágenes de referencia, Escala SketchUp, import CAD

Sesión larga de tres frentes (commits `aa43a2e`, `75e455d`, `4f4aec9`,
`c73cc84`, `76889df`); todo verificado contra archivos municipales reales.

- **Imágenes de referencia** (`Archivo ▸ Importar ▸ Imagen`): PNG/JPG como
  plano para calcar — display-only (invariante #4), en su capa `Images`,
  viaja DENTRO del `.igz` por el walker de texturas, da plano de trabajo y
  snap en sus bordes, y Mover/Girar/Escalar la tratan como entidad de
  primera clase. Clic derecho: tamaño exacto en metros y Bloquear (bloqueada
  no acepta clics pero SIGUE dando plano — el estado de calco).
- **Escala = SketchUp** (doc oficial): cajón amarillo con 26/8/2 grips
  (esquina=uniforme, arista=2 ejes, cara=1 eje), ancla opuesta o centro
  (Ctrl al toque), Shift = uniforme, VCB con factor / `a;b` por eje /
  absoluto con unidad / negativo espeja, re-tecleo en caliente. Funciona
  sobre suelto+grupos+imágenes mezclados. El flujo viejo ancla+referencia
  se fue; sus 4 pruebas se portaron conservando la intención.
- **Import CAD (D1–D3)**: DXF con ezdxf (nueva dep, MIT — la misma de
  IngeCAD) y DWG vía satélite `dwg2dxf` (porte del `dwg_bridge` de IngeCAD
  con sus dos remiendos: handles 0 y duplicados/LibreDWG#1356). Capas→
  grupos etiquetados, curvas con UN curve-id, bloques→componentes (42
  instancias/20 protos en el archivo real), 3DFACE/SOLID→caras + fusión
  coplanar, texto/cotas omitidos como SketchUp. **La unidad se sugiere
  midiendo el dibujo** (mediana del tamaño de entidad): la cabecera es un
  reclamo, no un hecho — Plaza Yanque declara mm y está en metros. UTM
  >100 km recentra solo (float32 del motor resuelve ~0,5 m a N=8,2M).
  Doble clic en `.dxf`/`.dwg` abre. Plaza Yanque DWG entero: 5,3 s.
- **Fuga del caché de texturas GL cerrada**: `Nuevo/Abrir` devuelven las
  texturas del documento anterior (`reset_texture_cache`) y `closeEvent`
  libera todas las familias — avisos "Texture has not been destroyed" al
  salir: 2 → 0. El gancho `aboutToBeDestroyed` solo NO alcanza (dispara
  cuando Python ya se desmonta).
- Método, otra vez: el bug del grupo llamado `'asrco'` (el bucle de bloques
  pisaba el parámetro `name`) lo cazó ÚNICAMENTE el DWG real — el sintético
  no tenía bloques. Y la sesión dejó regla nueva de sistema: un ayudante
  que el escritorio deba invocar no puede vivir en `~/.local/bin` (sandbox
  bwrap de GNOME 50 sin $HOME).

---

## 📦 Estado anterior (2026-08-28) — v0.3.7, componentes/texturas/colores

Sesión entera de dogfooding sobre la biblioteca. **Cada defecto lo reportó
Marco mirando la bandeja, y todos resultaron ser nuestros, no de los
modelos.** Lo entregado y lo aprendido:

- **Publicada la biblioteca en línea** (1510 modelos) en `ingetrazo.com`, vía
  los assets estáticos del Worker: gratis y sin coste de tráfico (la doc de
  Cloudflare es explícita), 3.021 archivos de un tope de 20.000 y el mayor de
  2,6 MB de un tope de 25 MiB. Vive en el repo de la web **ignorada por git y
  no por wrangler**: son datos derivados, se regeneran en 23 s (ver el
  CLAUDE.md de `web/`).
- **Un modelo llega como su fichero lo describe**: eje vertical, matriz del
  catálogo, talla declarada, coordenadas de textura y grupos de suavizado.
  Ver `8c3fc0a`. La lección de método: *un OBJ dice más de lo que estábamos
  leyendo, y adivinar donde el fichero afirma es lo que producía el desastre.*
- **El mapa de textura viaja con la geometría** al colocar/mover/girar/escalar.
  Estaba anclado a coordenadas del mundo y el mecanismo para reanclarlo ya
  existía (lo usaba pegar); simplemente no se llamaba.
- **427 texturas y 213 colores RAL**, ambos con su tamaño/nombre reales.
- **Bandeja: 21,6 s → 1,2 s** por pantalla de miniaturas (16 en paralelo, fuera
  del hilo de la interfaz, 40 filas por adelantado).
- **Tres bugs que se iban a la release y que solo cazó probar de verdad:**
  (a) Cloudflare devuelve **403 al User-Agent por defecto de Python** — la
  biblioteca en línea habría estado muerta para todos, y como el diseño
  devuelve lista vacía en vez de fallar, en silencio; lo destapó probar contra
  el sitio publicado en vez de contra una carpeta local. (b) `libX11` duplicada
  en el bundle (issue #6). (c) `resources/textures/library/` sin empaquetar.
- **Método, otra vez:** el arranque se alargó de 0,21 a 0,95 s al meter las
  texturas — trabajo que escalaba con TODO el catálogo para pintar secciones
  plegadas que nadie mira. Construirlas al abrir cada sección lo dejó en 0,14 s,
  **más rápido que antes de añadir nada**.

## 📦 Estado anterior (2026-08-25, tarde)

**v0.3.5 released 2026-08-25 — secciones + paridad + IA + la maratón de perf.** Decisión de Marco: las secciones salen (el dogfooding continúa sobre el release). Trae: **secciones S1–S5 completas** (+ section fill, globos de símbolo, toolbar), **batch de paridad F1–F5** (Flip, Crear componente G, Mano alzada, Pie, Equidistancia), **Asistente IA + AI Bridge MCP** (invariante #5 real), **import glTF/GLB nativo**, componentes/texturas de arranque, y la **maratón piscina.igz** (~13 cuellos: box select/siluetas/borrado vectorizados, zoom con ancla por pose + re-validación por proyección, previews congelados por VBO scratch para Move/Rotate/**Paste**, Merge Groups sin loose-mesh, **`Scene.bounds()` cacheado por versión** — el "no responde" del paste: corría 2×/hover en Python sobre 230k caras — y **paste O(1)**: el snapshot del clipboard es instancia identidad y cada estampado una hermana del proto; estampar 230k pasó de ~12 s a instantáneo). Gotcha nuevo: la cadena hover→`_world_from_pixel`→`_current_work_plane`→`_emit_coordinate` corre en CADA mouse-move sobre cielo/mapa base — todo lo que cuelgue de ahí debe ser O(1) o cacheado.

**📋 PLAN DE LA PRÓXIMA SESIÓN (fijado por Marco al cierre 2026-08-25, en orden):**
0. **✅ CERRADO 2026-08-26 (commit `fdeaad0`) — push dentro de grupo importado.** Medido en piscina.igz con la parrilla (Group 16, 3054 caras, 19 sólidos soldados en una malla): **110.6 s → 4.6 s los mismos 6 pushes (24×)** — inicio de drag 5.2 → 0.10 s, frame de preview ~17 → 0.46 s, commit ~17 → 0.61 s. La raíz era una sola forma repetida: trabajo que escalaba con la malla ENTERA del grupo para una edición que tocaba UN sólido. **Y salió un bug de fondo, no solo lentitud:** la paridad leía toda la malla, y un vecino **abierto** (una lámina suelta, la parrilla del asador) se cruza UNA vez → se leía como material → caras de un sólido real quedaban marcadas como particiones interiores por una lámina a un metro (63 marcas en el asador, 2 legítimas). Fixes: (a) **paridad por componente** — `orient_outward` juzga cada cara contra su propia componente conexa y `cap_rebuild.rebuild_plane` restringe sus consultas de material a la componente del plano, así ambos coinciden en el dominio (malla de una sola componente = bit-idéntico, el fuzz lo confirma); (b) **el stitch repara lo que su operación tocó** — la barrida de T-junctions de `run_stitch` era global, así que un push re-topologizaba geometría ajena (8 de 10 aristas partidas a un metro) y, como el preview revierte cada frame, lo rehacía en CADA movimiento del mouse; ahora `seedkeys` acota qué aristas pueden partirse; (c) `orient_outward(only=...)` acota el pase a las componentes de unas caras dadas; (d) el camino prisma difiere la orientación en frames de preview como ya hacía el de extrusión; (e) la barrida es un pase vectorizado (franja x + cascada y/z) en vez de bucle Python por arista; (f) `RebuildCache` memoiza normales/centroides/triangulaciones y el set de paridad empaquetado a través de los planos de un push (76k normales Newell por frame → ~6k). Geometría idéntica cara-por-cara en el sitio del push. Tests nuevos fijan ambos comportamientos y **fallan contra el código anterior** (`test_orient.py::test_nearby_open_sheet_does_not_mark_a_solid_face_interior`, `test_coplanar_merge.py::test_stitch_leaves_a_t_junction_outside_the_operation_alone`). Gotcha cazado en el camino: **hay DOS `_key`** — `core.topology._key` devuelve coordenadas redondeadas y `core.mesh._key` celdas enteras (×10⁴); `run_stitch` recibe las de topology, y confundirlas encogía la caja del seed 10⁴× (el filtro no seleccionaba nada y el T-junction test lo destapó).
0-ter. **✅ CERRADO 2026-08-26 (`380de73` + `7b468d1`) — el frame ya no re-sube el modelo entero.** Pregunta de Marco (SketchUp atenúa lo demás al entrar a un grupo, ¿está en IngeTrazo?, ¿mejora el rendimiento?): estaba a medias — la caja punteada sí, el picking ya acotado, pero el resto se dibujaba **y se re-subía** completo. Dos entregas: (1) **Cámara ▸ Resto del modelo al editar** con Normal/Atenuar/Ocultar (QSettings, default atenuar) — el atenuado es paridad SketchUp, el ocultar es además el modo rápido porque lo oculto no llega a los VBOs; para que el atenuado sea posible los búferes ahora ponen el contexto primero y el grupo editado último, `_visible_spans` acepta un `split` que nunca fusiona, y los tramos texturados llevan bandera de sujeto (se entrelazan por imagen, un offset no alcanza); los perfiles se saltan el contexto. (2) **`_upload_vbo`: subida incremental** — guarda las partes enviadas por búfer y re-manda solo el sufijo que cambió (los chunks son objetos cacheados → identidad; el bloque suelto cae a comparar bytes, memcmp, un orden bajo la transferencia que ahorra); búferes sobre-asignados 1.25× para que una cola que crece no fuerce realloc. **Medido en vivo con log aislado: primer paint `sync=1628ms` (frío), luego `sync=0ms` sin cambios y `sync=6–11ms` cuando los hay, contra ~197 ms antes; frames en régimen 4–6 ms.** El diagnóstico salió de medir, no de suponer: juntar los 25 MB de aristas en Python son 1,6 ms y la malla suelta de piscina está vacía, así que ni la concatenación ni un walk Python podían explicar los 197 ms — era la transferencia. **Gotcha de método:** el perf log juntaba todo lo que corriera sin distinguir proceso, y un racimo de syncs lentos pareció del build nuevo hasta que resultó ser la ventana vieja; ahora las líneas llevan `[pid]` y `$INGETRAZO_PERF_LOG` aísla una corrida (`3ce931b`). **Queda por validar con Marco:** el push DENTRO del grupo con el build nuevo (es la única medición que necesita mouse).
1. **Export .skp: arreglar las texturas** (guardó piscina como .skp, en SketchUp Web "las texturas salieron mal"). Primer paso: pedirle el `.skp` exportado + captura de cómo se ve; luego round-trip contra SketchUp Web como oráculo. Sospechosos: `skp_out.py` (uvw por cara / matriz texture→plane inversa), materiales colorizados, texturas compartidas, y el proto del paste O(1).
2. **✅ CERRADO 2026-08-26 (`35987b5`) — Import .skp: los componentes llegan como componentes.** Las definiciones colocadas UNA vez ya no se aplanan: toda colocación de nivel superior es prototipo+xform, así el grupo conserva sus ejes propios (la caja de selección tiene ejes reales en vez de deducidos) y Move/Rotate/copias toman los caminos O(1). Solo al nivel superior y solo donde no se pierde nada: un prototipo aplana su subárbol (no hay proto-en-proto), así que se rechaza un contenedor cuyos hijos ya son compartidos, y también los subárboles face-me o con capas (tienen que salir como grupos propios para seguir mirando a cámara y para poder ocultarse por capa). **El corpus fue lo que lo volvió honesto:** la primera versión pasaba ambas suites y aun así rompía dos cosas — tres archivos dejaban de importar (un payload de solo prototipos se leía como parse vacío y caía a skp2dae; arreglado en `formats/skp.py`) y seis perdían grupos, 47 en uno, porque los contenedores promovidos se tragaban a sus hijos compartidos. A/B sobre 25 `.skp` locales: grupos y caras idénticos en todos, instancias +1 a +32, y los tres que fallaban importan de nuevo. **Queda:** `Piscina Karen` (subárbol con capas) y `barp 1` (face-me + capas) siguen aplanados — llevarlos por instancia exige extraer los hijos etiquetados componiendo la matriz del prototipo.
3. Resto de la cola (detalle en los ítems de abajo): Ctrl+C 5.2 s del seto → compartir definición al copiar; P2 rebanada 2 (picks por rayo transformado, quitar arrays horneados por instancia); siluetas al GPU / pase de aristas (el nuevo top de la telemetría); dedup de protos al guardar .igz; parse del .igz (~8 s, hoy el piso del arranque frío); y **auditar el patrón que dio 3 bugs hoy**: helpers del viewport que asumen `mesh.Face` (`.loop`) y walks O(escena) dentro de handlers de eventos.

**🎯 Objetivos anotados para 0.3.8+ (pedido de Marco 2026-08-28, al cerrar la 0.3.7.1).**
Estado del código MIRADO antes de estimar; el orden es la recomendación, no el pedido.

**A. Baratos porque el motor ya lo soporta — caben en la 0.3.8**
1. **✅ Ocultar/mostrar aristas — HECHO 2026-08-31.** `HideEdgesCommand`
   (deshacible, restaura estados mixtos), Edición ▸ «Ocultar aristas» /
   «Mostrar todas las aristas» (todas = las del contexto de edición actual:
   sin modo "geometría oculta" una arista oculta no se puede clicar, así que
   "todas" es el inverso honesto), clic derecho con aristas, y **Shift+goma =
   ocultar el trazo** (gesto SketchUp). Lo no-obvio que pedía: el fingerprint
   del chunk NO veía `hidden` (contaba solo `soft`) — un toggle dentro de un
   grupo servía el chunk viejo; ahora lleva término sensible al índice
   (7º elemento; `_shift_chunk` y el digest de disco actualizados — el digest
   solo añade el término cuando ≠0 para no invalidar el caché existente).
   HLR/láminas ya filtraban. DIFERIDO: modo «ver geometría oculta»
   (punteado + clicable) y export del flag al `.skp` (el escritor openskp
   hoy es por cara, no por arista). Tests: `tests/test_hide_edges.py`.
2. **✅ Editor de estilos — HECHO 2026-08-31.** `StylesPanel` en la bandeja de
   Propiedades (entre Escenas y Materiales): combo de estilos (integrados +
   biblioteca del usuario), edición EN VIVO del `display_style` activo (modo
   de cara, aristas/perfiles/cielo/relleno + 4 colores), «Guardar estilo…» /
   Eliminar. La biblioteca vive en QSettings `styles/user` (JSON, mismo patrón
   que las fuentes de mapa custom, con `.sync()`); `core.style` ganó
   `user_styles`/`save_user_style`/`delete_user_style` y **`style_by_name`
   resuelve también la biblioteca** → los marcos del compositor pueden
   referenciar `style:<nombre de usuario>` (su combo los lista; se puebla al
   abrir el compositor, no en caliente). Un nombre integrado se rechaza al
   guardar (los presets son el vocabulario estable de las referencias).
   Sincronía en ambos sentidos vía `_sync_style_menu` (menú Cámara ▸ Estilo ⇄
   panel). No deshacible, como el panel de cotas. El `.igz` y las escenas ya
   llevaban el dict completo del estilo, así que un documento no depende de la
   biblioteca. Tests: `tests/test_style_editor.py`.
   **Del dogfooding del mismo día:** (a) `sky_color`/`ground_color` ahora son
   DATO del estilo (eran constantes del render — "no puedo cambiar el color
   del sky"); (b) **cielo y suelo con degradado** hacia bruma blanca en el
   horizonte (`_sky_gradient`, matemática pura testeable; color por vértice
   vía `_create_dynamic_color`, la línea del horizonte se deriva de los dos
   tonos); (c) lección de UX que costó dos iteraciones: **desactivar una
   muestra de color que "no se ve en este modo" fue peor** — Marco leyó "no
   puedo cambiarlo"; lo correcto es siempre editable + aviso en barra de
   estado de dónde se verá (`_color_hint`). Texturas de cielo/suelo tipo
   render: DIFERIDO a propósito — el suelo actual es quad de pantalla, no
   plano del mundo; las sombras reales dan más "render" por menos.
3. **✅ Ventana de configuración — HECHA 2026-08-31.** Ventana ▸ Preferencias…
   (`views/preferences_dialog.py`): General (idioma — mismo contrato que el
   menú, aplica al reiniciar; resto del modelo al editar — aplica EN VIVO por
   `set_edit_rest_mode`, el mismo camino del menú Cámara, y la marca del menú
   se actualiza), Importar (unidad sugerida OBJ/DXF — los diálogos siguen
   preguntando, esto es la respuesta preseleccionada; modo de coordenadas
   geo/UTM) y Asistente IA (las MISMAS claves `ia/*` que lee el diálogo del
   asistente al abrirse — sin duplicar lógica). OK escribe + `sync()`;
   Cancelar no toca nada. De paso: el submenú «Rest of model while editing» y
   sus tres opciones NO estaban en `es.json` (salían en inglés) — añadidos.
   Tests: `tests/test_preferences.py`.
   **Ronda 2 (cotejo contra las Preferences de SketchUp, pedido de Marco):**
   - **Auto-guardado** (General de SketchUp): `core/autosave.py` — slots
     `.igz` en el dir de datos del usuario (NO junto al documento: pCloud ha
     truncado escrituras ahí), uno por ruta absoluta + `untitled`. Invariante:
     **un slot existe solo entre un cambio y el siguiente guardado/cierre
     limpio** → slot en disco = sesión interrumpida; se ofrece recuperar al
     abrir ese documento (o al arrancar, para el sin-título). El timer no
     dispara con un botón del ratón apretado (guardar 283k caras a media
     arrastrada leería como cuelgue). Tests: `tests/test_autosave.py`.
   - **Copia de seguridad al guardar** (`nombre.igz.bak`, copiada ANTES de
     escribir — la versión buena anterior sobrevive a un guardado truncado).
   - **Invertir rueda** (Compatibility de SketchUp): `nav/invert_wheel`.
   - **MSAA configurable 0/2/4/8×** (Graphics): era un 4 fijo en
     `_ensure_scene_fbo`; cambiarlo desde Preferencias anula `_fbo_size` y el
     siguiente paint reconstruye el FBO. El fallback a 0 muestras se conserva.
   **DIFERIDO de SketchUp, con motivo:** editor de atajos (feature entera),
   click style de dibujo (es motor de herramientas, no preferencia), carpetas
   por defecto (Qt ya recuerda la última), plantilla/template y unidades →
   van con la ventana de inicio (0.3.9), colores de ejes/inferencias y editor
   de imágenes externo (nicho), buscar actualizaciones (política de red).
4. **✅ Escalar como SketchUp — HECHO 2026-08-31 (`75e455d`, sesión de la
   mañana).** Cajón amarillo con grips, ancla opuesta/centro, Shift, VCB por
   eje, espejo con negativo. Diferidos documentados en `tools/scale.py`
   (cajón alineado a ejes del componente; re-escalado global con Medir).
   Detalle en «Estado actual (2026-08-31)» arriba.

**B. La grande — ✅ SOMBRAS HECHAS 2026-08-31 (sesión entera de dogfooding con
Marco, pieza por pieza contra capturas de SketchUp):**
5. **Sombras con el sol real.** Lo que quedó construido y las lecciones:
   - **`core/sun.py`**: posición solar NOAA (tests pinneados a astronomía:
     equinoccio sale por el este; solsticio de junio en Arequipa, sol al
     norte a ~50°). `ShadowSettings` es DATO de escena (viaja en `.igz`);
     sitio = datum del modelo o Arequipa; zona = `round(lon/15)` u override.
     `daylight_minutes` para acotar el slider de hora a amanecer→atardecer
     (sin eso, una zona forzada dejaba el sol bajo el horizonte y "las
     sombras no aparecen" — SketchUp acota igual).
   - **Mapa de sombras** (`depth.vert/frag` + `_render_shadow_map`):
     profundidad EMPAQUETADA en RGB de un FBO común (sin fontanería de
     depth-texture), ortho ajustado a bounds+suelo, **independiente de la
     cámara** (orbitar/zoom lo reutilizan; clave = versión+sol+corte+bounds).
     Emisores: VBOs consolidados + instanciados SIN culling de cámara +
     billboards como quads **orientados al sol** con recorte alfa (la sombra
     del personaje no gira al orbitar) + **recortes con su trama** (la malla
     cocada proyecta tejido; las hojas de setos motean). **Vidrio: regla
     SketchUp — opacidad <70% NO proyecta** (ojo: `_tex_faces_count` incluye
     los runs translúcidos; el pase usa `_tex_opaque_count` + runs ≥0.7).
   - **Anti-acné, la saga completa** (tres intentos fallidos documentados en
     commits): bias constante NO alcanza; slope-bias del emisor por
     derivadas tampoco (clamp saturado en caras rasantes); la receta que SÍ:
     **PCF con corrección por plano del receptor** (Isidoro) — gradiente
     exacto por jacobiano inverso, cada tap compara contra el plano EN el
     tap. El moiré venía de los taps diagonales con gradiente diagonal.
   - **Sombreado por sol** («use sun for shading»): normal por fragmento con
     `cross(dFdx,dFdy)` (¡sin datos de vértice!), cara contra-sol = tono
     plano SIN consultar el mapa (mata todo artefacto residual), factor =
     `mix(dark, 1, clamp(ndl*1.5)*PCF)`.
   - **Suelo receptor = overlay**: el catcher en z=-0.005 pinta SOLO la
     sombra (negro translúcido, alfa=(1-dark)*(1-lit)) — pintarlo con color
     de suelo se veía como "un rectángulo oscuro en el piso" (Marco).
   - **UI**: dock desplegable Sombras (barra SketchUp: check, fecha dd/mm +
     slider del año con iniciales de meses, hora acotada a luz diurna con
     amanecer/atardecer, oscuridad, zona horaria, «Añadir localización…» →
     `pick_location` → datum del modelo). Cámara ▸ Sombras espejo.
   - **Los marcos del compositor renderizan con sombras** (mismo paintGL) →
     lámina de asoleamiento directa.
   - Kill-switch `INGETRAZO_NO_SHADOWS=1`. Caja negra `faulthandler` →
     `ingetrazo-crash.log` (un crash nativo en órbita quedó sin autopsia).
   - **DIFERIDO**: terreno/mapa no reciben sombra; face-me de malla no
     proyecta; calidad configurable (mapa 4096/PCF) como preferencia si se
     pide; reflejos = otro proyecto (agua planar factible; especular del sol
     barato ahora que hay normal por píxel). Previews arrastrados no mueven
     su sombra hasta soltar.
   - **PNGs de figuras saneados**: tinta interior con alfa a medias +
     recorte duro = pinholes (el eje verde se colaba punteado por la cara de
     Sumari); selladas a alfa pleno respetando huecos reales (codo-torso).

**C. Para después, y por qué**
6. **Oclusión ambiental (SSAO).** Ya renderizamos a FBO, así que la fontanería
   está. Pero es *pulido encima* de las sombras y comparte con ellas el pase de
   profundidad: hacerla antes es trabajo que habría que rehacer.
7. **⚠️ Elegir unidad de trabajo — MÁS HONDO DE LO QUE PARECE.** **No existe
   `core/units.py` ni un formateador de longitudes**: la app trabaja en metros y
   punto. «Elegir unidad» toca *todo lo que muestra o lee una longitud* — el VCB,
   las cotas, la barra de estado, las láminas, los importadores. Merece su propia
   release, no ser un desplegable de una ventana de bienvenida.
8. **Ventana de inicio con recientes y vista previa.** No hay lista de recientes
   ni miniatura guardada por archivo (habría que meterla en el `.igz` al guardar).
   La ventana es fácil; **lo caro es el punto 7, que Marco quiere dentro de ella**.
   Hacerla sin unidades es media ventana; con unidades, es la release entera.
9. **Anunciar el Asistente IA** (decisión de Marco, 2026-08-28). Estuvo MUERTO en
   todo paquete hasta la 0.3.7 (`core.ai` no entraba al bundle); ahora carga, pero
   **cargar no es funcionar**: probarlo de punta a punta con clave real antes de
   ponerlo en la web.

**🎯 Objetivos anotados para 0.3.7 (pedido de Marco 2026-08-27, al cerrar la 0.3.6.2):**
0. **⚠️ NVIDIA + X11: ARREGLO APLICADO EN LA 0.3.7 (`8d1b30c`), MITAD SIN VERIFICAR** — issue #6 de `jloveric`.
   El `.spec` excluye ahora `libX11.so.6`, `libX11-xcb.so.1` y `libxcb-glx.so.0`
   del bundle de Linux: vienen del anfitrión. **Verificado solo que NO rompe el
   caso que funcionaba** — paquete construido y arrancado aquí sobre AMD + X11,
   log limpio, sin error de GLX. **La mitad NVIDIA sigue sin verificar**: hay que
   probarlo con el eGPU antes de contestar el issue. Los otros trece `libxcb-*`
   se quedan (Qt los necesita y un anfitrión mínimo puede no tenerlos).
   Diagnóstico original, que sigue siendo el porqué: `qglx_findConfig: Failed to finding matching FBConfig` en tarball y AppImage; el mismo tag desde el fuente con PySide6 de pip sí abre. Verificado sobre el tarball PUBLICADO de la 0.3.6.2: el bundle no lleva Mesa (causa clásica descartada) pero **sí lleva `libX11.so.6`, `libX11-xcb.so.1` y `libxcb-glx.so.0` y NO lleva `libxcb.so.1`** — el driver GL del anfitrión resuelve por el libX11 del sistema mientras Qt pregunta por el del paquete. Mesa lo tolera, NVIDIA no. Arreglo propuesto: excluirlas del bundle. **SIN VERIFICAR** (la máquina de Marco es AMD + Wayland); él conecta un eGPU NVIDIA en la oficina y se prueba ahí antes de tocar el empaquetado y antes de contestar el issue. Observación suya y correcta: la prueba de humo de la CI usa `xvfb` (Mesa por software), por eso nunca lo iba a cazar.
1. **Iconos**: a Marco no le gustan los dibujados en `views/icons.py`. Pedido explícito para una release futura, no urgente.
2. **Texturas** (diferido desde el 26): el agua y el tronco de la palmera. Falta el 2º archivo de calibración — una textura colocada con "Posicionar textura" de SketchUp.
3. **✅ CERRADO 2026-08-28 (`8d1b30c`)** — el plugin `ai_assistant` no cargaba en el paquete: los plugins importan `core.ai` y `core.bim` en tiempo de ejecución, así que el análisis estático nunca los veía. Van a `hiddenimports`. **Y salió otro del mismo tipo, peor:** `resources/textures/library/` no se empaquetaba **nunca** — el `.spec` copiaba el manifiesto pero no las imágenes, así que en Windows la biblioteca de materiales salía **vacía**; el Flatpak copia todo `resources/` y por eso no se había notado. El paquete arranca ahora con el log limpio.
4. `skp2dae.exe` sigue adjuntándose a mano al release (vive sólo en la máquina de Marco). El flatpak ya no: desde el próximo tag lo arma `release-flatpak.yml`.
5. **⭐ EL RECTÁNGULO QUE SE DISUELVE AL VOLVER AL RAS — diagnosticado, intentado y REVERTIDO 2026-08-27.** Marco: dibuja un rectángulo en una cara, lo empuja hacia afuera y lo empuja de vuelta al ras — y el rectángulo desaparece, fundido en el muro. **Aislado pase por pase: tras `run_stitch` sigue ahí (7 caras); es `apply_rebuild` quien lo funde (6).** El reconstructor por plano vuelve a trazar las regiones desde las aristas y disuelve deliberadamente las costuras de la operación, que es lo que evita que cada push deje cicatriz. Su regla: una arista del **borde de la operación** (`op_rims`) puede disolverse, cualquier otra es estructura del usuario y sobrevive (`keep_segs`). **El rectángulo es las dos cosas a la vez**: al empujar una cara, el borde de esa cara ES por definición el borde de la operación, así que la regla no puede distinguir la línea que trazó Marco de la costura que dejó el push.
   **Intento medido y descartado:** "sólo puede disolverse lo que ESTA operación creó" (filtrar de `op_rims` las aristas que ya existían, vía las `before_edges` que `_mutate` ya captura). Arregla el caso de Marco —7 caras, el rectángulo de 3,0 m² intacto— y **rompe el motor: 39 tests rápidos y 6 secuencias del fuzz**, entre ellos `test_bump_pushed_flush_back_dissolves_to_clean_cube`, que pide **lo contrario**: un bulto hecho con un push ANTERIOR, empujado de vuelta al ras, debe disolverse y dejar el cubo limpio. Su contorno también "existía antes" de este push — lo creó el push anterior, no la mano del usuario. Es decir: **"antes de este push" ≠ "lo dibujó el usuario"**, y esa es justo la información que falta.
   **Lo que hace falta de verdad:** que la arista lleve su PROCEDENCIA (trazada por una persona / dejada por una operación). Hoy una arista son dos puntos y nada más. Es el mismo pendiente de fondo que ya está anotado como **A.3 (identidad/attrs por REGIÓN a través del rebuild)** y **A.4**; no es un parche, es darle memoria a la geometría.

**🎯 Objetivos anotados para 0.3.6 (pedido de Marco 2026-08-25):**
0. **🪆 GRUPOS ANIDADOS — ✅ OPCIÓN A HECHA 2026-08-26 (colocaciones anidadas como DATO), falta la edición por niveles.**
   **Lo cerrado (esto es lo que arreglaba el bug crítico de tamaño):** `Group.children` = colocaciones que el grupo POSEE, cada una con malla prototipo compartida + matriz local; se dibujan, se pican, se guardan y se exportan como parte de su padre — **un solo objeto para el usuario, por hondo que sea el árbol**. Piezas: `iter_placements`/`world_mesh` pliegan el árbol; `Viewport._placements()` lo expande a proxies ESTABLES (una malla, una matriz compuesta) para que render y picking no necesiten ningún caso especial y `owner` devuelva el clic al objeto de nivel superior; `Scene.placements()` para bounds/render/world_faces; jerarquía en el `.igz`; `skp_out` emite definiciones en post-orden (hijos antes que padres, la única orden que acepta el formato) con `add_instance` anidado; `_merge_equal_protos` funde prototipos de contenido idéntico (un .skp puede traer el MISMO material bajo dos ids, y eso partía las hojas del seto en dos prototipos gemelos de 4480 y 5120 caras). Invariante que sostiene todo: **un grupo con hijos es SIEMPRE instancia** (`Group.adopt`) — Move/Rotate componen `xform` y el camino por vértices se llevaría la malla propia dejando a los hijos atrás. `materialize()` (y por tanto entrar a editar el grupo) hornea los hijos y los suelta.
   **Resultado medido en piscina** (import → `save_skp`): **.skp 72,4 MB → 28,7 MB**, caras almacenadas **1 294 258 → 75 599** (17×), `.igz` 18,2 MB, caras del mundo idénticas (1 294 258), caja idéntica y área a −0,08 %. **Corpus A/B 25/25 con geometría idéntica** (la única diferencia era `-0.0` contra `0.0` en una cota, por componer dos matrices en vez de una).
   **⚠️ REGRESIÓN QUE DESTAPÓ EL DOGFOODING (Marco, 2026-08-26: "el arbusto cuando roto o muevo o copio tiene laj bastante").** No era lentitud: **el arbusto no se movía**. Los consumidores que tratan a un grupo como "su malla" leen `group.mesh`, y la malla PROPIA de un componente importado ahora está vacía — su geometría vive en las colocaciones. Medido: `begin_groups_preview([arbusto])` subía **0 aristas** a la copia de arrastre contra 406 368 antes, así que el arbusto quedaba congelado en su sitio (las cachés se congelan durante el arrastre) y saltaba al soltar. Lo que engaña de este bug: chunks, `_gather_instanced` y el índice de picking medían IGUAL O MEJOR que antes (45,8 ms contra 73,0 el frame de arrastre), o sea la telemetría de rendimiento decía que todo estaba bien.
   **Arreglado, cuatro sitios, todos por la misma causa:** (1) `begin_groups_preview` expande el subárbol con `_expand_placements` — sube 406 368 aristas otra vez y marca las 50 colocaciones como movedoras, si no los hijos seguían dibujándose por el paso consolidado; (2) `tools/rotate.py::_gather_copy_entities`, el fantasma de la copia al rotar, ahora recorre `iter_placements`; (3) `tools/select.py` — la caja de selección no alcanzaba al arbusto, y `_box_group_fast` caía al recorrido en Python de 1,15 M de vértices porque el chunk del grupo estaba vacío: ahora concatena los chunks del subárbol y sigue vectorizado (71 ms contra 57 antes, mismo veredicto); (4) `ExplodeGroupCommand` **perdía la geometría anidada** — explotar el arbusto habría dejado 0 caras en vez de 230 400. Los proxies quedan pinneados mientras hay una vista previa activa (soltarlos a media pasada crearía objetos nuevos que el preview ya no conoce). **Regla para lo que venga: cualquier consumidor que lea `group.mesh` de un grupo que puede tener hijos está mal; van `iter_placements` (core) o `_expand_placements` (viewport).**

   **DOS COSAS MÁS QUE DESTAPÓ EL DOGFOODING, las dos MEDIDAS contra HEAD:**
   - **Seleccionar el arbusto tardaba** (Marco). `_group_obb` construía una malla FUSIONADA de 230 400 caras para leer ocho esquinas: **23,6 s** con el anidado y **5,1 s ya antes** — trabajo de la forma equivocada desde el principio, la caja nunca necesitó una malla sino los PUNTOS. Nuevo `core.group.placement_points`: el array de cada prototipo se arma una vez y cada colocación es una multiplicación de matriz → **0,11 s** (215× / 46×). Verificado volcando las 85 cajas del modelo en ambas versiones: idénticas, desvío 0,000000 m. De paso `world_mesh` con hijos pasó de pegar cara por cara (20,8 s) a UNA pasada masiva `bulk_weld` (**4,19 s**, mejor que los 4,55 de HEAD) — y ahora los hijos conservan sus aristas suaves, que el append perdía.
   - **Caja fantasma al mover** (Marco: "queda líneas del cuadrado fantasma donde estaba inicialmente"). **Bug PREVIO al anidamiento**, verificado en HEAD: los dos caminos rápidos de traslación (`_shift_chunk`, `_shift_instance_entry`) desplazaban todos los arrays cacheados MENOS el `obb`, así que la caja se quedaba en el sitio viejo (medido en HEAD: el centro no se movía, 11,17 → 11,17 con un desplazamiento de 10 m). `_shift_obb` la lleva analíticamente: `lo`/`hi` son proyecciones sobre los ejes de la caja, o sea se corren la proyección de la traslación sobre cada eje, y el marco no gira. Coste 0 ms al mover; al rotar se recalcula (105 ms) porque ahí el marco sí puede cambiar.

   **⚡ CUELGUE AL BORRAR DENTRO DE UN GRUPO — bug PREVIO, cazado y arreglado 2026-08-27** (Marco: "hago doble clic en parrilla, selecciono algunos dibujos para borrar se cuelga"). **NO era del anidamiento: HEAD cuelga idéntico**, misma pila. Autopsia con `faulthandler`: `EraseSelectionCommand.do` → `heal_overlapping_faces` → `resolve_tjunctions` → `interior_vertex_on`. **Medido: borrar 60 caras dentro de la parrilla tardaba 206 s.**
   Y hay un **cliff** que explica por qué aparece "de golpe": `_HEAL_FACE_CAP = 3000` y la parrilla tiene **3054 caras** — con el grupo intacto el guard corta y no pasa nada; al borrar unas pocas baja a 2994, el guard deja pasar y se desata todo. Borrar 40 va instantáneo, borrar 60 cuelga.
   **Tres causas, las tres el mismo patrón (trabajo que escala con TODO el modelo para una edición que toca una parte):**
   1. `resolve_tjunctions` era O(cortes × A × V): `interior_vertex_on` recorría CADA vértice en Python y el bucle reiniciaba desde la arista cero tras cada corte — 6983 × 3993 = 27,9 M pruebas por pasada, **24,8 s la pasada**, repetida hasta 1000 veces. La versión vectorizada por lotes YA EXISTÍA dentro de `run_stitch` fase 1 (misma parrilla, mismo síntoma, sesión 2026-08-26) pero `heal_overlapping_faces` era un SEGUNDO sitio de llamada que nunca la recibió. Extraída a `topology.sweep_tjunctions(mesh, seedkeys=None)`; ahora **una implementación sirve a los dos** (el stitch la llama acotada al box de la operación, el heal sin acotar). → 0,59 s.
   2. Las dos pasadas O(caras²) del heal recalculaban `Face.normal()` (un Newell sobre QVector3D) dentro del bucle interno: **4,2 M cálculos de normal, 66 s**. Ahora el emparejado coplanar es UN producto punto vectorizado por cara contra toda la malla, misma tolerancia y mismos pares.
   3. `prune_collinear_orphan_edges` probaba cada arista huérfana contra TODAS (850 k llamadas al predicado). Ahora lleva broad phase por caja. Ojo al detalle de semántica: una huérfana ya podada no debe podar a la que estaba debajo — el bucle original leía la lista VIVA, así que hay que llevar un `gone`.
   **Resultado, A/B contra HEAD con huella canónica del resultado (caras + aristas + flags soft):** borrar 60 caras **206,36 s → 3,07 s**, borrar 200 **200,39 s → 3,04 s**, y las huellas son **idénticas** en los dos casos (`26f02edd44b2ac9d`, `6e81a17818a06bc8`). 67×, mismo resultado bit a bit. Lo que queda son 2,2 s de `orient_outward` (paridad por rayo), que es trabajo real.

   **🖱️ ZOOM CON LA RUEDA UN POCO MÁS PESADO — regresión mía, medida y arreglada 2026-08-27** (Marco: "parece que hay un pequeño laj cuando hago zoom, antes lo sentía más ligero"). El camino de la rueda en sí cuesta 0,1 ms (el foco va cacheado por pose de cámara); el coste estaba en el REPINTADO. `_gather_instanced` corre en cada frame y ahora recorre **411 colocaciones en vez de 89**, y por cada una re-derivaba elegibilidad (`_instanced_eligible` → chunk del prototipo), pedía el chunk y hacía el test de frustum en Python: **0,4 ms → 2,5 ms por frame**. Arreglo: QUÉ colocaciones son elegibles sólo cambia con la escena, así que el pool va cacheado por versión (+ una época de preview, no su tamaño: dos previews distintas del mismo tamaño colisionarían), y el descarte por frustum es UNA pasada NumPy sobre todas las cajas a la vez, el mismo test p-vertex. **→ 0,1 ms, mejor que los 0,4 de antes.** Verificado A/B contra la implementación vieja en 24 poses de cámara: selecciona exactamente las mismas instancias. Queda 1,2 ms por frame en el bucle de chunks (411 llamadas contra 90) — 0,7 ms más que antes sobre un presupuesto de 16 ms, y ahí sí es trabajo proporcional al número de colocaciones.

   **Lo que FALTA (2/3 de la lista original):** edición por niveles — pila en `begin_group_edit`, agrupar un grupo dentro de otro desde la UI, y el flujo de la banca de Marco. Hoy entrar a un grupo con hijos los hornea (SketchUp hace lo mismo al editar dentro de un componente, así que no es incorrecto, pero pierde el compartido de esa instancia).
   **Contexto original del pedido:** Su flujo en SketchUp: agrupa unas maderas, las mete en una banca, vuelve a agrupar. Y los componentes importados (`barp 1`) traen grupos adentro que hoy se aplanan. **Ya hecho (`ea16cf8`): agrupar con un grupo seleccionado AVISA en vez de agrupar a medias** — antes filtraba la selección a caras/aristas y dejaba el grupo afuera en silencio, o sea el resultado equivocado disfrazado de éxito. **Falta decidir la forma, dos opciones que Marco dejó para esta release:**
   - **(2) Anidamiento completo**: `Group` con hijos, jerarquía en el `.igz`, pila en `begin_group_edit` (entrar/salir por niveles), chunks y picking por nivel con transformaciones compuestas, e import que deje de aplanar (`_collect`). **Superficie medida: 70 lugares en 14 archivos recorren `scene.groups` como lista plana** — render, picking, guardado, exportadores OBJ/DAE/GLB/SKP, capas, BIM, HLR del compositor, puente IA. Riesgo si se hace a medias: los exportadores empiezan a perder geometría anidada en silencio.
   - **(3) Intermedio**: anidar en el modelo de datos y en la edición, pero que los exportadores APLANEN al escribir (que es lo que hacen hoy igual). Mucha menos superficie y destraba el flujo de la banca.
   **QUÉ SIGUE APLANÁNDOSE — censo de las 184 definiciones de piscina (pregunta de Marco 2026-08-26: "en SketchUp hay grupos con subgrupos, ¿revisaste que eso no se aplane?"). Respuesta honesta: PARCIAL.** Se comparte una definición cuando se REPITE; un subgrupo colocado una sola vez adentro todavía se aplana. Reparto de las caras que aún se duplican, sobre las 75 486 que escribimos:
   - **subárbol con etiquetas (8 defs, 10 410 caras)** — `Piscina Karen`, excluido por `_subtree_has_tagged`.
   - **repetida pero chica, <60 polys (28 defs, 9 839 caras)** y **ahorra poco, <400 (20 defs, 2 388)** — umbrales heredados del import DAE.
   - **anidada y colocada UNA vez (85 defs): 0 caras de coste.** No cuesta tamaño, pero el subgrupo deja de existir como objeto — es lo que arreglará la edición por niveles.
   - face-me (6 defs): 0 caras. Correcto que se extraigan.
   **Dos experimentos hechos y MEDIDOS, ninguno adoptado:**
   1. **Bajar los umbrales.** 60/400 → 12/40 → 1/1 da .skp 28,7 → 27,0 → 26,6 MB, pero los grupos de nivel superior pasan de 89 a 133 y a 157: parte el modelo en objetos que Marco no agrupó. Mal negocio.
   2. **Dejar compartir los subárboles etiquetados.** Da .skp **28,7 → 25,7 MB** y caras almacenadas 75 599 → 64 539, con el mundo idéntico y 89 → 80 grupos (los hijos etiquetados pasan a vivir dentro de su padre, como en SketchUp). **Pero rompe el ocultado por capa**: dentro de un prototipo, una instancia etiquetada que no es prototipo se aplana y PIERDE la etiqueta — que es justo lo que `_subtree_has_tagged` protegía. Compensarlo forzando a prototipo toda definición colocada con etiqueta arregla `Camada0` y `Top table` exactamente, y deja **una** diferencia: ocultar `Layer 0` (la etiqueta por defecto) tapa 1 152 caras más, porque los hijos sin etiqueta heredan la del contenedor. Defendible (es la regla de SketchUp) pero SIN verificar contra SketchUp — decisión de Marco, no se adoptó antes del release.
   `barp 1` (9 042 caras) seguirá aplanado igual: lleva face-me adentro, y un billboard necesita su lugar propio en el mundo por colocación.
   **✅ RESUELTO — la razón por la que esto era urgente, medida 2026-08-26 (pregunta de Marco: "¿por qué el .skp guardado pesa 80 MB si el original pesa 14?"):** el peso NO son las texturas (6,7 MB embebidos en el original contra 7,1 en el nuestro) — es **geometría duplicada por perder el compartido interno**. El original tiene **185 definiciones con 616 colocaciones**; el nuestro, **37 con 85**. Resultado: 324 349 registros de cara contra 59 845 (5,4×), y aristas y vértices en la misma proporción. La geometría del MUNDO es casi idéntica (1 319 022 caras contra 1 294 258): lo que se infla es la representación, porque el import aplana los subárboles anidados (`_collect`) y el export solo puede compartir lo que sobrevivió. De ahí también que SketchUp Web se ponga lento con nuestro archivo: 5,4× de geometría que dibujar sin instanciación que la agrupe. Es decir, el anidamiento no es solo comodidad de modelado — es lo que mantiene los archivos chicos y SketchUp fluido. Mitigación parcial sin anidamiento completo: el mismo content-hash del ítem 4 (dedup de protos al guardar `.igz`) aplicado al export `.skp`.
   **Lo que queda del 2× residual (28,7 MB contra 14,1), medido — ya NO es duplicación nuestra:** (a) **el escritor de openskp gasta ~82 bytes por (cara+arista) contra los ~38 de SketchUp**, con las texturas empatadas (7,11 MB contra 6,72) — es codificación, no geometría; (b) **la prueba de coplanaridad de openskp escala con el ANCHO DE LA CARA, no con la magnitud de las coordenadas**, y nuestros vértices son float32: una cara chica lejos del origen hereda el redondeo de un número grande y la rechaza — **15 516 de 75 486 caras** de piscina caen al fallback de triangulación (+18 446 registros de cara y sus aristas). Probado y DESCARTADO aplanar cada cara a su plano de mejor ajuste antes de escribir: arregla el test pero mueve las esquinas POR CARA, los vecinos dejan de compartir vértices y cada arista compartida se escribe dos veces (169 878 → 222 473 aristas, fichero 28,7 → 30,8 MB). El arreglo correcto es aguas arriba, en la tolerancia de openskp. (c) `Piscina Karen` + `barp 1` aplanados, arriba.
1. **Ctrl+C 5.2 s** en el seto de 230k (la copia profunda del snapshot). Candidatos: compartir la malla convirtiendo TAMBIÉN el original a instancia al copiar (la maquinaria F3/Make Component ya existe; `begin_group_edit` materializa al entrar), o copy-on-write.
1bis. **Import .skp: los componentes deben LLEGAR como componentes** (hallazgo de Marco 2026-08-25 con captura de SketchUp Web: los modelos del Warehouse de piscina — Ty, Piscina RiCAD, swimmers, parrilla, sombrilla — son DEFINICIONES de componente en el .skp y IngeTrazo los materializó como grupos clásicos). Causa probable: el proto-sharing del adaptador solo comparte definiciones REUSADAS (≥2 instancias); una definición de instancia única se materializa. Fix: importarlas como instancia (proto + xform) SIEMPRE — costo cero, y Move/Rotate/copias heredan los caminos O(1). Riesgo: exclusiones del proto-sharing (face-me, instancias taggeadas) — validar contra el corpus.
2. **BUG export .skp: texturas mal en SketchUp Web** (reporte de Marco con piscina: guardó .skp, lo abrió en SketchUp Web y "las texturas salieron mal"). Pedir el `.skp` exportado exacto + captura de cómo se ve; sospechosos: `skp_out.py` uvw por cara (matriz texture→plane inversa), materiales colorizados/texturas compartidas, y el proto compartido de 230k del paste nuevo.
3. **Más perf — meta medible: paridad de fluidez con SketchUp en piscina.igz limpio (benchmark de Marco 2026-08-25: "SketchUp va 2× en general"). PLAN COMPLETO POR FASES: `docs/performance-plan.md`** (P0 telemetría de frame → P1 frustum culling por chunk → P2 GPU instancing de componentes → P3 latencia de input → P4 async de stalls → P5 kernels nativos hoja SOLO con evidencia; explícitamente NO: rewrite C++/Rust, cambio de renderer, LOD todavía). El 2× no es fps crudo (pintamos 4–22 ms con la escena limpia) sino LATENCIA de interacción + falta de culling: (a) **frustum culling por bbox de chunk** (hoy se dibuja todo siempre — la ganancia grande que falta); (b) recortar la latencia gesto→frame (hover ~25–40 ms en Python, pick de zoom 25 ms al iniciar gesto, snap); (c) upload de teselas fuera del hilo (el `paintGL 100ms` del zoom); (d) primer paint frío ~11 s (chunk 230k 7.3 s + sync_edges + pick_index) → ¿perezoso o en hilo?; (e) confirmar que el 149% CPU en reposo no vuelve tras sesión larga. Techo honesto: Python no iguala C++ a 1M+ caras; el objetivo es el caso real (200–400k).
4. **Dedup de protos al guardar `.igz`**: las copias pegadas ANTES del paste O(1) pesan geometría completa (piscina: 2 duplicados del seto = +66 MB y 460k caras extra en escena). Al guardar, content-hash de mallas de grupos idénticas → UN proto + N instancias (recupera archivos viejos sin tocar la escena). Diagnóstico medido 2026-08-25: la escena con 5 setos = 1.2M caras → paints de 37-40 ms; el lag "tras suspender" era solo eso (GPU bostea bien, CPU 0%).

## 📦 Estado anterior (2026-08-25)

**v0.3.4 released 2026-08-25 — el release del dogfooding** (decisión de Marco: salió SIN secciones; secciones pasan a ser el gate de 0.3.5). Una sesión real de modelado → cacería de ~15 bugs/features, todo contra la documentación oficial de SketchUp: **(1) copy/paste completo** (grupos + componentes como hermanas del proto, attrs/texturas viajan y se re-anclan, preview SÓLIDO con colores y texturas siguiendo al cursor, pegar estampa UNA vez y vuelve a Selección); **(2) transportador y Rotar en paridad SketchUp** (base compartida `ProtractorBase`: inferencia de plano por hover con disco coloreado por eje, flechas/Shift para plano, marcas 15° con imantación cerca/0.1° lejos, pendiente `3:12` en el VCB, re-tipeo caliente tras commit; Rotar además Ctrl=copia y arrastre-desde-centro para eje de plegado); **(3) cursores de herramienta** (lápiz con insignia para dibujo, hotspot en el punto de acción, órbita/pan/lupa en navegación); **(4) ESTILOS** (`core/style.py`, Cámara ▸ Estilo: 7 presets SketchUp; escenas los recuerdan, `.igz` los persiste, y el composer elige estilo POR MARCO tipo LayOut vía `viewport.style_override`); **(5) fixes de fondo**: caja de selección toma grupos y guías, transforms sobre TODA la selección mixta (gather_targets multi-grupo), guías sobreviven la perspectiva (`_clip_segment_front`) y son seleccionables/borrables, Esc suelta el axis-lock, texturas planares ya no "nadan" en el preview. Gotcha nuevo: **QVector3D(0,0,0) es FALSY** en PySide6 — jamás `punto_a or punto_b`. openskp → upstream (ver abajo).

## 📦 Estado anterior (2026-08-21)

**v0.3.3 released 2026-08-21 — SketchUp round-trip completo.** Lo que estrena: **(1) registro de materiales completo** (track 0.4, 5 tajadas — identidad al pintar, re-estampar, metrado por material, exports con nombres, bandeja end-to-end); **(2) export .skp NATIVO** (`formats/skp_out.py` sobre `openskp.create`: grupos, componentes compartidos, huecos, material default, identidad de materiales); **(3) la cacería legacy**: corpus real completo de Marco 186/186 — MERGEADO upstream (PRs #194 aprobado tras review de fondo + #199 cherry-pick de Ahsan con autoría preservada); **(4) cotas y textos guía en AMBAS direcciones** (método Rosetta: mkdim/mktext con la SketchUpAPI.dll real; el SDK solo crea textos de PANTALLA — la gramática del texto guía real salió de casa bueno; PR upstream #203 enviado) — import a `Dimension`/`TextLabel` con posición de etiqueta, y export cableado en `_emit_annotations` (proyección del offset vectorial al escalar .skp); **(5) ciclo de vida completo del texto guía en la app**: pick por glifos (prioridad sobre geometría), mover con ancla clavada (`MoveTextLabelsCommand`, preview vivo), editar con doble clic, Supr (cazado: `DeleteTextLabelsCommand` sin importar desde el commit original), selección por caja; **(6)** fix drape-detection solo-legacy y Solid Inspector plugin. Pins de CI/requirements → **UPSTREAM desde 2026-08-24** (#203 mergeado el 2026-08-22; requirements = `iamahsanmehmood/openskp@main`, workflows pineados al SHA `f79e9b18` que incluye los follow-ups #204–#219 de Ahsan; suites completas + corpus smoke verdes contra ese SHA). Gotcha recurrente (4×): `pkill -f`/`pgrep -f` con patrón que matchea el propio shell invocante (exit 144) — usar `mai[n].py` y matar por PID.

## 📦 Estado anterior (2026-08-08)

**v0.3.0 released 2026-08-08** (tag en `main`, CI Windows + `skp2dae.exe` re-adjuntado): **el release del compositor de láminas** — composer C1–C5 completo (marcos a escala exacta, HLR vectorial, PDF/atlas, DXF a IngeCAD, cotas ancladas al modelo con estilos, formas con polígono/radio/colores, cajetín editable multi-columna, orden Z + bloqueo, zoom QGIS con 100% = tamaño real), G6 fotogrametría, UTM WGS84 en la UI de terreno con selector de marco de coordenadas y pin-origen explícito, fix del deadlock de import .skp e instancia única. Pre-release: review de 5 hallazgos verificados y corregidos (crash por rebuild mid-placement, guard en píxeles obsoletos, captura de re-anclaje, alt al mover origen lejos, clamp de líneas), suites completas verdes (1076 rápidos + 796 slow). Pin de openskp en CI avanzado a la cabeza del fork.

**v0.3.2 released 2026-08-18 — Extensiones.** Tag + instaladores Windows/Linux por CI verdes, `skp2dae.exe` re-adjuntado (ojo: a v0.3.1 se le olvidó), README/CONTRIBUTING puestos al día (What works today ganó capas/escenas/BIM+IFC/georef/composer que seguían en Planned; CONTRIBUTING ganó Tests and CI + Writing a plugin y el folder layout real). Detalle del sistema: el motor prometido por `docs/plugins.md` existe — menú **Extensiones** con descubrimiento en runtime (`core/extensions.py`: carga por ruta vía `app_root()`, funciona empaquetado; un plugin roto = entrada ⚠ deshabilitada, jamás impide arrancar; solo registra tools *definidos* en el plugin; atajos tomados se deniegan). Dos plugins de referencia empaquetados (`plugins/*.py` en el `.spec`): **Info del modelo** (materiales por `attrs`, BIM vía `collect_objects`, `loose_mesh`) y **Consola Python** (Ctrl+Shift+P; cada ejecución = un `SnapshotImport` por `viewport.history` → Ctrl+Z/dirty/redibujado, rollback entero si falla, sin entrada de undo si solo inspecciona). Origen: PRs #1–#3 de Ahsan Mehmood (openskp), consolidados y corregidos en PR #4 (asumían el modelo de datos de SketchUp); commits con su coautoría; 33 tests. **CI en PRs** desde entonces (`ci.yml`: suite rápida en cada pull request). Extension Manager `.itx` propuesto por Ahsan: pospuesto a post-0.5 (API inestable en 0.x). Gotcha de tests: cerrar un `MainWindow` sucio bloquea offscreen (QMessageBox modal de `closeEvent`) — setear `_saved_version` antes de `close()`.

**v0.2.4 released 2026-07-26** (tag `v0.2.4` + CI Windows verde + `skp2dae.exe` re-adjuntado desde v0.2.3): **`.igz` autocontenido** (texturas adentro del documento) + el import `.skp` deja de crear carpetas junto al archivo del usuario; arrastra además todo lo de la sesión 2026-07-24 (capas, escenas, cotas lineales, doble clic para abrir `.skp`, import sin congelar la ventana).

**v0.2.3 released 2026-07-22** (tag + binarios Windows por CI + `skp2dae.exe` re-adjuntado; instalado en la PC del usuario vía `scripts/install_desktop.sh`): **import .skp NATIVO puro-Python de todas las eras** — el build de Windows instala nuestro fork openskp (pineado por SHA en `build-windows.yml`; actualizar el SHA cuando avance la rama `ingetrazo` del fork) con hiddenimports en `ingetrazo.spec`; el fork hizo lazy trimesh/shapely (parse solo necesita numpy). El usuario lo usa como programa normal; las sesiones suelen arrancar con reportes de uso real.

**Sesión 2026-07-24 — fidelidad de import .skp (todo pusheado, fork SHA `3c85b4d`):** se cerraron 3 de los 4 pendientes que quedaban para el "100% fiel a SketchUp": **(1) capas/etiquetas** (asignación por entidad + visibilidad, ambas eras — se llaman **Capas** en la UI, decisión de naming CAD-first), **(2) escenas** (SavedView: cámara + capas ocultas por escena, panel en la bandeja, .igz, import VFF), **(3) cotas lineales** (entidad `5BCC`, extremos resueltos a mundo vía transformación de instancia; validadas con el expediente técnico real). Queda del set original: **texto/etiquetas** (falta repro con entidades Text) + jerarquía de grupos anidados. Método de RE de esta sesión: calibrar contra los `scene_thumbnails/*.png` embebidos en el propio `.skp` (ground truth interno cuando skp2dae/DAE no sirve de oráculo).

**El modelador está MUY completo:** dibujo (línea, rect, rect rotado, círculo, polígono, arcos ×4, offset, sígueme, texto 3D), push/pull robusto con **guard de hermeticidad grado-BIM** (nunca commitea un sólido roto; ops ambiguas se rechazan fail-safe), move/rotar/escala, grupos (v2: entrar con doble clic) + **componentes/instancias compartidas** (proto + xforms, O(1) transformar), materiales + texturas SketchUp-compatible (proyección planar + UVs afines por cara), pintar (B) con eyedropper, **Invertir caras**, cotas + texto guía, capas, **escenas** (SavedView: cámara + visibilidad de capas, panel en la bandeja, .igz, import .skp), bandeja lateral, face culling (dorso azul-gris, color de estilo del archivo), aristas soft/superficies curvas/profiles, **transparencias** (cutout con dither Bayer + materiales translúcidos con pase blend), zoom/zoom ventana, UI bilingüe (`tr()` + `es.json`).

**I/O:** `.igz` (JSON versionado, protos compartidos; **con texturas = contenedor ZIP autocontenido** — ver abajo) · import **`.skp` directo** (ver abajo) · **export `.skp` NATIVO** (2026-08-19/20, `formats/skp_out.py` sobre `openskp.create` upstream — PR #5 de Ahsan + follow-ups: material default para caras sin pintar, grupos → `add_group`, instancias con proto compartido → UNA definition + N `add_instance` (matriz = inversa exacta de `skp_openskp._matrix`, round-trip probado), huecos como inner loops; billboards face-me excluidos como en OBJ/DAE; validado con plaza Yanque 1039 grupos/300k caras) · import/export `.dae` COLLADA (export con **geolocalización** para asoleamiento) · import/export OBJ · export STL, **glTF/GLB** (PBR + geolocalización), imagen hi-res del viewport · IFC4 export a mano (STEP sin deps). **Dependencia openskp: upstream `iamahsanmehmood/openskp@main` desde 2026-08-19** (todos los parches del fork mergeados allá; fork `tuxiasumari/openskp` = archivo; SHA pineado en build-windows.yml/release.yml). **Cacería legacy 2026-08-19/20: el corpus REAL completo de Marco (186 .skp únicos 2015-2026, <50MB, pCloud) parsea 186/186 con la rama `tuxiasumari/openskp@fix-legacy-bugs`** (PR upstream #194, 6 commits: cotas/textos con refs escapadas y forward, color-by-layer texturizado, CImage, atributos Length/Point3d, índices MapObject quemados con traducción por tramos, separadores de capas v20 + filler tras decl, colas de líneas guía auto-calibradas por build). El venv local corre esa rama hasta que Ahsan mergee — entonces: mover requirements/pins a upstream y reinstalar. Detalle completo en la memoria `project-openskp-legacy-hunt`. Fix adaptador propio: detección de drapes solo en VFF (2aebc44 — en legacy manda el flag FTC bit 1; `model.version` es STRING "{18.0.16975}"). Repros de la cacería en `../probar-sketchup/` (untracked).

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
- **`Signal(dict)` en conexión encolada COPIA el payload** (lo marshalla a QVariantMap según el contenido): el slot recibe OTRO dict, setea el `threading.Event` copiado y el hilo que espera muere por timeout. Usar **`Signal(object)`** para pasar la referencia PyObject (cazado en el puente IA 2026-08-25; una sonda mínima pasaba de chiripa porque un Event solo no es convertible).
- **`signal.connect(lambda…, Qt.QueuedConnection)` sin objeto receptor** ejecuta el slot en el hilo EMISOR — Qt no tiene dónde encolarlo. Síntoma: "QObject::killTimer: Timers cannot be stopped from another thread" al tocar el diálogo de progreso. Hay que conectar a un **método enlazado** de un QObject del hilo de la UI; PySide6 NO acepta la forma de 3 argumentos `connect(contexto, slot, tipo)`. *(`_parse_skp_threaded` tenía este patrón y el 2026-08-08 pasó de warning a DEADLOCK total antes del primer paint — "doble clic en .skp y no abre nada"; arreglado con un QObject relay.)*
- **`QImageReader` rechaza imágenes de más de `allocationLimit()`, 256 MB por defecto**, con un error de "sin memoria" engañoso; hay que ponerlo a 0 y restaurarlo. Y **`setScaledSize` NO evita decodificar un PNG entero** (medido: 7,4 s y 2,5 GB de pico igual con y sin), de ahí la caché de atlas.
- **Un error en Z es INVISIBLE en vista superior.** El mapa base estuvo 1804 m bajo tierra y todas las comprobaciones de encaje en planta salían perfectas. Verificar siempre en vista frontal/lateral además de la superior.
- **`SceneDatum.geodetic_to_local(lat, lon)` sin altitud significa "sobre el plano de referencia"** (Z local = 0), no a nivel del mar. El default de 0.0 metros absolutos hundía todo lo que no lleva elevación propia en cuanto el datum tenía `alt` (teselas del mapa, alineamientos KML).
- **`capture_state` NO sirve para copiar mallas** (preserva identidad y aliasa); copiar = add_face/add_edge profundo.
- **`orient_outward` y glifos:** el probe de centroide falla en caras cóncavas sin huecos — los windings del texto 3D se fijan analíticamente; no tocar el probe.

---

## 🎯 Pendientes (por prioridad tentativa)

0pre. **CAD / imágenes / Escala — flecos de la sesión 2026-08-31:**
   - **Empaquetado DWG (lo primero que duele en release):** `vendor/libredwg/bin/dwg2dxf` está FUERA de git (copiado del build de IngeCAD, estático); hay que meterlo al manifest del Flatpak y al instalador de Windows, o la release tendrá DXF pero no DWG. Registrar también los MIME `.dxf`/`.dwg` en `install_desktop.sh` para que el doble clic funcione desde Nautilus.
   - Import CAD diferidos (documentados en `formats/dxf_in.py`): sharing anidado de bloques (hoy los INSERT internos se explotan al proto), opción «aplanar a Z=0», contornos de HATCH como bordes.
   - Escala diferidos (documentados en `tools/scale.py`): cajón alineado a los ejes propios del componente (hoy ejes del mundo), y re-escalado global con Medir (Tape Measure).
   - Imágenes, siguiente natural (NO urgente): control de opacidad para atenuar el escaneo mientras se calca.

0. **⭐ SECCIONES estilo SketchUp — S1–S5 RELEASED en v0.3.5 (2026-08-25; el dogfooding continúa sobre el release).** Todo contra la doc oficial ("Slicing a Model to Peer Inside"): entidad `core/section.py` (uid estable + nombre/símbolo), UNA activa por contexto, colocar la ACTIVA (SketchUp), herramienta con inferencia por hover + Shift + flechas (Up=Z/Right=X/Left=Y/Down=cara) + diálogo nombre/símbolo, clip por `gl_ClipDistance` gateado a los pases de geometría (cielo/ejes/terreno/previews intactos), **aristas de corte gruesas** (plano∩triángulos vectorizado sobre `tri_v0/e1/e2` del pick index, quads en el plano con ancho ~px, nudge al lado recortado), picks/snaps/oclusión filtran lo oculto (`_active_cut`), Move/Rotate/Supr/doble-clic (toggle activo)/menú contextual (Invertir/Corte activo/Alinear vista), toggles Cámara ▸ Planos/Cortes de sección, `.igz` + SavedView recuerdan la sección activa + toggles, y **HLR clipea + añade las cuerdas de corte** (`clip_to_section`) → plantas/cortes reales en láminas. DIFERIDO documentado: section fill + Troubleshoot, Crear grupo desde corte, cortes por contexto de grupo, import .skp de section planes, export Section Slice DWG. Plan original por fases (referencia histórica):
   - **S1 — Núcleo + corte visual:** entidad `SectionPlane` (`core/section.py`: origen + normal + `active` + nombre/símbolo; máx. una activa por contexto, como SketchUp), `Scene.section_planes`, y el corte en render vía **`gl_ClipDistance`** en `resources/shaders/basic.vert` (UN solo par de shaders para todo el render — verificado) + `glEnable(GL_CLIP_DISTANCE0)` + uniform vec4 del plano; toggle "Mostrar corte". Cuidado: el clip aplica a caras, aristas, chunks de grupos, instancias y silhouettes (mismo programa ✓); billboards y overlays QPainter (cotas/textos) decidir si se cortan (SketchUp: sí a geometría, no a UI).
   - **S2 — Herramienta + comandos:** tool de colocación estilo SketchUp (preview del plano alineado al plano/cara bajo el cursor usando `tool.work_plane`/`plane_axes`, clic = colocar), todo por `Command` (colocar/activar/voltear/mover/borrar, undo completo); pick del plano por su marco (esquinas), mover/rotar con los tools existentes; Supr. Picks: filtro por dot-product NumPy sobre el índice existente cuando hay sección activa (no pickear lo oculto).
   - **S3 — Aristas de corte:** intersección plano×triángulos vectorizada sobre los arrays que YA guardan los chunks (`v0/e1/e2`) → segmentos gruesos color de estilo (SketchUp classic); cachear por (plano, chunk rev). Relleno del corte (fill/hatch) DIFERIDO a después del release si estira.
   - **S4 — Persistencia + escenas:** `.igz` (SectionPlane serializado; formato versionado como siempre) + **`SavedView` guarda la sección activa** (escenas de SketchUp la recuerdan → plantas/cortes por escena). Import `.skp` de section planes: pedir repro a Marco, decodificar el TLV si aparece — opcional para el release.
   - **S5 — Composer (el porqué del track):** el corte activo respeta en HLR/`core/hlr.py` (clipping de triángulos y aristas antes de la proyección) → **cortes y plantas reales en las láminas**. Validar con la casita/expediente real: planta = sección horizontal + Top+Parallel.
   - DoD: dogfooding con archivo real (casita), suites verdes, app instalada en laptop (ya corre el repo vivo). Bump a 0.3.4 en `core/version.py` al taggear.
0bis. **Imports pesados rápidos (track CERRADO en 2 tajadas 2026-08-21, quedan flecos).** Medido en `plaza toros puquina.skp` (80 MB, 388k caras): total ~50 s = 10 s parse openskp + **~30 s adaptador `skp_openskp.py`** + ~10 s construir escena. El cuello es NUESTRO adaptador, no la librería — C++ no es la respuesta. **Primera tajada HECHA (2026-08-21): 50 s → 19 s** (parse 10.2 + adaptador 4.5 + escena 4.2); Yanque legacy 2017: adaptador 13 → 7 s. Lo que era: (1) `fit_uv_affine` buscaba el par de aristas más estable en O(n²) con bindings QVector3D — 24.7M `crossProduct`, 30 de los 37 s del adaptador; ahora |a×b|² = |a|²|b|²−(a·b)² en floats puros (NumPy solo para polígonos grandes, float64 — el golden diff en 3 archivos reales da payload idéntico fuera de `uvw` y UVs por vértice a ≤0.012 salvo UN sliver degenerado de 15 mm²); (2) `mesh._key` a celdas enteras (31M `round()` → 8M; los probes de frontera son ±1 sin redondeo); (3) import de `fit_uv_affine` izado fuera del camino por-cara (shiboken feature_import por llamada), `_plane_basis`/`_positioned_uvs`/`_bake_uvs` en float puro, `_soft_edge_segments` cachea pares marcados por definición. **Segunda tajada HECHA (2026-08-21) — arrays NumPy en la construcción:** puquina 19 → **17.2 s** (adaptador 3.2 + escena 3.8), Yanque legacy 23 → **20.5 s**, y **abrir un `.igz` grande 8.1 → 6.7 s**. Piezas: (1) `Mesh.bulk_weld`/`add_edges_welded`/`add_faces_welded` — welding vectorizado con **paridad exacta** con el camino secuencial (el sondeo de celdas frontera se repite por-punto solo en celdas candidatas; float32-cuantizado como QVector3D; `tests/test_mesh_bulk.py` lo fija; oráculo byte-idéntico del `.igz` para el loader); umbral ~1 000 esquinas — grupos chicos siguen secuencial (1 036 grupos chicos de Yanque pagaban el costo fijo NumPy); (2) adaptador emite **listas planas** (geometría local cacheada por defn + un matmul float64 por placement — ya no hay QVector3D ni `.map` por esquina; el payload cuantiza float32 para que el weld calce); (3) `igz._load_mesh` bulk + el walker de texturas ya no desciende a coordenadas/aristas (11 M nodos → gratis); (4) **GC off durante cargas masivas** (skp/igz/dae/obj — el GC generacional re-escaneaba el heap creciente: −1.8 s solo en Yanque); (5) fix de fidelidad: el matching de soft edges ahora resuelve por VÉRTICE soldado (misma tolerancia del weld) — recupera **5 715 flags soft** que el matching por celda redondeada perdía en puquina (y quita 10 falsos positivos). Decisión de diseño: se descartó el grupo "puro arrays sin Mesh" (los picks guardan objetos `Face` vivos, ~40 consumidores — multi-sesión); lo vectorizado es la CONSTRUCCIÓN del Mesh, consumidores intactos. Queda del track: parse openskp 10-12 s (no nuestro), guardar `.igz` ~7.8 s (`_face_json` + json.dumps), primer chunk build del viewport (sin medir), y adoptar bulk en el import DAE (hoy solo lleva el guard de GC).

0ter. **⭐ PARIDAD SketchUp de herramientas (plan 2026-08-25, pedido de Marco: "igual a SketchUp"):**
   - **F1 — Equidistancia (HECHO al armar el plan):** renombrar "Desfase" → "Equidistancia" (el nombre de SketchUp es; F ya coincide).
   - **F2 — Voltear (Flip):** la herramienta Flip de SketchUp 2023+ (investigar doc oficial): selección → tres planos translúcidos rojo/verde/azul, hover resalta, clic voltea por ese plano; Ctrl = voltear una COPIA. Además entradas de menú contextual "Voltear a lo largo de ▸ rojo/verde/azul" (clásico). Comandos undoables; grupos/instancias/selección suelta/mixta (instancias: espejar el xform; ojo gotcha .skp "instancias espejadas intercambian lados del material").
   - **F3 — Crear componente (G):** convertir selección en DEFINICIÓN (proto en coords locales, origen = esquina del bbox) + instancia con xform — la maquinaria de protos compartidos ya existe entera (copy/paste ya comparte, .skp round-trip ya escribe UNA definition + N instancias). Diálogo nombre/descripción como SketchUp; "Hacer único" en menú contextual (materialize ya existe); Polígono cede la G (en SketchUp no tiene atajo).
   - **F4 — Mano alzada (Freehand):** flyout de Línea en SketchUp; arrastre muestrea puntos (umbral px + simplificación RDP), suelta = polilínea con curve id compartido (selección de contorno entero como círculos) + detect_faces al cerrar.
   - **F5 — Pie + curvatura de cuerda:** herramienta Pie (= Arco por centro que CIERRA la porción con los dos radios y cara), y verificar/completar el VCB del arco 2 puntos (tipeo de comba/bulge, sufijo "r" = radio como SketchUp).
1. **⭐ TRACK SIGUIENTE RELEASE — EJES (Axes tool) estilo SketchUp:** mover/reorientar los ejes del dibujo (origen + rotación). NO es una herramienta suelta: snap engine completo, bloqueos de flecha, colores de inferencia, VCB (coordenadas en el marco activo), rejilla/ejes dibujados, y menú contextual del eje (Colocar/Alinear vista/Restablecer). Investigar doc oficial del Axes tool; plan por fases estilo secciones; persistir en .igz; ¿escenas recuerdan ejes? (verificar en SketchUp). Gate tentativo de 0.3.6.
2. **Import .skp — completar el "100% fiel" (activo 2026-07-24):** hecho capas + escenas + cotas lineales; **falta (a) TEXTO/etiquetas** (entidad Text — `plaza Yanque (1).skp` no la tenía; pedir repro con texto colocado, calibrar contra su contenido), **(b) cotas radiales/angulares** (otra entidad, sin decodificar), **(c) pulir el lado del offset de la línea de cota** (la dirección perpendicular se deriva, no calca exacto a SketchUp), **(d) jerarquía de grupos anidados**. Aparte: **detalles del render de transparencias** (pendiente viejo) y **optimizaciones**.
2. **Track .skp upstream:** issue instance-tree misplacement (hallado, sin reportar — lo único no reportado); **capas/escenas/cotas parseadas en el fork rama `ingetrazo` (2026-07-24) AÚN sin aportar upstream como PR** (preguntar a Marco — serían PRs nuevos sobre main); legacy MFC **HECHO local** (sin capas/escenas/cotas legacy aún — falta repro); seguimiento de PRs #3–#15 (11/13 mergeados) + issue #2.
3. **Lado IngePresupuestos** (sesión en aquel repo): `IFC_MAP` +RAILING/COVERING, preferir `Net*` sobre `Gross*`, mapear tags→partidas con el RAG "Sugerir partidas".
4. **Flatpak: AUTODISTRIBUCIÓN HECHA (2026-08-25)** — `packaging/flatpak/` calcado del molde IngeCAD (manifest `com.ingetrazo.IngeTrazo.yml` con krb5 + trim de PySide6 a Core/Gui/Widgets/OpenGL/Network — fuera Pdf/PrintSupport que IngeCAD sí lleva; sandbox CON red por teselas/DEM; MIME .igz/.skp; metainfo bilingüe validado). `build-flatpak.sh --bundle` → `IngeTrazo.flatpak` (59 MB) adjunto al release v0.3.4; PySide6+GL verificado corriendo en el sandbox Wayland. **Flathub sigue pendiente** (pip con red en build está prohibido allá → flatpak-pip-generator; capturas PNG; repo OSTree firmado como IngeCAD si se quiere auto-update).
5. **Renders:** (2) glTF PBR + "Enviar a Blender" con plantilla → (3) sombras de sol en viewport → (4) AI render opcional. NUNCA motor fotorrealista propio.
6. **Kit restante:** Tape Measure + guías (T) · Eraser (E) por arrastre · Outliner · Texture Position.
7. **Motor (diferido, atacar cuando duela):** iceberg de solapes coplanares (~326/1000 secuencias, invisible al bench; pre-STL/IFC en serio) + los 4 xfail draw-side + rechazos del guard → resultados correctos. La salida de fondo es **A.3: identidad/attrs por REGIÓN a través del rebuild** (el rule-set de declaraciones llegó a su techo). Limitación conocida: `apply_rebuild` disuelve diagonales de usuario en planos tocados por push.
8. **Perf de fondo:** grupos de referencia como arrays NumPy puros (import DAE 27 s → objetivo archivos 80 MB) · edición de mallas 17k+ tris.
9. **Georref expansión:** **G5 curvas de nivel** (siguiente natural: ya hay `photomesh.height_at`) · DXF · G6 y KML/GeoJSON HECHOS. Aparte, lo que pide el flujo del puente: **plano de trabajo que siga al terreno** (hoy los tools dibujan en Z=0 fijo) y **cotas persistentes** como anotación reutilizando `geo_points`.
10. **Registro de materiales (track 0.4, ABIERTO 2026-08-18):** primera tajada HECHA (a7affbe) — `core/materials.py` (Material + register con dedup), `Scene.materials`, `.igz` round-trip (texturas embebidas gratis por el walker genérico), **import .skp conserva los NOMBRES de materiales** (validado: archivo real → 17 nombrados, attrs["mat"] en las caras, remap en colisión con el documento), bandeja rotula swatches con el nombre. Diseño: attrs siguen siendo la verdad del render; "mat" es identidad que sobrevive el churn. **TRACK COMPLETO (2026-08-18, 5 tajadas):** núcleo + (a) Paint con identidad (SetFaceMaterialTagCommand compuesto en el paso de pintura; pintar anónimo LIMPIA "mat"; eyedropper recoge la identidad) + (b) editar-y-reestampar (RestampMaterialCommand: registro + todas las caras, loose y grupos, un undo; UI: clic derecho en swatch nombrado de "En el modelo") + (c) metrado por material (Model Info agrupa por nombre; plaza → 28/28 nombrados con m²) + (d) exports con nombres reales (plaza → 25/26 en el .mtl) + (e) bandeja con nombres end-to-end (biblioteca por display name, texturas sueltas por stem, "+ Color…" pregunta nombre opcional; registro LAZY al pintar — clickear un swatch no ensucia el registro). Todo estrena en 0.3.3. Siguiente natural del track (NO urgente): panel de registro propio (listar/renombrar/purgar materiales sin uso) y opacidad en el flujo de pintura.
11. **v2:** planos profesionales (LayOut-equivalente), DWG/DXF (IngeCAD es el hermano 2D), IFC import; plugins: motor HECHO (2026-08-18), falta importer/exporter/panel registration + manifest + manager (post-0.5; gatillo del manager mínimo: el primer plugin de terceros real).

---

## 🧭 Conceptos duplicados — medido el 2026-08-29 (pedido de Marco)

Marco pidió, mirando IngeCAD: *«dime si IngeTrazo e IngePresupuestos tienen
los mismos problemas de conceptos duplicados»*. Se midió con el mismo
escáner en los tres (nombres definidos en más de un archivo + funciones
**estructuralmente idénticas** en archivos distintos, AST normalizado):

| | archivos | líneas | nombres repetidos | clones reales |
|---|---|---|---|---|
| IngeCAD | 99 | 41 413 | 9 | 4 |
| **IngeTrazo (`app/`)** | **115** | **50 516** | **16** | **8** |
| IngePresupuestos (`app/`) | 90 | 88 606 | 17 | 11 |

**Los clones de acá, del más caro al más barato** (los dos primeros son
matemática, y ahí duplicar no da un bug de interfaz sino **dos resultados
distintos** el día que uno de los dos se toque):

1. `_loop_area` — **la misma función Newell, dos veces**: `core/mesh.py:1510`
   y `core/bim.py:68`. Idénticas salvo el docstring y el nombre de una
   variable (`cur` / `curr`). El área de un contorno es una pregunta del
   modelo: debe tener una sola respuesta.
2. `_faces` — `formats/obj.py` y `formats/stl.py` (131 nodos): la
   triangulación que va al archivo, dos veces. Un exportador arreglado y el
   otro no es exactamente el bug que nadie ve hasta que el colega abre el
   STL.
3. `_key` en **cuatro** archivos del núcleo (`formats/fuse.py`,
   `core/mesh.py`, `core/topology.py`, `core/arrangement.py`): la
   cuantización de un vértice a clave. Si dos de ellas redondean distinto,
   dos partes del motor dejan de reconocer el mismo punto.
4. `_newell` (`formats/fuse.py`, `core/triangulate.py`), `collect_geometry`
   (`formats/meshexport.py`, `core/hlr.py`), `_face_attrs` /
   `_image_has_cutout` / `_collect` (`formats/dae.py`,
   `formats/skp_openskp.py`), `_plog` (`views/viewport.py`,
   `core/history.py`), `value_label` (`tools/rotate.py`,
   `tools/protractor.py`), `on_activate` (los dos plugins).

**El método, que es lo que evita romper lo andado:** por cada concepto,
primero una prueba que **fije la conducta actual de los DOS sitios**,
después unificar, después medir que la salida no cambió (el bench de mallas
y el round-trip .igz/.skp ya dan ese "no cambió nada" gratis). Sin la
prueba previa, unificar es adivinar.

⚠️ **La medición detecta clones, no conceptos duplicados.** Los peores
casos que aparecieron en IngeCAD —dos constantes para la misma apertura de
picado, dos formas de resolver el color de un ACI— **no salen en esta
tabla**, porque son código distinto contestando la misma pregunta. Los
números de arriba son un piso, no un total.

---

## Memorias de Claude relacionadas

En `~/.claude/projects/-home-sumaritux-ingetrazo/memory/`: filosofía/flujo unificado · casita dogfooding · AI-native · estrategia OpenSKP (`project-skp-import-strategy-openskp`) · skp2dae · sitio web · migración SketchUp · IngeCAD. Del hermano IngePresupuestos: `project_integracion_ingetrazo_flujo` · gotchas Wayland/PySide6 originales.
