# Changelog

All notable changes to IngeTrazo are documented here.
Format inspired by [Keep a Changelog](https://keepachangelog.com); versions
follow [SemVer](https://semver.org).

## [Sin publicar]

### Cambiado
- **En KDE Plasma con Wayland, IngeTrazo arranca en X11 (XWayland)** (#136,
  @leo-smi): ahí los menús flotantes de Qt salen rotos. Preferencias ▸
  General ▸ Servidor gráfico sigue permitiendo elegir Wayland.
- **El instalador de Windows habla inglés, español y portugués** (#135,
  @xyont), según el idioma de Windows.
- **La figura de escala de un documento nuevo es el Ingeniero** (1,75 m,
  casco y chaleco), con los dos pies en el suelo: su pie izquierdo flotaba
  unos 4 cm. Sumari sigue en la biblioteca de personas.

### Añadido
- **Ratón 3D: invertir cada eje por separado** (#108, sugerencia de
  @mnavarromugas, el primero que lo prueba con un SpaceMouse real):
  desplazar izquierda/derecha y arriba/abajo, acercar, inclinar y girar,
  cada uno con su casilla en Preferencias ▸ Ratón 3D.
- **La lista de Elementos del compositor, como en QGIS** (#93, @pacaeiro):
  cada elemento con un ojo (mostrar/ocultar; oculto no se ve, no se toca y no
  se imprime) y un candado (bloquear/desbloquear); se puede renombrar (F2 o
  clic derecho; el nombre viaja en el .igz) y agrupar por tipo en carpetas.
  Un clic selecciona, doble clic lleva a sus propiedades.
- **Líneas ocultas a trazos en las láminas** (#81, @pacaeiro): una vista en
  estilo vectorial puede dibujar las aristas que quedan detrás de las caras,
  finas y a trazos, como en un plano técnico (casilla «Líneas ocultas» del
  panel; salen también en el DXF, en su propia capa discontinua).
- **Extensiones de ejemplo de varios archivos**: el menú Extensiones ▸
  Extensiones de ejemplo instala también una extensión que es una carpeta
  (la base para que el CAM de @felixriestra venga incluido, PR #132).
- **Espacio vuelve a Seleccionar en el compositor**, como en el modelo (#83,
  @pacaeiro).
- **IngeTrazo en chino simplificado** (Idioma ▸ 简体中文), traducido por
  @liujvnes (#123). Su archivo no cargaba por una coma y porque algunas
  variables venían traducidas (`{名称}` en vez de `{name}`); ahora una prueba
  revisa cada archivo de idioma para que eso no vuelva a pasar. De paso,
  Preferencias ya ofrece el portugués, que solo estaba en el menú.

### Corregido
- **Las líneas sueltas llegan al .skp** (#137, @pacaeiro): las aristas que no
  bordean ninguna cara (el círculo de camino de una esfera, una línea de
  construcción) no se exportaban. Ahora salen, y un círculo o arco como una
  sola curva, igual que en SketchUp.
- **Compositor: dos clics vuelven a colocar vistas, flechas y líneas** (#95,
  @pacaeiro): si entre el primer y el segundo clic el lienzo se redibujaba
  (por ejemplo al terminar el render de una vista), el primer clic se perdía.
- **El material de un grupo aparece en «En el modelo»** (#133, @fafecm):
  pintar un grupo no lo añadía a la lista hasta explotarlo, y Purgar podía
  borrar un material que solo llevaba un grupo.
- **Al explotar un grupo, lo de dentro se dibuja donde está** (#134,
  @fafecm): tras agrupar copias, mover el grupo y explotarlo, una copia se
  dibujaba donde estaba antes de agrupar y mover (su recuadro de selección sí
  estaba bien) hasta que algo la obligaba a redibujarse, como pintarla.
- **Un rectángulo dibujado de lado a lado de una cara la parte**: con las
  cuatro esquinas sobre el borde (una franja en un peldaño, desde el borde
  hasta la contrahuella) la cara quedaba entera con el rectángulo encima, y
  al tirar de él salía un sólido roto. Con líneas sí quedaba limpio.
- **Las copias de un componente comparten los grupos de dentro** (#97): al
  copiar un componente hecho de varios grupos, editar un grupo dentro de una
  copia no cambiaba las otras. Ahora todo lo que hay dentro de un componente
  es de su definición, como en SketchUp; un grupo que sale de una copia
  (Explotar) se vuelve suyo al abrirlo y no toca a las demás.
- **Sumari ya no se cuela en un diseño recién abierto** (#75, @pacaeiro): el
  visor guardaba datos de las figuras por su dirección en memoria, que Python
  reutiliza; tres de esas cachés no se vaciaban al abrir otro documento.
- **Tirar hacia arriba contra una pared** (#94, @xyont): un área dibujada en
  el peldaño de abajo de un escalón, pegada a la contrahuella, no se podía
  tirar hacia arriba («rompería el sólido»), y bajarla sí. La franja donde el
  lado nuevo queda pegado a la pared ahora desaparece, como en SketchUp. De
  paso, los anillos concéntricos empujados a distintas alturas (el «ojo»),
  que se rechazaban o dejaban una pared dentro del sólido, salen con el
  volumen exacto.
- **La esfera con Sígueme sale bien** (#125, #128): un círculo barrido
  alrededor de otro con el mismo centro daba una esfera achatada cuando el
  perfil no caía justo sobre un vértice del camino, y un perfil de círculo
  entero se barría dos veces. Ahora Sígueme gira el perfil alrededor del eje
  (esfera, torno, jarrón) y la esfera sale cerrada, exacta y como una sola
  superficie lisa que se pinta de un clic.
- **Compositor: una vista movida engancha donde está** (#122, PR #124 de
  @pacaeiro): tras mover una vista (con el ratón, las flechas o deshacer),
  la cota y todo lo que engancha seguían buscando los vértices donde estaba
  antes.
- **Rectángulo desde el centro: el «Cuadrado» es un cuadrado** (#119, PR #126
  de @pacaeiro): con Ctrl, el aviso de cuadrado salía con lados distintos
  (4,00 × 4,10 m).
- **Las unidades se recuerdan para los documentos nuevos** (#121): elegir
  milímetros en Preferencias ▸ Unidades solo valía para el documento abierto
  y cada archivo nuevo (o cada arranque) volvía a metros. Ahora la casilla
  «Usar también para documentos nuevos» las guarda; un archivo que se abre
  sigue con sus propias unidades.
- **Las líneas guía se cruzan donde deben** (#110): el cruce de dos guías
  diagonales, y lo que se dibujaba desde él, quedaba hasta 2 mm fuera de las
  guías (se veía al acercar el zoom). Una guía «infinita» llegaba al cálculo
  como un segmento de 10 km, demasiado largo para la precisión de los números;
  ahora se recorta a lo que se ve.
- **Modelos grandes con cotas o textos ya no van a tirones**: para saber qué
  parte de cada cota queda tapada, el visor lanzaba miles de rayos contra
  todo el modelo en cada cuadro (una casa de 284 000 triángulos con 25
  cotas: casi 2 s por cuadro al orbitar). Ahora lo lee de la profundidad que
  la tarjeta gráfica ya calculó: 34 ms por cuadro, 50 veces más rápido.
- **Modelos de SketchUp 2018 (y anteriores) que abrían incompletos**: una
  cota anclada a un punto dentro de grupos anidados desalineaba la lectura y
  se perdía casi todo lo que venía después en la raíz del modelo (una casa
  abría con 2 de sus 72 objetos: solo muros y césped). Ahora abren enteros
  (2384 colocaciones en vez de 12) y también se leen esas cotas. Arreglo
  propuesto a OpenSKP (iamahsanmehmood/openskp#384) y aplicado en IngeTrazo
  mientras tanto. Gracias a Juan José Noriega por los modelos.

## [0.5.3] — 2026-09-25

**Lo que pidieron los usuarios, y extensiones para lo que solo algunos
necesitan.** Pinzas de rotación en Mover y un menú Seleccionar como los de
SketchUp; copias `5x10m`; el ratón 3D; y los fallos que destaparon vuestros
vídeos: Escalar que rompía la geometría, el cubo fantasma al girar y la foto
tapada por lo que tenía detrás. Las extensiones ya pueden guardar datos en
el documento, añadir un panel y ofrecer inferencias; Niveles, de José Castro
Basso, es la primera y viene como ejemplo.

### Añadido
- **Los componentes se desarman** (PR #96, Félix Riestra):
  - **Importar OBJ conserva sus piezas:** un archivo con varios grupos
    (`g`/`o`) llega como UN componente con un grupo por pieza, cada una con
    su nombre (sin la jerga de Blender). Un OBJ de un solo grupo se importa
    como antes.
  - **Dividir en piezas** (Edición, clic derecho y panel Piezas): separa un
    componente en sus piezas físicas, aunque los tableros se toquen.
  - **Panel Piezas** con la **lista de corte**: largo × ancho × espesor de
    cada pieza, material, ocultar, renombrar, y copiar la lista a una hoja
    de cálculo (piezas iguales en una línea con su cantidad).
  - **Vista explosionada:** un deslizador separa las piezas hacia fuera o a
    lo largo de un eje, y Reensamblar las devuelve; se guarda en el `.igz`.

- **Estilos: Color trasero** (PR #99, Gabriel Rodríguez), como en SketchUp:
  junto al Color frontal, el color de las caras vistas por detrás (el
  interior de un sólido, una cara invertida). Sin elegir, sigue el de
  siempre o el que traiga un `.skp`; se guarda en el documento, en las
  escenas y en la biblioteca de estilos.

- **Copias con cantidad y separación en una sola entrada** (#111): al mover
  con Ctrl, escribir `5x10m` hace cinco copias separadas 10 m en la dirección
  del cursor; justo después de una copia, recoloca las copias con esa
  separación. `3x` y `/3` siguen como en SketchUp.

- **Clic derecho ▸ Seleccionar** (#106), como en SketchUp: todo lo
  conectado, aristas delimitantes, todo con el mismo material y todo en la
  misma capa. Actúa dentro del grupo que se está editando, como Seleccionar
  todo.
- **Ratón 3D (SpaceMouse de 3Dconnexion)** (#108): se sostiene el modelo
  como en SketchUp y FreeCAD (mover, subir, acercar, inclinar y girar la
  tapa). En Linux lo lee `spacenavd`; en Windows, Raw Input junto al
  controlador de 3Dconnexion. Los dos botones ajustan el modelo a la vista.
  Preferencias ▸ Ratón 3D: velocidad, invertir cada grupo y «solo desplazar
  y zoom» para dibujar en planta. Sin probar aún con un dispositivo real;
  macOS todavía no.

- **Pinzas de rotación en Mover** (#115), como en SketchUp: al pasar Mover
  sobre un grupo o componente aparecen cruces rojas en las caras de su caja;
  al tomar una, el objeto gira en ese plano alrededor de su centro, con el
  transportador, los pasos de 15°, el ángulo tecleado y Ctrl = copia.

- **Extensiones que van más allá de una herramienta**: con `setup(app)` una
  extensión guarda sus datos en el documento (con deshacer), añade una
  pestaña a la bandeja lateral, dibuja sobre el visor y ofrece inferencias al
  cursor, sea cual sea la herramienta activa (`docs/plugins.md`). Ejemplo:
  **Niveles** (`examples/extensions/niveles.py`), idea y primera versión de
  José Castro Basso (FADU–UDELAR): niveles del edificio con guías en alzados
  y cortes y enganche a sus alturas, y un botón «Ver alzado». Viene con el
  programa pero sin activar: se instala desde **Extensiones ▸ Extensiones de
  ejemplo**. Lo que solo algunos necesitan vive en una extensión, no en el
  núcleo.

- **Edición ▸ Invertir selección** (Ctrl+Mayús+I, PR #113, Gabriel
  Rodríguez), como en SketchUp: selecciona lo que no estaba seleccionado en
  el contexto abierto, sin tocar lo oculto ni lo que está en capas ocultas o
  bloqueadas.

### Cambiado
- **La bandeja lateral recuerda qué secciones dejaste plegadas** (Info de
  entidad, Capas, Escenas, Materiales, Componentes…): al volver a abrir
  IngeTrazo aparecen como las dejaste (pedido de un usuario de Brasil).
- **Asistente IA: LM Studio además de Ollama.** El proveedor local ya hablaba
  la API compatible con OpenAI que usa LM Studio; ahora la interfaz lo dice:
  «Local: Ollama / LM Studio», con la URL de cada uno en la ayuda
  (`http://localhost:1234` para LM Studio).
- **Icono de Zoom a extensión** (#112): ahora es la lupa con tres flechas
  hacia las esquinas, como en SketchUp, para que quien viene de allí lo
  reconozca; antes eran cuatro esquinas que pocos identificaban.

### Corregido
- **Fuga de memoria al abrir documentos**: cada Nuevo / Abrir dejaba vivos
  los datos de dibujo del documento anterior (y con ellos sus caras), y cada
  componente editado sus búferes en la tarjeta gráfica. Reabrir la plaza de
  Yanque cinco veces llevaba la 0.5.2 de 610 a 1440 MB y cada apertura era
  más lenta; ahora la memoria se estabiliza. Lo encontró la nueva
  verificación previa a cada versión (`scripts/release_check.sh`, resultados
  en `benchmarks/results/`).
- **Láminas: una vista redimensionada ya no se estira** (PR #116, Pedro
  Caeiro, #80): como en LayOut, el dibujo conserva su escala, el borde nuevo
  se ve como papel y la vista se vuelve a renderizar sola al soltar (con
  Autorenderizar), sin bloquear la ventana.
- **Una imagen de referencia ya no queda tapada por lo que está detrás**:
  un triángulo trazado sobre una foto en el suelo y empujado hacia abajo
  pintaba sus caras sobre la foto vista desde arriba. Lo que se traza encima
  de la imagen sigue viéndose encima.
- **Escalar ya no destroza la geometría suelta**: al arrastrar una pinza a
  factores muy pequeños y volver varias veces, algunos vértices quedaban sin
  escalar y las caras se rompían al soltar (vídeo de un usuario, en Linux y
  Windows). La vista previa se calcula siempre desde las posiciones
  originales.
- **Un grupo girado sobre su centro seguía dibujado donde estaba**: el visor
  reconoce «sin cambios» por una suma de coordenadas, y girar sobre el
  centro no la cambia. Con las pinzas de rotación (que giran siempre sobre
  el centro) quedaba siempre el cubo fantasma; con Rotar, al girar sobre el
  centro exacto.
- **Compositor sin barras de herramientas** (#114, macOS): si al abrir no
  queda ninguna barra visible (y entonces no hay dónde hacer clic derecho
  para recuperarlas), vuelven a su sitio de fábrica. Una barra ocultada a
  propósito sigue oculta.
- **Láminas: la cota con Mayús pasa de horizontal a vertical** (#104): con
  los dos puntos ya puestos, el cursor elige la dirección como en AutoCAD
  (arriba o abajo = horizontal, a un lado = vertical). Antes la decidían los
  dos puntos y una cota horizontal nunca podía volverse vertical.
- **Un `.skp` vacío abre vacío** (#103): una plantilla de SketchUp sin nada
  dibujado se mandaba al convertidor externo, así que en Windows pedía
  instalar `skp2dae` para abrir una hoja en blanco. Ahora abre y la barra de
  estado dice que el archivo no tiene geometría.
- **Mac:** el diálogo de cambios sin guardar ya se lee en el tema oscuro, y
  los deslizadores destacan sobre el fondo oscuro (PR #96).

## [0.5.2] — 2026-09-24

**Grupos que son grupos, láminas más cómodas y la perspectiva de dos puntos.**
Un grupo de grupos ya no se hace pasar por componente y Hacer único no
explota los subgrupos (#90); Crear componente con varios grupos hace uno
solo; Ctrl+Tab entre el modelo y las láminas; la perspectiva de dos puntos y
la vista actual a DXF, de José Castro Basso; la guía provisional del Metro y
el Transportador; y el compositor con cursores, dos clics y edición de
varias cotas a la vez.

### Añadido
- **Perspectiva de dos puntos** (José Castro Basso, FADU–UDELAR), como la
  de SketchUp: **Cámara ▸ Perspectiva de dos puntos** mantiene verticales
  las líneas verticales, como pide un dibujo de arquitectura, con lo que
  se mira siempre en el centro. Las escenas la recuerdan; mirando casi en
  vertical hacia abajo vuelve sola a la perspectiva normal.
- **Archivo ▸ Exportar ▸ Vista actual como DXF** (José Castro Basso): la
  vista en pantalla como líneas para CAD, sin las ocultas. En paralela, a
  tamaño real en metros, con aristas, perfiles y corte en capas separadas
  (como «Exportar vista como DXF» de las láminas). En perspectiva —la de
  dos puntos incluida— las líneas ocultas se calculan en la propia
  perspectiva y el dibujo se recorta a lo que muestra la ventana; lo que
  está a la distancia del punto de mira sale a tamaño real.
- **Ctrl+Tab: del modelo a las láminas y vuelta** (#91, @pacaeiro). Desde
  el modelo va a la última lámina abierta (o crea la primera); desde el
  compositor, al modelo. En el compositor, **Ctrl+RePág / Ctrl+AvPág**
  pasan a la lámina anterior o siguiente, como las hojas de Calc. Al
  pasar el ratón por las pestañas Modelo y Lámina, un aviso lo recuerda.
- **Rectángulo girado: Mayús fija la dirección de la arista base** (#70,
  @pacaeiro), como ya fijaba el ángulo del ancho: con Mayús pulsada solo
  la longitud sigue al cursor, y la longitud escrita va en esa dirección.
- **La guía que vas a crear se ve antes del clic** (#89, @pacaeiro): con
  el Metro y el Transportador, la línea guía provisional sigue al ratón a
  trazos, como quedará. Ya se intentaba dibujar, pero en perspectiva una
  guía tiene un extremo detrás de la cámara y se descartaba entera.

### Corregido
- **Compositor: «dos clics» vuelve a funcionar** (#95, @pacaeiro) al colocar
  una vista, un rectángulo, una línea… Si la mano se movía unos píxeles al
  soltar el primer clic, contaba como un arrastre diminuto: dejaba una vista
  del tamaño mínimo y el segundo clic se perdía. Ahora manda la distancia de
  arrastre del sistema.
- **Un grupo de grupos es un grupo, no un componente** (#90, @fafecm). Al
  hacer Crear grupo con grupos dentro, el resultado se presentaba y se
  exportaba como componente, y Hacer único fundía sus subgrupos en una sola
  malla. Ahora:
  - Info de entidad lo llama **Grupo**, no sale en la lista de componentes
    y ofrece **Crear componente**, que lo convierte con sus subgrupos.
  - **Crear componente con varios grupos seleccionados** (o grupos y
    geometría suelta) hace UN componente que los contiene, cada uno aún
    grupo dentro. Antes hacía un componente por grupo, o se negaba.
  - **Hacer único** sobre un componente con subgrupos lo deja como grupo,
    con su propia copia de todo el árbol y los subgrupos intactos.
  - Las **copias de un grupo** ya no se editan todas a la vez: al abrir una
    para editarla se hace única, como en SketchUp.
  - En **.skp** un grupo de grupos sale como grupo de SketchUp y sus
    subgrupos como grupos (validado con el SDK de SketchUp). Los `.igz`
    guardan la diferencia; los archivos anteriores la deducen al abrirse.
- **La consola de Python sigue el tema** (#92, @xyont): con el tema claro
  tenía el fondo negro. Ahora usa colores claros (los de VS Code Light+), y
  cambia con el tema aunque esté abierta, incluido lo ya escrito.
- **«Añadir localización» ya abre el mapa** desde el panel de Sombras. En
  Wayland se quedaba cargando sin mostrar nada: el diálogo colgaba del menú
  desplegable de la barra. Ahora el menú se cierra y el diálogo sale sobre
  la ventana principal; lo mismo para los colores y el nombre de los estilos
  y el color de cota.
- **Las pestañas BIM y Terreno ya no se pierden.** Al plegar y desplegar la
  barra lateral solo volvía la pestaña que estaba delante, y el menú
  Ventana no dejaba recuperar las otras (salían en gris). Ahora vuelven
  todas las que estaban abiertas, y **Ventana ▸ Panel BIM** se suma a
  Panel de propiedades y Panel de terreno.
- **Compositor: el panel cambia TODO lo seleccionado.** Con varias cotas
  seleccionadas, poner la unidad en m (o el grosor, las flechas, el tamaño
  del texto…) solo cambiaba una; ahora cambian todas las del mismo tipo, y
  un solo Ctrl+Z las devuelve. Viaja solo lo que tocaste: cada una guarda
  su texto y su sitio. Vale para textos, formas, vistas y demás.
- **Compositor: Ctrl+clic suma o quita de la selección donde sea**, también
  sobre el texto de una cota. Ahí la cota se seleccionaba y se volvía a
  deseleccionar en el mismo clic, y un temblor del ratón movía el texto.
  El panel sigue mostrando la primera elegida mientras siga seleccionada.
- **Compositor: cada herramienta muestra su cursor** (#79, @pacaeiro):
  mano para desplazar, lupa para el zoom, cruz para las que colocan o
  dibujan. Tras pasar el ratón por un marco se quedaba la flecha de
  Seleccionar.
- **Compositor: una vista redimensionada se vuelve a pintar sola** (#80,
  @pacaeiro) con el render automático activo, sin pulsar Actualizar.
- **Compositor: una Planta sigue siendo una Planta** (#82, @pacaeiro): al
  editar una vista fija (Planta, Frontal, Posterior, Izquierda, Derecha)
  solo se desplaza, se hace zoom y se gira; ya no se puede orbitar y
  dejarla distinta de lo que dice su panel. Ahí el botón central desplaza,
  como en la lámina (#83). Isométrica, escenas y perspectivas siguen
  orbitando.
- **Los paneles Propiedades, BIM y Terreno se abren siempre al arrancar.**
  Solo queda cerrado el que quites desde el menú Ventana, y así se
  recuerda; una barra plegada al cerrar vuelve desplegada.

## [0.5.1] — 2026-09-23

**La revisión 4 de Rafael, las tandas de @pacaeiro y la de los usuarios.**
Lo que dibujas dentro de un grupo se ve al momento; una puerta que arranca
del suelo atraviesa el muro; copiar y pegar entre ventanas; Orientar caras;
Zoom extensión que encuadra de verdad; la órbita que ya no se queda pegada
en Windows; Primera persona, de @sherodtaylor; y una barra de estado con
sitio para leer la pista de cada herramienta.

### Añadido
- **Copiar y pegar entre ventanas** (#76, @pacaeiro): lo copiado en un
  IngeTrazo se pega en otro abierto al lado, con sus materiales, texturas,
  grupos y componentes. **Archivo ▸ Nueva ventana** (Ctrl+Mayús+N) abre un
  segundo IngeTrazo para tener dos diseños lado a lado.
- **Deshacer y Rehacer en la barra Principal**, justo después del puntero,
  con iconos propios (flecha curva, contorno en tinta y relleno naranja
  suave).
- **Orientar caras** (#77, @pacaeiro), como en SketchUp: clic derecho sobre
  una cara ▸ Orientar caras, y todas las conectadas se voltean para mirar
  hacia el mismo lado que ella. Vale para sólidos y para superficies
  abiertas; se detiene donde tres caras comparten una arista.
- **Reconstruir caras (planas) sobre la selección** (#73, @pacaeiro): con
  caras seleccionadas en un mismo plano, rehace solo ese plano aunque el
  resto del modelo sea 3D. Sin selección hace lo de siempre (todo el
  dibujo, si es plano).
- **Primera persona: pasear el modelo como en un videojuego**, junto a
  Caminar y no en su lugar (Cámara ▸ Primera persona y la barra Paseo).
  W/A/S/D caminan y se mueven de lado, Q/E bajan y suben, Mayús corre y
  Alt atraviesa paredes; arrastrar con el botón derecho (o el izquierdo)
  gira la cabeza a un ritmo fijo por píxel, que se ajusta en
  Preferencias ▸ General ▸ Sensibilidad al mirar con el ratón (1–100,
  25 por defecto). Paredes, escalones y altura
  del ojo son los de Caminar. Mientras la herramienta está activa, esas
  seis letras son suyas y no cambian de herramienta; con Ctrl siguen
  siendo atajos (Ctrl+S guarda). El puntero se oculta al mirar y, donde
  la plataforma lo permite, vuelve a su sitio tras cada movimiento —
  en Wayland no se puede mover, así que al llegar al borde se suelta y
  se vuelve a arrastrar.

### Cambiado
- **Acerca de IngeTrazo reconoce a todos los que aportan**, en unos
  créditos que suben despacio y sin parar, como al final de una película:
  Pedro Caeiro, Rafael García, Ahsan Mehmood, dafrobozao (portugués),
  Félix Riestra (versión para Mac) y Sherod Taylor (Primera persona), y un
  agradecimiento a todos los que prueban y reportan.
- **La barra de abajo deja sitio a la pista de la herramienta** (Marco): el
  nombre de la herramienta va delante de la pista en vez de ocupar su propio
  hueco, las coordenadas UTM salen compactas (completas al pasar el cursor),
  la pista cortada se lee entera al pasar el cursor, y las pestañas de
  láminas tienen un ancho máximo con flechas ◀ ▶ si no caben.
- **En la ventana del modelo, las pestañas son Modelo | última lámina:**
  la pestaña de lámina lleva a la última que abriste (en la Lámina 2 →
  Modelo → vuelves a la Lámina 2); todas las láminas se ven como pestañas
  en el compositor.

### Corregido
- **Una cara pegada encima de otra se une con ella** (#73, @pacaeiro):
  como un rectángulo dibujado ahí, parte el plano en sus regiones en vez
  de quedar una cara superpuesta a la otra. Pegar al lado no toca nada.
- **Un grupo girado conserva sus ejes al copiarlo y pegarlo** (#78,
  @pacaeiro): la copia salía con los ejes alineados al mundo.
- **La órbita ya no se queda pegada al ratón** (Andrés Rodríguez, Windows 11).
  Si el aviso de «soltaste el botón» se perdía (algunos ratones y paneles
  táctiles en Windows, un clic en otra ventana, cambiar de herramienta con
  el teclado a media órbita), cada movimiento del ratón giraba la vista,
  con cualquier herramienta. Ahora un movimiento sin botón pulsado, o
  elegir otra herramienta, termina la órbita.
- **Lo que dibujas dentro de un grupo o componente se ve al momento**
  (Rafael, revisión 4). Las líneas nuevas no aparecían hasta salir del
  grupo: la parte del dibujo que guarda las aristas de los grupos no se
  enteraba de los cambios en el grupo abierto. Pasaba desde la 0.4.0.
- **Una puerta que arranca del suelo ya atraviesa el muro** (Rafael,
  revisión 4). Al empujarla, la cara de abajo del muro queda en forma de
  «C», y el motor probaba un punto que podía caer en el hueco de la C:
  creía que esa cara estaba fuera del sólido, la borraba y el empuje se
  rechazaba, dejando un nicho ciego. Dependía del orden interno de las
  caras, por eso a veces funcionaba y a veces no, con o sin booleanas.
- **El muñeco de escala solo ofrece el punto de sus pies** para enganchar,
  y ya no sirve de referencia para «Desde el punto»: sus esquinas, cabeza y
  ejes robaban las inferencias del dibujo cercano.
- **Sobre una arista, «Desde el punto» ya no se pierde** (Rafael, revisión 4:
  «hasta el final no me llega»): con un punto adquirido, la arista ofrece el
  punto alineado con él en vez de «En arista» a secas.
- **La prolongación de una arista aparece aunque haya una pared detrás del
  cursor** (Rafael: «a veces te bloquea y a veces no»). Se decidía con el
  punto de esa pared; ahora se mira también en pantalla, solo al prolongar
  la arista desde su propia línea. Medido en el arnés de inferencias
  (997 920 casos): cambian 1120, ninguno le quita un punto con nombre.
- **Al cerrar la ventana, lo copiado sigue en el portapapeles** para pegarlo
  en otra ventana; de paso se evita un cierre brusco del proceso.
- **Los cuadros de «escribe un nombre» ya no salen diminutos** con el
  título cortado («Crear…»): tienen un ancho mínimo (Rafael, revisión 4).
- **Desfase sobre una línea suelta lo explica:** si la línea no tiene nada
  unido a sus extremos, lo dice así y la deja seleccionada para que se vea.
- **El panel derecho ya no salta al seleccionar:** Info de entidad guarda
  un alto fijo (antes crecía o encogía con cada selección y arrastraba
  Capas, Escenas y Materiales), y si has bajado el panel, lo que miras se
  queda quieto aunque cambie algo de arriba. Tampoco salta la lista de
  materiales al crear un componente.
- Faltaba traducir el mensaje de la Cinta «Punto guía a … con su segmento»,
  y el panel «En el modelo» no se refrescaba al salir de un grupo.
- **«Deshacer grupo» se llama ahora «Explotar»**, como en SketchUp: el
  nombre anterior se confundía con Deshacer.
- **Redondeo 3D daba «Conflicting cuts» en un cubo girado y aplastado**
  (#74, @pacaeiro). Al girar la pieza fuera de los ejes, las dos aristas de
  cada esquina calculaban el mismo punto con una milésima de milímetro de
  diferencia por redondeo numérico, justo lo que el programa tomaba como
  dos puntos distintos. Ahora redondea igual que el cubo recto, en
  cualquier orden de aristas.
- **Zoom extensión encuadra también las figuras** como el muñeco de escala,
  igual que «Ver modelo centrado» de SketchUp: en un documento nuevo, donde
  solo está él, no hacía nada.
- **Zoom extensión a veces no hacía nada.** Encuadraba la esfera que
  envuelve al modelo, que no depende de hacia dónde miras: tras orbitar o
  pasar a una vista estándar, repetirlo daba la misma cámara y el modelo
  podía quedar en un 10 % de la pantalla (una torre vista desde arriba).
  Ahora encuadra el modelo tal como lo ve la cámara en ese momento y según
  la forma de la ventana, que en vertical además lo cortaba por los lados.
  Y una lámina renderizada ya no le deja a Zoom extensión los límites de
  su propia vista.

## [0.5.0] — 2026-09-23

**Sólidos, ejes locales y Mac.** Las herramientas de sólidos de SketchUp
(Revestimiento exterior, Unión, Sustraer, Recortar, Intersecar, Dividir) e
Intersecar caras, pedidas por Rafael; los ejes locales de grupos y
componentes, el pendiente grande de @pacaeiro (#44), con Cambiar ejes y el
`.skp` que los conserva; la tanda de pacaeiro del 22 de septiembre;
el tema claro o el del sistema; y la primera versión empaquetada para
macOS, gracias a @felixriestra.

### Añadido
- **Versión para macOS** (PR #64, @felixriestra): un `IngeTrazo.app`
  empaquetado en `.dmg` para Apple Silicon, que abre `.igz` y `.skp` con
  doble clic. Sin firma de Apple: la primera vez, clic derecho ▸ Abrir.
- **Ejes locales en grupos y componentes, como SketchUp** (#44, @pacaeiro):
  cada grupo recuerda hacia dónde mira cuando se mueve, gira, escala,
  voltea, copia o explota, y se guarda en el `.igz`. Al entrar a editarlo
  se ven SUS ejes, en su origen, y la inferencia de eje, las flechas, el
  suelo, el rectángulo, círculos y arcos y las vistas estándar los siguen,
  nivel por nivel en grupos anidados. Crear grupo o componente dentro de
  uno girado sale alineado con él. El cuadro de selección y la caja de
  Escala se alinean a los ejes del objeto. Clic derecho ▸ **Cambiar ejes**
  (origen, rojo, verde) sin mover la geometría; en un componente cambia la
  definición y todas sus copias se quedan en su sitio.
- **Herramientas de sólidos, como SketchUp** (pedidas por Rafael y en la
  #61): Revestimiento exterior, Unión, Sustraer, Recortar, Intersecar y
  Dividir sobre grupos y componentes sólidos. Barra propia, Herramientas ▸
  Revestimiento exterior / Herramientas de sólidos, y el clic derecho sobre
  una selección de sólidos. Clic en el sólido 1 y luego en el 2 (en
  Sustraer y Recortar el primero es el que corta), o preselección; el
  cursor dice «1», «2» o «no es un sólido». El resultado es siempre un
  grupo, cada cara conserva su material y las del corte toman el del
  cortador; un paso de deshacer. Info de entidad muestra «Grupo sólido» y
  su volumen. Motor: manifold3d (Apache-2.0), dependencia nueva.
- **Intersecar caras** (Edición ▸ Intersecar caras ▸ Con el modelo / Con la
  selección / Con el contexto, y en el clic derecho): aristas donde se
  cruzan las caras, en el contexto que se está editando, partiendo sus
  caras — la forma clásica de SketchUp de recortar sin sólidos.
- **Tema claro, y tema que sigue al sistema.** Preferencias ▸ General ▸
  **Tema**: Oscuro (el de siempre, sigue por defecto), Claro, o Igual que
  el sistema — este toma el modo claro u oscuro del escritorio (GNOME, KDE,
  Windows 10/11 y macOS) y cambia en vivo cuando el usuario lo cambia, sin
  reiniciar. El visor 3D conserva su estilo y la lámina sigue siendo papel;
  el fondo detrás de la hoja se aclara en el tema claro.
- **Material «por defecto» (sin material) en Pintar** (#47, @pacaeiro):
  un cuadro partido crema/gris-azul junto a «Activo» lo elige, el
  cuentagotas lo toma de una cara sin pintar, y pintar con él quita el
  material de la cara, de su revés o de un grupo entero.

- **Rectángulo rotado con transportadores**, como SketchUp (#70,
  @pacaeiro): uno en la primera esquina para la dirección de la primera
  arista (marcas cada 15° cerca del borde; el cuadro acepta `largo` o
  `largo;ángulo`) y otro perpendicular a esa arista para el ancho y su
  inclinación, que ahora se lee sobre el plano del transportador — antes
  solo salía tumbado (0°/180°) salvo cambiando la vista. Shift fija la
  inclinación. De paso, un ángulo tecleado en un documento en milímetros
  ya no se lee como longitud (`3;90` daba 0,09°).

### Cambiado
- **Alt alterna el cuentagotas de Pintar**, como SketchUp desde 2021.1:
  un toque lo activa y se queda hasta tomar un material (entonces vuelve
  al balde) o hasta otro toque. Mantener Alt y hacer clic también muestrea;
  Alt+Tab no cuenta. El puntero lo sigue siempre, también cuando la barra
  de menús se quedó con el teclado (#47).
- **Explotar quita UN nivel** (#72, @pacaeiro): los grupos y componentes
  anidados salen enteros, en su sitio y seleccionados, en vez de
  deshacerse también; uno sin pintura propia toma la del contenedor.
- **Planos de sección** (#62, @pacaeiro): al colocarlos llevan el color de
  la inferencia (rojo/verde/azul según el eje, magenta si no), el activo se
  ve naranja y los demás gris claro (el seleccionado, con marco continuo),
  y colocar uno vuelve a encender los cortes si estaban apagados.

### Arreglado
- **Las caras de un cilindro casi no se podían seleccionar** (#71,
  @pacaeiro): las costuras suaves, que no se dibujan, y las aristas del
  otro lado del sólido se llevaban el clic — a zoom normal, el 100 % del
  costado. Un clic ya solo toma aristas que se ven.
- **Al explotar un grupo pintado, el revés de sus caras perdía la
  pintura** (#47).
- **La goma no borraba textos** (#66, @pacaeiro): ahora los borra por las
  letras o por la guía, y los resalta antes del clic.
- **Preferencias ▸ Unidades salía en español con la interfaz en inglés**
  (#65, @pacaeiro): los nombres de las unidades se traducen.
- **macOS: el visor fallaba en cada cuadro con la herramienta Paseo** (#67):
  la etiqueta de la altura de ojos no tiene punto 3D y el visor intentaba
  proyectarla igual. Y el README decía `cd ingetrazo/app`, carpeta que no
  existe en el repositorio.
- **La ventana del puente MCP daba un comando que no sobrevivía a la
  sesión en los paquetes de Linux.** Con el AppImage enseñaba la ruta del
  montaje temporal (`/tmp/.mount_…`), que muere al cerrar la app; con el
  Flatpak, una ruta de dentro del sandbox que el anfitrión no puede
  ejecutar, y además el Flatpak no llevaba el servidor dentro. Ahora dice
  `<ruta del .AppImage> --mcp`, `flatpak run com.ingetrazo.IngeTrazo
  --mcp` o `/snap/bin/ingetrazo --mcp` según el paquete, el Flatpak
  incluye `scripts/`, y la ventana trae la línea de **Antigravity CLI**
  (`agy mcp add ingetrazo -- …`) junto a la de Claude Code. Lo encontró
  Marco montando Antigravity para el tutorial.

### Cambiado
- **La ventana del puente MCP nombra a Antigravity CLI, no a Gemini CLI.**
  Google cerró el 18-06-2026 el acceso gratuito con cuenta de Google a
  Gemini CLI («This client is no longer supported for Gemini Code Assist
  for individuals»); su sucesor para particulares es **Antigravity CLI**
  (`agy`), con plan Individual gratis, que lee el bloque `mcpServers` en
  `~/.gemini/config/mcp_config.json`. El manual y el guion del tutorial
  van con él.

## [0.4.9] — 2026-09-21

**La release de @pacaeiro: dieciséis de sus reportes, y las guías de
Rafael.** Lo que quedaba abierto de él desde la 0.4.4 (unidades del
modelo, rectángulo desde el centro, desfase de aristas, el vértice
compartido) y la tanda nueva del 20 y 21 de septiembre: Dividir, la
cámara guardada en el documento, la barra de progreso al abrir, los
planos de sección que terminan y se colorean por eje, los pasos de
deshacer, el scroll de las listas, Pintar con la regla de SketchUp
(cara sobre grupo), lo oculto que se puede clicar, la cota lineal, el
imán de ejes en todas las herramientas de dibujo. De la tercera revisión
de Rafael: la cinta saca guías desde los ejes y deja puntos guía con su
segmento, y el Asistente IA dice en claro cuándo falta la clave. Y el
programa habla portugués de Brasil gracias a @dafrobozao. Archivos
recientes, por fin.

### Añadido
- **Archivo ▸ Abrir recientes**: los últimos diez documentos `.igz`
  abiertos o guardados, con «Limpiar lista»; los que ya no existen
  desaparecen solos.
- **El documento recuerda su cámara** (issue #60, @pacaeiro: «If I do a
  New drawing, or open a drawing, the Camera stays in the position where it
  was before»). El `.igz` guarda la cámara con la que se guardó y al abrirlo
  se ve lo que veía su autor; un documento nuevo vuelve a la vista por
  defecto. Los `.igz` anteriores abren como hasta ahora.
- **Dividir** (issue #63, @pacaeiro: «In SK we have a command DIVIDE…
  It's a needed command»): clic derecho sobre una línea o un arco ▸
  **Dividir…** y el número de segmentos. Una línea se parte en N trozos
  iguales; un arco o círculo se mide a lo largo de su cadena, se corta en
  las marcas k/N y queda en **N arcos independientes**, cada uno
  seleccionable por su cuenta (un círculo dividido en cuatro son cuatro
  cuartos, como en SketchUp). Las caras que bordean reciben los vértices
  nuevos. Un solo paso de deshacer.
- **Pasos de deshacer configurables** (issue #56, @pacaeiro): Preferencias
  ▸ General ▸ «Pasos de deshacer» (200 por defecto; 0 = sin límite). Cada
  paso lleva una instantánea del modelo, así que en un modelo grande el
  tope es memoria.
- **Capas y Componentes con su propio scroll** (issue #55, @pacaeiro): las
  dos listas crecen hasta 12 filas y a partir de ahí desplazan ellas solas,
  en vez de estirar la bandeja entera. Las listas cortas siguen sin scroll
  anidado, como pidió Marco.
- **Unidades del modelo** (issue #33, @pacaeiro: «when doing architecture I
  work in meters and with mechanical pieces all the work is in
  millimeters»). **Preferencias ▸ Unidades**: metros, centímetros,
  milímetros, pulgadas, pies, pies y pulgadas (decimales o fraccionarias) y
  los decimales. La unidad viaja en el documento y manda en las dos
  direcciones: un número tecleado **sin unidad** está en ella (`2` son 2 mm
  en un documento en milímetros; `2m` sigue siendo 2 m), y todos los
  rótulos —herramientas, Info de entidad, barra de estado, resumen por
  materiales— se muestran en ella. El estilo de cota la sigue al cambiarla
  (y se puede apartar en su panel). Los documentos anteriores abren en
  metros.
- **Rectángulo desde el centro** (issue #39, @pacaeiro): con la
  herramienta activa, **Ctrl** alterna entre esquina→esquina opuesta y
  centro→esquina, como Mover/Copiar; el sello del lápiz cambia (dos iconos,
  uno por método) y la barra lo dice. Desde el centro, un `4;2` tecleado es
  el ancho y el alto **completos**, y el cuadrado imantado sigue centrado.
  Al volver a coger la herramienta arranca desde la esquina.
- **Barra de progreso al abrir un `.igz`** (issue #59, @pacaeiro: «if the
  file is big the user feels that the program has frozen»). Los mismos
  hitos que ya enseñaba la importación de `.skp`: leyendo, texturas,
  geometría, grupos. Un documento pequeño no llega a verla.
- **Planos de sección** (issue #62, @pacaeiro): la herramienta **termina
  tras colocar uno** y vuelve a Seleccionar; el cuadro del nombre trae «No
  volver a preguntar» (y Preferencias ▸ General lo reactiva); y un plano
  perpendicular a un eje se dibuja **del color de ese eje** (rojo, verde,
  azul; los oblicuos siguen neutros).
- **Interfaz en portugués de Brasil** (PR #54, @dafrobozao): 1 260 textos,
  tercer idioma del programa y el primero aportado desde fuera. Se elige en
  Ventana ▸ Idioma ▸ «Português (Brasil)», y un sistema en portugués
  arranca en él la primera vez. Lo que aún no está traducido sale en
  inglés hasta que se complete.

### Arreglado
- **Cuatro cosas de la primera pasada de Marco por el banco de pruebas.**
  (1) Una cara oculta que la vista enseña se seleccionaba y el pase de
  dibujo la soltaba al instante por no ser «visible»: solo el doble clic
  parecía funcionar; ahora lo seleccionable se queda. (2) Apagar Ver ▸
  Objetos/Geometría ocultos quita de la selección lo que deja de verse:
  el contorno naranja de la caja fantasma sobrevivía al interruptor.
  (3) **Una cara nueva mira hacia arriba, y si es vertical hacia la cámara
  que la dibujó** (regla de SketchUp): una cara cerrada con Línea o el
  contorno del Desfase salían con el reverso hacia fuera según el orden
  en que se hubiera recorrido el ciclo. (4) **La cinta enseña «En el eje»**
  (cuadradito rojo, verde o azul) al pasar por un eje antes del primer
  clic: la guía desde el eje funcionaba y nada lo decía. (5) **Pintar
  un componente desde fuera no se veía** hasta entrar en él: el pase que
  dibuja las instancias las agrupa por prototipo y las pintaba todas con
  el horneado sin pintura; ahora agrupa por (prototipo, pintura), así que
  la copia pintada se ve pintada y sus hermanas siguen como estaban.
- **La cinta saca guías desde los ejes y deja puntos guía con su
  segmento** (Rafael, Revisión 3, 20-09). Con el documento vacío, un clic
  en el eje rojo, verde o azul y una distancia —arrastrada o tecleada—
  da una guía paralela a ese eje: así se sitúa un proyecto «a 20 m y a
  5 m del origen» antes de dibujar nada. Y desde un punto con nombre
  (extremo, origen, intersección, centro), el segundo clic o el valor
  tecleado deja un **punto guía con su segmento discontinuo** hasta el
  punto de partida, como el «segmento guía» de SketchUp que él usa para
  centrar círculos o marcar el vuelo de un alero; de un punto a otro
  punto con nombre solo mide, y un punto medio no cuenta como punto
  («es ficticio»). El segmento se pinta con la profundidad del modelo,
  viaja en el `.igz` y se borra con su punto.
- **Pintar: las tres de la issue #47** (@pacaeiro). (1) **Alt mantenido
  = cuentagotas**, sin que el puntero haga de interruptor: el estado de
  los modificadores que leía Qt es el del ÚLTIMO evento entregado —al
  pulsar Alt aún no lo incluía y al soltarlo todavía sí—, así que el
  cursor cambiaba una vez por pulsación en vez de seguir a la tecla; ahora
  los manejadores de teclado dicen explícitamente si Alt está abajo.
  (2) **El cuentagotas actualiza el material activo** del panel
  Materiales (la casilla «Activo» y los campos de tamaño). (3) **Pintar un
  grupo o componente desde fuera pinta el objeto entero**, con la regla
  de SketchUp tal como la describió: el material de una cara va por
  delante del del contenedor; solo las caras con el material por defecto
  visten el del grupo, por las dos caras; y al explotar, esas se quedan
  con él. El material del contenedor viaja en el `.igz`, sobrevive a
  copiar/pegar, y dos instancias del mismo componente pueden ir de
  colores distintos. El cuentagotas sobre una cara por defecto de un
  grupo pintado toma el color del grupo. Al exportar a `.skp` el material
  va en el grupo o la instancia, como lo guarda SketchUp. Pendiente: las
  exportaciones de malla (.dae/.obj/.glTF) y el resumen por materiales.
- **Lo oculto que la vista enseña se puede clicar** (issue #53, @pacaeiro:
  «we cannot select them with mouse click, only by window selection»). El
  índice de picking guardaba el bloque de objetos con una firma que sabía
  qué grupo estaba oculto pero no si Ver ▸ Objetos ocultos / Geometría
  oculta estaba encendido: ocultar lo sacaba del bloque y encender la vista
  lo dejaba fuera. Ahora el fantasma responde al clic como cualquier
  objeto, y una arista oculta solo se clica mientras la vista la enseña
  (igual que ya hacía la selección por ventana).
- **Un vértice suelto gana a la esquina de un componente en el mismo
  punto** (issue #36, @pacaeiro: «Endpoint in component and the vertice
  endpoint share the same coordinate, but no face created»). Empatados a
  distancia, el motor elegía por el orden en que los había encontrado;
  ahora el punto del contexto en el que dibujas va primero, que es el
  único al que una línea puede soldarse. Misma familia que la regla de la
  0.4.4: una inferencia derivada nunca gana al punto del que sale.
- **Desfase funciona con aristas, no solo con caras** (issue #40,
  @pacaeiro: la barra decía «Clic en una cara, o en aristas conectadas» y
  las aristas no estaban). Un clic sobre una arista toma su cadena de
  aristas conectadas —polilínea abierta o contorno cerrado sin cara— y la
  desplaza a la distancia arrastrada o tecleada, con esquinas a inglete;
  y si seleccionas las aristas antes de activar la herramienta, el primer
  clic ya empieza el desfase, como en SketchUp. Una cadena recta se
  rechaza diciendo por qué (no tiene plano).
- **El imán de ejes de Línea llega a arcos, círculos, polígonos,
  rectángulo girado, Texto y Cota** (issues #52 y #51, @pacaeiro: «The
  Draw commands in the group of ARCS and SHAPES should also use the
  magnetic Snaps, like LINE. Except Freehand»). A menos de 3° de un eje el
  punto cae SOBRE el eje, y el eje que el plano de trabajo no alcanza se
  encuentra en pantalla; Alt lo apaga, como en Línea. Solo en los clics
  que son una dirección desde el primer punto: la comba del arco, la
  altura del rectángulo girado y la colocación de la cota van libres.
  Mano alzada queda fuera, como pidió; el Rectángulo también, a
  propósito: su segundo clic es la esquina opuesta, y una esquina imantada
  al eje de la primera es un rectángulo de altura cero.
- **La cota del modelo puede ser lineal, no solo alineada** (issue #50,
  @pacaeiro: «When a line is rotated some degrees, the Dimension tool
  should be able to measure aligned (as it does now), but also linear»).
  Como en SketchUp, lo decide dónde tiras la línea de cota: en escuadra
  con el segmento, alineada; pasado un extremo hacia un lado, la vertical
  (la extensión en Y); por encima o por debajo, la horizontal (en X); y en
  3D lo mismo con Z. La vista previa ya enseña cuál va a salir y el texto
  mide lo que corresponde. Viaja en el .igz (`axis`); los documentos
  anteriores no cambian. Y el segundo punto ya no se queda pegado a la cara
  bajo el cursor cuando vas casi por un eje: el imán lo sube al eje.
- **El Transportador soltaba todo menos el bloqueo de plano al
  recargarlo** (issue #48, @pacaeiro: «define a Hard Axis (Z) and Reload
  the command (Shift+H) — the Hard Axis keeps active»). Volver a pulsar
  Shift+H con la herramienta en la mano es el «empezar de nuevo» de
  SketchUp y ahora suelta también la flecha; Esc igual.
- **Línea acepta longitudes negativas** (issue #58, @pacaeiro). `-2` y
  Enter dibuja 2 m en sentido contrario al cursor, como ya hacían Mover y
  Copiar. Solo el cero se rechaza.
- **El Asistente IA dice en claro cuándo falta la clave** (Rafael,
  Revisión 3). «Groq (gratis)» se leía como «sin clave»: Probar conexión
  con el campo vacío devolvía el JSON crudo del HTTP 401 de Groq. Ahora
  los proveedores gratuitos se llaman «gratis, con clave», la clave vacía
  se detecta antes de tocar la red —con la dirección donde crearla— y una
  clave rechazada dice qué comprobar (entera, sin espacios, del proveedor
  correcto, el prefijo `gsk_`/`sk-ant-`/`AIza`…). Enviar un pedido sin
  clave deja el texto en la caja en vez de perderlo.

### Cambiado
- **«Redondear» pasa a llamarse «Redondear 3D»** (issue #49, @pacaeiro).
  Solo redondea aristas de un sólido; el redondeo 2D de una esquina sigue
  en la herramienta Arco (tangente a las dos aristas, arco magenta), y el
  nombre a secas mandaba allí a quien buscaba eso.
- **Las vistas Superior e Inferior en proyección paralela no eran
  rectas** (issue #45, @pacaeiro: «camera not perpendicular to view»).
  Estaban a 89° para esquivar el caso degenerado de la cámara, y en
  paralela ese grado se ve: cada arista vertical salía como un trazo
  corto y la planta, un pelo oblicua. Ahora son exactamente verticales
  —también las plantas de los marcos de lámina— y la orientación en
  pantalla es la misma de siempre (norte arriba en Superior).
- **El Borrador borra grupos y componentes** (issue #46, @pacaeiro: «only
  raw edges and faces»). Un objeto bajo el cursor se marca entero (su
  caja) y se borra al soltar, en el mismo trazo que las aristas; con
  Mayús se oculta en vez de borrarse. Dentro de un grupo abierto, su
  contenido sigue siendo geometría suelta, como antes.

## [0.4.8] — 2026-09-20

**La tanda de @pacaeiro sobre la 0.4.7, y lo que salió de comprobar la
0.4.7 punto por punto.** Cinco reportes suyos del mismo día: el imán de
ejes que faltaba en Cinta, Transportador y Mover (Mover solo enganchaba Z
desde una vista oblicua), la cara de atrás que ganaba en vista paralela,
un grupo que se agrupaba dentro de una copia de sí mismo, y el arco
magenta que tomaba el número como comba en vez de como radio. De la
comprobación de Marco: la cota que no seguía al grupo al escalarlo —el
caso que faltaba del usuario del vídeo—, la separación texto–línea de las
cotas de lámina a la norma, Texto 3D en metros, la N que gira con la
aguja, Zoom y Zoom ventana en la lámina, y las pistas de los iconos que
salían en una tira.

### Añadido
- **La cinta y el transportador se imantan a los ejes** como la Línea
  (issue #41, @pacaeiro): una medida a pocos grados de X, Y o Z cae sobre
  el eje, con su color; la cinta encuentra también el eje que su plano de
  trabajo no contiene. Los brazos del transportador se imantan a los
  ejes que están en el plano de su disco.
- **Con el arco magenta (redondeo de esquina), el número tecleado es el
  radio** (issue #43, @pacaeiro): fijadas las dos tangencias, teclea el
  radio y el redondeo se dibuja con él, tangente a las dos aristas y
  recortando la esquina; un radio que no cabe en las aristas se rechaza
  con las cifras. Fuera del redondeo, el valor sigue siendo la comba y
  `2r` el radio.
- **Zoom y Zoom ventana en la barra de la lámina** (Marco): los dos del
  modelo, en el compositor. **Zoom**: arrastra hacia arriba para acercar
  y hacia abajo para alejar, alrededor del punto donde pulsaste (un clic
  acerca un paso); **Zoom ventana**: arrastra un recuadro y la vista se
  llena con él. Las dos siguen armadas hasta que cambias de herramienta,
  como Desplazar. Ctrl+rueda sigue funcionando con cualquier herramienta.

### Arreglado
- **Una cota sobre un grupo no seguía al grupo al escalarlo** (Marco:
  «la vez pasada arreglamos a medias… faltaba en grupo»). Crear grupo
  lleva la geometría a la malla del grupo y deja en la malla suelta
  vértices huérfanos en los mismos puntos; la cota se agarraba a esos
  fantasmas, que no se mueven. Un vértice al que nada hace referencia
  ya no vale de ancla, y la tolerancia del enganche es la de soldadura
  de la malla (0,1 mm), así que una cota sobre un componente a cientos
  de metros del origen también se agarra. Y **si agrupas el dibujo junto
  con su cota** (Marco: «hice un cubo, lo acoté y todo en su conjunto lo
  hice grupo; escalo y la cota no sigue»), la cota cambia de manos con
  los vértices: tras cada orden —agrupar, explotar, deshacer— vuelve a
  agarrarse a lo que hay en su sitio, antes de que nada lo mueva.
- **En vista paralela se detectaba la cara de atrás** (issue #37,
  @pacaeiro: «face detection is identifying the face that is behind the
  one in front… in CAMERA orthogonal mode»). El rayo de la cámara
  paralela nace en el plano lejano, 10 km atrás, y la tolerancia con la
  que dos caras cuentan como «a la misma profundidad» era proporcional a
  esa distancia: un metro entero, así que una cara más pequeña 30 cm por
  detrás ganaba el desempate. Ahora se mide desde el ojo y vuelve a ser
  una fracción de milímetro; en perspectiva no cambia nada.
- **Mover / Copiar no enganchaba los ejes X e Y** (issue #42, @pacaeiro:
  «aligns well with the Z axis» pero X e Y nunca). Mover arrastra sobre
  un plano vertical de cara a la cámara, que contiene Z y la horizontal
  de la propia cámara — X o Y solo con la vista de frente; desde
  cualquier vista oblicua el detector nunca los veía. Ahora los encuentra
  por dónde apunta el cursor, como la Línea desde la #31, y el movimiento
  va exactamente por el eje. Medido sobre el arnés de snaps: 368 celdas
  cambian, todas de Mover y todas «nada → eje X/Y»; ninguna que ya tenía
  un punto con nombre.
- **Un grupo solo ya no se agrupa dentro de una copia de sí mismo**
  (issue #35, @pacaeiro): con un único grupo o componente seleccionado,
  Crear grupo lo dice en la barra de estado en vez de fabricar la muñeca
  rusa, y el clic derecho no ofrece la entrada. Dos grupos, o un grupo
  con geometría suelta, se agrupan como siempre.

### Cambiado
- **Las pistas largas de los iconos salen en un cuadro**, no en una tira
  a lo ancho de la ventana (Marco). Qt solo pliega un texto de pista
  cuando no cabe en la pantalla, por eso unas salían en una línea y otras
  en un bloque; ahora todas se pliegan a un ancho cómodo.
- **La N del norte gira con la aguja** (Marco: «cuando giro la N de norte
  debería la N girar también»): va en la punta de la aguja, fuera del
  círculo, y da la vuelta con ella; a 0° queda donde estaba, encima. El
  compás se centra en su caja y se ajusta para que la letra no salga de
  ella en ningún ángulo.
- **El número de la cota, a la distancia de la norma.** Marco puso su
  lámina junto a la de Rafael: «todavía no se ve como la norma». Dos
  cosas: la **separación** entre la línea de cota y el número se mide
  ahora hasta la **base de las cifras** (antes sumaba la altura de la
  fuente, y salía el doble de lo que se ve en la lámina de Rafael) y una
  cota nueva nace con 0,5 mm, un cuarto de la altura del texto; y el
  texto de una cota nueva **siempre va alineado con la línea** (una
  vertical se lee de abajo arriba, a la izquierda), aunque la última que
  editaste fuera horizontal — la orientación ya no se hereda. «Horizontal»
  sigue en el menú, marcada como fuera de norma, para devolver a la
  norma una cota que la lleve. Las cotas ya dibujadas no se mueven.
- **Texto 3D: altura y extrusión en metros**, la unidad del modelo en
  todo lo demás (Marco). La 0.4.6 las había pasado a centímetros porque
  Rafael tecleó «20» de extrusión y el campo, con tope de 10 m, lo
  rechazaba; la culpa era del tope, no de la unidad. Tres decimales y
  sin tope bajo.

## [0.4.7] — 2026-09-20

**Las láminas de la segunda revisión de Rafael, y la acotación a norma.**
La otra mitad de su vídeo de una hora (la 0.4.6 fue la del modelo) más su
vídeo sobre **normativa de acotación**, que Marco revisó punto por punto
antes de cerrar esta versión. Lo grande: **la sección tapa** (el poché ya
no se ve a través), **cotas a la norma ISO** —el texto encima y centrado, se
lee girando la cabeza a la izquierda, la línea se prolonga bajo el texto,
flechas por defecto—, **radio y diámetro** con un clic sobre el arco, la
**angular** que por fin engancha, la **cota forzada recta** y la **línea
base** de AutoCAD, y en el modelo **cotas que siguen a la geometría** —
escalas el dibujo y la cota se redimensiona y vuelve a medir—, lo primero
que echó en falta un usuario del vídeo de DriveMeca. De propina, la vista
previa de impresión que en el Flatpak no hacía nada, la #38 de @pacaeiro y
las barras de herramientas que dejaban a Paseo al fondo de la columna.

### Añadido
- **La sección tapa.** Lo que Rafael más repitió (46:00–49:30): al cortar,
  las líneas de lo que queda detrás se veían a través del achurado y el
  relleno «Sólido» tampoco lo tapaba. Ahora los anillos que el compositor
  rellena **ocluyen** con la misma regla par-impar y desde el mismo dato:
  lo que está detrás del plano y dentro de la región rellena está dentro
  de material macizo. El contorno del corte sobrevive siempre (y con la
  pluma de corte, más gruesa), un muro hueco conserva su hueco, y tapar ya
  no depende del relleno («Ninguno» también tapa). Snap y DXF dicen lo
  mismo que el PDF.
- **Cotas a la norma ISO**, según el vídeo de normativa de Rafael y la
  decisión de Marco («hagamos las ISO por ahora»). El **texto va encima
  de la línea de cota y centrado** en ella; una cota vertical se lee de
  abajo arriba, esté trazada hacia arriba o hacia abajo —la regla que él
  más repite, «girando la cabeza a la izquierda, nunca a la derecha»—;
  cuando el texto va fuera de un extremo **la línea se prolonga hasta
  cubrirlo** («si el texto crece, la línea crece»); y una cota nueva nace
  como la lámina de referencia de Rafael: **flechas** y el número sobre el
  centro. La posición del texto a lo largo de la línea es de cada cota, ya
  no se hereda de la última editada (una cota con el texto llevado al
  final enseñaba a todas las siguientes). La norma alemana/japonesa (línea
  partida, texto en medio) queda fuera del menú hasta otra versión; una
  lámina que ya la lleve se ve igual.
- **Cota de radio y de diámetro** (Rafael, 42:40, y su lámina de normas
  caso por caso): **un clic sobre el círculo o el arco** y la cota toma el
  centro y el radio por sí sola —como en AutoCAD, no hace falta buscar un
  centro que el plano no marca—; el punto del clic decide por qué lado
  sale la línea, y al pasar el cursor por el arco se ve en punteado la
  cota que va a colocar. **Ctrl** = diámetro. Reconoce los círculos y
  arcos que el marco ve de frente. La línea **siempre llega al centro**,
  el símbolo `R` / `Ø` acompaña al valor, el texto va encima y nunca
  cabeza abajo; si cabe, dentro con las flechas hacia el arco; si no, la
  línea se prolonga fuera y las flechas apuntan al centro. El número de un
  diámetro se pone en la **mitad derecha** de la línea, nunca sobre el
  centro, que es de los ejes («se cruzaría con otras líneas que salen del
  radio»). Un arco se acota igual que un círculo.
- **Cota angular con snaps y ángulos redondos** (Rafael, 29:20: «no
  engancha a nada, no hay manera de poner 90°»). Los tres primeros clics
  enganchan a la geometría del marco, y con **Mayús** el brazo cae en un
  múltiplo exacto de 15°: el primero desde la horizontal de la hoja y el
  segundo desde el primer brazo, así que el ángulo medido sale redondo.
- **Cota forzada recta**, la lineal de AutoCAD (DIMLINEAR). Rafael pedía
  «que me cogiera el punto final» con Shift y que no saliera inclinada por
  soltarlo antes de tiempo: ahora **Shift no mueve el punto, endereza la
  cota** —los dos puntos se quedan donde engancharon, mide solo su
  separación horizontal o vertical, con líneas de referencia de distinta
  longitud llegando a cada punto real— y **se queda pegado** hasta colocar
  la cota. El desplegable **Dirección** del panel endereza una cota **ya
  dibujada**. La cadena lo hereda entera. Shift sigue moviendo el punto
  en Línea, Flecha y Terreno, donde no hay nada que proyectar.
- **Cotas desde línea base** (DIMBASELINE): todas miden desde el primer
  punto y se apilan una fila más afuera; **Escalón de línea base** en
  Estilo de cota (8 mm por defecto, el DIMDLI de AutoCAD), viaja en el
  documento. Y **cadena y línea base continúan desde una cota ya puesta**,
  como DIMCONTINUE / DIMBASELINE: selecciona una cota, arma Cadena o Línea
  base y la serie arranca de ella —su línea, su separación y si iba
  forzada recta— a un clic por punto. Sin nada seleccionado, como antes.
- **Las cotas del modelo siguen a la geometría.** Cada extremo puesto
  sobre un vértice **se agarra a él**: si luego escalas, mueves o estiras
  el dibujo, la cota se va con él y **vuelve a medir**, también dentro de
  un componente. Si el vértice desaparece, el extremo se queda donde
  estaba; un extremo en un punto medio o sobre una arista se queda fijo.
  Con **Mover** sobre una cota, la **línea de cota se desplaza** y las
  líneas de referencia se estiran desde sus vértices, como en SketchUp.
  Y **Extremos** en Estilo de cota: flechas (lo que trae un documento
  nuevo), trazos oblicuos o ninguno; un documento anterior conserva sus
  trazos. Las tres cosas que echó en falta el primer usuario del vídeo de
  DriveMeca.
- **El nivel se lee solo**: en una elevación o una sección, la cota de
  nivel toma la altura del modelo sin necesidad de un punto de snap (le
  salía 0.00 clicando donde no había punto); en una planta no inventa.
- **Secciones por LETRA** (A-A, B-B…), como piden los planos, en vez de
  «1 … 1»; y **Nombre y símbolo…** en el clic derecho del plano de sección,
  que era donde Rafael no encontraba dónde cambiarlo.
- **Escalas de ampliación** (10:1, 5:1, 2:1) en la lista de escalas del
  marco, y la lámina, el rótulo de vista y `{escala}` escriben «10:1».
- **La N del norte** va en una banda despejada encima de la rosa, que
  sobre la aguja era ilegible.
- **Una imagen engancha al dibujo**: al arrastrarla, su esquina más
  cercana se imanta a un punto dibujado de la vista.
- **Iconos de radio y angular** redibujados con la clave de IngeCAD: el
  sujeto en acento y la cota encima en tinta (la angular usaba el icono
  del transportador, que es otra herramienta). Y la pista de la barra de
  estado dice que **Alt = paso fino** al mover con las flechas (existía
  desde siempre y no había forma de saberlo).

### Arreglado
- **La vista previa de impresión no hacía nada — en el Flatpak.** Está
  implementada y funciona en todas partes menos en el paquete que Rafael
  usa: la receta del Flatpak recorta PySide6 a los módulos que el programa
  usa y el de impresión estaba en la lista de recorte, mientras que
  exportar PDF, que va por otro camino, le funcionaba (eso explica las dos
  mitades de su reporte). El módulo vuelve al paquete, y si algún día
  falta, el programa lo dice y señala Exportar PDF.
- **Parpadeos en vectorial al mover una vista** (Rafael, y Marco lo leyó
  bien: «cuando pones vectorial la gráfica trabaja más»). Un marco
  vectorial entintaba cada arista visible en cada repintado, y arrastrar
  repintaba todo eso por movimiento (350 ms con 60 000 segmentos). Mientras
  se arrastra, el marco dibuja su silueta —cortes, perfiles y las aristas
  que quepan— y el dibujo exacto al soltar: de 660 a 120 ms por ocho
  movimientos, y el coste deja de depender del modelo.
- **Un `10:1` tecleado se convertía en `1:1` en silencio** sobre un plano
  técnico: la casilla leía solo lo que sigue a los dos puntos.
- **Un marco nuevo salía vestido con la vista de una escena borrada**
  (Rafael, 33:40: «pongo una ventana y me muestra ese previo que yo ya no
  tengo»): las cachés iban por la dirección del objeto y nada las soltaba
  nunca; ahora se barren tras cada cambio.
- **El texto de una cota del modelo proyectada a la lámina se leía con la
  cabeza a la derecha**: la regla de lectura estaba copiada en cinco
  sitios con dos convenciones contradictorias, y la que proyectaba las
  cotas del modelo giraba toda vertical al revés. Una sola regla para
  todas, y la zona de clic de una cota vertical vuelve a caer sobre su
  rótulo.
- **La cota angular no enganchaba a nada**: la herramienta pedía un punto
  enganchado y nunca estuvo en la lista de las que lo reciben.
- **La lámina se quedaba desplazándose sola** con el puño cerrado cuando
  la suelta del botón central no llegaba (una captura de pantalla, un
  cambio de escritorio, un diálogo: en Wayland es rutina): el arrastre
  termina en cuanto no hay botón pulsado, y el cursor vuelve al de la
  herramienta armada.
- **Ctrl+A seleccionaba sin que el programa se enterara** (issue #38,
  @pacaeiro): la barra contaba, el visor no pintaba la selección e Info de
  entidad decía «nada seleccionado». Construía el conjunto a mano, por
  detrás de la selección normal, que es quien avisa a todos.
- **Esc no sabía de una cota de radio a medias**: con el centro clicado,
  el primer Esc soltaba la herramienta en vez de la colocación.
- **Las filas de una línea base salían a distinta separación**: el
  escalón se tomaba de la cota más alta hasta el momento y crecía a mitad
  de serie.
- **Paseo (cámara, caminar, mirar) al fondo de la columna izquierda con
  un hueco encima** — en el vídeo de DriveMeca y en la máquina de Marco.
  El diseño de ventana guardado lleva la longitud de cada barra y se
  aplicaba tenga la barra lo que tenga hoy; ahora las barras se compactan
  al abrir, en su mismo orden.

## [0.4.6] — 2026-09-19

**Lo del modelo de la segunda revisión de Rafael, entero.** Su vídeo de una
hora sobre la 0.4.x (Rafael 3D, 16-09) se repartió en dos releases: esta es
la del **modelo** —los tres bugs y los cinco pedidos— y la siguiente será la
de las **láminas**. Lo grande aquí es la **cámara de paseo** para mirar los
interiores, **ocultar objetos** y capas que se usan de verdad, el **texto 3D
editable** letra a letra, y una inferencia que SketchUp no tiene: la
ventana de la pared de al lado **a la altura** de la primera. Y de propina,
la issue #34 de @pacaeiro sobre los snaps bajo bloqueo, cazada el mismo día
con el arnés recién ampliado — sexto punto ciego que le encuentra a esa red.
Marco probó cada fase en vivo antes de cerrarla («me encanta»).

### Añadido
- **Cámara de paseo: Situar cámara, Caminar y Mirar alrededor**, las
  tres de SketchUp (Rafael, 13:00: «pasitos» para mirar los interiores),
  hechas a su documentación oficial y a la grabación de Marco de su barra
  de estado. Menú Cámara y barra **Paseo**. **Situar cámara**: clic en un
  punto y el ojo se pone 1,68 m encima mirando en horizontal (la caja de
  medidas, «Desplazamiento en altura», admite otra altura); o clic y
  arrastrar desde donde quieres estar hasta lo que quieres mirar; al
  soltar pasa sola a Mirar alrededor. **Mirar alrededor**: arrastrar gira
  la cabeza sin mover el ojo; «Altura del ojo» en la caja. **Caminar**:
  clic y arrastrar con una cruz donde pulsas — cuanto más lejos, más
  rápido; arriba/abajo avanza y retrocede, izquierda/derecha gira; el ojo
  mantiene su altura sobre lo que pisa (sube y baja escalones) y las
  paredes te paran. Ctrl = correr, Mayús = vertical o de lado, Alt =
  atravesar paredes. Sin tocar el modelo de cámara ni el motor: el suelo y
  las paredes salen del mismo índice de picking de siempre.
- **Ocultar objetos** (Rafael, 38:40: «tiene ocultar aristas, pero no sé
  si tenemos opción de ocultar un objeto en concreto»; no la había).
  Edición ▸ **Ocultar** y el clic derecho ▸ Ocultar esconden los grupos y
  componentes seleccionados (y las aristas, como antes): dejan de dibujarse,
  de clicarse, de imantar y de exportarse, pero siguen en el documento.
  Edición ▸ **Mostrar ▸ Lo último / Todo** los devuelve, con deshacer. Y
  las **escenas los recuerdan**, que era lo que él quería —«una escena en
  donde esto esté oculto»—: cada objeto lleva ahora una identidad estable
  en el `.igz` y la escena guarda cuáles estaban ocultos; una escena
  guardada antes de esta versión no toca nada. Las **caras** también se
  ocultan (Marco: «en SketchUp también puedes ocultar caras»); sus
  aristas se quedan, como allí.
- **Cámara ▸ Objetos ocultos / Geometría oculta**, los dos interruptores
  de SketchUp: lo oculto se dibuja como una **rejilla transparente** (las
  aristas, punteadas) y vuelve a poder seleccionarse, que es el camino a
  **Edición ▸ Mostrar ▸ Seleccionado** y al «Mostrar» del clic derecho.
  Los dos interruptores viajan en el documento y en las escenas.
- **Cambiar de capa donde se busca** (Rafael, 39:00: «no sé cómo cambiar
  el objeto de capa… las propiedades… botón derecho… no lo veo»). **Info
  de entidad** tiene ahora el campo **Capa** de SketchUp: muestra la de la
  selección («(varias)» si mezcla) y elegir otra la mueve. El **clic
  derecho** gana un submenú **Capa** con las del documento, la actual
  marcada, y «Capa nueva…». El botón **Asignar selección** del panel de
  capas hace lo mismo y, cuando no hay capa marcada o nada seleccionado,
  lo dice en vez de callar (es lo que le «funcionó a la segunda»). Los
  tres caminos pasan por un mismo comando con deshacer, y una capa que no
  existe se crea al asignarla.
- **Posicionar textura: el transportador de SketchUp en el pin verde**
  (Rafael, 04:30: «en SketchUp te bloquea a los 0, a los 45 y a los 90… si
  no es un poco a ojo»; Marco trajo capturas y una grabación, y se calcó
  fotograma a fotograma). Al arrastrar el pin verde aparece sobre el pin
  rojo el pequeño transportador azul de SketchUp: el disco con el brazo
  de partida cruzándolo, la cuña del ángulo barrido, un cuadradito en
  cada brazo, la línea punteada del brazo actual que atraviesa el pin
  verde y sigue, y el ángulo en la caja de medidas. El giro se pega a
  pasos de 15° desde donde empezó (0, 15, 30, 45… 90: los 0/45/90 de
  Rafael están entre ellos), esté el cursor donde esté; Ctrl mientras
  arrastras lo deja libre («Ctrl = Sin ajuste», como allí).
- **Texto 3D como en SketchUp: cada letra es un grupo, y el texto se
  edita.** El texto llega como un componente con un grupo por letra
  («que cada letra aparezca como grupo, como lo hace SketchUp»), así que
  una letra se empuja, se pinta o se mueve sola: doble clic entra al texto
  como a cualquier grupo (lo de SketchUp), y dentro, doble clic en la
  letra. Y el texto **sigue siendo texto**: clic derecho ▸ **Editar texto
  3D…** reabre el cuadro con lo que se escribió —texto, fuente, negrita,
  cursiva, altura, extrusión— y lo regenera en el mismo sitio, con el mismo
  giro y la misma escala. Deshacer lo devuelve como estaba. El `.igz`
  guarda los parámetros, así que un texto de hace un mes se reabre igual
  de editable. Rafael lo pidió sabiendo que «SketchUp tampoco» lo hace.
  Y una salvaguarda: **si tocas una letra a mano** —la empujas, la pintas,
  la borras, la mueves sola— el texto pasa a ser geometría y «Editar texto
  3D…» se apaga con el motivo; regenerarlo habría tirado ese trabajo.
  Mover o girar el texto entero no cuenta.
- **Editar grupo** en el menú contextual, la entrada de SketchUp: la misma
  puerta que el doble clic.
- **«A la altura del punto»: la ventana de la pared de al lado, a la misma
  altura que la primera** (Rafael, 02:20: «que la línea guía se extendiera
  por aquí y yo pudiera fijar la ventana aquí… tampoco eso lo hace
  SketchUp»). Memoriza la esquina de una ventana —el mouse quieto un
  instante encima— y ve a **otra pared**, perpendicular o la de enfrente:
  al pasar a su altura, el cursor se engancha a una línea punteada que
  recorre esa pared a esa altura, con el rótulo **A la altura del punto**.
  Dos guías llevan el ojo desde la esquina hasta el cursor: por su pared
  hasta la esquina del cuarto y desde ahí por la nueva, cada una del color
  de su eje. SketchUp no lo hace porque su «Desde el punto» es la LÍNEA
  del eje que pasa por la esquina, que a una pared perpendicular la toca
  en un solo punto y a la de enfrente nunca; esto es el PLANO horizontal
  por la esquina cortado con la pared, que es una línea entera. Los otros
  dos planos también cuentan —**En línea con el punto**—: sobre el suelo,
  bajo una esquina alta, la línea que la tiene justo encima. Va por
  debajo de los puntos con nombre y del «Desde el punto» de siempre, así
  que en la propia pared de la esquina no cambia nada.

### Arreglado
- **Bajo un bloqueo de eje, las referencias se pescan a los DOS lados del
  inicio, y las que están a nivel también** (issue #34, @pacaeiro:
  «not all of them are detected… Origin not always detected, I think it
  is if the position of the Origin is negative from the other point… a
  point at the same level: no points are detected»). Medido con seis
  trazos alrededor del inicio y cinco cámaras, el cursor encima de cada
  uno: con el eje rojo fijado cada cámara perdía un trazo distinto; con
  el azul, los tres a la altura del inicio no salían nunca. La recta del
  bloqueo va en los dos sentidos, pero el lado permitido lo decidía dónde
  cortaba el RAYO del cursor a la recta, y con el cursor sobre una
  referencia lejos de la recta eso cae en cualquier parte. Ya no hay
  lado prohibido bajo bloqueo; y una referencia al nivel del inicio
  muestra su guía con el pie en el propio inicio («está a nivel»), y el
  clic ahí no dibuja nada (antes iba al historial como arista nula y
  volvía como deshacer ruidoso).
- **Shift sobre el eje suave también tiene snaps** (issue #34, punto 4:
  «suelto Shift para orbitar con el botón central, lo vuelvo a pulsar y la
  mitad de los puntos no se detectan»). Cuando la pulsación de Shift no
  encuentra nada que capturar y el cursor se alinea después con un eje,
  entra un tercer bloqueo —Shift sostenido sobre la inferencia suave—
  que no tenía NINGÚN snap: la #27 se los dio a las flechas y la #31 al
  Shift capturado. Los tres bloqueos comparten ahora un mismo cuerpo
  (`_lock_line_snaps`: cerrar la figura, vértice sobre la recta, cruce con
  otra arista, «desde el punto»). El arnés ganó la dimensión de bloqueos
  (flechas X/Z y Shift; 570 240 celdas).
- **Pulsar de nuevo la tecla de la herramienta la reinicia** (issue #34,
  punto 5): con una línea a medias, `L` suelta el primer punto y los
  bloqueos, como en SketchUp. Antes no hacía nada.
- **«Desde el punto» ya no se sale de la cara.** Con una esquina
  memorizada y el cursor sobre una cara, la línea del eje que pasaba por
  la esquina *por el aire* —paralela a esa cara, o atravesándola en
  diagonal— ofrecía su pie en el aire, un punto a metros de la pared a la
  que apuntaba el cursor; un rectángulo empezado ahí nacía fuera de su
  plano. Ahora la respuesta se queda en la cara: si la línea la atraviesa,
  el punto donde la atraviesa; si corre paralela fuera de ella, nada (y
  entra lo de arriba). Medido con la rejilla del arnés ampliada con una
  escena de tres paredes: 250 celdas cambian, todas con una esquina
  memorizada en otra pared; ninguna en las escenas planas de siempre.
- **Tirar de una caja con la cámara a ras de suelo: se frenaba en el
  horizonte y el clic sobre la cara superior no fijaba la altura**
  (Rafael, 0:40: «te bloquea aquí… hago clic aquí para que quede fijado y
  no me deja, tengo que venirme al lateral»). Las dos cosas eran una: el
  visor convierte cada píxel en un punto del mundo cortando un plano —a
  medio empuje, el suelo— y cuando el rayo no lo corta (por encima del
  horizonte, o rasante con la cámara baja) la herramienta no se entera de
  nada: ni del movimiento (la caja se congela) ni del clic (la tapa está
  donde está el cursor, así que ese clic se perdía; el lateral queda bajo
  el horizonte, por eso ese sí llegaba). Empujar/Tirar solo necesitaba el
  píxel, así que ahora le da al visor un plano que contiene su eje y mira
  a la cámara: el rayo siempre lo corta, la tirada sigue al cursor hasta
  donde llegue y el clic sobre la tapa comete.
- **Empujar hacia dentro no se veía en vivo con la cara invertida** (Marco,
  18-09): el empuje se hacía, pero durante el arrastre no aparecía nada. La
  vista previa esconde la cara base para que se vea el hueco que se forma
  detrás, y decidía «detrás» por el signo de la extrusión respecto a la
  normal de la cara — correcto solo cuando la normal mira al que dibuja.
  Mirando el reverso (una cara invertida, o un muro visto desde dentro de
  la habitación), empujar alejándose de la cámara salía «hacia fuera», la
  cara se quedaba y el hueco se formaba enterrado tras ella. Ahora lo
  decide la cámara: la base se esconde siempre que el barrido se aleja del
  ojo, esté la cara como esté.
- **Orientar una cara ya no lleva la textura al otro lado del muro.**
  Pregunta de Marco al ver una cara azul volverse blanca tras un empuje:
  «si tengo una casa con paredes, texturas exteriores diferentes a las
  interiores, hago push de adentro, ¿la textura cambiaría?». Cambiaba: la
  pasada automática de orientación (la que corrige una cara al revés al
  empujar, al cortar o al importar) invertía el sentido de la cara y la
  pintura de cada lado se iba con él — el ladrillo de fuera acababa
  dentro y el yeso de dentro, en la calle. Ahora una cara **pintada por
  los dos lados** conserva cada pintura en su lado; una pintada por un
  solo lado sigue la corrección, como hasta ahora (un rectángulo pintado
  que se tira hacia arriba sigue saliendo caja pintada por abajo). El
  «Invertir caras» del usuario no cambia: es el de SketchUp.
- **El cuadro de Texto 3D no aceptaba «20» de extrusión** (Rafael): pedía
  metros con un tope de 10 m, y nadie extruye un rótulo veinte metros.
  Altura y extrusión se piden ahora en **centímetros**.

## [0.4.5] — 2026-09-18

**Cuarenta y ocho minutos.** Eso tardó @pacaeiro en descargar la 0.4.4,
probarla y reabrir las dos issues que dábamos por cerradas. Tenía razón en
las dos, y en una de ellas me había leído mal a mí mismo.

### Arreglado
- **El bloqueo de eje se suelta cuando la LÍNEA existe** (issue #30), no
  cuando termina la operación. La herramienta Línea encadena, así que «la
  operación» es la polilínea entera — pero él habla del momento en que la
  línea está hecha: *«dibujo una línea con bloqueo de flecha y, después de
  crear la línea, el bloqueo sigue activo»*. La señal correcta es **si el
  clic creó geometría**, no si la herramienta quedó ociosa. Un clic que no
  crea nada —el primero de una línea— conserva el bloqueo, que es el único
  sitio donde sirve de algo.
- **El bloqueo con Shift ya tiene snaps** (issue #31). Con las flechas
  funcionaban y con Shift no: *«when I get an Axis and locked it with Shift,
  I do not have any Snaps»*. La issue #27 le había dado al bloqueo de flechas
  tres reglas —un extremo sobre la recta, el cruce con otra arista, y una
  esquina o punto medio proyectados sobre ella— y el de Shift se había
  quedado solo con la primera, y únicamente para un vértice que cayera
  exactamente encima. Ahora tiene las tres, y lee la recta en los dos
  sentidos. Su explicación es la que lo justifica: **Shift es el bloqueo que
  usas precisamente para fijar una dirección e ir a buscar un punto a otro
  objeto.**

## [0.4.4] — 2026-09-18

**La release de la inferencia, y casi toda salió de dibujar.** Marco se pasó
la tarde probando en vivo y encontró, uno detrás de otro, siete fallos que no
había visto ninguna prueba automática — incluida una rejilla de medio millón
de situaciones construida ese mismo día para vigilar justo eso. Se cierran
además las dos issues que @pacaeiro tenía abiertas.

### Arreglado
- **El bloqueo de eje dura una operación, no hasta que pulses Esc**
  (issue #30). Con la flecha fijas un eje, terminas la línea… y seguía
  puesto, así que la siguiente salía constreñida en silencio. Se suelta al
  terminar y también **al cambiar de herramienta**, que era una fuga peor
  que la reportada: un bloqueo tomado dibujando una línea seguía activo al
  pasar a Rectángulo.
- **Con un eje bloqueado ya se puede CERRAR la figura.** El clic sobre el
  punto de partida volvía como un punto de eje cualquiera, así que la
  polilínea nunca terminaba: parecía cerrada —el punto cae donde debe— y el
  bloqueo no se iba porque la operación seguía viva.
- **La inferencia de eje IMANTA de verdad** (issue #31). La barra decía «En
  eje rojo» y la línea salía dos o tres centímetros torcida: el rótulo
  prometía un imantado que no ocurría. De paso, el conmutador **Alt** ahora
  también apaga el de Mover, donde nunca había llegado.
- **La Línea alcanza el tercer eje** (issue #31, segunda parte). Cada vista
  ofrecía dos ejes y nunca tres —x/y en planta, x/z de frente— porque el
  cursor se convierte en punto apoyándose en el plano de trabajo, y un plano
  contiene como mucho dos de los tres. El que faltaba es el más perpendicular
  a la cámara, como precisó @pacaeiro. Con un tope para que el punto no se
  dispare: visto de punta, un eje ocupa poquísima pantalla y un temblor del
  ratón llegó a mandar un punto **a 16 km**.
- **Tres fallos de la misma familia con los puntos con nombre.** Una
  inferencia *derivada* de un punto le ganaba al punto del que salía, y eso
  desplazaba el dibujo unos centímetros sin avisar: (a) la línea de
  alineación de un punto adquirido tapaba el punto medio —clicar el medio de
  un muro caía 2,8 cm al lado—; (b) esa misma referencia moría al primer
  clic, justo cuando hace falta para sujetar el largo de un rectángulo a una
  esquina; (c) **pausar sobre un punto lo volvía inalcanzable**: al mirarlo
  lo adquirías y la recta «a través» te dejaba corto, sin llegar a él.
- **Los rectángulos nacen con la cara correcta.** Dos de las cuatro
  diagonales por las que puedes arrastrar daban la cara al revés —azul en
  vez de blanca— porque el contorno heredaba el signo del recorrido. Igual el
  rectángulo girado en sentido antihorario. No es cosmético: el reverso viaja
  al `.skp` y al etiquetado BIM.
- **Borrar ya no deja vértices huérfanos.** `remove_edge` solo desenganchaba,
  así que cada borrado dejaba sus vértices en el documento: invisibles, pero
  se guardaban en el `.igz` y se acumulaban. Cuando son lo único que queda,
  Zoom a extensión no tiene nada que encajar y te deja mirando el vacío.
- **El rectángulo dice la verdad cuando sale plano.** «Elige la esquina
  opuesta» era mentira cuando ya la habías elegido: el problema era el plano
  heredado de la cara bajo el cursor. Ahora lo distingue y nombra la flecha
  que sirve.
- **Los dos rótulos del visor salen en tu idioma.** «X axis locked» nunca
  pasaba por el traductor y el del estado del Alt llevaba el español escrito
  a mano — cada uno roto en una dirección.

### Para quien mantenga esto
`scripts/probe_snap_matrix.py` congela lo que responde el motor de
inferencia en **513 216** situaciones (11 cámaras × 3 escenas × 6
herramientas × 3 estados de Alt × con y sin punto adquirido × antes y
después del primer clic × 3 radios × 72 direcciones) y se reproduce byte a
byte. Nació con 57 024 y hubo que ensancharla **cuatro veces** en una tarde,
cada vez porque no podía ver un fallo que la mano ya había medido. La
lección quedó escrita en su cabecera: una red no demuestra nada sobre una
forma que no sabe sostener.

## [0.4.3] — 2026-09-17

**La release de openskp 1.3.0 y de los cuatro reportes de Pedro Caeiro.**
El lector de SketchUp pasa de nuestro fork a la versión oficial 1.3.0, y
con ella un modelo que llevaba tiempo sin abrir —`edificio.skp`, de
SketchUp 8— abre. Se midió archivo por archivo antes de dar el salto: 214
del corpus de Marco, 212 idénticos, uno rescatado, ninguno perdido, y el
`.skp` que exportamos sale byte a byte igual a través del SDK de Trimble.
Lo demás son las cuatro issues que @pacaeiro abrió probando IngeTrazo
como si fuera SketchUp, y la vista en perspectiva que Marco pidió para sus
láminas.

### Añadido
- **Una lámina puede llevar una vista en PERSPECTIVA, con su propio sol.**
  Hasta ahora todo marco era paralelo: bueno para plantas y cortes, pero
  una isométrica no se ve «como en campo». El marco tiene ahora casilla de
  perspectiva con distancia de cámara y ángulo de visión, y sombras e hora
  propias, independientes del modelo. En perspectiva no hay escala, así que
  el rótulo dice «SIN ESCALA» en vez de inventar un 1:N.
- **Girar + Ctrl: «3x» y «/3» reparten copias en círculo** (issue #24). La
  matriz polar de SketchUp, hermana de la que Mover estrenó en la 0.4.2:
  con Ctrl pulsado, teclear `3x` deja tres copias a múltiplos del ángulo y
  `/3` tres que lo dividen. Re-teclear rehace la matriz y todo cabe en un
  solo deshacer.
- **Ctrl en la Cinta y el Transportador: medir, o medir Y marcar**
  (issue #29). En la Cinta, Ctrl recorre los tres modos de SketchUp —líneas
  guía, puntos guía, medida sola— y los puntos guía son una entidad que no
  teníamos. En el Transportador alterna guía sí/no. Es un modo, no un
  modificador de un solo clic: se mantiene entre operaciones y vuelve a
  guías al recoger la herramienta, como el original. El `+` junto al cursor
  dice en cuál estás antes de hacer clic, que en SketchUp es toda la
  interfaz de este conmutador.
- **La barra de estado lleva los modificadores de la herramienta**, no solo
  su nombre: la Cinta muestra «Ctrl = [líneas guía] / puntos guía / medida»
  con el modo activo entre corchetes, y durante una operación aparece el
  «Alt = inferencias (…)» con su estado. Uno por fase, que es como lo hace
  SketchUp — apilarlos no cabía en la barra.
- **Las personas de fuera del proyecto cuyo trabajo está dentro, acreditadas**
  en `AUTHORS`, en el README y en Ayuda ▸ Acerca de IngeTrazo: Pedro
  Caeiro (@pacaeiro) por los reportes y el PR #21, Rafael García Rodríguez
  por la revisión y las sugerencias, y Ahsan Mehmood por openskp.

### Arreglado
- **Exportar todas las láminas a PDF ya no se deja una fuera.** Marco
  exportó las cuatro de Plaza Yanque y salieron tres: la cuarta moría con
  `setUniformValue(15, None)`, la exportación se abortaba desde dentro del
  manejador del clic y Qt cerraba el PDF con lo que llevaba, sin decir nada
  en pantalla. El mapa de sombras se guarda en caché y al reutilizarlo no
  se reponía su matriz de luz. Además el atlas ya no pierde un documento
  entero por un marco malo: lo imprime como «actualiza la vista», sigue y
  al terminar nombra las láminas que hay que mirar.
- **openskp 1.3.0, la versión oficial** (antes iba pineado a nuestro fork).
  Con ella abre `edificio.skp`, de SketchUp 8, que caía en el lector de
  archivos grandes. Verificado sobre 214 archivos del corpus de Marco:
  212 idénticos, ese rescatado, ninguno perdido. El que queda no abre con
  ninguna de las dos versiones y no cuenta como corpus: es salida de
  nuestro propio exportador de cuando estaba roto, y el SDK de Trimble
  también lo rechaza. Y la exportación a `.skp`
  produce el mismo archivo medido con el SDK de Trimble (179 trozos, 35
  materiales, 147 componentes en ambos sentidos).
- **Los snaps funcionan en las dos direcciones con un eje bloqueado**
  (issue #27). Con el eje rojo fijado, la misma esquina se imantaba viniendo
  por la izquierda y no por la derecha: la rama del bloqueo pasaba el eje
  como vector positivo dibujaras hacia donde dibujaras, y se descartaba todo
  lo que quedaba «detrás». Y el origen del mundo no estaba en ninguna lista
  de referencias, así que con un eje bloqueado solo existía si alguna
  geometría lo tocaba por casualidad.
- **La Cinta saca una guía de una arista que está DENTRO de un grupo o
  componente** (issue #28). Preguntaba por la malla suelta, así que un clic
  en la arista de un componente no encontraba nada y se quedaba midiendo.
- **Alt ya no roba las inferencias al cambiar de ventana** (issue #26).
  @pacaeiro usa Alt+Tab todo el día y cada vez perdía las inferencias.
  Ahora la tecla solo actúa con una operación en marcha, que es cuando
  SketchUp la ofrece, y el conmutador dura esa operación y no la sesión.
  Se actúa en la PULSACIÓN y se traga la suelta: es la suelta la que hace
  que la barra de menús tome el foco, y por ahí se perdían cinco de cada
  seis toques.
- **Exportar ▸ SketchUp con un grupo clásico dentro de un contenedor** ya
  no revienta: sin matriz propia, la colocación es la identidad.
- **Una capa apagada en el archivo .skp llega apagada.** Se leía un atributo
  que no existe en openskp, así que todas entraban visibles.
- **Las guías quedan tapadas por la geometría que tienen delante**
  (issue #23), en vez de atravesarla.
- **El Transportador y Girar enseñan la inclinación mientras arrastras**
  (issue #25), no solo al soltar.

## [0.4.2] — 2026-09-16

**Lo que pidió Pedro Caeiro, y exportar a SketchUp otra vez.** @pacaeiro,
delineante, prueba IngeTrazo como si fuera SketchUp y anota cada gesto que
no responde igual: aquí caen sus cuatro pendientes de inferencia y
herramientas, todos paridad con SketchUp. Y el arreglo que no podía
esperar: Exportar ▸ SketchUp moría en el .exe, el AppImage, el tar y el
snap.

### Añadido
- **Mover + Ctrl copia, y «3x» / «/3» hacen una matriz** (issue #20). Un
  toque de Ctrl durante Mover deja el original quieto y estampa una copia
  trasladada en el segundo clic (la copia se previsualiza como alambre; una
  instancia de componente se copia como hermana, O(1)). Justo después,
  tecleando `3x` (o `3*`, `*3`) salen tres copias a múltiplos de la
  distancia, y con `/3` (o `3/`) tres copias que la dividen; re-teclear
  rehace la matriz y todo cabe en UN deshacer. La ventana se cierra con el
  siguiente clic, Esc o cambio de herramienta. La «x» solo entra en el
  cuadro de valores después de un dígito: sola sigue siendo el atajo de
  Texto.
- **La cinta métrica saca una guía a partir de otra guía** (issue #22).
  Clic en el cuerpo de una guía y tirar (o teclear la distancia) coloca una
  segunda guía paralela: así se traza una retícula. Antes solo valían las
  aristas de la malla, porque el selector de la cinta no veía guías. El
  cruce de dos guías (la X verde) es un punto y mide en vez de tirar.
- **El transportador se inclina con clic y arrastre** (issue #10). Como en
  SketchUp: clic en el vértice y arrastre fijan el eje del instrumento a lo
  largo del arrastre, fuera de los planos ortogonales; el ángulo se mide y
  la guía se coloca en ese plano inclinado. Rotar ya tenía el gesto; ahora
  lo comparten. Un clic seco conserva el plano inferido.
- **Flecha «abajo»: el círculo perpendicular a una arista** (issue #10,
  segunda parte). El bloqueo magenta de SketchUp (2016+) en el círculo, el
  polígono, el rectángulo, el rectángulo girado y los arcos: antes del
  primer clic, `↓` con el cursor sobre una arista fija el plano de dibujo
  perpendicular a ella, y sobre una cara, paralelo a ella; `↓` otra vez lo
  libera y una flecha de eje lo sustituye. El anillo del cursor se pinta
  magenta mientras dura. Es el flujo de las tuberías de Pedro: la línea
  inclinada del eje, `↓` sobre ella, centro en su extremo, radio y Sígueme,
  sin rotar el círculo después.

### Arreglado
- **Exportar ▸ SketchUp volvía «[Errno 2] No such file or directory:
  …\_internal\openskp\_scaffold\blank_v17.skp»** en el instalador de
  Windows, el AppImage, el tar y el snap (solo el Flatpak se salvaba).
  openskp escribe cada .skp sobre un andamio que carga como dato del
  paquete, y el empaquetado llevaba sus módulos pero no sus datos; roto
  desde la 0.3.5, reportado desde Windows con la 0.4.1. Ahora se incluyen
  los datos y el `--check` de cada paquete exige el andamio, así que la CI
  del release atrapa esta clase de olvido.
- **Mover y Rotar ya no infieren contra sí mismos** (issue #19). Lo que se
  está arrastrando o girando queda fuera de los candidatos del snap —como
  hace SketchUp con las entidades en movimiento—, así que arrastrar una
  cara a lo largo de un muro ya no se pega a las esquinas de la propia
  cara. En modo copia el original no se mueve y no se excluye nada.
- **Dos guías que se cruzan vuelven a dar su intersección** (PR #21 de @pacaeiro, issue #18). El motor de
  snaps solo fabricaba el punto «intersection» con una línea de bloqueo
  activa (una flecha de eje, un trazo perpendicular, una extensión), así
  que el cruce de dos guías —que no propone dirección alguna— nunca se
  ofrecía: el cursor resbalaba por la guía más cercana («on_edge») y el «X»
  verde no aparecía, aunque una guía sola sí se podía snapear. Ahora se
  recogen las aristas que pasan bajo el cursor y se cruzan de dos en dos en
  3-D —por debajo de los vértices y de los bloqueos, por encima del punto
  medio y del borde—. Una guía sola sigue dando «on_edge»; las paralelas y
  las que se cruzan solo en proyección (separadas en el espacio) no
  inventan un punto.

## [0.4.1] — 2026-09-15

### Arreglado
- **El origen gana a las inferencias lineales**: al acercarte al origen del
  dibujo alineado con un punto «animado» o con el eje rojo, el clic caía a
  milímetros del origen (proyección sobre el eje) y quedaban tramos
  diminutos; el origen es un punto con nombre, como una esquina, y ahora
  manda sobre «Desde el punto» y el eje.

## [0.4.0] — 2026-09-15

**La inferencia a la altura de SketchUp, el visor más rápido, y las tres
herramientas que faltaban.** Revisión 1 de Rafael (partes B y C) y una tarde
de mediciones sobre la plaza de Yanque.

### Añadido
- **Asistente IA con recetas de arquitectura**: `house(...)` levanta una
  casa completa en una sola llamada (muros con espesor, puertas con hoja,
  ventanas con vidrio, piso, techo a dos aguas, a cuatro aguas o plano, con
  alero), y `wall(...)` / `prism(...)` para muros con vanos y losas; el
  modelo lo sabe y hace los pedidos sencillos en un solo turno. Un modelo
  que «cuenta» lo que hizo sin mandar código recibe un toque y los sistemas
  agénticos de Groq (compound) ya no se ofrecen. Las capturas viajan en JPEG
  de 640 px (un cuarto de los tokens de antes).
- **Redondear (fillet)** — la herramienta que SketchUp no tiene. Clic en una
  arista (o las aristas seleccionadas), mueve el cursor para fijar el radio o
  tecléalo, clic: la arista se convierte en una tira tangente a las dos caras;
  las tapas reciben el arco, las aristas encadenadas (el borde de una losa) se
  unen a inglete y en las esquinas de tres aristas (una caja) aparece el
  parche esférico. Cóncavas también. Lo que no se puede redondear lo dice y no
  toca el modelo. «Ns» fija los segmentos.
- **Posicionar textura** (clic derecho en una cara con imagen ▸ Textura ▸
  Posicionar): los cuatro pines de SketchUp — rojo mueve, verde escala y
  rota, azul escala y cizalla —, la textura semitransparente con su retícula
  de baldosas, levantar un pin con un clic para clavarlo en una esquina, menú
  interno Listo / Restablecer / Voltear / Girar / Deshacer, Enter termina y
  Esc restaura. Textura ▸ Restablecer posición vuelve a la proyección por
  defecto. (El pin amarillo de perspectiva se muestra pero aún no se arrastra.)
- **La textura envuelve las superficies curvas**: al pintar un cilindro o
  una esquina redondeada, la imagen se apoya en la faceta clicada y va
  girando de faceta en faceta alrededor de cada arista suave, así que los
  ladrillos continúan sin cortes ni saltos (antes cada faceta proyectaba por
  su cuenta).
- **La muestra de una textura posicionada viaja a otras caras**: el
  cuentagotas sobre una cara con la textura escalada o girada con los pines
  y el cubo sobre otra cara de distinto plano aplican el mismo tamaño de
  baldosa y el mismo giro (las caras coplanarias siguen recibiendo la
  posición exacta).
- **Arco que redondea esquinas como SketchUp**: al empezar sobre una arista la
  vista previa es el arco tangente (cian, «Tangente a la arista»); en la arista
  contigua, a la misma distancia del vértice, se clava y se vuelve magenta;
  doble clic ahí dibuja el arco y **recorta la esquina sola**; doble clic
  cerca de otra esquina repite el mismo radio; Alt deja los tramos.
  «Semicírculo» en la fase de curvatura y «Ns» segmentos (también rehace el
  arco recién dibujado).
- **Inferencia como en SketchUp**: rectángulo, círculo, polígono y arcos
  dibujan en el plano más perpendicular a la vista (de pie junto al
  horizonte, planos al orbitar arriba) y **enseñan el plano en el cursor**
  (anillo o cuadradito, en el color del eje con las flechas); **«Desde el
  punto» antes del primer clic** con puntos «animados» al pausar ¼ s sobre
  una esquina o un centro, y **dos puntos a la vez** (el cursor se clava en
  el cruce de sus punteadas); **Tangente en el vértice** para arcos que nacen
  en el extremo de otro; **Punto medio del arco**, **Origen del componente**,
  guías rotuladas «Sobre la línea»; todo alcanza a grupos y componentes
  anidados desde fuera, con el rótulo «… en componente». Empujar/Tirar infiere
  «En arista» además de esquinas y caras.
- **Servidor gráfico automático**: en Wayland con un solo monitor a escala
  fraccionaria (125 %) el visor arranca por X11 (XWayland), que en esa
  combinación pinta sin tirones (p90 149 → 30 ms medido); con dos monitores
  o escala entera se queda en Wayland. Preferencias ▸ General ▸ Servidor
  gráfico: Automático / Wayland / X11.
- Bancos de pruebas `scripts/bench_nested.py` (editar anidados) y mediciones
  de arrastre.

### Arreglado
- **Empujar una pieza del borde hasta la cara opuesta la elimina** (la
  esquina que deja un arco de redondeo, empujada hasta el fondo): la cara
  trasera se recorta con el arco y no queda la tapa; antes solo se
  perforaban aberturas interiores y el trozo del borde quedaba como una
  lámina pegada al fondo. Si te pasas, el empuje se detiene justo en la cara
  opuesta y recorta igual.
- **El asistente IA reintenta cuando el proveedor está saturado** (el 503
  «high demand» de Gemini dejaba una casa en las paredes): hasta cuatro
  reintentos con espera creciente, avisando en el panel; los errores reales
  (clave inválida) siguen cortando al momento.
- **El puente MCP dice que sirve con cualquier cliente MCP** (Claude Code,
  Claude Desktop, Cursor, VS Code, Windsurf, Gemini CLI, Codex CLI…) y dónde
  pega cada uno el bloque; el manual igual.
- **Bloquear un eje con la flecha ya lee la referencia bajo el cursor** (B3
  de Rafael, 04:20): Medir desde la arista inferior del muro, ↑, y el cursor
  sobre la esquina o el alféizar de la ventana → la guía toma esa altura,
  con la punteada «Desde el punto». Antes había que acertar con el pie sobre
  la propia línea bloqueada.
- **Paquetes Linux en NVIDIA (issue #6, seguía en la 0.3.19)**: el tarball
  y el AppImage llevaban la `libstdc++`/`libgcc_s` del runner de CI y GLib;
  cargadas antes que el driver, un NVIDIA compilado contra un runtime más
  nuevo no podía cargar y Qt abortaba en GLX sin decir por qué. Ya se usan
  las del sistema (como hace la lista de exclusión de AppImage), y el
  sondeo de OpenGL imprime el mensaje fatal en vez de tragárselo.
- **Dibujar sobre la cara de un componente anidado** (el poste de la pérgola):
  el plano se leía en las coordenadas del prototipo — normal invertida y
  punto en otro sitio — y el rectángulo salía fuera de la cara. Ahora toda
  lectura de plano pasa por la colocación con su matriz compuesta.
- **Doble clic dentro de un contenedor abierto** no entraba en el siguiente
  nivel (el índice de picking seguía respondiendo «la plaza»).
- **Esc no salía del grupo**: el atajo Esc del menú Herramientas se disparaba
  antes que el visor con una cascada sin ese paso. Una sola cascada.
- **Pegar/insertar mientras se edita un contenedor** iba a la raíz; ahora
  entra en el contenedor (y Deshacer lo quita de ahí).
- Un error interno al pasar el ratón con aristas sueltas junto a un
  componente mataba el movimiento (los clics «no hacían nada»).
- Rectángulo de lado cero: se rechaza con aviso en vez de fallar y revertir.
- Pegar coloca en el plano de la referencia (antes solo sobre caras o al suelo).

### Rendimiento (plaza de Yanque, mediana)
- Mover el ratón con una herramienta: **1004 → 493 ms por 60 movimientos**
  (los candidatos de snap se comprueban por oclusión en orden de distancia
  hasta el primero visible).
- Entrar en el contenedor de la plaza **473 → 126 ms**; mover un hijo dentro
  **460 → 100 ms** (envolvente convexa con prefiltro de 16 direcciones y
  arrays de puntos por prototipo).
- Confirmar una edición **32 → 22 ms**; arrastre de Mover **67 → 42 ms** por
  cuadro; Empujar/Tirar 9 ms (una «época de colocaciones» sustituye a la
  versión de la escena como clave de las cachés del lado de los grupos, y los
  chunks aceptan mallas intactas en O(1) por contador de mutación).
- Barra de estado a ~12 actualizaciones/s (cada cambio de texto volcaba la
  ventana entera); recolector de basura con umbral 50 000 (pausas de 80 ms
  → 0; `gc.freeze` medido y descartado).
- **Pendiente para modelos mayores**: la parte suelta del índice de picking
  por cuadro (~11 ms) y la caja del grupo editado (~9 ms) en los arrastres.

### Cambiado
- **Barra de estado a la SketchUp**: una sola pista para la herramienta y el
  paso en que está («Clic en el punto final, o teclea la longitud y Enter…»),
  en vez de la tira con todos los atajos a la vez.
- **La bandeja aprovecha el ancho**: las muestras de materiales y los
  botones de componentes fluyen en tantas columnas como quepan al ensanchar
  la barra lateral (antes, 5 y 3 fijas con la mitad derecha en blanco).
- Iconos de las barras: **Normal (24 px)** por defecto (Grande queda como
  opción).
- Los puntos de componentes ya no se pintan en magenta (el rótulo sigue
  diciendo «en componente»).

## [0.3.20] — 2026-09-14

**El ortomosaico, las etiquetas con varias flechas y la cara nueva de las
barras.** Una sesión entera sobre las láminas de la plaza de Yanque: el
ortomosaico del dron entra como GeoTIFF sin instalar nada, las escenas
recuerdan el mapa y el sol, las etiquetas del compositor señalan dos o tres
cosas con un mismo texto, y las barras de herramientas estrenan iconos
dibujados uno a uno con Marco, tamaño configurable y una barra lateral
que se pliega como en LibreOffice. También la primera tanda de la revisión
de Rafael: capturas en la tienda, icono del AppImage y el «Abrir» de GNOME
Software.

### Añadido
- **Importar ▸ Ortomosaico (GeoTIFF).** El lector propio (`georef/geotiff.py`)
  lee la cabecera —escala de píxel y punto de amarre o matriz, zona UTM por
  las GeoKeys o por la cita, PixelIsPoint— y descodifica los píxeles sin
  GDAL ni Pillow: sin comprimir, Deflate, PackBits, LZW (filas de teselas
  repartidas en procesos) y JPEG dentro del TIFF, reduciendo al vuelo hasta
  el techo de textura. La imagen aterriza sobre el datum a su tamaño y en su
  sitio, como imagen de referencia bloqueada. Medido: 3 MB JPEG 0,1 s;
  170 Mpx Deflate 6,8 s; 665 Mpx LZW 33 s.
- **Opacidad de imágenes y del mapa base.** Clic derecho sobre una imagen
  para darle transparencia (deshacible); el mapa base tiene su deslizador
  en Terreno y se guarda en el `.igz`. El clic derecho alcanza a una imagen
  BLOQUEADA (Desbloquear / Eliminar) aunque haya geometría dibujada encima:
  antes un escaneo bloqueado no volvía a seleccionarse nunca.
- **Las escenas recuerdan el mapa base, el terreno, el levantamiento y las
  sombras** tal como se capturaron, y los marcos de las láminas se renderizan
  con eso mismo: una escena sin mapa sale sin mapa en la lámina, una con
  sombras sale con sombras. Las escenas anteriores a estos campos no tocan
  nada.
- **Etiquetas con varias flechas en el compositor.** El segundo clic de la
  herramienta Etiqueta sobre una etiqueta existente le añade otra flecha
  (anclada al modelo si el punto se pegó a un marco); Ctrl+arrastrar una
  punta saca una nueva; soltar una punta sobre las letras la quita. Un punto
  donde cada guía sale del texto (casilla en el panel). La esquina de la
  etiqueta redimensiona el ancho de ajuste, que estaba dibujado pero inerte.
- **Fondo de las etiquetas y textos pegado a las letras**: ancho por la línea
  más ancha, alto por los glifos (0,25 × tamaño sobre las mayúsculas para las
  tildes, 0,05 × bajo el último descendente), líneas apiladas al paso real del
  pintor; margen lateral 1,0 → 0,5 mm.
- **Plumas ráster en las láminas**: los marcos ráster toman los grosores de
  Aristas y Perfiles del estilo (el render redibuja las líneas GL con
  desplazamientos subpíxel hasta el grosor de la pluma); un píxel a 300 ppp
  era un pelo de 0,085 mm que casi no se veía.
- **Iconos nuevos** en las barras, elegidos entre propuestas dibujadas:
  cuentagotas al estilo Inkscape, Empujar/Tirar como losa con flecha maciza,
  las vistas estándar como una misma casita a dos aguas con la pared que se
  mira en naranja, la mano de desplazar como gesto de arrastre, las
  herramientas de dibujo con sus puntos y guías de construcción, rectángulo
  girado con sus tres clics, Cota con puntos, líneas de extensión y un «3»,
  Estilo de cota con brocha, secciones mínimas (caja, plano punteado, borde
  de corte, relleno), cinta métrica espejada, y las órdenes de Organizar del
  compositor en el mismo estilo.
- **Tamaño de los iconos como Preferencia** (Ventana ▸ Preferencias ▸
  General ▸ Iconos de las barras: 20/24/32/40 px), aplicado en vivo a todas
  las barras de la ventana del modelo Y del compositor. Por defecto 32 px, y
  la distribución de barras de fábrica es la de Marco (Dibujar y Anotar a la
  izquierda, el resto arriba); un perfil que ya guardó la suya la conserva.
- **Barra lateral plegable como en LibreOffice**: una manija sobre la línea
  donde se redimensiona la barra de la derecha, a media altura; clic pliega
  las tres bandejas (Propiedades, BIM, Terreno) y otro clic las devuelve;
  Ctrl+F5 o Ventana ▸ Barra lateral hacen lo mismo. Igual en el compositor
  con su panel derecho.
- **Pantalla limpia (Ctrl+0) con botón de salida** arriba a la derecha, para
  quien no conoce el atajo; también en el compositor (oculta barras, panel,
  reglas y barra de estado).
- **Las barras del compositor se pueden mover** y su distribución se guarda
  al cerrar; una instalación nueva ve la de fábrica: las 14 herramientas de
  elementos de lámina a la izquierda y, arriba, Lámina → **Dibujo** (barra
  nueva con línea, flecha, terreno, rectángulo, elipse, polígono y las tres
  cotas: 23 iconos en una sola columna no cabían en una laptop) →
  Organizar, que ahora se muestra por defecto.
- **Tamaño de icono según la pantalla** en una instalación nueva: 32 px con
  900 px o más de alto disponible, 24 px en pantallas menores (medido:
  a 32 px la distribución de fábrica desborda una laptop de 1366×768).
  Lo que el usuario elija en Preferencias manda siempre.
- **Botón de desbordamiento de las barras** con doble flecha naranja y
  tooltip «Más herramientas de esta barra»: cuando una barra no cabe, Qt
  esconde el resto tras un botón que en tema oscuro era un bloque gris sin
  flecha visible.
- **Tienda y escritorio (revisión de Rafael, parte A):** el metainfo lleva
  seis capturas con pie en los dos idiomas (GNOME Software mostraba «Sin
  capturas»); dentro del Flatpak la ventana declara el id de la app como
  archivo `.desktop`, para que el shell la asocie a su lanzador; el AppImage
  se ofrece a instalar su lanzador e icono en el menú de aplicaciones la
  primera vez (`core/appimage.py`; Ayuda ▸ Añadir/Quitar del menú).

### Arreglado
- **Sombras con una imagen translúcida activa**: al orbitar aparecía un
  agujero blanco bajo el modelo. El pase de imágenes apagaba el blending
  tras una imagen desvanecida y no lo reencendía, y el receptor de sombras
  escribía alfa 0 sobre el suelo en cada cuadro que reutilizaba el mapa de
  sombras. El blending es ahora estado del cuadro (test con GL real).
- **La pestaña Diseño del compositor saltaba a propiedades del elemento**
  con cada clic en las flechas de un cuadro numérico; solo salta cuando se
  selecciona un elemento DISTINTO.
- **El editor en sitio de las etiquetas** tenía un margen de documento de
  1,5 mm que descolocaba y reajustaba el texto de otra manera; sin margen y
  con tarjeta opaca.
- **Enderezar modelo** avisa cuando el grupo seleccionado no está girado ni
  movido en lugar de no hacer nada en silencio.
- **Listas de las bandejas sin scroll dentro del scroll**: Capas, Escenas,
  Componentes en el modelo y la tabla BIM crecen a sus filas; el único
  scroll es el de la bandeja.
- **Guardar** es el primer botón de la barra Principal del modelo, como en
  el compositor.

### Cambiado
- Orden de la barra Modificar: Empujar/Tirar, Mover, Rotar, Escalar,
  Simetría, Sígueme, Equidistancia. Orden de las vistas estándar: iso,
  superior, frontal, derecha, izquierda, posterior, inferior.
- El manual de trampas del AI Bridge: nunca reemplazar en caliente un
  método virtual de Qt (`paintGL`, `boundingRect`, `eventFilter`…) en una
  clase viva; solo métodos normales, y relanzar para el resto.

## [0.3.19] — 2026-09-14

**El norte del proyecto.** La plaza de Yanque, dibujada a escuadra con los
ejes, se había girado 33,5° como grupo para encajar en el satélite — y las
vistas Frontal, Derecha e Izquierda dejaron de significar nada. Esta
versión hace lo que SketchUp: el modelo se queda en sus ejes y el que gira
es el mapa. Y llegan los tres primeros arreglos de un colaborador externo,
@pacaeiro, con sus issues: el bloqueo de eje con Shift, las guías
punteadas y los iconos grandes.

### Añadido
- **Norte del proyecto: el mapa gira bajo el modelo, no el modelo bajo el
  mapa.** En el panel Terreno/Mapa base, el campo **Norte** dice hacia dónde
  queda el norte verdadero, en grados en sentido horario desde el eje verde
  (0° = el verde apunta al norte; la misma convención que Solar North de
  SketchUp). Al cambiarlo giran por debajo el mapa base, el terreno 3D, las
  rutas y puntos importados, la lectura UTM de la barra de estado y el sol
  de las sombras; el modelo no se toca, así que las vistas estándar, los
  bloqueos de eje y el rectángulo siguen a escuadra. Se guarda en el `.igz`
  (clave `north`, solo si no es 0: los documentos y lectores anteriores no
  ven nada nuevo).
- **Enderezar modelo sobre el mapa.** Para un modelo que ya se giró y
  arrastró como grupo para encajar en el sitio: se selecciona ese componente
  y con un botón vuelve a sus propios ejes, el origen pasa a su esquina y el
  ángulo del norte queda calculado, de modo que ningún punto cambia de
  latitud/longitud. Viajan con él los demás grupos, la geometría suelta, las
  cotas, textos, guías, planos de sección, imágenes, rutas y puntos, las
  escenas guardadas y los marcos y cotas ancladas de las láminas. Un paso de
  deshacer. Un modelo inclinado o escalado se rechaza (no hay norte para
  eso); la parte vertical de la colocación se descarta, porque el mapa solo
  puede estar en z = 0.
- **Iconos grandes en las barras** (@pacaeiro, #15): clic derecho sobre una
  barra ▸ «Iconos grandes en las barras» pasa de 24 a 32 px; se recuerda
  entre sesiones y viene apagado.

### Arreglado
- **Shift bloqueaba una dirección torcida** (@pacaeiro, #13): con la
  inferencia de eje activa, Shift capturaba la dirección del cursor —unos
  grados fuera del eje— en vez del eje X, Y o Z exacto. Ahora bloquea el
  eje inferido, conservando el sentido.
- **Las guías de construcción salían a línea llena en vez de punteadas.** La
  Cinta de medir trazaba sus guías continuas, sin el punteado fino de
  SketchUp. El lápiz siempre fue `Qt.DashLine`: lo que fallaba era la ESCALA.
  Una guía se recorta en `_clip_segment_front` justo delante del plano de la
  cámara (con `w = 1e-3`), de modo que su extremo se proyecta a MILLONES de
  píxeles del origen, y el trazador de trazos de Qt —que trabaja en punto
  fijo— colapsa el patrón a una línea sólida a esa distancia. Medido con una
  sonda sobre un `QOpenGLWidget` real: un segmento de 400 000 px todavía
  puntea (8 huecos), uno de 4 000 000 px sale lleno (0 huecos), y da igual el
  color o el grosor del lápiz. Arreglo: `_clip_pixel_line` recorta el
  segmento —en espacio de píxel, por Liang-Barsky— a la ventana ANTES de
  dibujarlo, de forma que el `drawLine` nunca recibe más que la diagonal de la
  vista y el punteado se conserva; de paso el rasterizador deja de generar
  cientos de miles de trazos que iba a descartar. Vale para las guías
  (`_draw_guides`) y para la línea punteada de inferencia del snap
  (`_draw_snap_indicator`), los dos únicos trazos punteados de extensión
  ilimitada del visor: la caja de selección, los contornos de imagen y los
  planos de sección viven dentro de la pantalla y no sufrían esto.

## [0.3.18] — 2026-09-12

**Mobiliario en la plaza.** La segunda sesión sobre la Plaza Yanque: los
grupos anidados como los hace SketchUp, la pileta, el arco, la luminaria y
el campesino traídos de sus propios archivos como componentes, y las caras
con dos lados. Casi todo lo de abajo lo reportó Marco usándolo, con captura
o con el modelo vivo delante; el rendimiento se midió antes de publicar
(`scripts/bench_session.py`): +0,3 ms por cuadro, nada que se sienta.

### Añadido
- **Grupos anidados, como en SketchUp.** Un grupo puede contener grupos, y
  se entra a ellos por niveles: doble clic para bajar, Esc o clic afuera
  para subir uno, con la ruta a la vista en la barra de estado («Editando
  Plaza ▸ Jardinera ▸ Banca»). Dentro de un grupo, un clic selecciona a su
  HIJO —no al contenedor entero— y no se puede agarrar el resto del modelo.
  «Crear grupo» ya no se niega cuando hay grupos en la selección: los adopta,
  y la parte suelta pasa a ser la malla del contenedor, como SketchUp.

  Hasta ahora entrar a un contenedor lo **horneaba**: sus hijos se fundían
  en una sola malla. Marco lo vivió con su plaza — nueve grupos convertidos
  en 17 577 caras de una sola pieza, perdiendo de paso los nueve chunks
  independientes y el instanciado. El modelo de datos ya sostenía el árbol
  desde agosto; lo que faltaba era la edición por niveles, y es esto.
- **Importar otro documento .igz como componente.** Archivo ▸ Importar ▸
  «Documento IngeTrazo como componente (.igz)…»: el archivo entero llega
  como UN componente que se coloca con un clic, como el Import de un .skp
  en SketchUp — la pérgola, el arco y la luminaria dibujados en sus propios
  archivos entran en la plaza con sus grupos (anidados, como estaban), sus
  materiales y sus capas. Se sostiene por su origen, así que las zapatas
  dibujadas bajo el suelo quedan bajo el suelo. Los face-me del archivo
  vienen con él (el torito sobre el arco); solo el muñeco de escala de la
  app se queda fuera. Un material cuyo nombre ya usa OTRA receta entra como
  «nombre (2)».
- **El .igz conserva los nombres de los grupos.** Nunca los escribía: cada
  documento reabierto renumeraba sus grupos y una «Pérgola» volvía como
  «Group 7» (pendiente conocido). Los nuevos no repiten un número guardado.
- **Inferencia «Centro», como en SketchUp.** Al pasar el cursor por la
  cara de un círculo (la tapa de un cilindro, un pavimento con un arco en
  el borde, un hueco circular) o por la arista de la curva, el centro
  queda marcado con un punto verde y el cursor snapea a él («Centro») para
  dibujar, acotar o mover. Vale para curvas dibujadas aquí y para las
  importadas, que no traen id de curva: se leen por sus segmentos suaves o
  por su forma. La referencia se queda hasta que otro círculo la sustituye
  o cambias de herramienta.
- **Dentro de un grupo, el resto del modelo sigue siendo referencia.** Mover
  una jardinera anidada hasta la esquina del pavimento de afuera no daba el
  punto verde: el índice de picking solo conocía el grupo abierto. Ahora
  lleva el modelo entero — lo de afuera atenuado se puede snapear y tapa lo
  que queda detrás, como en SketchUp, y sigue sin poderse seleccionar. Con
  «Ocultar» el resto del modelo, lo que no se dibuja tampoco atrae al
  cursor.

- **Las caras tienen dos lados, y se pinta el que se clica.** Como en
  SketchUp: el cubo pinta el lado bajo el cursor, y el otro conserva el
  color de reverso del estilo (el azul grisáceo que delata una cara al
  revés). Un material translúcido —cristal, agua, una malla raschel, una
  hoja calada— se ve igual por los dos lados, también como en SketchUp.
  Hasta ahora toda pintura aparecía por los dos lados («si a una cara le
  aplico un color o textura también se aplica a su revés», Marco). El
  cuentagotas toma el lado que muestreas; el `.igz` guarda el reverso
  propio; el import `.skp` respeta lo que cada lado tiene pintado y el
  export escribe lo mismo; los modelos OBJ/DAE/glTF, que no tienen lados,
  llegan como caras de dos lados. Documentos anteriores: las caras
  pintadas desde IngeTrazo muestran ahora el reverso por defecto — para
  pintarlo, se pinta desde atrás.

### Arreglado
- **Dentro de un contenedor: borrar, caja de selección y Seleccionar todo
  alcanzan a sus hijos.** Suprimir un hijo buscaba el grupo en la lista
  raíz, no lo encontraba y el comando se anulaba en silencio; la caja se
  saltaba todos los grupos dentro de un contexto; Seleccionar todo tomaba
  los grupos de la raíz. Marco lo vivió con una pileta dentro de un
  componente importado: «quiero seleccionar toda esa pileta, no
  selecciona; quiero eliminar, tampoco puedo».
- **La caja punteada de un contenedor sigue a sus hijos.** Al entrar a un
  componente importado el marco salía largo (seguía contando un hijo ya
  borrado) y corrido hasta los ejes (seguía a la matriz del contenedor,
  que al entrar baja a los hijos). La caja de un contenedor sale de sus
  hijos y ahora se recalcula con cada cambio de la escena.
- **Un cuadro en blanco al editar dentro de un grupo anidado.** Borrar una
  cara (o cualquier cambio) dentro de un hijo de un contenedor dejaba el
  cuadro siguiente sin el grupo, sin sus vecinos, sin ejes y sin muñeco
  («por un segundo el grupo desaparece, pensé que se había eliminado»,
  Marco). El hijo se dibuja instanciado, y construir su entrada de dibujo a
  mitad del cuadro soltaba el programa de sombreado para todo lo que venía
  después. Solo se veía con las sombras apagadas.

### Cambiado
- **Empujar/Tirar ya no atraviesa un grupo cerrado.** Un dibujo agrupado se
  dejaba empujar sin abrirlo, y si era un componente la herramienta abría a
  tus espaldas una sesión de edición y compartía el resultado a TODAS las
  copias. Se escribió como «mejor que SketchUp» en junio; usándolo en obra
  resultó ser lo contrario, porque el modelo cambia donde no apuntaste
  (Marco, 2026-09-10). Ahora la cara de un grupo cerrado ni se sombrea al
  pasar por encima —sombrearla es prometer un empuje que no va a ocurrir— y
  el clic responde diciendo qué hacer: abrir el grupo con doble clic y
  empujar adentro. Es la regla de SketchUp, dicha por su propia guía de
  solución de problemas. Dentro del grupo no cambia nada, incluido que
  editar una copia de un componente sigue llegando a todas.
- **El aviso del límite del empuje dice qué se frenó y por qué.** Decía
  «Equidistancia limitada a 0.02 m» en mitad de un push — el nombre de otra
  herramienta (la `F`) y ninguna razón. Ahora: «Empuje limitado a 0,02 m:
  más adentro se saldría del sólido». Un límite correcto que se lee como un
  fallo es un fallo aparte, y este se llevó por delante un rato de trabajo
  de Marco intentando cortar una losa donde solo había 2 cm de material
  bajo una esquina de su figura.

## [0.3.17] — 2026-09-10

**La sesión de la Plaza Yanque.** Un día entero modelando una obra de verdad
en IngeTrazo y cazando lo que fuera saliendo. Casi todo lo de abajo lo
reportó Marco mientras dibujaba, con captura o con el modelo vivo delante.

### Añadido
- **Purgar capas y materiales sin usar**, con su botón en cada bandeja y
  deshacible. Nació de un import de SketchUp del que se borró casi todo: las
  capas del dibujo grande seguían ahí cuando ya no quedaba ni una cara suya.
  Las capas vuelven a su posición original al deshacer, no al final de la
  lista.
- **Tinte de textura**: cambiarle el color a un material texturizado, como el
  colorize de SketchUp. Tono y saturación del color elegido sobre la
  luminosidad de la imagen; el original se guarda al lado, así que se puede
  cambiar el tinte cuantas veces se quiera o quitarlo. Viaja dentro del
  `.igz`.
- **El tercer paso del rectángulo rotado es anchura Y ÁNGULO**, como el
  transportador de SketchUp: con la base tumbada, escribir `3;90` levanta el
  rectángulo de pie. Era la única forma de dibujar un rectángulo
  perpendicular y no estaba.
- **Equidistancia hacia adentro de verdad.** Al meterse hacia adentro de una
  forma cóncava hay segmentos que se cruzan y desaparecen; el trazado ingenuo
  los conservaba y salía un nudo. Ahora la forma se reconstruye con el motor
  de arreglo planar: lo que colapsa se elimina, y si la figura se parte en
  dos —una U estrecha— salen las dos piezas.
- **Invertir caras en el menú del botón derecho.** Estaba solo en el menú
  Edición, que no es donde se busca: SketchUp la pone sobre la propia cara.

### Corregido
- **Tres teclas no hacían nada: `H`, `O` y `F2`.** Lo reportó `@pacaeiro`
  (PR #11): el Transportador y Desplazar compartían la `H`. Cuando dos
  acciones de la misma ventana piden el mismo atajo, Qt no elige una — lo
  marca ambiguo y **no dispara ninguna**, así que la tecla queda muerta
  para las dos. Al medirlo aparecieron dos más del mismo molde: `O` la
  peleaban el Arco por centro y Orbitar, y `F2` estaba registrada dos
  veces, una por el botón de la barra y otra por la entrada del menú
  Cámara. Ahora las teclas de cámara son las de SketchUp — Orbitar `O`,
  Desplazar `H`, Zoom `Z` y **Zoom a extensión `Mayús+Z`**, que allá es la
  suya y aquí faltaba (`F2` sigue valiendo). Las dos herramientas que
  cedieron su tecla —que en SketchUp no tienen ninguna asignada de
  fábrica— quedan en `Mayús+H` el Transportador y `Mayús+O` el Arco por
  centro. Y un test nuevo recorre todas las acciones de la ventana y falla
  si dos comparten atajo: la misma regla que el cargador de extensiones ya
  le aplicaba a los plugins, que nadie había aplicado a las teclas propias
  entre sí.
- **El rectángulo rotado dibujaba siempre en el suelo.** `work_plane` estaba
  declarado, se reseteaba y se leía… y no se asignaba nunca, así que sobre un
  muro la anchura salía disparada en horizontal, y con la arista base
  vertical la herramienta no hacía nada en absoluto, sin decir palabra. Ahora
  el plano sale del bloqueo de las flechas o de la cara del primer clic, como
  en el rectángulo normal y los arcos. Detrás vinieron tres más de la misma
  herramienta, cada una encontrada dibujando: con un eje bloqueado el snap
  podía tumbar el rectángulo; el ángulo que enseñaba la vista previa se
  perdía al escribir la anchura en el cuadro (y salía tumbado); y el lado
  escrito iba al contrario del cursor.
- **Una astilla podía borrar 447 caras.** `QVector3D.normalized()` devuelve el
  VECTOR NULO por debajo de 1e-5, y una normal cero pasa cualquier prueba de
  plano: una cara de 3 × 1 mm se convertía en comodín y se llevaba por
  delante todo lo que tocaba. `Face.normal()` divide a mano.
- **«Pongo crear grupo y no crea».** Con la selección vacía, o con un grupo
  dentro, se volvía en silencio. Ahora cada camino RESPONDE, y cuando hay
  grupos seleccionados ofrece las salidas que sí existen —fusionar,
  desagrupar y agrupar, o agrupar solo lo suelto— en vez de callarse.
- **Un grupo se volvía líneas al dibujar dentro.** El chunk de un grupo se
  reutilizaba tras un cambio de materiales, así que una arista nueva en una
  esquina dejaba el modelo entero sin caras hasta deshacer. Y la equidistancia
  perdía la pintura de la cara: las dos mitades nuevas heredan sus atributos.
- **El punto del cursor se iba al horizonte.** Con el plano del suelo capturado
  y la cámara casi a ras, el rayo roza el plano y la intersección se dispara:
  medido, 85 m a media pantalla y 405 m veinte píxeles más arriba, hasta los
  1757 m que vio Marco en una plaza de 100. Un rayo que corta el plano por
  debajo de 6° ya no vale, y si hay una cara bajo el cursor manda la cara —
  que es lo que se está señalando.
- **Una arista oculta revivía al agrupar.** Una arista lleva cuatro cosas
  además de sus extremos (soft, curve, layer, hidden) y tres comandos —crear
  grupo, deshacer grupo y reconstruir caras— solo se llevaban las dos
  primeras. La lista vive ahora en un solo sitio y los comandos preguntan en
  vez de recordar, así que la próxima bandera no se puede olvidar.
- **La perpendicular no estaba en el plano inclinado.** La inferencia
  «perpendicular a la arista» giraba 90° en XY y devolvía siempre una
  dirección horizontal, que en una rampa no está sobre la rampa: cruzar la
  pendiente de una arista a la de enfrente quedaba enganchado a un bloqueo
  magenta imposible de satisfacer. Ahora es `cross(normal, arista)`, que en el
  suelo da exactamente lo mismo que antes.

### Cambiado
- **`P` es Empujar/Tirar, como en SketchUp** (pedido de Marco). Era `U`, y
  la `P` estaba gastada en alternar perspectiva/paralela — que en SketchUp
  no tiene tecla ninguna. La `U` no se tira: sigue valiendo como segundo
  atajo del MISMO comando, para no romper un año de memoria muscular. La
  proyección pasa a `Mayús+P`, la misma regla que el Transportador y el
  Arco por centro: la que cede se queda con `Mayús`+su tecla.
- La CI guarda los artefactos de release **7 días** en vez de 90. La cuenta
  iba por el 90 % de su cuota de almacenamiento con los binarios de cada
  build.

## [0.3.16] — 2026-09-09

**La release de los dos primeros probadores de fuera.** El mismo día
llegaron un youtuber que probó las dos apps por correo y `@pacaeiro` con
dos issues en GitHub, y entre los dos destaparon tres cosas que ninguna
prueba local podía cazar: en un equipo con NVIDIA sobre Wayland la
aplicación **no abría en absoluto**, el eje vertical del orbitar estaba
invertido desde siempre, y un grupo hecho solo de líneas y arcos no daba
ni una referencia ni se dejaba seleccionar.

### Corregido
- **Un grupo hecho solo de líneas y arcos no daba ni una referencia, y
  costaba seleccionarlo pinchando sus líneas** (issue #8). Los grupos sin
  ninguna cara se caían enteros del índice de selección, así que las
  inferencias no veían sus aristas y el clic sobre una línea no encontraba
  nada — el propio camino de rescate para «un grupo de solo líneas» ya
  estaba escrito, pero leía una lista vacía. Cualquier grupo con al menos
  una cara nunca se vio afectado, que es por lo que había pasado
  desapercibido.
- **Al orbitar, el eje vertical estaba invertido.** Arrastrar hacia abajo
  bajaba la cámara en vez de asomarte por encima del modelo, al revés que
  SketchUp, Blender o FreeCAD — y al revés que el propio encuadre de
  IngeTrazo, que sí agarra el modelo en los dos ejes. Lo reportaron dos
  usuarios el mismo día (issue #7 y un correo), ninguno capaz de decir
  cuál de los dos ejes era el malo, que es exactamente lo que se siente
  cuando hay uno solo invertido. Quien prefiera el gesto de antes lo
  tiene en **Preferencias ▸ Invertir el eje vertical al orbitar**.
- **La aplicación no abría con driver NVIDIA sobre Wayland.** El EGL de
  esas máquinas no sirve el contexto OpenGL 3.3 que pide el visor
  (`Failed to create context: 3009`, es decir `EGL_BAD_MATCH`), y como
  ese formato es el de por defecto se llevaba por delante hasta el
  dibujado de las ventanas de Qt: no era un visor roto, era una app que
  no arrancaba. El mismo driver lo sirve sin problema por X11, así que
  ahora IngeTrazo lo comprueba al arrancar y, si hace falta, pide un
  formato más modesto o se reinicia sola bajo X11. El Flatpak pasa a
  pedir `--socket=x11` para que ese reinicio tenga a dónde ir.
- **Avisos de librerías al arrancar el AppImage.** Los módulos GIO del
  sistema chocaban con la glib que va dentro del paquete y escupían dos
  `undefined symbol` antes de que la app existiera siquiera. El AppImage
  ya no los carga.

## [0.3.15] — 2026-09-08

**La release de la tarde entera de láminas con la obra real.** Marco
montó la lámina del arco de Yanque de principio a fin y cada tropiezo
salió al momento: el compositor gana reglas y guías como en QGIS, mover
la selección con las flechas, seleccionar lo que está debajo, el texto
de la cota que se arrastra como en LayOut, la línea de terreno, el fondo
del papel en los marcos, cotas que siguen activas, Shift ortogonal, una
barra de lámina con iconos, exportar a PNG/JPG, guardar desde el
compositor y el menú de las pestañas de lámina. El modelo gana el
bloqueo del plano de dibujo con las flechas. Y se corrigen la cota que
perdía su línea, el nivel que se partía al crecer, la guía de etiqueta
que no llegaba al texto, el punto verde gigante, la escena que no
actualizaba el marco y el cambio a Modelo que había que pulsar dos veces.

### Cambiado
- **«Modelo» desde el compositor ya no adivina.** El traspaso de ventana
  esperaba 400 ms a ver si el escritorio activaba la ventana del modelo
  y a veces se quedaba a medias (Marco, 2026-09-08: «a veces no hace
  efecto, como que tengo que hacer doble clic»). Ahora, si el compositor
  tapa a la ventana del modelo, se aparta al instante en cualquier
  escritorio; lado a lado, en dos monitores, se queda. Una pestaña de
  lámina lo trae de vuelta tal como estaba.
- **Guardar desde el compositor.** Ctrl+S y Ctrl+Mayús+S funcionan en la
  ventana del compositor y hay un botón «Guardar» en el panel; guardan
  el documento entero, modelo y láminas. El autoguardado de Preferencias
  ya cubría las láminas (Marco, 2026-09-08: «me gustaría que haya
  autoguardado o el icono de guardar en composiciones»).
- **Las cotas del compositor se quedan activas** tras colocar una: cota y
  cota angular siguen armadas para la siguiente, como el comando de
  acotar de AutoCAD. Esc cancela primero lo que esté a medias y, con nada
  en curso, deja la herramienta; el icono del cursor también. El resto de
  herramientas sigue devolviendo a Seleccionar tras un ítem (Marco,
  2026-09-08: «quiero seguir acotando… que siga activo ese comando a no
  ser que apriete Esc o haga clic en el icono del cursor»; y tras
  probarlo en todas: «tal vez eso solo para lo que es acotar»).

### Añadido
- **Menú del botón derecho en las pestañas de lámina** de las dos
  ventanas: cambiar nombre, duplicar (la copia queda justo después),
  eliminar (con confirmación; un documento conserva al menos una lámina)
  y nueva lámina (Marco, 2026-09-08: «desde los botones de lámina de
  abajo con el menú del mouse»).
- **Reglas y guías en el compositor, como en QGIS.** Una regla en
  milímetros arriba y otra a la izquierda del lienzo, que siguen el zoom
  y el desplazamiento y marcan la posición del cursor. Arrastrando desde
  una regla sale una guía (línea azul discontinua) a la página; los
  ítems se imantan a las guías al moverlos o redimensionarlos; una guía
  se desliza por su eje, se quita arrastrándola de vuelta a la regla o
  con Supr, y el botón derecho sobre la regla las quita todas. Se
  guardan con la lámina (Marco, 2026-09-08: «en QGIS muestran como unas
  guías… sería bueno implementar eso en composición»).
- **Exportar la lámina como imagen** (PNG o JPG) desde el compositor, a
  la resolución que elijas (se recuerda la última), con el mismo pintor
  que el PDF (Marco, 2026-09-08: «sería bueno poder guardar o exportar
  la lámina en jpg o png»).
- **El cajetín se copia y se pega entre láminas** (Ctrl+C en la lámina 1,
  Ctrl+V en la 2): como cada lámina tiene un cajetín, el pegado ocupa
  su sitio, con deshacer (Marco, 2026-09-08: «quiero copiar el cajetín
  que hice o algún objeto de la lámina 1 y pegarla a la lámina 2»). El
  resto de ítems ya se copiaban entre láminas.
- **Barra de lámina bajo el título del compositor, con iconos:** Guardar,
  Actualizar vistas, Exportar PDF, Exportar imagen y Vista previa de
  impresión, que salen del panel lateral (Marco, 2026-09-08: «para no
  sobrecargar la barra lateral derecha»). La casilla «Renderizado
  automático» va en la fila de estado, a la derecha de las pestañas
  Modelo | Láminas y antes de la posición del cursor.
- **Ctrl+Alt+clic selecciona el ítem que está debajo** en el compositor,
  y vuelve a pulsar para seguir bajando por la pila y volver arriba (el
  «seleccionar por detrás» de Inkscape e Illustrator); el menú del botón
  derecho ofrece «Seleccionar el ítem de debajo» donde hay ítems
  apilados, para escritorios como GNOME que se quedan el Alt. El texto de escala
  de un marco quedaba entero bajo un título más alto y no había forma de
  pincharlo con el ratón (Marco, 2026-09-08: «no puedo seleccionar ese
  objeto porque "detalle de letra y escultura" está casi encima de "esc.
  1:25"»).
- **Las flechas mueven la selección en el compositor**, como en el
  diseñador de impresión de QGIS: 1 mm por pulsación, 10 mm con Shift,
  0,1 mm con Alt. Un solo paso de deshacer por pulsación para toda la
  selección; los ítems bloqueados no se mueven; una cota anclada al
  modelo se desancla al moverla, igual que al arrastrarla (Marco,
  2026-09-08: «una vez seleccionado debería mover con las teclas de
  desplazamiento, así como lo hace QGIS»).
- **El texto de la cota se mueve como en LayOut.** Se arrastra con el
  ratón agarrándolo por las letras y se queda donde lo dejes; la línea
  de cota no se mueve (arrastrar la línea sigue moviendo la cota entera).
  En el panel, «A lo largo de la línea» lo pone sobre el centro, fuera
  del inicio o fuera del final (el texto al lado de la cota, a izquierda
  o derecha), y «Devolver el texto a su sitio» deshace el arrastre. Un
  texto centrado solo abre la línea cuando está en su sitio automático
  (Marco, 2026-09-08: «me refería al lado de la cota, ya sea derecho o
  izquierdo; es más, en SketchUp LayOut se puede mover el texto de la
  cota»). Además, «Posición del texto» gana «al costado de la línea» y
  «al otro costado»: la etiqueta entera a un lado de la línea sin
  cruzarla, útil en cotas verticales con texto horizontal.
- **Las flechas fijan el plano de dibujo del círculo, polígono,
  rectángulo y arcos**, como en SketchUp: antes del primer clic, → fija
  el plano normal a X (YZ), ← el normal a Y (XZ), ↑ el normal a Z (XY);
  la misma flecha otra vez lo libera y Esc también. Una etiqueta arriba a
  la izquierda, del color del eje, lo indica. La figura gasta el
  bloqueo, y tras el primer clic las flechas vuelven a ser el bloqueo de
  eje de siempre (Marco, 2026-09-08: «quiero dibujar un círculo en el
  plano ZX… en SketchUp me restringe a qué plano quiero dibujar apretando
  las teclas de desplazamiento»).
- **Shift fija en horizontal o vertical el segundo punto de una cota** (y
  de una línea, flecha, línea de terreno o el siguiente punto de una cota
  en cadena): el Orto de AutoCAD, el bloqueo de eje de SketchUp. Gana el
  eje más cercano al cursor; el imán a la geometría sigue actuando y el
  punto cae sobre el eje fijado; al pulsar o soltar Shift la goma elástica
  se actualiza sin mover el ratón. El tercer clic de la cota (la
  separación) nunca se bloquea (Marco, 2026-09-08: «cuando acote para
  sacar una distancia me gustaría que apretando Shift me restrinja de
  forma ortogonal»).
- **«Fondo del papel» en los marcos de vista.** Una casilla bajo el estilo
  del marco: renderiza sobre blanco y sin cielo ni suelo, sea cual sea el
  fondo del estilo elegido. Antes un marco en Rayos X (o Predeterminado)
  traía el gris y el cielo del modelo a la lámina (Marco, 2026-09-08, el
  acero del arco en Rayos X: «no me gusta que tenga el fondo gris del
  model»). Desactivada, el marco conserva el fondo del estilo.
- **Línea de terreno en el compositor.** Una forma nueva junto a la línea
  y la flecha: el suelo de una elevación con lo que cuelga por debajo
  según la convención de dibujo — pelos de tierra a 45°, banda rayada o
  banda rellena translúcida (largo, separación, alto y color en el
  panel). Se traza con dos clics o arrastrando, se imanta a la geometría
  de los marcos, admite pendiente y el terreno queda siempre del lado de
  abajo (Marco, 2026-09-08, el arco de Yanque: «la idea es decir mira de
  esta línea para abajo es el terreno»). La siguiente línea de terreno
  de la lámina nace con el último aspecto elegido.

### Corregido
- **El punto verde del imán crecía con el zoom** en el compositor: medía
  1,6 mm de papel, y al acercarse a una esquina para acotar se hacía
  enorme (Marco, 2026-09-08). Ahora mide siempre lo mismo en pantalla.
- **Cambiar la escena de un marco no cambiaba la imagen.** Los ajustes
  de cámara hechos dentro del marco (orbitar, encuadrar o hacer zoom
  tras el doble clic) mandaban sobre la escena recién elegida, así que
  el marco seguía mostrando lo de antes (Marco, 2026-09-08: «la escena 1
  como que no me actualiza la vista»). Elegir otro origen de vista
  descarta esa cámara manual y parte de la cámara de la escena.
- **La guía de una etiqueta salía del borde del bloque, no del texto.**
  Un bloque de 50 mm alrededor de dos palabras cortas arrancaba su guía
  en el centro inferior del bloque, 15 mm más allá de las palabras, y
  parecía que no había línea (Marco, 2026-09-08: «¿por qué no me sale la
  línea hasta el texto?»). La guía sale ahora del borde del texto real
  que mira al punto señalado; la zona de clic de la guía va igual.
- **El nivel (N.P.T.) se rompía al subir el tamaño del texto.** Con 3,5 mm
  «N.P.T. +0.20» ya no cabía en la línea de nivel de 14 mm, se partía en
  dos renglones y perdía el de arriba (Marco, 2026-09-08: «cuando
  aumento el tamaño de la letra de NPT se distorsiona»). La línea de
  nivel y la caja del ítem crecen ahora con el texto, que va siempre en
  un renglón.
- **Una cota vertical con el texto centrado y horizontal perdía su línea
  de cota.** La abertura de la línea alrededor del texto se medía con el
  ANCHO del texto aunque el texto fuera horizontal sobre una línea
  vertical, donde solo tapa su alto: una cota de 16 mm se quedaba sin
  línea y una de 10 mm la conservaba (Marco, 2026-09-08: «en 0.80 no se
  ve la línea de acotación y en la 0.50 sí»). Ahora la abertura es la
  sombra de la caja del texto sobre la línea.
- **«Modelo» desde el compositor no cambiaba de ventana en Windows.** El
  compositor es una ventana hija de la principal y Win32 mantiene siempre
  una ventana hija por encima de su dueña: la principal se activaba, pero
  seguía tapada (Marco, 0.3.14 en Windows: «cuando quería cambiar al
  modelo con los botones de abajo no podía»). Ahí el compositor se aparta
  al instante cuando tapa a la principal; en dos monitores, lado a lado,
  se queda.

## [0.3.14] — 2026-09-07

**La release de la primera tarde con la 0.3.13.** Marco la instaló desde
el Flatpak, en Wayland, y en una hora salieron tres cosas que el
desarrollo en X11 no había mostrado: la franja de pestañas sin puerta al
compositor en un documento nuevo, «Modelo» que no cambiaba de ventana y
un cierre en seco en el lienzo. Con ellas van la selección por cuadro del
compositor, el estilo Arquitectónico para los marcos nuevos y, por primera
vez, ejemplos reales para abrir: cuatro documentos de la plaza de Yanque.

### Añadido
- **Pestaña «+» al final de la franja Modelo | Láminas.** Un documento
  nuevo no tiene láminas y la franja solo decía «Modelo», sin ninguna
  puerta al compositor (Marco, 0.3.13 en Flatpak: «no aparece compositor
  de láminas abajo»). Como en AutoCAD, «+» abre el compositor en una
  lámina nueva (en un documento sin láminas, en la primera), desde las dos
  ventanas.

- **Selección por cuadro en el compositor** (Marco, 2026-09-07: «falta
  seleccionar varios objetos con el mouse haciendo un cuadro»). Con la
  herramienta Seleccionar, arrastrar desde la hoja vacía dibuja un cuadro:
  de izquierda a derecha (azul, continuo) selecciona lo que queda
  encerrado; de derecha a izquierda (verde, a trazos) lo que toca — la
  regla de SketchUp y AutoCAD. Mayús alterna, Ctrl añade, Mayús+Ctrl
  quita, como en el modelo; los ítems bloqueados no entran; un clic en
  la hoja vacía sigue vaciando la selección.

- **Ejemplos.** Cuatro documentos reales de la plaza de Yanque en la
  carpeta `examples/` del repositorio y en cada release
  (`IngeTrazo-ejemplos.zip`): la pileta, la banca con pérgola y la
  luminaria solar con su lámina A3 y el PDF resultante, y el arco de
  bienvenida con todo su acero. Licencia CC BY 4.0.

### Cambiado
- **Un marco de vista nuevo nace con el estilo «Arquitectónico»** — fondo
  blanco, sin cielo, con aristas y perfiles: el aspecto de una lámina de
  planos (Marco, 2026-09-07: «que el model view, cuando se abre por
  defecto el compositor, sea el estilo de arquitectura»). Vale para la
  lámina inicial, para el marco que se dibuja con la herramienta Vista y
  para «Añadir marco»; los marcos ya guardados conservan su estilo.

### Corregido
- **Cambiar de ventana con las pestañas de abajo en Wayland.** En Wayland
  una ventana no puede traer otra al frente: «Modelo» desde el compositor
  parecía no hacer nada cuando GNOME no concedía la activación (Marco:
  «quiero cambiar con los botones de abajo, no cambia»). Si el modelo no
  se activa en 0,4 s, el compositor se aparta (se oculta) y la pestaña de
  la lámina en la ventana del modelo lo trae de vuelta tal como estaba.
- **Las franjas ya no marcan la pestaña equivocada tras un clic.** QTabBar
  hace actual la pestaña pulsada DESPUÉS de avisar del clic, así que el
  cambio de ventana hecho dentro del aviso dejaba al compositor marcando
  «Modelo» y a la ventana del modelo marcando la lámina; además rehacía
  las pestañas debajo de una pulsación en curso. Ahora el cambio corre
  desde el bucle de eventos y las pestañas solo se rehacen cuando cambian
  los nombres.
- **Soltar un marco ya no reconstruye la lámina dentro de su propio evento
  de ratón.** La reconstrucción borra todos los ítems del lienzo — incluido
  el que Qt todavía está atendiendo en ese instante. Lo mismo con el editor
  de texto in situ, que se retiraba desde su propio foco perdido. Ambos
  esperan ahora al bucle de eventos. Y si un ítem del lienzo pierde su
  parte Python (el «pure virtual method 'QGraphicsItem.boundingRect' not
  implemented» del registro de Marco, tras el cual la 0.3.13 se cerró), el
  lienzo se reconstruye desde los modelos en vez de dejar que Qt siga con
  él.

## [0.3.13] — 2026-09-07

**La release del día de dogfooding del compositor.** Marco dibujó dos
láminas reales del poste solar y fue pidiendo lo que faltaba, una cosa a
la vez: pestañas Modelo | Lámina en la barra de estado como AutoCAD,
girar la vista dentro de su marco, un cajetín que reparte el alto según
lo que lleva cada fila, arrastrar 10× más fluido, diálogos que abren en
la última carpeta y Mayús+clic que quita de la selección — más los bugs
que salieron modelando: la selección impresa en el PDF, la ventana que
no maximizaba, la edición de vista que se cortaba al primer gesto, el
pan con la hoja entera a la vista y los ítems bloqueados que se colaban
en la selección.

### Añadido
- **Pestañas Modelo | Lámina 1 | Lámina 2… en la barra de estado** (Marco,
  2026-09-07: «como lo tiene AutoCAD», «en la misma fila donde está el
  cuadro de las medidas»). Pasar del modelo a una lámina era ir a Archivo ▸
  Compositor de láminas y elegirla; ahora es un clic en el extremo
  izquierdo de la barra de estado, en las dos ventanas: en el modelo, la pestaña de una
  lámina abre el compositor en esa lámina; en el compositor, «Modelo»
  vuelve al modelo y las demás cambian de lámina. Las dos franjas siguen
  al documento (láminas nuevas, renombradas o borradas) y cada una marca
  lo que muestra su ventana. Los mensajes de estado ya no las esconden (la
  barra los muestra en su propio rótulo y, pasado el aviso, vuelve la ayuda
  fija).
- **Girar una vista en la lámina.** El marco del compositor tiene ahora
  «Giro de la vista» en el panel: el DIBUJO gira dentro del marco, en
  sentido horario y con el mismo ángulo que se le pone a la flecha de
  norte, mientras el marco, su rótulo y todo lo demás de la lámina se
  quedan donde están. El modelo no se toca: es un giro de la cámara del
  marco, así que gira con él todo lo que sale de ella — el render, el
  paso vectorial de líneas ocultas, los puntos de imantación, las cotas
  ancladas, las marcas de sección y el DXF exportado. También a mano: en
  edición de vista (doble clic en el marco) **Mayús+arrastrar** gira el
  dibujo alrededor del centro del marco, con imantación cada 15°, y toda
  la maniobra es un solo paso de deshacer. El giro viaja en el `.igz`.

### Corregido
- **La ventana del modelo vuelve a maximizarse.** La ayuda fija de la
  barra de estado es una línea larga y, como rótulo permanente, pedía
  todo su ancho como mínimo: en una pantalla más chica la ventana no
  podía encogerse ni maximizarse (Marco, 2026-09-07: «no puedo
  maximizar la ventana»). El rótulo ya no pide ancho mínimo y recorta
  con puntos suspensivos.
- **La selección ya no se imprime.** Si al renderizar un marco había algo
  seleccionado en el modelo, sus indicadores salían en la lámina y en el
  PDF: el recuadro naranja alrededor de Sumari (Marco, 2026-09-07,
  captura), el tinte de las caras y las aristas resaltadas. Los renders de
  exportación (marcos del compositor e imagen en alta resolución) ya no
  dibujan ningún indicador de selección.
- **Doble clic sobre un texto de lámina tras un deshacer ya no falla.** El
  editor de texto in situ moría con el lienzo al reconstruirse (undo,
  pegar, soltar un marco) y el compositor seguía apuntándolo: el siguiente
  doble clic tocaba un objeto borrado («Internal C++ object already
  deleted», repetido en el log de Marco, 2026-09-07). La reconstrucción
  suelta el editor y cerrarlo comprueba que siga vivo.
- **Se acabaron las congeladas de un segundo al editar la lámina.** El
  visor informa la versión del modelo al pintar; dos ediciones de lámina
  seguidas entre dos pintadas dejaban la primera pareciendo un cambio del
  modelo: todos los marcos pasaban a desactualizados, se tiraban los
  puntos de imantación y el paso exacto de líneas ocultas se rehacía por
  marco (~1 s cada uno en la lámina del poste). Ahora el compositor
  reconoce TODAS las versiones que produjo él mismo (Marco, 2026-09-07:
  «cierto lag cuando arrastro un leader»).
- **Soltar un ítem arrastrado ya no reconstruye la lámina entera.** Al
  soltar una etiqueta, una cota o un texto se rehacían los 39 ítems y se
  repintaba todo en frío (~80 ms de tirón por suelta); ahora la suelta es
  solo su paso de deshacer. Un marco sí reconstruye: las cotas ancladas y
  los textos ligados tienen que seguirlo.
- **La lámina se puede desplazar aunque quepa entera en la ventana.** El
  lienzo solo dejaba hacer *pan* (rueda, botón central) cuando la hoja era
  más grande que la ventana (Marco, 2026-09-07). Ahora el área desplazable
  es la hoja más el tamaño de la ventana por cada lado, a cualquier zoom,
  como en cualquier CAD; una franja de 20 mm de la hoja queda siempre a la
  vista para no perderla. Las barras de desplazamiento quedan fijas.
- **Editar la vista de un marco ya no se corta al primer gesto.** Tras el
  doble clic sobre un marco, cada muesca de la rueda o cada arrastre
  confirmaba el paso y reconstruía el lienzo, y la reconstrucción soltaba
  el modo de edición: para el segundo zoom había que volver a hacer doble
  clic (Marco, 2026-09-07). Ahora la edición pasa al ítem nuevo del marco
  y se sigue orbitando, encuadrando y haciendo zoom hasta Enter, Esc o un
  clic fuera.

### Cambiado
- **Los diálogos de archivo abren en la última carpeta que elegiste.**
  Abrir, guardar, importar y exportar (PDF, DXF, imagen, IFC, OBJ…)
  arrancaban en la carpeta donde está instalado el programa (Marco,
  2026-09-07). Ahora los 28 diálogos comparten una memoria: empiezan en la
  última carpeta usada en cualquiera de ellos; si no hay ninguna, en la
  carpeta del documento abierto, y si tampoco, en Documentos.
- **Un ítem bloqueado de la lámina ya no se selecciona desde el lienzo.**
  Ni con clic ni con caja: el clic va a lo que está encima (cotas, textos)
  o a la hoja, y un marco de vista bloqueado deja de mezclarse con las
  cotas que se editan sobre él (Marco, 2026-09-07). La única puerta a un
  ítem bloqueado es la lista **Items** del panel: desde ahí se selecciona,
  se edita en el panel y se desbloquea (Ctrl+L o menú). Al pasar la
  selección a otra cosa, la puerta se vuelve a cerrar.
- **Arrastrar en el compositor va 10× más fluido.** Cada movimiento del
  ratón volvía a dibujar los marcos afectados escalando su render de
  300 dpi (Marco, 2026-09-07: «siento algo de lag en composiciones cuando
  arrastro un objeto»). Ahora cada ítem de la lámina conserva su dibujo en
  una caché a resolución de pantalla y arrastrarlo es copiar píxeles: en
  la lámina real de la pileta (A3, cuatro marcos, 47 %) un movimiento
  pasó de 11,2 ms a 1,1 ms, medido con eventos de ratón reales. Lo que se
  dibuja es idéntico (comparado píxel a píxel). La caché se suelta sola
  para un ítem que, muy ampliado, necesitaría más de 4 Mpx, y vuelve al
  alejar. Impresión y PDF no pasan por ella.
- **El cajetín reparte su alto según lo que lleva cada fila.** Un nombre de
  proyecto largo se encogía dentro de su fila hasta quedar en letra
  diminuta al lado de una fecha y una lámina dibujadas al doble de tamaño
  (Marco, 2026-09-07: «no se ve bien porque la fuente disminuye y lo demás
  se hace más grande»). Ahora la fila **crece** —hasta 3× su parte igual— y
  lo pagan las filas que nunca usaban la suya, así que el cajetín conserva
  el alto que le diste y **todos los valores salen prácticamente del mismo
  tamaño**. En la lámina real de Yanque el nombre del proyecto pasa de 3,8 a
  4,9 mm, igual que el resto. Un cajetín cuyos textos ya cabían no cambia en
  nada (filas iguales), un campo vacío sigue pidiendo su línea completa, y
  en un cajetín demasiado chico la letra vuelve a encoger como antes. Las
  filas se miden columna por columna, así que en un cajetín de varias
  columnas las líneas horizontales siguen alineadas.
- **Mayús+clic ahora quita de la selección** (regla de SketchUp, pedido de
  Marco: «debería haber una opción para deseleccionar ciertas líneas o
  planos»). Con la herramienta Seleccionar, **Mayús+clic alterna** lo que
  toca — una arista o cara ya seleccionada sale de la selección, una que
  no lo estaba entra —, **Ctrl+clic añade** siempre y **Mayús+Ctrl+clic
  quita** siempre. La caja de selección lee los mismos modificadores, y un
  clic con modificador en el vacío ya no borra la selección que estabas
  armando (antes Mayús solo sumaba y no había forma de descartar algo sin
  empezar de cero).

## [0.3.12] — 2026-09-05

**La release de las láminas profesionales y del `.skp` que SketchUp
guarda.** Una sesión entera sobre la lámina real de la pileta de Yanque:
el estilo vectorial dibuja con tres plumas y rellena los cortes, el marco
lleva rótulo numerado, la planta marca por dónde va cada sección, y llegan
las cotas de nivel, las cotas en cadena, las llamadas de detalle y las
fotos en círculo con borde desvanecido. Por debajo, el exportador `.skp`
que SketchUp abre, muestra con las texturas en su sitio y **guarda** — con
openskp fijado al fork `tuxiasumari/openskp@73ba410` mientras upstream
revisa el PR #266 que lo lleva todo.

### Cambiado
- **Un `.igz` de una versión más nueva ya abre.** Las láminas guardadas con
  campos que esta versión no conoce cargan ignorando esos campos, una
  ficha corrupta dentro de una lámina se salta, y una lámina que no se
  puede reconstruir se omite con un aviso en el log en vez de impedir
  abrir el modelo entero.
- **Panel de propiedades del marco más compacto.** Las casillas ocupan todo
  el ancho, las etiquetas largas se acortaron (la explicación queda en el
  tooltip), las filas del rótulo de vista solo aparecen con el rótulo
  activado y las de las plumas solo con el estilo vectorial, y en un panel
  estrecho una fila que no cabe baja el campo bajo su etiqueta en vez de
  recortar el texto. A 480 px se lee todo.
- **La barra «Organizar» del compositor ya no aparece por defecto.** Sus
  órdenes siguen a mano: alinear y distribuir en el menú contextual de los
  ítems (submenú Organizar, con dos o más seleccionados), y agrupar,
  desagrupar, bloquear y duplicar en sus atajos y en el mismo menú. Para
  volver a verla, clic derecho sobre la barra de herramientas de la
  izquierda y marcar «Organizar»; la elección se recuerda.

### Añadido
- **Grosores por clase y poché en el estilo vectorial de las láminas.** La
  vista «Vector (líneas ocultas)» ya no dibuja todo con una sola pluma: el
  paso de líneas ocultas clasifica cada trazo como corte de sección,
  perfil (siluetas y contornos contra el fondo, los «perfiles» de SketchUp)
  o arista entre dos caras, y cada clase sale con su pluma (0,50 / 0,35 /
  0,18 mm por defecto, ajustables por marco en el panel). Donde el plano de
  sección corta un sólido cerrado, el marco rellena el corte (sólido o
  achurado a 45°, color y paso configurables); las superficies abiertas
  quedan en blanco. Las cuerdas colineales del corte se fusionan en una
  sola línea y las verticales vistas de canto ya no dejan puntos. La
  exportación DXF de la vista reparte las clases en capas `VISTA`,
  `VISTA-PERFIL` y `VISTA-CORTE` para la tabla de plumas de IngeCAD.
- **Rótulo de vista profesional.** El título del marco (antes una línea
  centrada «Planta — 1:100») tiene ahora tres estilos: el de LayOut
  (burbuja numerada con la lámina debajo, título en negrita, «ESC. 1:N» y
  una línea de base hasta el borde del marco, con subtítulo opcional),
  la barra vertical de los planos brasileños (franja a la izquierda del
  marco con título, subtítulo y escala girados 90° y la burbuja al pie) y
  la línea simple de siempre. Título, subtítulo, número y lámina admiten
  campos ({escala}, {lamina}, {escena}…), se elige alineación, posición
  (debajo o encima) y alto del texto, y todo se edita en vivo desde el
  panel del marco sin recalcular la vista. Cambiar el título o el borde
  ya no deja en blanco un marco vectorial hasta el siguiente «Actualizar».
- **Cotas de nivel.** Herramienta nueva en la barra del compositor: un
  clic sobre un punto de una vista del modelo pone la marca de nivel
  («N.P.T. +0.15») leyendo la altura de ese punto — triángulo sobre su
  vértice en secciones y elevaciones, círculo en cuadrantes en plantas —
  con la línea de nivel y el valor encima. Anclada al modelo, sigue al
  punto si la geometría cambia y actualiza la altura; se puede deslizar
  por la lámina (queda una guía fina hasta el punto). Nivel de referencia
  (±0.00), decimales, texto con `{z}`, símbolo, tamaño, largo de la línea,
  lado, grosor y color desde el panel; una cota libre muestra el nivel que
  escribas. Copiar/pegar estilo y organizar la reconocen. Las etiquetas con
  guía vuelven a anclarse al modelo (la herramienta no tenía snap).
- **Cotas en cadena.** Herramienta nueva junto a la cota: dos puntos y la
  separación de la línea, y cada clic siguiente añade el siguiente tramo
  sobre la misma línea de cota (con un quiebre, el tramo nuevo se acomoda
  para pasar por la línea de la cadena). Un clic sobre el último punto, Esc
  o cambiar de herramienta terminan la cadena y apilan la **cota total**
  una fila más afuera (con dos tramos o más; Ctrl+Z la quita si sobra).
  Cada tramo se ancla al modelo cuando sus dos puntos cayeron sobre la
  misma vista. El **estilo de cota por defecto** (la última editada) ahora
  se recuerda entre sesiones, no solo dentro de la lámina.
- **Marcas de sección en las vistas.** Opción nueva del marco: dibuja la
  traza de cada plano de sección del modelo que atraviesa esa vista como
  línea de corte (raya-punto, con remates gruesos), flechas hacia el lado
  que mira la sección y la letra del plano en burbujas a ambos extremos, así
  la planta dice por dónde va el «Corte A-A». Un plano paralelo a la vista
  no deja marca. La letra sale del símbolo del plano (o A, B, C… por orden).
  Activar marcas, anotaciones o progresivas ya solo rehace la capa de papel
  del marco, no la vista entera.
- **Llamadas de detalle.** Herramienta nueva: encuadra (rectángulo o
  círculo a trazos) la parte de una vista que otro dibujo amplía y pone la
  burbuja «3 / L-05» con una guía; la burbuja se arrastra aparte y el
  encuadre se mueve y redimensiona como cualquier ítem. Dibujada sobre un
  marco, queda ligada a él y se mueve con él. Número, lámina (admite
  {lamina}), forma, tamaño, grosor y color desde el panel.
- **Imágenes con opacidad, recorte y borde desvanecido.** El panel de la
  imagen tiene ahora opacidad, forma del recorte (rectángulo, esquinas
  redondeadas, elipse o círculo), borde desvanecido en milímetros, ajuste
  (estirar, cubrir recortando o contener) y contorno opcional. Una foto en
  círculo con el borde fundido al papel, como en las láminas de
  presentación. Copiar/pegar estilo también entre imágenes.
- **Perfil de terreno en láminas.** Un ítem nuevo del compositor (herramienta
  «Perfil» en la barra) dibuja la cota del terreno bajo un trazado contra la
  progresiva, como en un plano de carretera o canal: escala horizontal 1:N o
  ajustada al ancho, exageración vertical o ajuste al alto, cuadrícula con
  pasos de progresiva y de cota, sombreado del terreno, título y tamaño de
  texto. Muestrea el levantamiento fotogramétrico si está visible y el DEM en
  el resto, se recalcula si mueves el trazado, se guarda con la lámina y sale
  en la impresión con el rótulo «Esc. H 1:N · V 1:M · exag. ×k».
- **Los trazados se ven en las vistas de modelo de las láminas.** El eje o
  el lote trazado con la herramienta Ruta salía en el visor pero no dentro
  del marco de la lámina (ni en pantalla ni impreso): ahora se dibuja sobre
  el papel, en el cian del visor y con sus nodos, en todos los estilos y sin
  activar «Anotaciones del modelo», apoyado en el terreno igual que en el
  visor. Y con **progresivas**: la casilla «Progresivas en los trazados» del
  marco pone una marca y su rótulo 0+020 a cada paso; el paso «auto» es el
  mismo que elige el perfil de terreno de ese trazado, así planta y perfil
  coinciden, y en los dos se puede escribir el paso que se quiera.
- **Las figuras «cara a la cámara» viajan al `.skp`.** Las personas 2D y los
  recortes (la figura Sumari, los bañistas) se quedaban fuera del archivo y
  desaparecían en SketchUp. Ahora salen como componentes en la convención de
  SketchUp (pies en el origen, frente hacia −Y, colocados en su ancla) y, si
  el escritor de openskp lo admite, con el comportamiento «siempre mirar a la
  cámara»; con el escritor actual quedan de pie mirando a −Y.
- **Las aristas ocultas viajan al `.skp`.** El exportador nunca marcaba una
  arista como oculta, así que SketchUp dibujaba un marco negro alrededor de
  cada figura recortada (y de las hojas importadas cuyo contorno es la
  máscara de su textura). Una cara con todas sus aristas ocultas en
  IngeTrazo sale con ellas ocultas.
- **La geometría repetida se escribe una sola vez.** Un modelo guardado por
  una IngeTrazo anterior tenía los componentes explotados: la piscina llevaba
  24 setos de 9600 caras fusionados en un solo grupo y tres bancas idénticas
  como tres grupos, y el `.skp` pesaba 70 MB. Ahora el exportador reconoce las
  piezas que son copias de otra, trasladadas o giradas sobre el eje
  vertical, dentro de una malla o entre grupos; las verifica punto por
  punto y cara por cara (pintura y texturas), y las escribe como una
  definición colocada N veces, como hace SketchUp. La piscina baja de 70 a
  27 MB con las mismas caras en los mismos sitios.
- **Solo viajan las capas en uso.** Al guardar en SketchUp Web, Purgar
  tiraba 8 de las 10 capas de la piscina, todas vacías, y la capa por
  defecto de IngeTrazo ya es la «Layer0» de SketchUp. El resto del ahorro
  que da SketchUp al guardar es su formato comprimido: nuestros archivos
  llevan las mismas caras, definiciones y texturas.

### Corregido
- **Compositor: la selección sobrevive a cada cambio del panel.** Cambiar la
  escala, el ancho o un campo del cajetín deseleccionaba el marco y había que
  volver a clicarlo para el siguiente ajuste: el auto-render reconstruía el
  lienzo y la selección vivía en los ítems que se destruían. Ahora la
  reconstrucción recuerda qué modelos estaban seleccionados y los vuelve a
  seleccionar.
- **SketchUp ya puede GUARDAR un `.skp` exportado.** Los archivos abrían bien
  pero cualquier intento de guardarlos, en SketchUp Web o con el SDK, acababa
  en «Guardado fallido». El escritor de openskp numeraba los identificadores
  persistentes de cada sección desde 1 y dejaba corto el contador de la
  cabecera, así que SketchUp encontraba duplicados al cargar, los renumeraba
  y luego no podía serializar el modelo. Cazado con el SDK a partir de un caso
  mínimo (una definición de 1 cara seguida de otra de 3). El escritor del fork
  numera en una sola secuencia (arreglo propuesto a upstream); mientras tanto
  IngeTrazo corrige el contador del archivo al guardar y escribe las figuras
  al final, con lo que la pileta y la piscina se guardan.
### Corregido
- **Las texturas de un `.skp` exportado se ven en SketchUp donde IngeTrazo
  las dibujó.** Tres causas, cazadas con el conversor del SDK de SketchUp
  como oráculo. Dos están en el escritor de openskp y se compensan hasta
  que upstream las arregle (una sonda lo comprueba en cada exportación): la
  matriz de cada cara pineada se escribía en la base «primera arista» y
  SketchUp la lee en la base «Z × normal», así que cada cara salía girada el
  ángulo de su primera arista (el tronco de la palmera, miles de caras, hecho
  añicos); y los UV pineados no se multiplicaban por el tamaño aplicado del
  material, que SketchUp divide al leer, así que una textura de 2 m salía 78
  veces más grande (el agua de la pileta, un azul plano). La tercera era de
  IngeTrazo: la proyección por defecto del visor usaba otra base que la de
  SketchUp y en muros que miran a +Y o −X la textura se veía girada 180°
  respecto de lo que sale en el archivo. Ahora hay una sola receta
  (`core.texture.projection_basis`, la de SketchUp) para el visor, los
  exportadores OBJ/glTF/DAE, la vista previa de pegar y el importador.
- **Un `.skp` exportado ya no muestra caras lavanda en SketchUp.** IngeTrazo
  pinta las dos caras de una superficie y SketchUp solo la que nombra el
  archivo, así que toda cara vista desde atrás (las bancas, el bajo del
  techo, las hojas de la palmera) salía con el color de reverso por defecto.
  Ahora el reverso lleva el mismo material y la misma posición de textura
  que el frente, o el suyo propio cuando la cara venía pintada distinta por
  cada lado.
- **Las caras horizontales ya no salen con la textura girada 90° en
  SketchUp.** La base de proyección de SketchUp (Z × normal) es discontinua
  justo en la vertical, y la normal de una cara horizontal calculada en
  float32 traía un ruido de hasta 6e-4 que la mandaba a la base equivocada
  (Marco: encimeras, pisos y losas de la piscina). Medido con el SDK:
  SketchUp usa los ejes del mundo mientras la inclinación es menor que 1e-3.
  Ahora la receta única usa esa misma tolerancia, la normal de cada cara se
  acumula en doble precisión y el exportador expresa los pins contra el
  plano que el propio escritor guarda en el archivo.
  Y las caras que miran hacia abajo (el bajo de losas, bancas y encimeras)
  salían 180° giradas: SketchUp les da la base (−X, +Y), no la (X, −Y) que
  asumía el lector; medido igual y corregido en la misma receta.

## [0.3.11] — 2026-09-04

**Release de Windows y de intercambio.** Todo lo que salió al probar la
0.3.10 en la máquina de un amigo de Marco: un `.igz` con texturas que no
abría, un `.skp` exportado que SketchUp rechazaba, el visor arrastrándose
en una laptop con dos gráficas, y un puente MCP que no podía conectarse
porque el paquete no llevaba el servidor. Cinco de los seis arreglos tienen
la misma raíz: el nombre de la textura en caché crecía en cada guardado.

### Añadido
- **Puente IA (MCP) utilizable desde Windows y desde los paquetes.** El
  paquete no llevaba el servidor MCP y la guía mandaba `python3`, que en
  Windows no existe: Claude Desktop nunca llegaba a IngeTrazo. Ahora el
  instalador incluye `ingetrazo-mcp.exe`, el ejecutable acepta `--mcp` en
  Linux, y al encender el puente se abre una ventana con las líneas exactas
  para Claude Code y Claude Desktop en ese sistema, con botón Copiar.
- **Laptops con dos gráficas (Intel + NVIDIA/AMD): IngeTrazo pide la GPU
  dedicada.** Windows arranca los programas nuevos con la integrada y el visor
  se arrastra mientras la RTX no hace nada. El instalador y la propia app
  escriben la misma preferencia que Configuración ▸ Sistema ▸ Pantalla ▸
  Gráficos («Alto rendimiento») para `ingetrazo.exe`, solo si el usuario no
  había elegido nada; se aplica desde el siguiente arranque y se puede
  cambiar ahí mismo.
- **Quién dibuja el visor.** Al arrancar, la app anota la tarjeta gráfica y
  el controlador que le dieron el contexto OpenGL en `ingetrazo-gl.txt`
  (carpeta de registros) y lo muestra en Ayuda ▸ Acerca de. Si el visor está
  dibujándose por software (`opengl32sw.dll` de Qt en Windows, `llvmpipe` en
  Linux), la barra de estado lo avisa: es la causa habitual de un
  «rendimiento pésimo» y la solución está en el controlador de la GPU, no en
  IngeTrazo.

### Corregido
- **El `.skp` exportado por la 0.3.10 no abría en SketchUp cuando una
  textura venía de la caché con nombre apilado.** Mismo origen que el fallo
  de Windows: el nombre de 250 caracteres caía en la carpeta temporal, la
  ruta superaba el límite de 255 del escritor de openskp y este fallaba con
  la imagen ya escrita a medias; el «respaldo a color» se escribía encima y
  SketchUp rechazaba el archivo entero (SUResult 12). Ahora cada textura se
  copia a una carpeta temporal con su nombre corto antes de entregarla al
  escritor, la ruta de tu máquina ya no viaja dentro del `.skp`, y una
  imagen ilegible pasa a color sin tocar el escritor. Las texturas BMP, TIFF
  o GIF (las que traen los modelos importados de SketchUp) se reconvierten a
  PNG en vez de perderse. Validado con el conversor oficial del SDK de
  SketchUp.
- **Un `.igz` con texturas dejaba de abrir en Windows tras varios guardados.**
  Cada guardado envolvía el nombre de la imagen en un prefijo de hash más
  (`textures/<hash>-<hash>-…-sumari.png`): al cabo de unos veinte guardados la
  ruta en la caché superaba el límite de 260 caracteres de Windows y el archivo
  fallaba con «[Errno 2] No such file or directory». Ahora el nombre se limpia
  de prefijos al guardar y al abrir, se recorta a 64 caracteres, los archivos
  ya hinchados se abren y quedan sanos al volver a guardarlos, y una caché en
  la que no se puede escribir deja la cara sin imagen en vez de impedir la
  apertura.

## [0.3.10] — 2026-09-04

**Release urgente.** La 0.3.9 salió con dos fallos serios que este release
cierra: el instalador de Windows no arrancaba instalado en Archivos de
programa, y cualquier modelo con una figura «face-me» de malla (la Susan de
SketchUp) dejaba el visor en blanco. Además entra todo lo trabajado desde
entonces sobre las láminas y el modelado de Marco.

### Añadido
- **Componentes: editas uno, cambian todos.** Entrar en una copia de un
  componente (doble clic) edita su definición compartida: al salir, el
  cambio llega a todas las copias, y toda la sesión se deshace en un solo
  paso. Empujar/Tirar sobre una copia desde fuera también edita la
  definición. Para cambiar una sola copia, antes: clic derecho ▸ Hacer
  único. Mirar dentro y salir sin tocar nada no cambia nada.
- **Medidas en pulgadas y pies junto a metros**, como SketchUp: `2"`, `2in`,
  `1'`, `1ft`, `1'6"`, `3/4"`, `1 1/2"` (o `1-1/2"`), mezclables por campo
  (`1 1/2";3 1/2"` es una tabla de 2×4; `3,2;1'6";10cm` un
  desplazamiento). Los números sin sufijo siguen siendo metros.
- **Cotas en pulgadas o pies**, en el estilo de cotas del modelo y en cada
  cota de lámina: `in`, `ft`, `ft-in`, y las fraccionarias `in-frac`
  (`1 1/2"`) y `ft-in-frac` (`1'6 1/2"`); Decimales fija el denominador
  (0 enteras, 1 cuartos, 2 dieciseisavos, 3 treintaidosavos, 4
  sesentaicuatroavos).
- **Copia de seguridad del autoguardado descartado.** Cerrar sin guardar ya
  no borra la copia automática: se retira a una carpeta de descartados
  (se conservan las 20 últimas) y Archivo ▸ Recuperar una copia
  auto-guardada descartada… la abre como documento nuevo.
- **Publicar el repositorio Flatpak a mano** desde Actions ▸ release-flatpak
  ▸ Run workflow con el tag de una release existente, sin compilar ni crear
  releases nuevas.

### Cambiado
- **openskp 1.2.0** (upstream `6e3e568`, 4 de septiembre): trae nuestro
  aporte de tamaño aplicado y opacidad de materiales al escribir .skp, los
  diccionarios de atributos de grupos, entidades de imagen, y un arreglo de
  memoria y de triangulación para archivos grandes. Validado contra el
  corpus real de 189 .skp: los mismos 178 abren, geometría idéntica archivo
  por archivo y un 5 % más rápido en conjunto.

### Corregido
- **La 0.3.9 dejaba el visor en blanco** con cualquier modelo que trajera una
  figura «face-me» de malla (la Susan de SketchUp y similares, importadas
  del .skp): al dibujarla faltaba una coordenada del ancla y el pintado
  fallaba en cada frame. Se veían las etiquetas y los ejes, nada más.
- **El zoom «se trababa» cerca del modelo**: con la distancia de órbita en
  su mínimo (2 cm), acercar no hacía nada y alejar retrocedía milímetros
  por muesca hasta un Zoom extensión. Ahora alejar retrocede al menos un
  1 % del tamaño del modelo por muesca y acercar sigue deslizando la vista
  hacia el punto del cursor.
- **Una línea dibujada sobre la cara de un grupo no se podía seleccionar**:
  el clic siempre tomaba el grupo. Como en SketchUp, la línea visible gana
  al objeto que tiene detrás; una línea escondida detrás del bloque deja
  el clic al bloque.
- **Mover, medir y acotar hacia la cara de otro objeto**: el punto cae ahora
  sobre esa cara (inferencia «en cara» para el segundo punto, salvo que la
  dirección coincida con un eje), y las caras de las instancias de
  componente dan su plano real, no el del prototipo en el origen.
- **Empujar/Tirar sobre una instancia de componente** dejaba de funcionar
  (solo un aviso en inglés): ahora empuja y el cambio llega a las copias.
- **Sumari, la figura de escala, con un pie en el aire en alzado**: la
  ilustración tenía un pie dibujado 7 cm más alto; los dos pies apoyan
  ahora en la línea de tierra.
- **Flatpak: los archivos .igz, .skp y .dae mostraban una hoja genérica** en
  el gestor de archivos; los iconos de documento se exportan ahora con el
  prefijo del identificador de la app, como exige Flatpak.
- **Windows: el instalador de 0.3.8 y 0.3.9 no arrancaba** si se instalaba en
  Archivos de programa: al iniciar, la app intentaba crear su registro de
  fallos (`ingetrazo-crash.log`) en la carpeta de instalación, de solo
  lectura, y el respaldo usaba la consola, que un .exe sin consola no tiene
  («sys.stderr is None»). Los registros de fallos viven ahora en la carpeta
  de datos del usuario (`%LOCALAPPDATA%\IngeTrazo` en Windows,
  `~/.local/state/ingetrazo` en Linux) y el arranque nunca depende de que
  exista una consola.

## [0.3.9] — 2026-09-03

**La release de las láminas.** Dos días de dogfooding sobre las láminas
reales de la pileta de Yanque: el compositor se puso a la altura de LayOut,
y Sígueme a la de SketchUp.

### Añadido
- **Sígueme como en SketchUp: arrastra y ve la extrusión.** Haz clic en el
  perfil y mueve el cursor por el camino tocando sus aristas: el camino se
  resalta en rojo y la extrusión se previsualiza en vivo, ingletes
  incluidos; clic (o soltar un arrastre real) al llegar al final, `Esc`
  para empezar de nuevo. Saltarte tramos de un arco no importa (se siguen
  las aristas conectadas entre medio), retroceder por el camino lo acorta,
  y con **Alt** sobre una cara el camino es su perímetro. Los flujos de
  camino preseleccionado (aristas o una cara) siguen igual. Todo según la
  página oficial «Extruding with Follow Me» y la tarjeta de referencia.
- **Cajetín con diseños y plantillas.** Siete diseños (Clásico, Esquinas
  redondeadas, Esquinas achaflanadas, Rótulos sombreados, Banda de
  cabecera, Minimalista, Doble borde) y los controles para armar el tuyo:
  forma y radio de las esquinas, disposición, doble borde, relleno de
  rótulos o banda, colores de rótulo, texto y línea, ancho de la columna
  de rótulos. Elegir un diseño cambia solo el aspecto: tus filas y el
  tamaño se conservan. Y tus propios cajetines se guardan como
  **plantillas** (Plantillas… ▸ guardar, aplicar, predeterminada para
  cajetines nuevos, eliminar, abrir carpeta); copiar/pegar estilo funciona
  también entre cajetines de distintas láminas.
- **Copiar, cortar y pegar ítems de lámina** (Ctrl+C / Ctrl+X / Ctrl+V),
  también entre láminas: en la misma lámina el pegado baja 5 mm en
  diagonal (y sigue avanzando en cada pegado), en otra cae en el mismo
  sitio; las vistas del modelo pegadas son marcos nuevos y los textos y
  cotas ligados a ellas los siguen.
- **Negrita, cursiva y subrayado** en bloques de texto y etiquetas con
  guía, desde el panel y en el editor in situ.
- **Etiqueta de escala móvil**: un bloque de texto ligado al marco
  («ESC. {escala}») que lee la escala de ESE marco, se mueve con él y se
  edita in situ. Sustituye a la etiqueta fija; las láminas antiguas la
  convierten solas al abrirse.
- **Agrupar, desagrupar y bloquear** ítems de lámina (Ctrl+G,
  Ctrl+Mayús+G, Ctrl+L): seleccionar un miembro selecciona el grupo y
  arrastrar la selección es un solo paso de deshacer.
- **La sesión LayOut del compositor.** Auto-render de los marcos cuando el
  modelo cambia; edición de la vista dentro del marco (doble clic: pan,
  órbita, zoom, Encuadrar modelo); escalas personalizadas del documento;
  texto editable en cotas (doble clic, `<>` = medida) y estilo de texto de
  cota (posición, alineación, color, fondo con opacidad); cota angular;
  pincel de formato y copiar/pegar estilo; fondo de color en textos; vista
  previa de impresión; bordes de marco y de lámina (simple, doble,
  discontinuo, esquinas redondeadas); anotaciones del modelo en los marcos
  como superposición de papel; plantillas de lámina; campos dinámicos
  ({proyecto} {autor} {lamina} {escala} {escena} {fecha} {archivo}…);
  organizar (alinear, distribuir, duplicar); etiquetas con línea guía; y
  edición in situ de textos y etiquetas con doble clic.
- **Anotaciones con capa** en el modelo (cotas y textos guía), estilo
  SketchUp: una capa «Anotaciones» oculta en una escena da el modelo
  limpio para la lámina.
- Las páginas de Propiedades del ítem mantienen sus filas juntas arriba y
  se desplazan si no caben.
- **Asistente IA: modelar desde una foto.** Botón «Foto…» en el chat
  (Ctrl+Shift+A): adjunta la foto de un objeto — una fuente, un mueble, una
  fachada — y el modelo la interpreta y lo recrea por partes como grupos
  editables, iterando contra capturas del viewport. La foto viaja
  reescalada a 1280 px como JPEG (con su rotación EXIF aplicada) y solo en
  el mensaje al que se adjunta. Las medidas las pones tú: una foto no las
  trae, y el asistente declara como supuesto lo que estima de la imagen.
  Requiere un proveedor con visión (Anthropic, OpenAI, Gemini, OpenRouter);
  con otro, el chat lo avisa.
- **Recetas IA con torno y prisma de fábrica.** Mirando sesiones reales,
  cada modelo se inventaba su propia matemática de revolución por pieza —
  40 líneas frágiles y facetadas cada vez. El scope de las recetas (chat y
  puente MCP por igual) ahora trae `revolve(perfil, …)` (sólido de
  revolución con tapas, festones opcionales por `scallop`, aristas suaves y
  orientación correcta) y `extrude(contorno, z0, z1)`: una línea por pieza,
  menos tokens y sólidos herméticos.

### Corregido
- **Plano de sección con un eje bloqueado (flechas) que escondía todo el
  modelo.** La normal era fija (+X/+Y/+Z): con la cámara al sur, un plano
  en Y delante de la fuente ocultaba la fuente entera de un clic. Ahora el
  plano colocado con un eje bloqueado (o sobre el suelo) mira a la cámara y
  oculta TU lado, como SketchUp: lo que hay detrás queda hasta que lo metes
  con Mover.
- **Cursiva, fuente y alineación de los bloques de texto no se aplicaban**
  desde el panel (las casillas estaban; el cambio nunca llegaba al ítem).
- **La etiqueta de escala fija de láminas antiguas no se podía quitar**
  (su control había desaparecido del panel): ahora se convierte en un
  texto normal al abrir el documento.
- **Doble clic en un marco tras pegar, duplicar o deshacer** fallaba con
  «objeto FrameItem ya eliminado»: la edición de vista anterior apuntaba a
  un ítem destruido con el lienzo.
- **Sígueme en un camino cerrado con el perfil en una esquina**: el barrido
  arrancaba por el tramo equivocado y el primer anillo colapsaba; además el
  perfil dejaba sus aristas sueltas. Ahora recorre el camino en el sentido
  perpendicular al perfil y consume el perfil, como SketchUp.
- **Rayos X y alámbrico dejan imantar a través de las caras** (antes el
  agua de una pileta tapaba los puntos de detrás para la Cota).
- **El texto guía ya no cruza sus palabras** cuando la etiqueta queda a la
  izquierda del anclaje.
- **Las escenas creadas antes del primer plano de sección** no recordaban
  «sin corte» y se contaminaban con el corte activo al recuperarlas.
- **Figura de escala (face-me) girada en proyección paralela**: ahora mira
  la dirección de vista, no un ojo ficticio.
- **El compositor no devolvía el corte ni el estilo** al modelo tras dibujar
  un marco (los cambiaba al aplicar la escena y no los restauraba).
- **Marcos raster «en blanco» y manchas en el agua**: el aviso «Actualiza
  la vista» se colaba en marcos que sí tenían imagen, y la lectura del FBO
  llegaba premultiplicada; ambos corregidos.
- **Cota de lámina anclada** que medía la distancia 3D entre sus puntos:
  ahora mide la distancia proyectada en el plano de la vista, como LayOut.
- **Export .skp**: el escritor entiende las dos generaciones de argumentos
  de tamaño aplicado (texturas) de openskp.
- **Asistente IA: una respuesta cortada por el límite de tokens ya no
  termina el chat en silencio.** Cazado en vivo con gemini-2.5-flash: el
  modelo se quedaba sin espacio a mitad del bloque ```python y el loop lo
  leía como "no hay código, terminé" — nada se dibujaba y nada avisaba.
  Ahora el asistente lo detecta, avisa en el chat y le pide al modelo un
  bloque más corto y completo; además el presupuesto de respuesta subió de
  4096 a 8192 tokens (16384 para Gemini: sus modelos 2.5 descuentan el
  «pensamiento» oculto del mismo presupuesto). Y el chat **nunca termina en
  silencio**: al agotarse el límite de pasos (ahora 12) lo dice y basta
  escribir «continúa» para retomar donde quedó.
- **Asistente IA: mucho menos consumo de cuota.** Cada turno reenvía la
  conversación entera, y con ella viajaban TODAS las capturas del viewport
  viejas — a la ronda 10, nueve imágenes muertas por petición. Ahora viaja
  la foto de referencia del usuario y solo la captura más reciente. Además
  la visión se detecta por modelo, no solo por proveedor: los Llama 4 de
  Groq (gratis) y los llava/qwen-vl de Ollama ya reciben foto y capturas.
- **Asistente IA: un modelo sin visión ya no revienta con la foto.** Groq
  rechaza con HTTP 400 el formato con imágenes en modelos de texto, y como
  la foto quedaba en la conversación, todos los reintentos fallaban igual.
  Ahora a un modelo sin visión no se le envía imagen alguna (la foto queda
  guardada y vuelve a viajar al cambiar a un modelo con visión), y el aviso
  del chat lo dice claro.
- **El costo por turno ya casi no crece con la sesión**: el código de las
  recetas viejas se reenvía como «[receta ya ejecutada — código omitido]»
  (su efecto ya está en el documento; la prosa y los resultados se
  conservan, y los 2 bloques más recientes viajan enteros). Además el
  prompt le enseña al modelo que el scope persiste entre bloques — no
  necesita redefinir sus funciones en cada receta.
- **Más dieta de tokens**: los bloques `<thought>` que algunos modelos
  (Gemma) filtran a su texto se limpian antes de guardar la conversación,
  el stdout de una receta se recorta a ~1500 caracteres en el feedback, y
  la captura del viewport solo se toma cuando el modelo CAMBIÓ (tras un
  error o una inspección, la anterior sigue siendo exacta).

## [0.3.8] — 2026-08-31

**La release del sol.** Un solo día de trabajo mano a mano: cada pieza se
probó en vivo contra SketchUp antes de darse por buena.

### Añadido
- **Sombras con el sol de verdad.** No una luz de adorno: la posición solar
  se calcula con las ecuaciones de la NOAA para la geolocalización del
  modelo (o Arequipa si no tiene), por fecha y hora — un **estudio de
  asoleamiento**, el entregable que SketchUp cobra. Panel de Sombras al
  estilo SketchUp: fecha con slider del año por meses, hora acotada de
  amanecer a atardecer (imposible dejar el sol bajo el horizonte sin darse
  cuenta), oscuridad, zona horaria automática por longitud, y «Añadir
  localización…» sobre el mapa. Las reglas finas también son las de
  SketchUp: **el vidrio (opacidad <70 %) no proyecta**, los personajes 2D
  proyectan su silueta orientada al sol (quieta al orbitar), la malla y las
  hojas proyectan su trama, y el sombreado de caras sigue al sol. Orbitar y
  hacer zoom reutilizan el mapa de sombras: el costo se paga al editar, no
  al mirar. Las láminas del compositor salen con sombras.
- **Import de CAD**: `.dxf` con ezdxf y `.dwg` vía el satélite LibreDWG
  (incluido en los paquetes de Linux). Capas → grupos etiquetados, bloques →
  componentes, la unidad se sugiere **midiendo el dibujo** (las cabeceras
  CAD mienten), y las coordenadas UTM de topografía se recentran solas.
  Doble clic en un `.dxf`/`.dwg` abre. En Windows, DWG queda para una
  siguiente entrega (falta el satélite .exe); DXF sí va.
- **Imágenes de referencia** (`Archivo ▸ Importar ▸ Imagen`): un plano
  escaneado o una foto como fondo para calcar — da plano de trabajo y snap,
  viaja dentro del `.igz`, y se puede bloquear para que no estorbe.
- **Escalar como SketchUp**: el cajón amarillo con agarraderas por esquina
  (uniforme), arista (2 ejes) y cara (1 eje), Ctrl desde el centro, Shift
  uniforme, factor negativo para espejar, y el VCB acepta factor, `a;b` por
  eje o medida absoluta con unidad.
- **Ocultar/mostrar aristas** (Edición y clic derecho), con **Mayús+goma**
  para ocultar de pasada, como en SketchUp.
- **Editor de estilos**: panel con los estilos integrados y una biblioteca
  personal («Guardar estilo…»), colores de cielo y suelo con **degradado
  atmosférico**, y los estilos guardados disponibles por marco en las
  láminas.
- **Ventana ▸ Preferencias**: idioma, resto del modelo al editar, unidades
  sugeridas de import, coordenadas geo/UTM, y el Asistente IA — más
  **auto-guardado con recuperación** tras un cierre abrupto, **copia de
  seguridad** del archivo anterior a cada guardado, invertir la rueda del
  ratón y el suavizado MSAA configurable en vivo.
- **Ctrl+0 — pantalla limpia** (como AutoCAD): solo el modelo, para
  presentar; Ctrl+0 otra vez y el espacio de trabajo vuelve tal cual.
- **Malla cocada** en la biblioteca de materiales (Metal): rombos a escala
  real con transparencia — y su sombra proyecta el tejido.

### Cambiado
- **Estilos, Sombras y Estilo de cota ya no viven en la bandeja derecha**:
  son desplegables del toolbar «Paneles» — se abren bajo el botón y se
  pliegan al hacer clic fuera. La bandeja de Propiedades respira.
- **La disposición de toolbars y paneles se recuerda** entre sesiones, y las
  instalaciones nuevas arrancan con el orden de fábrica (Dibujo vertical a
  la izquierda).
- Las figuras de personas se sanearon por dentro (su tinta interior
  translúcida perforaba la silueta con puntitos del color de los ejes).

### Corregido
- El caché de texturas GL ya no se fuga al abrir otro documento.
- Un crash nativo ahora deja autopsia en `ingetrazo-crash.log`.

## [0.3.7.1] — 2026-08-28

**La 0.3.7 revisada en inglés.** Marco la usó con la interfaz en ese idioma
y encontró que el catálogo hablaba español por su cuenta.

### Corregido
- **La biblioteca de componentes salía en español con la interfaz en
  inglés**: la categoría, el nombre del modelo y la licencia. Ahora cada
  uno se dice en el idioma que se está leyendo, y el buscador acepta los
  dos («chair» y «silla» encuentran lo mismo). Las categorías se traducen
  desde una sola lista canónica porque **las dos del catálogo se
  contradicen** — el mismo modelo es «Dormitorio» en español y «Office» en
  inglés, y tomar las dos partiría una categoría entre dos filtros.
- **Fuera las medidas en cm de la ficha del modelo.** Todo llega ya al
  tamaño que declara el catálogo, así que el dato no decía nada que no se
  pueda medir en el dibujo, y se leía como una especificación que el
  componente no tiene.

### Cambiado
- **Las figuras de escala van por nombre de pila**: Richard, Linus, Elon,
  Stephen.
- **Fuera los ocho colores sin nombre** de la bandeja de Materiales. Al
  lado de 213 colores RAL que llevan una referencia comprable, un cuadrado
  anónimo solo confunde.
- **Sumari nuevo**, a su altura real de 1,68 m. `SOURCES.md` decía 1,65 y
  el programa insertaba 1,72: la nota y el código no coincidían y ninguno
  acertaba.

## [0.3.7] — 2026-08-28

**La release de los componentes, las texturas y los colores.** Una sesión
entera de dogfooding sobre la biblioteca en línea: cada arreglo salió de
Marco abriendo la bandeja y diciendo qué se veía mal, y todos resultaron ser
nuestros, no de los modelos.

### Añadido
- **Biblioteca de componentes en línea publicada** en `ingetrazo.com`:
  1510 modelos con miniatura, tamaño real, licencia y autor. Navegar cuesta
  medio mega; solo se descarga el modelo que se pulsa, y queda en caché.
- **8 modelos y 6 figuras de escala dentro del programa**, para trabajar sin
  red. Las figuras van a su altura real: la cartela mapea la imagen entera a
  esa altura, así que el recorte tiene que ser exacto.
- **427 texturas** (antes 30), de las bibliotecas de Sweet Home 3D. Lo que
  importa no son las fotos: el catálogo declara el tamaño real de cada una,
  y un ladrillo puesto a ojo se ve como un mosaico.
- **213 colores RAL Classic** con su nombre. Al pintar dejan un material CON
  NOMBRE — «RAL 7035 Gris claro» —, o sea una referencia que un pintor puede
  comprar, no tres números.

### Corregido
- **Los modelos importados entraban tumbados.** Un OBJ no dice cuál es su
  vertical y las dos convenciones del mundo no coinciden. Al arreglar el
  giro apareció el resto: el catálogo aplica su propia matriz y estira el
  modelo al tamaño declarado, y **uno de cada cuatro de estos ficheros no
  está en centímetros** (una barandilla de 126 cm cuyo OBJ mide 3,7).
- **Las texturas salían hechas añicos en lo curvo.** Se descartaban las
  coordenadas del propio fichero y se proyectaba la imagen en plano sobre
  cada faceta.
- **Y se quedaban atrás al colocar.** El mapa está anclado a coordenadas del
  mundo; ahora viaja con la geometría al colocar, mover, girar y escalar.
- **Las aristas de la triangulación se dibujaban todas.** El fichero dice
  qué caras forman una superficie continua (`s`); ahora se le cree.
- **No se podía uno acercar a un componente**: la cámara tenía un tope de
  50 cm. Ahora 2 cm, con el plano cercano acompañando.
- **Dos modelos tumbaban la importación** por una arista que empieza y acaba
  en el mismo vértice.
- **Issue #6 — los paquetes de Linux no arrancaban con NVIDIA + X11.** El
  bundle llevaba `libX11` y el driver del anfitrión cargaba la del sistema:
  dos copias en un mismo proceso. Ahora vienen del anfitrión. *Verificado
  solo que no rompe el caso que funcionaba (AMD + X11); la mitad NVIDIA
  sigue sin verificar.*
- **El plugin del asistente no cargaba en el paquete** (`core.ai` no
  entraba), y **la biblioteca de texturas no se empaquetaba** en Windows,
  así que la sección Materiales salía vacía.
- **La biblioteca en línea habría salido muerta**: Cloudflare responde 403
  al User-Agent por defecto de Python.

### Rendimiento
- **Llenar la bandeja de componentes: 21,6 s → 1,2 s.** Las miniaturas son
  de 10 KB y el coste es el viaje, no los bytes; se piden 16 a la vez, fuera
  del hilo de la interfaz, con 40 filas por adelantado.
- **El arranque no se alargó** pese a meter 427 texturas y 213 colores: las
  muestras de cada sección se construyen al abrirla, no al abrir el
  programa. Medido: 0,21 → 0,95 s al añadirlas, y 0,14 s ya arreglado.

## [0.3.6.3] — 2026-08-27

**The release that puts .skp import back.** A change in OpenSKP upstream
turned every imported model into a field of spikes, and hunting Marco's
report through a modelling session took five more defects with it.

### Fixed
- **Imported `.skp` models came in shattered into triangles and spikes.**
  OpenSKP normalized what a coedge's flag carries — SketchUp's raw storage
  bit (0 forward, 1 reversed) became the documented +1 / −1 — and reading it
  as a boolean then took the same endpoint for every coedge, so any polygon
  holding a reversed one came out as a self-intersecting star. Measured on
  Marco's plaza: the same 115973 faces and the same bounding box, with the
  model's surface down from 43008 to 13590 m². The ring now comes from the
  loop's connectivity, which reads the same under either contract, so a
  future rename cannot break it again. v0.3.5 was built before that change
  and was never affected; every 0.3.6.x build was.
- **Drawing a rectangle on a solid opened it.** The Rectangle tool adds its
  own faces, and the flag that says so also gated propagating an edge SPLIT
  into the other faces carrying that edge — so a door drawn on a wall split
  the wall's bottom edge in three while the floor kept the original long
  one. Coincident, not shared, and the box stopped being closed. Everything
  volumetric quietly stops working on an open shell, which is where the next
  three came from. Three fuzz sequences that used to hit a known engine gap
  now pass.
- **Push/Pull into a face read the drag backwards on an open shell.** The
  tool signs the distance along the base's outward normal, which
  `orient_outward` can only establish where there is a volume to test parity
  against. On an open shell a face keeps whatever winding the draw gave it,
  so a drag INTO a wall read as positive: the base face was never hidden and
  the outer face stood there covering the pocket forming behind it, and the
  commit then swept the push the wrong way entirely.
- **Push/Pull's drag preview now reads as one clean solid.** It draws the
  sweep's own edges (they were missing), softens a curve's facet seams the
  way the commit does, carries the material and re-anchors the texture to
  each new face, and paints both sides of a preview face alike — an overlay
  has no back. A clean prism extend or shrink is previewed by moving the
  cap in the model instead, so nothing of the old shape is left standing.
- **Push/Pull extrudes the material with the shape.** Pulling a painted
  rectangle up gave a box with one painted face; the new sides come out
  painted too, each mapping the texture in its own plane.
- **Splitting or carving a painted face keeps the paint.** A line drawn
  across a textured face wiped it off both halves, and a door outlined on a
  textured wall came out bare. Both keep the mother's paint now, and keep
  its texture map, so the image runs straight across the cut instead of
  restarting on each piece.
- **Snapping no longer reaches through a group.** Occlusion only knew the
  loose mesh, so nothing inside a group hid anything and drawing on a box
  snapped to the edge on its far side. It asks the pick index now — the one
  structure that holds the whole model — so occlusion and picking can never
  disagree about what is in front.

### Known
- A rectangle drawn on a face, pushed out and pushed back flush, dissolves
  into the wall. Isolated to the per-plane rebuild: its rule may dissolve
  the operation's own seams, and a pushed face's boundary is both the user's
  line and the operation's rim. Telling them apart needs an edge to carry
  where it came from — the identity work already on the list.

## [0.3.6.2] — 2026-08-27

### Fixed
- **Base-map tile cache evicted the tile it had just written.** Eviction
  reads the filesystem's modification times, and their granularity can be
  coarser than the gap between two writes — so a busy cache had no order
  left to sort by and dropped fresh tiles while keeping stale ones. Each
  write now stamps its tile as strictly the newest.

## [0.3.6.1] — 2026-08-27

### Fixed
- **Saving `.skp` was broken in the 0.3.6 build.** The exporter passed the
  writer two arguments only our OpenSKP fork has (a texture's applied size
  and the opacity gate), so against the library the release is built with,
  every scene with a painted face failed to save. The joins now ask the
  installed writer what it accepts and pass only that; an older library
  writes the file without them rather than not at all.

## [0.3.6] — 2026-08-27

**The nested-placement release**: an imported component keeps the sharing
SketchUp gave it inside itself, which is what makes the files we write
small again — and, hunting that through a real modelling session, three
long-standing freezes fell with it.

### Added
- **Nested placements**: a group owns placements of shared prototype
  meshes, drawn, picked, saved and exported as part of it — one object
  to you, however deep the tree. An imported component no longer arrives
  flattened, so a hedge stored as 9600 faces placed 48 times stays that
  way instead of becoming 230400 real ones.
- **Eyedropper parity (Paint ▸ Alt)**: sampling a face now carries its
  material to the next click the way SketchUp does — image, applied
  size, rotation, translucency and the material identity. A face with an
  explicit world→UV map hands it on only within its own plane, where it
  keeps the pattern lined up; a face on another plane takes the material
  with its own projection at the same size (copying the map across
  planes smeared the image into stripes). The pointer becomes an
  eyedropper while Alt is down.

### Fixed
- **`.skp` files were five times too big.** Saving Marco's pool wrote
  80 MB against SketchUp's 14. Not textures (6.7 MB embedded there
  against 7.1 here) — geometry duplicated by losing a component's
  internal sharing. Now **72.4 MB → 28.7 MB**, with stored faces down
  from 1 294 258 to 75 599 and the world geometry identical (same
  bounding box, area within 0.08%). Prototypes with identical content
  are folded too: a .skp can carry the SAME material under two ids,
  which was splitting the hedge's leaves into twin prototypes.
- **Deleting inside an imported group hung the app** — 206 s to erase
  60 faces in a 3054-face barbecue, and a cliff that made it look
  random: the heal's 3000-face guard let the work through only once you
  had deleted enough. Three passes that scaled with the whole model for
  an edit that touched a part: the T-junction sweep (one pass alone
  measured 24.8 s and repeated per split — the batched version already
  written for Push/Pull now serves both call sites), the heal's
  quadratic coplanar pairing (4.2M face-normal recomputations), and the
  orphan-edge prune. **206 s → 3.07 s**, with a byte-identical result.
- **A moved group left a ghost selection box** where it used to be: the
  translation fast paths carried every cached array except that one.
- **Selecting a big component took seconds** — the box was derived by
  welding a merged copy of the whole component (23.6 s with nested
  placements, 5.1 s before) to read eight corners. Now it works from
  the points: **0.11 s**, and the box is identical.
- Drag previews, rubber-band selection, Explode and the scene queries
  (bounds, world faces, BIM quantities, model info) all reach a
  component's nested geometry; Explode used to leave it behind entirely.
- Zoom got its lightness back: the per-frame instance gather is cached
  per scene version and its frustum cull is one vectorised pass
  (2.5 ms → 0.1 ms per frame).

## [0.3.5] — 2026-08-25

**Sections, the SketchUp parity batch, AI modelling, and the performance
marathon** — a full real-world modelling session (a 280k-face pool
project) hunted down every freeze it hit.

### Added
- **Section planes** (SketchUp's Sections, complete): place the active
  cut with hover plane inference (arrow keys / Shift to lock), one
  active cut per context, GPU-clipped model with **thick cut edges**,
  **section fill**, corner symbol balloons and the Sections toolbar.
  Sections move/rotate/delete like geometry, reverse and "Align View"
  from the context menu, picks and snaps ignore the clipped side, and
  scenes + `.igz` remember the active cut. The composer's hidden-line
  pass clips too and draws the cut chords — real plans and sections on
  sheets.
- **SketchUp tool parity batch**: **Flip** (2023-style axis planes,
  Ctrl = flip a copy, classic context-menu entries), **Make Component**
  (G, shared definitions + Make Unique), **Freehand** (sampled,
  RDP-simplified, selects as one contour), **Pie** arc (closes the
  wedge with a face) and chord bulge / radius suffixes in the
  Measurements box. "Offset" is now **Equidistancia** (SketchUp's
  Spanish name).
- **AI Assistant** (Extensions menu): chat with an AI provider from
  inside IngeTrazo — provider picker with per-provider API key and
  model memory; every AI edit lands as ONE undoable command with full
  rollback on failure. Plus the **AI Bridge (MCP)**: model with Claude
  from outside the app over the Model Context Protocol.
- **Native glTF/GLB import** (PBR materials mapped to the paint
  system).
- **Starter components and textures**: CC0/CC-BY sedan, oak, bush and
  a scale figure standing at SketchUp's real offset; texture library
  additions (bark, rock, river pebbles, lawn, concrete pavers, water);
  glass paints translucent end-to-end (library → paint → face).
- Drawing axes recalibrated against SketchUp (fine-dot negative
  directions, denser dots); imported files show their name in the
  window title; the plugin path is documented for outside developers.

### Fixed
- **The paste "app not responding" hang**: `Scene.bounds()` walked the
  whole model in Python and ran twice per hover over empty space (work
  plane + status-bar coordinate) — the event loop starved for 10+
  seconds on big scenes. Now cached per scene version with a
  vectorized walk. This was most of the "zoom feels slow" report too.
- Billboards keep mipmaps with a hard alpha cut (no more dither dots
  at distance); Groq 403/404 in the AI Assistant.

### Performance
The pool-project marathon, in order of pain: box select vectorized ·
loose-edge silhouettes vectorized (the constant orbit/zoom lag) ·
erase cascade indexed (30 s curved-surface deletes → instant) ·
`heal_overlapping_faces` capped at hand-drawing scale · zoom focus
pinned to the camera pose and revalidated by projection after an orbit
(no ~25 ms re-pick per notch) · ray picks bucket only hit triangles ·
**Move, Rotate AND Paste preview through frozen scratch VBOs** (one
upload, every drag/hover frame is a translated MVP — SketchUp-grade
dragging of a 230k-face group) · Merge Groups fuses group-to-group
without the loose-mesh detour · one Newell per face on edit frames ·
group copies go through the bulk-weld pass · **pasting a huge classic
group stamps an O(1) sibling of the clipboard prototype** (SketchUp
semantics: copies share the definition until edited) — stamping the
230k-face group went from ~12 s to instant, rotating a pasted copy
from seconds to 0.1 s.

## [0.3.4] — 2026-08-25

**The dogfooding release: a real modelling session's bug hunt, plus
SketchUp-parity work.** Everything here came from drawing an actual
model and comparing, tool by tool, against SketchUp's official
documentation.

### Added
- **Display styles** (Camera → Style), SketchUp's Styles scoped to what
  serves printing: Default, Architectural (textures on white), Shaded
  (materials as their texture's average colour), Hidden line (the plan
  style), Monochrome, Wireframe and X-ray — plus Edges/Profiles toggles.
  Scenes remember their style; `.igz` persists it.
- **Composer frames pick any style** (LayOut-style viewports): each
  sheet frame can render in any of the styles above, the model's active
  style, or the exact vector hidden-line pass.
- **Copy/paste for groups and components** (Ctrl+C/X/V, context menu):
  instances paste as siblings of the same prototype; attrs (colours,
  textures, layers, BIM tags) travel; positioned textures re-anchor to
  the paste point. Paste previews the SOLID model — colours and
  textures riding under the cursor — and stamps once, returning to
  Select (SketchUp).
- **Protractor rebuilt to SketchUp parity** (official docs): plane
  inference by hover with axis-coloured disc, arrow-key plane locks,
  Shift freeze, fixed-size disc with 15° ticks, tick snapping near the
  disc / 0.1° free farther out, slope input as rise:run (`3:12`), and
  the guide stays retypeable after creation.
- **Rotate shows the same protractor**, with tick-snapped live preview,
  Ctrl = rotate a COPY (groups, instances and loose geometry), a
  click-drag from the centre to set a custom fold axis, and hot retype
  after the commit. The Measurements box accepts `3:12` here too.
- **Tool cursors**: the pointer becomes the active tool — a pencil
  (with the shape as a badge) for the drawing tools, hotspot at its
  tip; eraser/bucket/tape/protractor at their action points; orbit,
  pan and the magnifier during camera navigation.

### Fixed
- Box selection now takes groups and component instances (window =
  fully enclosed, crossing = touched), and guides (crossing only).
- Move/Rotate/Scale transform the WHOLE mixed selection — every group
  plus loose geometry — as one undo step (only the first group moved).
- Guides survive perspective (an endpoint behind the camera made the
  whole guide vanish from render, snap and eraser), and are now
  selectable/deletable with Select + Delete, right-click, or a
  crossing box. Guide points feed the snap engine.
- Esc releases the arrow-key axis lock / reference before cancelling
  the operation (it never did).
- Copying painted or textured loose geometry pasted bare; attrs now
  travel through the clipboard with textures re-anchored.
- Planar-projected textures (hand-painted, the scale figure) no longer
  swim through the paste preview as the cursor moves.
- About dialog: Arequipa, Perú.

### Changed
- openskp dependency back on upstream (`iamahsanmehmood/openskp`):
  every IngeTrazo patch is merged there, including the annotations
  writer (PR #203). CI pins upstream by SHA.

## [0.3.3] — 2026-08-21

**The complete SketchUp round trip.** IngeTrazo now writes native `.skp`
(File → Export → SketchUp) and opens Marco's entire 13-year real-project
corpus — 186 of 186 files, 2013–2026 — natively. Annotations travel BOTH
ways: dimensions and leader texts drawn in IngeTrazo appear in SketchUp,
and the ones in `.skp` files land in IngeTrazo as live, editable
annotations. The underlying reader fixes are merged into upstream
[OpenSKP](https://github.com/iamahsanmehmood/openskp) (PRs #194/#199);
the annotation writer is proposed as PR #203.

### Added
- **Native `.skp` export** (`formats/skp_out.py`, powered by
  `openskp.create`): faces with holes, groups, shared components (one
  definition + N placements), named materials with textures, layers —
  and now **dimensions and leader texts**.
- **`.skp` annotation import**: linear dimensions (all eras) and leader
  texts with their real label position and leader line; text records
  decoded byte-exact against SDK-generated ground truth ("Rosetta"
  files) and human-drawn corpus records.
- **Material registry** — materials have NAMES that survive editing:
  painting keeps identity, right-click a named swatch to edit-and-restamp
  every use, Model Info reports per-material quantities (m²), and OBJ/DAE/
  glTF/SKP exports carry the real names (`Concreto_visto`, not `mat0`).
- **Leader-text lifecycle**: select by clicking the text itself (glyphs
  outrank geometry), move with the anchor pinned (leader stretches, live
  preview), edit on double-click (SketchUp's gesture), delete with
  Supr/context menu, box-select — every step one undoable command.
- **Solid Inspector** (bundled plugin): explains WHY a solid is not
  watertight.

### Fixed
- Legacy (2013–2020) `.skp` reader: 16 decoded format variants merged
  upstream — burned MapObject indices with piecewise reference
  translation, v20 layer-list separators, self-calibrating guide-line
  tails, CImage entities, escaped/forward entity refs, Length/Point3d
  attributes, per-object layers on 2014-era files, and more. Every fix
  validated against fingerprint-identical corpus parses.
- Texture drape detection now only runs on legacy files (the projected
  flag is authoritative there); modern VFF files trust their own flags.
- Deleting a selected leader text with Supr raised a silent NameError
  (missing import since the Text tool's original commit); the context
  menu's Delete ignored leader texts entirely.
- `.skp` export kept same-recipe named materials separate (a repaint in a
  different name no longer merges them), and unpainted faces keep
  SketchUp's default material instead of turning white.
- Python Console: a failing script no longer drags an internal
  SyntaxError into the error report.

## [0.3.2] — 2026-08-18

**IngeTrazo has extensions.** The plugin system `docs/plugins.md` had been
promising is implemented: an **Extensions** menu discovers Python plugins at
startup from `<app>/plugins/` and the per-user directory
(`~/.local/share/ingetrazo/plugins/` on Linux, `%APPDATA%\ingetrazo\plugins\`
on Windows). Based on contributions by Ahsan Mehmood
([OpenSKP](https://github.com/iamahsanmehmood/openskp)) — thank you! —
consolidated and reworked in #4.

### Added
- **Extensions menu + plugin engine** (`core/extensions.py`): plugins load
  by file path (works in the packaged builds), a broken plugin shows as a
  disabled "⚠ (load error)" entry instead of preventing startup, only tools
  *defined* in a plugin register, and a plugin cannot steal a built-in
  shortcut.
- **Model Info** (bundled plugin): geometry counts, bounding box in the
  document's units, materials in use with painted area per material, layers,
  and BIM objects with quantities — the same numbers the BIM tray and the
  IFC export report.
- **Python Console** (bundled plugin, `Ctrl+Shift+P`): a live REPL over the
  open document. Every run is ONE undoable step through the command layer
  (Ctrl+Z, dirty flag, immediate repaint); a failing script rolls back
  whole; a demo script builds a BIM-tagged pavilion
  (`scripts/create_architectural_showcase.py`).
- **CI on pull requests**: the fast test suite runs on every PR (previously
  only on release tags).
- `docs/plugins.md` rewritten: the implemented contract, plus the
  `SnapshotImport` recipe for plugins that modify the model.

## [0.3.1] — 2026-08-12

Linux gets first-class installers: every release now ships an **AppImage**
(make executable and run; needs FUSE) and a **plain tarball**
(`IngeTrazo-<version>-linux-x86_64.tar.gz` — extract and run `./ingetrazo`,
no FUSE, unpacks anywhere), both built and smoke-tested by CI on
ubuntu-22.04 so they start on 22.04 and later. The Windows installer is
unchanged.

### Added
- `packaging/build-appimage.sh` (PyInstaller onedir → AppImage + tarball,
  adapted from IngeCAD's) and the `release-linux` workflow.
- `main.py --check`: self-diagnosis that reports whether the install can
  find its shaders, translations, textures, components and icons, plus
  whether the optional Wine/skp2dae converter is present. CI gates the
  bundle, the AppImage and the extracted tarball on it.
- `core/paths.py` (`app_root()`): the six runtime resource lookups that
  derived paths from `__file__` now go through it, so a frozen build fails
  loudly at `--check` instead of at first shader load if the bundle layout
  ever drifts.

### Changed
- Composer: big models no longer freeze the sheet tools.
- Repository references updated from `tuxiasumari/ingetrazo` to
  `ingelibre/ingetrazo` (About dialog, tile-fetcher user agents, and the
  skp2dae download URL, which only worked through GitHub's rename
  redirect).

## [0.3.0] — 2026-08-08

The sheet-composer release: model to printed plan without leaving IngeTrazo.

### Added
- **Sheet composer** (Archivo ▸ Compositor de láminas): QGIS-style page
  layout with model-view frames at EXACT scale (1:100 on a 200 mm frame is
  20 m of model), N sheets per document persisted in the `.igz`, its own
  undo history, and vector PDF export (single sheet or the whole atlas in
  one file).
  - Frames render shaded, technical (white + dark edges via exact
    hidden-line removal) or lines-only; automatic frame titles, graphic
    scale bar, north arrow, layer legend, images, text and an editable
    title block; DXF (R12) export of a frame's vector view for IngeCAD.
  - **Sheet dimensions anchored to the model**: snap both points to frame
    geometry (green dot) and the cota remembers the 3D points — edit the
    model, move or rescale the frame, and the dimension follows with its
    label re-measured (the exact 3D distance). LayOut-style placement:
    two clicks for the points, a third pulls the line away with extension
    lines; separation stays draggable afterwards.
  - Dimension styles: text height, decimals, oblique ticks / arrows /
    none, line width, colour.
  - Shapes: line, arrow, rectangle (with corner radius), ellipse and
    regular polygon (3–24 sides), each with line colour, fill and fill
    colour.
  - Title block: editable rows (add/remove/rename fields), 1–4 column
    groups, outer border and inner line widths, exact width/height; long
    values wrap to more lines and only then shrink.
  - QGIS habits: stacking order (bring to front / raise / lower / send to
    back) and per-item lock via right-click; items panel lists the stack
    top-first; zoom combo with fit-width / fit-page / presets where 100%
    is TRUE paper size.
- **Photogrammetric survey import (WebODM/ODM)**: the textured drone mesh
  loads as display-only reference geometry with its real UTM placement and
  altitudes, texture atlases capped to the GPU budget, saved inside the
  `.igz`, and a plan-grid `height_at` query that feeds the live profile.
- **UTM WGS84 in the georef UI**: the base-map panel and the project
  locator accept zone/hemisphere/E/N (what the drone or total station
  reports) or lat/lon — one frame at a time, chosen with a remembered
  selector. The locator's centre pin is explicitly the model's origin
  (0,0), and moving an existing origin asks first.
- New app icon (V11D): line-drawn cube with amber nodes on the IngeCAD
  family tile, now a single SVG source of truth.

### Fixed
- **Opening a `.skp` by double-click could freeze before the window
  appeared** (a progress callback ran on the worker thread and
  deadlocked); imports also no longer fall back to the external converter
  silently.
- **Single instance**: a second launch opens the file in the running
  window instead of dying to a zombie; an unresponsive instance no longer
  swallows launches.
- Drawing tools: the first unsnapped point stays in the plane you are
  looking at; bigger snap markers; frontal measurement in standard views.
- Georef: omitting altitude means "on the reference plane", not sea level.

## [0.2.4] — 2026-07-26

Self-contained `.igz` documents: textures travel INSIDE the file (ZIP
container, 5× smaller than the previous flat JSON), no absolute paths
left; `.skp` import stops creating folders next to the user's file. See
the GitHub release notes for the details.

## [0.2.3] — 2026-07-22

Native pure-Python `.skp` import for ALL SketchUp eras (our OpenSKP fork:
VFF walker + legacy MFC parser), validated for exact parity on real
models; skp2dae becomes an emergency fallback only. See the GitHub
release notes for the details.

## [0.2.2] — 2026-07-20

A polish release focused on the toolbar icons, plus two new zoom tools and
branded file-type icons.

### Added
- **Zoom** and **Zoom Window** camera tools on the View toolbar (and Camera
  menu). Zoom (`Z`) drags up/down to zoom in/out; Zoom Window drags a
  rectangle and frames that region. Icons: a magnifier, and a magnifier
  inside a rectangle.
- **Branded document icons** for the file types IngeTrazo works with —
  `.igz` (native), `.dae` (COLLADA) and `.skp` (SketchUp). On Linux a
  freedesktop MIME package paints the icons in the file manager (installed
  by `scripts/install_desktop.sh`); on Windows the installer associates the
  `.igz` icon and adds IngeTrazo to the "Open with" list for `.dae`/`.skp`.
  Double-clicking a `.dae`/`.skp` now imports it.
- **3D Text** now has a button on the Annotate toolbar (it was menu-only).

### Changed
- **Redesigned the tool icons** so each is the plainest picture of what it
  does, on its own visual identity: Paint is now Inkscape's tilted-bucket
  "fill" mark, Rotate is a pair of circular arrows, Orbit is an arrow
  circling a sphere, Pan is a cleaner open hand, and the Standard Views are
  little houses drawn from each viewpoint (front with a door, back with a
  window, mirrored sides, roof-from-above, an isometric house) — 3D Text is
  a solid extruded "A".

### Fixed
- Toolbar icons are re-drawn when the OS theme flips light ↔ dark while the
  app is open — they were baked at startup and previously stayed in the old
  theme's ink until a restart.

## [0.2.1] — 2026-07-16

Open SketchUp files directly: File ▸ Import ▸ SketchUp (.skp)…

### Added
- **Direct `.skp` import** through the external `skp2dae` converter — run as
  a separate process (the proprietary Trimble DLL never enters the GPL
  tree). The `.dae` and its texture folder land next to the `.skp`, then the
  existing COLLADA importer takes over (groups, components, textures,
  face-me sprites). On Linux the converter runs via Wine.
- **One-click converter install**: if `skp2dae` is missing, the import
  dialog offers to install it automatically — the converter executable is
  downloaded from the IngeTrazo release and the SketchUp runtime DLLs from
  the Blender "SketchUp Importer" add-on's public release, into
  `~/.local/share/skp2dae/`. No terminal required.

### Fixed
- `.skp` files stored under accented paths (`Imágenes`, `ñ`…) failed with a
  UTF-8 decode error — Wine re-encodes command-line arguments to the
  Windows ANSI codepage. The conversion now routes through an ASCII
  temporary path and tolerates any output encoding.

## [0.2.0] — 2026-07-15

The BIM release: the IFC bridge to IngePresupuestos is validated end to end,
SketchUp models migrate with textures and components, the terrain workflow
takes real field data — and the UI grew into its SketchUp skin.

### BIM → IFC (the thesis, closed)
- **Per-class base quantities** (`Qto_*BaseQuantities`): walls report net
  side area + height/length/width, slabs area + thickness + perimeter,
  columns/beams volume + length + cross-section, doors/windows real leaf
  dimensions (also as `OverallHeight/Width` attributes), piles/members/
  railings by the metre via `IfcQuantityLength`.
- **IFC4 export validated against a real consumer**: ifcopenshell parses it
  with zero schema/EXPRESS issues, tessellates every body, reads the
  quantity sets — permanent in the test suite.
- **The bridge works**: a tagged model imported by IngePresupuestos' IFC
  importer lands every takeoff EXACT (walls in m², columns in m³, piles by
  the metre, doors by the unit) — also a permanent cross-repo test.
- **Tag as you draw** (active class): arm a class in the BIM panel and every
  trace assumes it — one BIM object per trace, honest per-object takeoffs.
  Push/pull extends a tagged base to the solid it raises.
- The BIM panel now shows the **budget measure per object** (10.40 m²,
  0.31 m³, 1 und) instead of the misleading shell area.

### Bring your SketchUp models
- **COLLADA (.dae) import with real textures**: per-face UV maps from the
  file's TEXCOORDs, texture-tolerant coplanar fusion (no dirty
  triangulations), representative colours when the image folder is missing.
- **SketchUp's group structure survives**: one Group per assembly (a plaza
  imports as 291 groups, not one blob) — click selects the lamppost, not
  the world; edit by entering the small group.
- **Components import as shared instances**: one prototype mesh, N
  transforms (16 instances/6 prototypes saved 59k faces on a real nursery
  project; import went 24.7 → 10.8 s).
- **Face-me sprites recovered**: the cutout people/trees SketchUp exports
  without the flag turn toward the camera again, with SketchUp-style
  selection outlines and snap anchors (feet, head).
- **Big-model interaction**: vectorised pick index (2138 → 22 ms), per-group
  render/pick chunks, one-draw-call faces — a 394k-triangle plaza orbits
  at 60 fps and a 17k-triangle building imports in 0.8 s.

### Terrain, from field data
- **Survey-point CSV import** (P,N,E,Z,desc in UTM — GPS/total station):
  points become snappable reference markers; the pencil lands bit-exact on
  the surveyed coordinate. Anchors the scene datum at the first point.
- **Named XYZ sources, saved forever** (QGIS-style): add a tile source once
  with a name and it is always in the menu, each with its own tile cache;
  the last-used source restores on startup.
- The Georef tab is now **Terreno** — the trade's word.

### New tools
- **Text (X)**: leader-text annotations — the prompt prefills with the
  clicked edge's length, face's area, or point coordinates (SketchUp-style);
  occluded leaders, selectable, saved in `.igz`.
- **3D Text**: real extruded geometry from any system font — one watertight
  solid per letter (counters preserved), smooth thickness, glued to the
  face under the cursor (a relief sign on a wall, text lying on a slab).
- **Hi-res image export** (File ▸ Export ▸ Image): the current view at any
  pixel width through the exact render pipeline, presentation overlays
  included — 4K sheets straight from the program.
- **Component placement with the cursor**: inserts follow the mouse and
  settle on the ground plane (or any face you point at); Esc discards.

### UI, SketchUp-shaped
- Menu bar reorganized to mirror SketchUp: **Archivo · Edición · Cámara ·
  Dibujo · Herramientas · Ventana · Ayuda** (Draw groups Arcs/Shapes,
  Camera owns views/projection/orbit, Window owns panels + language).
- **Components tray panel** with static image thumbnails (no 3D rendering
  to show them), replacing the File-menu submenu.
- File menu unified into **Import** and **Export** submenus (survey CSV
  included); duplicate dock titles above the tray tabs removed.

### Fixes
- Graze intersections snap to the vertex they graze (tangent circles).
- Lines drawn on a populated plane run the scoped rebuild (no stacked
  inverted faces).
- A slit edge deletes the line and keeps the face.
- Face attrs (textures, colours, layers, IFC tags) travel through Make
  Group / Explode.
- MSAA moved into the scene FBO — first real antialiasing.
- Orbiting with dimensions visible: occlusion test cached + vectorised
  (280 → 6 ms/frame).

## [0.1.0] — 2026-07-11

The first release. A usable, free, Linux-first SketchUp-style 3D modeler for
civil engineering and architecture — draw → model → tag → take off → export.

### Modeling engine
- Shared-vertex non-manifold topology engine (SketchUp's model): sticky
  geometry, automatic welding, face detection, planar-arrangement rebuilds.
- Push/Pull with the full solid pipeline: recess, steps, through-holes,
  clamps, distance inference, Ctrl = copy, double-click repeats — and the
  **BIM-grade watertightness guard**: the engine never commits a broken
  solid (ambiguous operations are refused safely, and told to the user).
- Robust curve entities: circles, polygons, 4 arc types; curves select as
  whole contours, split at intersections, survive copy/paste/offset/groups.
- Deterministic intersections: circle×line, circle×circle, rect×rect split
  into proper regions — on flat drawings, next to solids, and on solid faces.
- Transactional command history: any internal failure rolls back to the
  exact previous state, tells the user, and logs to `ingetrazo-errors.log`.
- Fuzz-tested: 1000 seeded operation sequences with structural invariants
  (watertightness, orientation, undo fidelity) — 996 clean, 4 known-hard
  frozen as expected failures.

### Tools
- Draw: Line, Rectangle, Rotated Rectangle, Circle, Polygon, Arc (2-point,
  3-point, centre+angle), Offset, Follow Me (profile swept along a path,
  mitred corners, closed paths weld into lathes).
- Transform: Move, Rotate (protractor), Scale (anchor + factor, negative
  mirrors) — live previews, exact snapshots undo, autofold.
- Select: click (curves/surfaces as wholes), double-click (face + edges),
  triple-click (whole connected solid), window/crossing box, Select All.
- Annotate: Tape Measure with construction guides, Protractor (angled
  guides), Dimensions with styles, terrain profile for geo paths.
- Eraser (click + stroke), Paint with materials, escalating Esc.

### Materials, layers, groups
- Categorised texture library (22 procedural, seamlessly tileable,
  licence-clean textures across 9 civil categories) painted at real-world
  tile size; edit width/height/rotation of any texture, undoably.
- Layers/tags with visibility and locking — top view + parallel projection
  + layers = the plan drawing, no separate 2D module.
- Groups: isolated geometry, edit-inside context (double-click in),
  cross-context undo correctness, face-me billboards.

### BIM (the thesis)
- Tag any faces or group as an IFC object (15 curated classes) — metadata
  over freeform geometry, never rigid primitives.
- Live quantities per object: area always, volume only when watertight.
- Takeoff CSV export — the bridge to IngePresupuestos today.
- **IFC4 export**, hand-written STEP (zero dependencies): spatial skeleton,
  real IFC classes, faceted BRep geometry, BaseQuantities in the file.

### Georeferencing (Track G)
- Local datum + UTM conversion; satellite base maps (Esri/Sentinel-2/custom
  XYZ) with area-limited capture; 3D draped terrain from free global DEM;
  geo paths with longitudinal profiles (stations, slopes, CSV/PNG export);
  KML/GeoJSON import.

### Interchange
- Native `.igz` documents (JSON, versioned).
- Import: COLLADA `.dae` (SketchUp exports, components, Y-up/inches
  conversion), OBJ (+MTL colours), KML/GeoJSON.
- Export: IFC4, STL (3D printing), OBJ (+MTL, textures with UVs).

### Experience
- Bilingual UI (English source, full Spanish), SketchUp-style movable
  icon toolbars, QGIS-style panels (Properties | BIM | Georef tabs),
  sky/ground horizon, paper-white maquette shading with face culling,
  infinite dashed axes.
- Scale figure: the author himself (1.65 m) as a face-me billboard cutout,
  plus generic 2D/3D people, tree, bush, car components — and "insert your
  own transparent PNG at real height".
- Desktop launcher + icon installer (`scripts/install_desktop.sh`);
  the icon is the author's mark: his tri-blade wrapped around the cube.

[0.1.0]: https://github.com/tuxiasumari/ingetrazo/releases/tag/v0.1.0
