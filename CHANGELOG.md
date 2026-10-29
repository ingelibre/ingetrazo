# Changelog

All notable changes to IngeTrazo are documented here.
Format inspired by [Keep a Changelog](https://keepachangelog.com); versions
follow [SemVer](https://semver.org).

## [Sin publicar]

### Arreglado

- **La oclusión ambiental ya no pinta bandas verticales** en caras planas
  vistas de forma oblicua (#989): el pase a media resolución leía la
  profundidad en las esquinas de los texeles y la normal reconstruida
  oscilaba, así que la propia cara se auto-ocluía en franjas. Ahora la
  lectura cae en el centro de un texel y la cara queda uniforme. Se notaba
  sobre todo en Windows, con el bloque escalonado de la captura.

## [0.5.11] — 2026-10-27

**Capas 2.0, la oclusión ambiental deja de ser experimental, sombras
nítidas al exportar y en la vista quieta, cuatro idiomas nuevos, el gestor
de extensiones que vuelve a conectar en Windows y más de treinta aportes
de la comunidad.**

**Si viene de la 0.5.10, esta versión trae también lo de la 0.5.10.1:** el
arreglo de la textura que se perdía al guardar dos veces (#877), las
sombras del sol sin escalones y los diálogos de archivos que ya no se
traban con una carpeta de red en Windows (#948). El detalle está en la
sección 0.5.10.1, más abajo.

### Añadido

- **Capas 2.0** (#652, @canalsecuario-blip en #728): las capas tienen
  pestaña propia junto al Navegador, con ojo, candado, aislar, capa activa,
  color, tipo y grosor de línea, transparencia e impresión por capa,
  carpetas, filtros y menú contextual completo. Una **barra Capas** cambia
  la capa activa o mueve la selección a otra. Lo nuevo (grupos, cotas,
  textos, guías) va a la capa activa; sin capa activa, las guías, cotas y
  textos van a sus capas automáticas «Guías», «Dimensiones» y «Textos».
  «Color por capa» en el estilo. En las láminas, cada capa con su tipo y
  grosor de línea, «No imprimir» y leyenda; el DXF lleva una capa DXF por
  capa del modelo, con su color y tipo de línea. Los .igz guardados abren
  igual en la 0.5.10.
- **La oclusión ambiental deja de ser experimental** (#954): la casilla de
  Estilos se llama ahora «Oclusión ambiental» y sigue apagada en todos los
  estilos. Se afinaron los defectos de la ronda Windows: el halo oscuro
  y dentado junto al borde de pilares y tablas (el cielo junto a un objeto
  ya no se oscurece nunca) y el moteado en «nubes» de las caras grandes y
  lisas. Además, un error gráfico pasajero al abrir un archivo grande ya no
  la apaga para toda la sesión. Apagada, la imagen es idéntica a la de
  antes; encendida cuesta lo mismo que en la 0.5.10.1.
- **Sombras nítidas en las imágenes exportadas y en las láminas**: la vista
  reparte el mapa de sombras sobre todo el modelo, así que en una plaza de
  100 m cada punto cubre 5 cm y la sombra sale suave. Al exportar imagen
  (PNG/JPG) o al dibujar una lámina, el mapa se calcula solo para esa imagen
  cuatro veces más fino (1,2 cm en la plaza): la sombra de las tablas de una
  pérgola sale rayada como es.
- **Sombras nítidas también en pantalla con la vista quieta** (#958): en un
  modelo grande la sombra se veía pixelada de cerca. Cuando la cámara se
  queda quieta un quinto de segundo, el mapa de sombras se rehace solo para
  lo que se ve (en la plaza, unos 33 m en lugar de todo el modelo): las
  tablas de una banca proyectan su sombra una por una. Al orbitar, mover o
  editar vuelve al mapa de siempre, así que la órbita no se hace más lenta;
  al quedarse quieta hay un solo cuadro de unos 40 ms en el modelo SPR.
- **Cuatro idiomas nuevos:** japonés (@nonasige-ui, #597), coreano
  (@ultracat, #785), vietnamita (@vandang890615, #936) y tailandés
  (@PRIDA-TAKON, #824). IngeTrazo arranca en ese idioma la primera vez si
  el sistema lo usa; se cambia en Preferencias ▸ Idioma. La traducción al
  lao (@bounkirdni-2025, #850) ya viene en el programa, pero todavía no se
  ofrece: en Windows las vocales y los tonos salían separados de su
  consonante, y vuelve en la próxima versión cuando eso esté resuelto.
- **Línea bloqueada que encuentra aristas y caras** (#245, @pacaeiro en
  #876): con una dirección bloqueada (flechas, Mayús o la referencia), el cursor sobre
  una arista ofrece el punto donde la línea bloqueada corta la recta de esa
  arista («Intersección con arista», con su prolongación punteada), y sobre
  una cara, donde atraviesa su plano («Intersección con cara»). Sirve en
  Línea, Medir, Escalar y Rectángulo girado.
- **Medir empieza desde la línea bajo el cursor** (#846, @hamzah1985): si al
  tomar la herramienta el cursor está sobre una arista, una guía o un eje,
  la guía paralela sale de inmediato; basta un clic o escribir la distancia.
  El punto medio de una arista vuelve a servir como origen de una guía.
- **Equidistancia muestra su referencia** (#843 y #844, @hamzah1985): la
  arista desde la que se mide se resalta en azul, un cuadrito rojo marca el
  punto de partida y una guía discontinua lo une a la vista previa. El
  cursor es ahora una flecha con el icono al lado, y el clic cae en la
  punta.
- **Puente** (#614, @canalsecuario-blip en #683): con dos caras, una cara
  y una línea, o dos líneas seleccionadas, construye las caras laterales
  entre ellas. Está en la barra Modificar y en el menú Herramientas.
- **Escala… para grupos y componentes** (@pacaeiro, #771): clic derecho
  sobre un grupo o componente ▸ Escala… abre un cuadro con X, Y y Z, sobre
  los ejes propios del objeto, con «Restablecer escala» y deshacer.
- **Cambiar los lados de un círculo o polígono, o los segmentos de un arco,
  ya dibujado** (@canalsecuario-blip, #813): en Propiedades ▸ Info de
  entidad, el campo «Lados:» o «Segmentos:» rehace la figura en su sitio.
- **Cotas sin unidad** (#374, #637, @canalsecuario-blip en #741): la casilla
  «Mostrar unidad» del Estilo de cota deja solo el número (1.30 en lugar de
  1.30 m), para láminas que indican la unidad una sola vez. Por defecto la
  unidad sigue visible.
- **Materiales: renombrar y cambiar el color del material activo**
  (@canalsecuario-blip, #806); un color RAL editado pasa a ser un material
  nuevo y el original queda intacto.
- **Un «+» tras las pestañas de la barra lateral** para añadir o quitar
  paneles (@canalsecuario-blip, #797), la misma lista de Ventana ▸ Paneles.
- **Campos de lámina en inglés y alemán** (@pkoska, #899): `{project}`,
  `{projekt}`… además de los nombres en español de siempre.
- **Elegir el cursor de las herramientas** (@Booshdag-io en #858): en
  Preferencias, «Cursor de herramienta» ofrece el icono de la herramienta
  (como siempre, por defecto), la cruz clásica o la flecha.
- **Agua de piscina**, un segundo material de agua en la biblioteca (#941,
  @hamzah1985).

### Arreglado

- **Windows: el gestor de extensiones y la biblioteca vuelven a descargar**
  (#783, @pkoska en #903): en una instalación nueva de Windows faltaba el
  certificado raíz y la descarga fallaba con un error de certificado; ahora
  se verifica con el propio Windows, que lo obtiene como lo hace el
  navegador. La verificación sigue siempre encendida.
- **Windows: actualizar ya no deja archivos de versiones viejas**: el
  instalador copiaba la versión nueva encima de la anterior sin quitar lo
  que ya no venía, y en una instalación actualizada desde la 0.5.8 quedaban
  83 archivos viejos, entre ellos las bibliotecas OpenSSL que la 0.5.9 dejó
  de usar (#564), causa probable también de #783. Ahora la carpeta del
  programa se renueva entera; los ajustes, extensiones y autoguardados no se
  tocan, porque viven en la carpeta del usuario.
- **Un rectángulo largo y delgado ya no se convierte en una línea** (#389,
  @pkoska en #909): la segunda esquina caía sobre la fila de la primera
  (la perpendicular al muro, «desde el punto») y el rectángulo no se
  dibujaba. Igual para el Rectángulo girado y las imágenes.
- **Abrir un archivo desde fuera pregunta por los cambios sin guardar**
  (#956, @tony1233200 en #977): el doble clic en un `.igz` con un dibujo
  modificado abierto lo reemplazaba sin preguntar.
- **Los grupos sin nombre se numeran igual cada vez que se abre el
  archivo** (#943, @tony1233200 en #971): antes dependía de lo abierto
  antes en la misma sesión.
- **Las unidades elegidas ya no vuelven al valor anterior al reiniciar**
  (@hamzah1985, #883).
- **Un .skp importado queda encuadrado** (@hamzah1985, #867): la vista se
  quedaba donde estaba y el modelo parecía no haber cargado.
- **.skp: componentes escalados por la matriz ya no llegan 100 veces más
  grandes** (#865, @tony1233200 en #970).
- **Las circunferencias siguen enteras** tras copiar, explotar, las
  herramientas de sólidos y Sígueme (@canalsecuario-blip, #812): un clic en
  el borde de un cilindro vuelve a seleccionar todo el círculo.
- **Al editar un grupo, las figuras que miran a la cámara y las imágenes de
  referencia también se atenúan** (@canalsecuario-blip, #805).
- **Mover: los asideros de giro no desaparecen** mientras el cursor está
  dentro de la caja del grupo (#871, @tony1233200 en #978), útil en tubos y
  perfiles largos.
- **Rendimiento del visor** (@tony1233200): las cotas cuestan mucho menos
  por cuadro (#439, en #976), la vista quieta se guarda una vez y no en cada
  cuadro de la órbita (#944, en #973), y una caja sin límites conocidos ya no
  se descarta por error (#952, en #972).
- **Una ventana dibujada contra la esquina de una caja corta solo su muro**
  (#895, @konevenkatesh).
- **Una línea suelta que va en parte sobre otra arista conserva el resto de
  su largo** (#896, @konevenkatesh).
- **Sígueme: un barrido que falla ya no deshace el paso anterior** (#897,
  @konevenkatesh).
- **Dividir una arista llega a todas las caras que la usan** (#898,
  @konevenkatesh): en modelos reales quedaban tramos sin partir (220 en
  nuestra batería de 48 modelos).
- **Una importación por script que falla devuelve lo que había borrado**
  (#893, @clinta).
- **DXF: las mallas POLYFACE, las polilíneas de malla y las entidades MESH
  se importan como caras** (#878, @nicolasmarc en #879).
- **DAE: la importación conserva los grupos del archivo**, anidados como en
  el archivo (#919, @BastelBaus).
- **OpenGL anterior a 3.3: un aviso claro** en lugar de una vista en blanco
  (#751, @pkoska en #910).
- **Windows: las miniaturas de los .skp se conservan** al hacer de
  IngeTrazo el programa predeterminado (#804, @pkoska en #905).
- **.skp que no abre: el registro dice por qué** (#497, @pkoska en #907).
- **Agrupar o borrar un grupo ya no deja geometría fantasma** (#987,
  @canalsecuario-blip en #988): los vértices y aristas sin uso que quedaban
  partían la cara que se dibujaba encima y ofrecían esquinas invisibles a la
  inferencia. Y una arista oculta, o en una capa oculta, ya no atrae al
  cursor.
- **El borde de una imagen bloqueada ya no cruza la vista**: un ortomosaico
  bloqueado dibujaba su rectángulo a trazos sobre el cielo, porque la foto
  no llena sus esquinas transparentes. Ahora el borde aparece solo cuando la
  imagen está seleccionada; las imágenes sin bloquear lo siguen mostrando,
  para encontrarlas en el suelo.

## [0.5.10.1] — 2026-10-27

**Arreglo de una pérdida de datos y, como función experimental, la oclusión
ambiental.**

**Si viene de la 0.5.9, esta versión trae también todo lo de la 0.5.10:**
- **Motor Rust encendido por defecto** (también en el Flatpak), con el de
  Python de reserva en Preferencias: si el módulo no carga, IngeTrazo vuelve
  solo a Python.
- **Modelos enormes sin tirones** (planta de 14 M de caras): el cursor de
  Línea y Rectángulo pasa de segundos a ~40 ms por movimiento; un clic de
  selección, de 1,2 a 0,2 s; mover, deshacer, borrar, pegar y entrar o salir
  de un grupo tocan solo lo que cambió; en Windows también.
- **Nuevo:** Cámara ▸ Ejes (Alt+A), Cámara ▸ Campo de visión (10°–120°),
  enganche «Intersección» donde se cruzan dos caras, y mover, copiar y rotar
  guías.
- **Unos sesenta arreglos:** Empujar/Tirar, inferencias, cotas que ya no se
  duplican al reabrir (y las duplicadas se reparan), deshacer y rehacer,
  importar y exportar (materiales, curvas, coordenadas topográficas),
  extensiones, y protección contra archivos comprimidos maliciosos.
- **Rendimiento:** las guías ya no ralentizan cada cuadro, y en Linux la
  memoria ya no crece al reabrir documentos grandes.

El detalle completo está en la sección 0.5.10, más abajo.

### Añadido

- **Oclusión ambiental (experimental)** en el panel Estilos (#954):
  oscurece suavemente donde se juntan las superficies (rincones, el pie de
  un muro, bajo una banca), con **Distancia** e **Intensidad** ajustables.
  Viene apagada en todos los estilos y se guarda con el estilo, en el
  archivo y en las escenas; un archivo guardado con ella abre en la 0.5.10,
  que la ignora. Cuesta ~1 ms por cuadro incluso en una planta de 14
  millones de caras. **Probada a fondo en Linux** (gráfica integrada AMD
  Radeon 780M, Wayland). En Windows y Mac aún no la hemos visto funcionar:
  si en su tarjeta gráfica se ve mal, apáguela y avísenos. Si el
  controlador no puede dibujarla, la casilla se desactiva sola y dice por
  qué.

### Arreglado

- **Un grupo o componente pintado entero con una textura ya no la pierde al
  guardar dos veces** (#877, análisis de @alanmirandaj): el primer guardado
  de la sesión borraba sin querer la ruta de la imagen en el modelo abierto,
  y el siguiente (un autoguardado basta) escribía el archivo sin ella. Al
  reabrirlo, el grupo salía sin textura. Venía desde la 0.5.0.
- **Windows: los diálogos de Abrir, Guardar, Importar y Exportar vuelven a
  abrirse** cuando la última carpeta usada estaba en una unidad de red que
  ya no responde (#948): ahora empiezan en la carpeta del documento o en
  Documentos.
- **Las sombras del sol ya no se ven pixeladas** en el borde: cada muestra
  se suaviza entre los puntos del mapa de sombras, y la orilla queda lisa en
  vez de en escalones (de 4 cm en una plaza, de 30 cm en una planta de
  280 m). **Probado en Linux** (Radeon 780M); en Windows y Mac aún no lo
  hemos visto: si las sombras se ven mal o la vista va más lenta con ellas
  encendidas, avísenos. El detalle fino de cerca en modelos grandes llega en
  la 0.6 (#958).

## [0.5.10] — 2026-10-26

**Motor Rust encendido por defecto y modelos enormes sin tirones.** El motor
nativo de la 0.5.9 deja de ser experimental: viene activado (el motor de
Python sigue de reserva y se elige en Preferencias), también en el Flatpak.
Sobre la planta de 14 millones de caras de #158, pasar el cursor con Línea o
Rectángulo baja de varios segundos por movimiento a unos 40 ms, y un clic de
selección de 1,2 s a 0,2 s. Mover, deshacer, borrar, pegar y entrar o salir
de un grupo tocan solo lo que cambió, no el modelo entero. Llegan el
enganche donde se cruzan dos caras, Cámara ▸ Ejes y Cámara ▸ Campo de
visión, y unos sesenta arreglos.

### Añadido
- **Cámara ▸ Ejes (Alt+A)** (#398, #557, Gabriel Rodríguez,
  @canalsecuario-blip): muestra u oculta los ejes rojo, verde y azul del
  mundo. Solo se deja de dibujarlos: las inferencias sobre ellos y los
  bloqueos con flechas siguen, y un grupo abierto muestra sus propios ejes.
  Se guarda en el documento.
- **Cámara ▸ Campo de visión…** (#826): el ángulo de la lente de la vista
  3D, de 10° a 120° (antes fijo en 45°). Se guarda con la cámara y con las
  escenas; en vista paralela no aplica y la barra de estado lo dice.
- **Enganche «Intersección» donde se cruzan dos caras** sin arista entre
  ellas (#819, @xcd-droid): se puede empezar o terminar una línea justo en
  esa recta. Las aristas reales y los puntos con nombre siguen ganando.
- **Mover, copiar y Rotar guías** como el resto del modelo; Seleccionar
  todo las incluye (#627, @canalsecuario-blip).
- **Ctrl+Intro acepta el diálogo de texto con directriz** (Alexis).

### Cambiado
- **Motor Rust activado por defecto** con Python de reserva: quien no lo
  eligió nunca recibe Rust; quien lo apagó lo sigue teniendo apagado; si el
  módulo no carga, o un arranque no llega a dibujar, IngeTrazo vuelve al
  motor de Python. Los textos dejan de decir «experimental» en los diez
  idiomas.
- **El Flatpak lleva el motor Rust** (#767).
- **Windows: el motor Rust acelera también ahí el cursor sobre modelos
  enormes.** Los rayos de oclusión y los cálculos de caras en Rust solo se
  usan si reproducen bit a bit la longitud de vector de Qt, y solo conocían
  la fórmula de Linux (libstdc++); el Qt de Windows está compilado con MSVC,
  que redondea distinto, y todo iba por el camino lento (los saltos de
  hasta 1,2 s con Línea sobre el SPR en la ronda de Windows). Ahora también
  conocen la de MSVC, comprobada contra su código fuente en 3,3 millones de
  vectores; `--check` dice cuál se usa.
- **Modelos enormes (#158)**, con el motor Rust:
  - pasar el cursor con las herramientas de dibujo sobre la planta de 14 M
    caras: de segundos por movimiento a ~40 ms. Las copias ligeras ya no se
    convierten en malla para responder al cursor: esquinas, aristas, caras
    y oclusión se calculan en Rust sobre las copias tal como están; lo que
    tapa el modelo se descarta con la profundidad del cuadro; mientras solo
    se mueve el cursor, se redibuja el cursor sobre la imagen guardada del
    modelo (GPU 40 → 3 ms por cuadro). El resultado es el mismo punto por
    punto que antes, comprobado con A/B de inferencias en cuatro modelos;
  - un clic de selección: 1,2 s → 0,2 s;
  - mover, soltar y deshacer: actualizan solo las copias que se movieron
    (antes ~3 s cada uno);
  - borrar, pegar, entrar y salir de un grupo: se conserva todo lo que no
    cambió (entrar a un grupo en la planta: 821 → 331 ms de sincronización);
  - orbitar: no se dibujan las copias de menos de un píxel (70 % de las
    caras vistas de lejos) y se reutilizan los lotes mientras la vista no
    sale de ellos.
- **Las guías ya no ralentizan cada cuadro** (#816): 40 guías en la plaza
  subían el cuadro de 18 a 112 ms; ahora 29 ms.
- **La toma de medidas BIM no vuelve a medir al seleccionar**; una edición
  mide solo lo que tocó (#857, modelo de @buildsmart888).
- **Linux: la memoria ya no crece al reabrir** documentos grandes (límite de
  dos zonas de malloc; la plaza reabierta 15 veces se queda en ~795 MB).
- **Zoom: acercarse hasta 5 mm** de una pieza pequeña, en vez de 2 cm (#653,
  #692, @canalsecuario-blip).
- **Paint explica** por qué no cambia un componente con todas sus caras ya
  pintadas (#807).
- **El asistente de IA responde en el idioma del usuario** (#790).

### Corregido
- **Selección**: sin marcado de la cara bajo el cursor con la herramienta
  Seleccionar (#832, @GitHuhl); Paint no marca caras sobre un grupo o
  componente cerrado (@canalsecuario-blip); el botón derecho sobre
  geometría suelta seleccionada pegada a un grupo la conserva (#744).
- **Inferencias**: una arista bajo el cursor gana al bloqueo perpendicular
  desde una esquina (#544, @pkoska); Línea empieza de cero cuando un tramo
  corta una cara (#496, @pkoska); sin «En arista» justo pasado el extremo de
  una arista suelta (#587); un bloqueo de eje ignora la posición lateral del
  cursor (#769); un punto en una línea de bloqueo conserva su color (#711);
  ningún NaN llega a una herramienta o a la malla (#466, #754).
- **Empujar/Tirar**: una línea entre dos pinturas sobrevive a un aterrizaje
  a ras (#649, Francis Rebouças); una esquina empujada a través de un
  tablero delgado lo corta (#710, Francis Rebouças); una lámina que la
  reconstrucción devuelve igual sigue siendo del usuario (#552); las
  propias paredes de la cara empujada no son un nivel al que llegar (#839,
  mediciones de @hamzah1985).
- **Geometría**: un lazo que rodea o cruza un hueco no queda dentro de la
  cara (#519); un pliegue que muere dentro de un plano no delimita nada
  (#570); Intersecar con el modelo corta la selección también contra sí
  misma (#541); un rectángulo contra el borde de un vano agranda el vano
  (#489); un bloque levantado de una lámina junto a otra queda hacia fuera
  (#550); borrar la línea bajo una ventana conserva el frente del muro
  (#356); dibujar sobre un plano DWG explotado sin congelarse ni perder la
  línea (#491); un círculo plano inclinado lejos del origen vuelve a ser
  plano (#571, @canalsecuario-blip).
- **Cotas**: ya no se duplican en cada reapertura (#765, @tony1233200) y al
  abrir se reparan las ya duplicadas; se quedan en su sitio al entrar a un
  componente, siguen al objeto en que se dibujaron y acompañan la vista
  previa de Mover/Rotar (#621, Francis Rebouças); Mayús y flechas bloquean
  también el paso de colocación (#770, #810, @pacaeiro); una cota sobre una
  arista colapsada vuelve con ella al deshacer (#254); una cota anclada del
  compositor sigue a su vértice (#854).
- **Deshacer/Rehacer**: rehacer Crear grupo devuelve el mismo grupo, así no
  se pierde el rehacer de Explotar (#737, @canalsecuario-blip); deshacer
  Cambiar ejes devuelve las copias exactas, y un componente que conservaba
  los ejes de grupo toma el nuevo marco (#484).
- **Herramientas**: la Cinta deja el tramo discontinuo del punto guía
  (#693, Francis Rebouças); el Rectángulo en reposo muestra su vista previa
  desde la esquina del lápiz (#848, @hamzah1985); los tiradores delanteros
  de Escalar se dibujan y eligen antes que los traseros (#833); el cuadro
  de medidas muestra el valor al reescribir en caliente (#859); Ampliar
  selección cuenta una guía por su punto, no por su segmento de 10 km
  (#627).
- **Áreas y capas**: Info. de entidad y la toma de acabados restan los
  huecos de la cara; Piezas y la etiqueta de Texto leen el área neta (#742,
  @tony1233200); el contenido sin capa de un grupo abierto sigue la capa
  del grupo (#366).
- **Dibujo en pantalla**: una copia rotada de un componente se ilumina como
  está colocada (#482); una guía lejana conserva sus trazos (#481);
  alejarse tras un zoom profundo devuelve la precisión de profundidad
  (#579); una imagen de referencia delante de una cara recibe el clic
  (#426); una imagen de .skp pegada a una cara se queda en ella (#429);
  rotar un grupo conserva la textura de las caras sin mapa UV (#847,
  @tony1233200); Render ▸ «Cambiar fecha y hora…» vuelve a abrir el panel
  de Sombras (Victor Crespo).
- **Nuevo y Abrir** vacían los materiales y la lectura UTM del documento
  anterior (#759, @tony1233200).
- **Importar y exportar**: cada material conserva su nombre y la pintura de
  un grupo llega a GLB, DAE y OBJ (#794); las superficies curvas salen
  suaves (#131); los archivos en coordenadas topográficas llegan cerca del
  origen y sin deformarse en OBJ, STL, glTF y DAE (#798) (los tres de
  @canalsecuario-blip); las líneas sueltas de un COLLADA entran como
  aristas (#633); importar un .skp grande mantiene viva la ventana (#787).
- **Extensiones**: se listan las gestionadas que salieron del catálogo y se
  apartan al reemplazarlas (#611, @pkoska); se reconocen las copias
  instaladas a mano con finales de línea CRLF (#764, @tony1233200); una
  extensión del botón derecho que falla o tarda se omite en la sesión
  (#588); las barras de las extensiones vuelven a su sitio tras el
  arranque asíncrono (#845, @hamzah1985).
- **Seguridad**: un archivo comprimido de fuera (.igz, KMZ, portapapeles,
  biblioteca) no puede desempaquetarse hasta llenar la memoria («bomba
  zip»), y un documento real de más de 4 GB sigue abriendo (Victor Crespo).
- **Plataformas**: Windows: el registro de errores descarta al arrancar los
  errores COM manejados de la sesión anterior (#763), y reacomodar las barras no deja pequeña una ventana
  maximizada (#800); algunos controladores gráficos de Windows con
  respuestas falsas ya no hacen saltar el repintado grabado; AppImage: las
  carpetas y enlaces se abren con el entorno del sistema (#456); motor
  Rust: los colores con transparencia (RGBA) ya no impiden dibujar el
  modelo.

### Créditos
- Código: Gabriel Rodríguez (@canalsecuario-blip), Pedro Caeiro
  (@pacaeiro), Francis Rebouças, @pkoska, @tony1233200, @hamzah1985,
  Victor Crespo y Alexis. Reportes y modelos: @xcd-droid, @GitHuhl,
  @buildsmart888 y todos los que abrieron issues.
- Difusión: gracias a los canales de YouTube que mostraron IngeTrazo —
  Blender 3D Architect, IngeTrazo Tutorials, JRobredo3D, Rafael 3D, Allan
  Brito, Savoirpourtous, BuildSmart Learning y todos los que le dedicaron un
  vídeo.

### Para desarrolladores
- **Una prueba falla si `INGETRAZO_RUST=1` corre sin el módulo o con uno
  desactualizado** (huella de las fuentes Rust).
- `scripts/profile_window_open.py`: abrir un documento en la ventana fase
  por fase (segundos, memoria residente y pico), en Linux y Windows (#760).
- Las pruebas que muestran una ventana para GL la cierran antes de
  saltarse.

## [0.5.9] — 2026-10-19

**Motor Rust experimental, modelos enormes mucho más fluidos y una semana
de pedidos atendidos.** Un motor nativo nuevo, apagado por defecto, hace en
segundos lo que tardaba minutos (líneas ocultas, Intersecar, Orientar) y
abre la planta de 14 millones de caras en 16 s en vez de 110. Con los dos
motores, orbitar, mover y deshacer en modelos grandes va dos o tres veces
más rápido. Llegan «En el eje» en el primer punto, órbita y desplazamiento
sin soltar la rueda, Unir segmentos, Explotar curva, una figura de escala a
elegir, el ruso, y unos cincuenta arreglos; en Windows, el gestor de
extensiones ya no se cae con un OpenSSL ajeno (#564).

### Añadido
- **IngeTrazo con tu color: acento de los iconos y las barras** (#393,
  pedido de Peter Mican). El naranja no le queda a todos los escritorios,
  así que ahora eliges el color que acompaña a todo el programa: los
  puntos y tiradores de cada icono (los clics que definen una forma, el
  pivote de Rotar, el punto donde empieza un arrastre), el fondo de los
  botones bajo el ratón y las marcas que aparecen al acoplar barras y
  paneles. En Ventana ▸ Preferencias ▸ General ▸ «Color de acento»:
  - **naranja IngeTrazo** (el de siempre, por defecto), **azul**,
    **verde**, **rojo**, **morado** o **amarillo**;
  - **«Igual que el sistema»**: toma el color de acento que elegiste en tu
    escritorio (si el sistema lo comparte con las aplicaciones), así
    IngeTrazo se ve como una aplicación más de tu equipo.

  Funciona con el tema claro y el oscuro, se aplica al instante sin
  reiniciar —todos los iconos de IngeTrazo se vuelven a pintar en ese
  momento— y se recuerda para la próxima vez. La
  selección en el visor 3D sigue en naranja, para que lo elegido se
  distinga siempre del modelo. En los nueve idiomas.
- **«En el eje» al empezar Línea, Rectángulo, Círculo y Arco** (#546, #718,
  @pacaeiro): en espacio vacío, el primer punto se engancha a los ejes rojo,
  verde y azul, como ya hacía la Cinta. Solo cuando no hay nada mejor bajo
  el cursor: nunca sobre una cara, ni con el eje tapado por el modelo o
  visto de punta.
- **Cambiar entre órbita y desplazamiento sin soltar la rueda** (#231, #720,
  @pacaeiro): durante el arrastre con el botón central, pulsar o soltar
  Mayús pasa de orbitar a desplazar y al revés.
- **Unir segmentos**, lo contrario de Dividir (Gabriel Rodríguez,
  @canalsecuario-blip): los tramos en línea recta de una línea dibujada en
  varios clics, dividida o que quedó con el punto de un cruce borrado
  vuelven a ser una sola línea. Botón derecho sobre dos o más aristas, o
  Edición ▸ Unir segmentos (sin selección, limpia todo lo que se edita).
  Antes de hacerlo marca en color cada punto: verde se quita; rojo, esquina
  real de menos de 1°; naranja, llega otra arista; morado, distinto
  suavizado, oculto o capa; azul, parte de una curva.
- **Explotar curva**: botón derecho sobre un círculo o un arco lo deja en
  segmentos sueltos que se eligen uno a uno; la geometría no se mueve y
  Deshacer lo vuelve a juntar.
- **Figura de escala a elegir** (#655): en Preferencias ▸ General, una de
  las personas incluidas (con su altura real) o «Mi propia imagen…», un PNG
  recortado con su altura y su nombre. La figura del Elon sale de la
  biblioteca de personas (#680); los modelos que ya la usan la conservan.
- **«Ns» justo después de un círculo o un polígono lo rehace en el sitio**
  con ese número de lados (#305), como ya hacía el arco.
- **Barras de herramientas flotantes con aspecto de ventana**: una franja
  con su nombre y un botón para cerrar, que también sirve para arrastrarla
  y volver a acoplarla. **Ventana ▸ Restaurar barras de herramientas**
  (también con el botón derecho sobre una barra) las devuelve a su sitio de
  fábrica. Las pistas de los botones muestran el nombre en negrita, la
  tecla y debajo qué hace (Gabriel Rodríguez).
- **Ayuda ▸ Acerca de ▸ «Copiar al portapapeles»** con la versión, el
  sistema, Qt, OpenGL, pantalla e idioma, en inglés y sin datos personales,
  listo para pegar en una issue (#476, Gabriel Rodríguez).
- **Navegador**: crear grupo, crear componente y explotar desde el botón
  derecho, también dentro de un grupo abierto (#561, #490); Hacer único y
  Seleccionar instancias en los componentes; material desde la propia fila
  (#565); renombrar varias filas a la vez con número, buscar y reemplazar,
  prefijo y sufijo (#565, #87); el ojo y el candado actúan sobre toda la
  selección; un botón para aislar y otro para desplegar (Gabriel
  Rodríguez).
- **Información de entidad suma** el área y la longitud de una selección
  múltiple de caras y aristas (#274).
- **Escenas: borrar varias a la vez**, en un solo paso de deshacer (#280).
- **BIM: barra de refuerzo** (`IfcReinforcingBar`) con longitud, diámetro
  nominal y peso en acero; el metrado la cuenta en kg (#495).
- **Asistente IA: «Local / compatible con OpenAI»** acepta servicios
  alojados cuya dirección ya trae la versión (vLLM, LiteLLM, OpenCode…)
  (#650).
- **Ventana ▸ Barra lateral izquierda (Ctrl+F6)**, junto a Barra lateral
  (Ctrl+F5): la tecla ya existía pero no estaba en ningún menú (#575,
  Gabriel Rodríguez).
- **Equidistancia muestra la distancia en vivo** en la casilla de medidas
  y deja reescribirla después (#604, #665, Luis Romo); si la nueva distancia
  no cabe, se conserva la equidistancia ya hecha.
- **Empujar/Tirar se engancha al origen** de los ejes a media operación
  (#407).

### Cambiado
- **Los menús de las extensiones se ordenan solos cuando hay muchas.** Con
  el catálogo entero instalado, el menú del botón derecho era más alto que
  la pantalla (Qt lo partía en dos columnas) y el menú Extensiones tenía
  62 líneas. Ahora las entradas sueltas de una misma extensión van en un
  submenú con su nombre; en el botón derecho, con más de 8 extensiones,
  todas van bajo «Extensiones ▸»; y en el menú Extensiones, con más de 15,
  cada una va en su categoría del catálogo (Arquitectura, Dibujo,
  Render…). Con pocas extensiones casi nada cambia. Preferencias ▸ General
  ▸ «Menús de las extensiones» permite agruparlas siempre o dejarlas como
  antes.
- **Elegir otra vez el mismo componente de la biblioteca pone una copia
  del mismo componente.** Cada vez se volvía a leer el archivo del modelo
  y se añadía una pieza nueva e independiente: cuatro veces el mismo
  mueble de 12 600 caras eran 50 400 caras en el modelo y la lectura de
  2 s se repetía cada vez. Ahora la primera vez se coloca un componente y
  las siguientes son copias que comparten su definición, como en
  SketchUp (editar una cambia todas; «Hacer único» separa una). Vale para
  la biblioteca en línea y para los componentes incluidos. Medido con 40
  inserciones de 10 modelos: cargar el modelo pasa de 440 a 30 ms
  (mediana; el peor, de 2,2 a 0,13 s) y colocarlo de 286 a 118 ms. La
  ventana de la biblioteca pinta además su primera pantalla de
  miniaturas al abrir, sin esperar un ciclo.
- **El gestor de extensiones abre con las imágenes ya puestas.** Cada
  apertura volvía a leer y reducir las capturas completas (algunas de más
  de 3000 px) y las tarjetas salían con «Vista previa no disponible» antes
  de su imagen. Ahora la miniatura ya reducida se guarda junto a las
  capturas (y se rehace si la captura cambia), se recuerda mientras
  IngeTrazo está abierto y las demás se preparan en segundo plano; no se
  descarga nada que antes no se descargara.
- **El plano de Rectángulo, Círculo y Arco en espacio vacío lo elige la
  cámara, por el origen de los ejes** (#719, @pacaeiro), como en SketchUp:
  el suelo al mirar hacia abajo y los planos verticales rojo o verde según
  hacia dónde mira la vista; antes iban al plano por el centro del modelo.
  En vistas casi a ras, donde antes el clic no daba punto, ahora sí lo da.
  La forma se ve del color de su plano mientras se traza. Línea, Cinta y
  Cota no cambian.
- **Motor Rust experimental** (apagado por defecto): en Ventana ▸
  Preferencias ▸ General, «Motor Rust (experimental)» calcula las partes
  más pesadas con un módulo nativo nuevo, y se aplica al volver a abrir el
  programa. En la Plaza de Yanque (115 883 caras): las líneas ocultas de
  una lámina vectorial pasan de 150 s a 5 s, Intersecar caras con todo
  seleccionado de 266 s a 9 s, y Orientar caras de 34 s a 9 s; empujar y
  tirar sobre un terreno grande va unas cuatro veces más rápido. El
  resultado es el mismo que con el motor de siempre, comprobado cara por
  cara. Si el módulo no carga, IngeTrazo sigue con el motor de siempre sin
  avisar de error; Ayuda ▸ Acerca de dice qué motor está en uso. Viene en
  Windows, macOS, AppImage y Snap; el Flatpak sigue con el motor de siempre
  en esta versión. Es una prueba: guarda copia de tus archivos y reporta lo
  raro con la etiqueta `rust-engine`.
  Con el motor encendido, además, los modelos grandes se abren como
  **mallas ligeras**: cada grupo se queda en arreglos compactos y solo se
  construye cuando lo editas o haces clic en una de sus caras; el dibujo,
  la selección, el panel de Materiales y el guardado leen esos arreglos.
  En una planta industrial de 14 millones de caras (#158) abrir en ventana
  pasa de 110 s a 16 s, la memoria de 7,5 GB a 4,8 GB y guardar de 15 s a
  9 s, con el archivo guardado idéntico byte a byte. Si una vez el programa
  no llega a abrirse con el motor encendido, el siguiente arranque vuelve
  solo al motor de siempre y lo avisa; `--python-engine` en la línea de
  órdenes hace lo mismo para un arranque. Con el motor encendido, el
  enganche y la selección en esos modelos consultan un índice espacial
  nativo para saber qué componentes mirar, y las consultas tardan la mitad
  con el mismo resultado.
- **Modelos grandes más fluidos** (#158), con los dos motores: orbitar,
  desplazar y hacer zoom en esa planta pasa de 86 ms a 34 ms por cuadro (de
  12 a 30 imágenes por segundo en una gráfica integrada); mover un objeto,
  de 1 s a 0,25 s por movimiento del ratón; deshacer, de 4,6 s a unos
  2,5 s; entrar a un grupo, de 5,2 s a 3,1 s. Las miniaturas del panel de
  Componentes se dibujan solo para las filas visibles y el panel de
  Materiales ya no relee las texturas del disco tras cada cambio. La
  imagen es la misma, comprobada píxel a píxel.
- **Instalar una extensión no revisada pregunta antes** (Victor Crespo):
  la tarjeta decía «no revisada», pero un clic ejecutaba el código de su
  autor con tus permisos. Instalar, actualizar o reemplazarla pide ahora
  confirmación nombrando al autor, con «No» por defecto; las revisadas y
  las que trae IngeTrazo se instalan como antes.
- **El gestor de extensiones vuelve a pedir una captura que no se pudo
  descargar**, hasta tres veces y alternando GitHub con la copia de
  ingetrazo.com, en vez de dejar «Vista previa no disponible».
- **Las flechas y Mayús fijan el plano de dibujo durante toda la forma**
  en Círculo, Polígono, Rectángulo y los arcos (#545, #543, @pacaeiro):
  antes solo respondían antes del primer clic. Derecha = YZ, Izquierda =
  XZ, Arriba = XY; la misma tecla suelta el plano.
- **Una longitud tecleada suelta el bloqueo de eje**, igual que el clic que
  termina el tramo (@pacaeiro).
- **Empujar/Tirar mide el arrastre desde el punto donde hiciste clic**, no
  desde el centro de la cara: en una losa grande clicada cerca de una
  esquina, subir 0,3 m se leía 1,8 m, y en un anillo 1 m de cursor daba
  0,44 m de muro.
- **Un contorno de menos de 1 cm² ya se cierra en cara**: un círculo de
  menos de 5,7 mm de radio quedaba en aristas sueltas, así que no se podían
  dibujar avellanados ni cabezas de tornillo a su tamaño.

### Corregido
- **La ventana no se dejaba encoger con muchas extensiones.** Sus barras
  de herramientas se sumaban a la misma fila de arriba (34 barras con el
  catálogo entero) y la ventana no podía ser más estrecha que 2205 px en
  una pantalla de 1477. Ahora una fila que no cabe en la pantalla sigue
  en otra fila; las que caben no se mueven.
- **La ventana no se maximizaba con paneles de extensiones muy altos.** Un
  panel de 652 px de alto mínimo hacía que la ventana necesitara 902 px en
  una pantalla con 890: GNOME no la maximizaba (o quedaba más grande que
  la pantalla). Ahora, solo cuando la ventana no cabe, los paneles
  laterales más altos ganan una barra de desplazamiento.
- **Ocultar la barra lateral dejaba un panel suelto.** Una extensión que
  crea su panel por su cuenta («Escenas» de igz_tb_scenes) se quedaba sola
  a la derecha al plegar la barra, y al moverla mostrar dejaba de responder
  como se esperaba. Plegar y desplegar (Ctrl+F5, Ctrl+F6 y las manijas)
  se llevan ahora cualquier panel acoplado en ese lado.
- **«Crear componente…» salía dos veces** en el menú del botón derecho con
  geometría suelta y grupos seleccionados a la vez.
- **Pasar el cursor con Línea sobre un modelo muy grande ya no da error**
  (#158): en modelos con más de un millón de caras en componentes, las
  aristas de los grupos cercanas al cursor se medían en una versión del
  índice de selección y se leían en otra, que ya había incorporado más
  componentes; el enganche podía tomar una arista ajena o fallar con
  «index … is out of bounds». Pasaba con los dos motores y ya estaba en la
  0.5.8. También afectaba a seleccionar un grupo por su arista.
- **Inferencias más ligeras sobre modelos densos** (#158): la inferencia
  «En arista» comprobaba si cada arista cercana estaba tapada, una por una,
  aunque solo se queda con la más cercana visible; ahora pregunta desde la
  más cercana y en tandas. Con el motor Rust encendido, además, esas
  comprobaciones de «¿está tapado?» se calculan en el módulo nativo (las
  pocas que quedan al límite de la precisión las sigue respondiendo el
  cálculo de siempre, así que el punto enganchado es el mismo). Pasar el
  cursor con Línea sobre una planta industrial de 4,7 millones de caras: el
  movimiento más lento pasa de 28,7 s a 5,2 s y el gesto entero de 204 s a
  103 s.
- **Ratón 3D (SpaceMouse) en Windows: sin saltos y con el zoom en su
  sentido** (vídeo de revisión de Rafael García; PR #581 de @deedend como
  pista): el controlador de 3Dconnexion convierte el movimiento de la tapa
  en giros de la rueda del ratón para los programas que no conoce, y esos
  pasos de zoom (unos ocho por segundo) se sumaban a la lectura directa del
  aparato. Ahora la rueda no hace nada mientras la tapa mueve la vista (por
  encima de la zona muerta, y 0,4 s después); con la tapa quieta, la rueda
  del ratón va como siempre. Además el eje adelante/atrás se leía con el
  signo cambiado en Windows, así que el zoom iba al revés. Y en Preferencias
  ▸ Ratón 3D hay una lectura en vivo: los seis números que manda el aparato
  y cómo los entiende IngeTrazo.
- **Una guía con coordenadas inválidas ya no impide guardar** (#723,
  @kcgemail): el guardado se negaba entero con «un punto con coordenadas
  inválidas … scene › guides[0] › point[0]» y el trabajo no se podía
  guardar. Una guía es solo una ayuda para dibujar, así que ahora se deja
  fuera del archivo, como ya pasaba con la cámara (#485); y la Cinta y el
  Transportador ya no dejan guías así.
- **Las caras con etiqueta propia de un .skp llegan a su capa** (#700,
  @Aaron1992): llegaban a una capa con el número interno de la etiqueta
  («84», «680»…) en vez de su nombre, así que ocultar «Banderas» o «Roof»
  no las ocultaba. Pasaba en casi todos los .skp con caras etiquetadas.
- **Las partes que se separan de un grupo etiquetado de un .skp conservan
  su etiqueta** (#703, @Aaron1992): imágenes, figuras que miran a la cámara
  y copias de componentes caían en Layer 0 y seguían a la vista al ocultar
  la etiqueta del grupo.
- **Ver todo encuadra también las imágenes de referencia visibles** (#702,
  @Aaron1992): un plano importado para calcar, lejos del origen, se quedaba
  fuera de la pantalla.
- **El Asistente IA ya no cierra IngeTrazo al arrancar en algunos Flatpak**
  (#706, @mvanhorn): pedir la fuente monoespaciada del sistema podía
  romperse dentro del sandbox; el chat usa ahora la fuente de la
  aplicación.
- **Puente IA: una lámina creada con `run_python` es un paso que se puede
  deshacer** (#715, @francisreboucas, parte de #694): antes el puente
  respondía «sin cambios» y el deshacer del agente quitaba la edición
  anterior del usuario.
- Alemán: la vista trasera es «Hinten» y el relleno sólido del corte
  «Gefüllt» (#705, @Aaron1992).
- **La goma ya no borra las aristas que quedan detrás de una cara** (#663,
  @SPMech): al pasar la goma por una cara para borrar una arista dibujada
  en ella, también marcaba la arista de la cara de atrás que caía bajo el
  cursor, y las dos se borraban. Ahora la goma solo toma las aristas que se
  ven, igual que Seleccionar desde #71; vale también para ocultar con Mayús
  y para el resaltado al pasar el ratón.
- **Abrir otro documento ya no arrastra los planos de sección del
  anterior** (#602, ArchXQ IT): un archivo sin planos se abría con los del
  documento que estaba abierto antes, y al guardarlo se quedaban grabados
  en él. Lo mismo pasaba con los interruptores de planos y cortes, Objetos
  y Geometría ocultos, las escalas propias, el color del dorso de las caras
  y las capas que el archivo no tenía. Ahora cada documento se abre solo
  con lo suyo. Y Archivo ▸ Nuevo borra también un documento que solo
  tenía planos de sección.
- **Borrar la diagonal de un rectángulo ya no le da la vuelta a la cara**
  (#529, @GWydouw): al unir dos caras de un mismo plano, el contorno salía
  en cualquiera de los dos sentidos, y casi la mitad de las veces la cara
  unida quedaba del revés. Ahora conserva el lado de la cara original y su
  pintura por delante y por detrás.
- **Intersecar caras ya no falla con caras casi paralelas**: dos planos
  separados por un ángulo minúsculo hacían una división por cero y la orden
  no hacía nada. Además, la búsqueda de qué caras pueden cruzarse va mucho
  más rápida en modelos grandes.
- **«x5» tras copiar hace la matriz, igual que «5x»** (#542): después de
  copiar con Mover o Rotar + Ctrl, teclear «x5» abría la herramienta Texto,
  porque la X sola es su atajo. Justo después de una copia, mientras «3x» o
  «/3» harían una matriz, la X va a la casilla de valores; en cualquier otro
  momento sigue abriendo Texto. Esc justo después de copiar cierra esa
  ventana (y la X vuelve a ser Texto) antes de quitar la selección.
- **El Asistente IA vuelve a funcionar con OpenAI** (#517, @jb-dev-github):
  los modelos nuevos de OpenAI rechazaban cada pedido con «HTTP 400:
  Unsupported parameter: 'max_tokens'». Con OpenAI se manda ahora
  `max_completion_tokens`, que aceptan todos sus modelos; Groq, Gemini,
  OpenRouter, DeepSeek y Ollama siguen con el nombre de siempre.
- **El STL exportado sale en milímetros** (#513, @toSvenson): un STL no
  guarda la unidad y los programas de impresión 3D lo leen en milímetros,
  pero IngeTrazo escribía los metros del modelo, así que una pieza de
  15 × 25 mm entraba al laminador 1000 veces más chica. Ahora Archivo ▸
  Exportar ▸ STL pregunta la unidad, con milímetros por defecto, y recuerda
  la elección, igual que la importación.
- **Un plano de sección ya no deja encajar en lo que oculta** (#384,
  @jonson7777): solo se quitaban del snap las aristas con los dos extremos
  en el lado cortado, así que la arista que cruza el corte —la vertical de
  un muro cortado a media altura— seguía ahí entera, y el cursor encajaba en
  su extremo y en su tramo ocultos. Ahora lo que el corte oculta cuenta como
  oculto para todo punto: extremos, puntos medios, «en arista», cruces, y
  también al pulsar aristas, vértices y grupos. Vale en todos los estilos,
  también en Rayos X y alambre; con los cortes apagados no cambia nada.
- **El gestor de extensiones ya no parpadea al cambiar de pestaña, instalar
  o descargar** (#555): cada cambio entre Explorar e Instaladas reconstruía
  todas las tarjetas, las viejas seguían pintadas un instante debajo de las
  nuevas y cada captura se volvía a leer y escalar. Ahora cambiar de pestaña
  solo muestra la otra página, una reconstrucción se pinta de una vez y las
  tarjetas nacen con su imagen. Al abrirlo, la ventana ya no se queda en
  blanco un tercio de segundo: se decodificaban todas las capturas, no solo
  las visibles, y el catálogo recién descargado, igual al guardado, volvía a
  reconstruir las dos páginas. En Windows, además, el gestor se abre
  transparente y aparece en cuanto está pintado, en vez de mostrarse en
  blanco durante la animación de apertura, y abre mucho antes: cada tarjeta
  llevaba una docena de hojas de estilo propias, que en Windows costaban
  24 ms por tarjeta (más de un segundo con el programa congelado); ahora
  comparten una sola, con el mismo aspecto píxel a píxel. La causa
  principal estaba en el botón «Repositorio» de cada tarjeta: se mostraba
  antes de entrar en la tarjeta, y en Windows eso lo convertía un instante en
  una ventana propia; eran 43 ventanitas que aparecían y desaparecían al
  abrir el gestor, unos 0,8 s de los 0,9 s que tardaba.
- **Windows: el gestor de extensiones ya no se cae con un OpenSSL de otro
  programa** (#564): en equipos con otra versión de OpenSSL en System32,
  abrir el gestor (o cualquier descarga de Qt) fallaba con «No se encuentra
  el punto de entrada CRYPTO_calloc». Qt usa ahora el TLS del propio
  Windows. Comprobado en Windows con ese OpenSSL instalado.
- **Windows: los archivos publicados ya no llevan la firma de prueba**
  (#566): la 0.5.8 se volvió a subir con una firma de prueba que Windows no
  reconoce y que Smart App Control podía bloquear.
- **Cambiar el color de acento ya no rompe la ventana** (#654): el
  siguiente Abrir fallaba con «already deleted» en los paneles Estilos y
  Sombras, o F3 cerraba el programa.
- **Una tecla asignada a una extensión sobrevive al reinicio** (#595,
  @tomlai-git): desde la 0.5.8 se perdía, porque las extensiones cargan
  después de abrir la ventana.
- **No se podía dibujar tras «Ver todo» en piezas muy pequeñas** (#583,
  @andku85): con la cámara a 2 cm de una pieza de 10 mm, el rayo del cursor
  salía inválido y cada clic fallaba con «cannot convert float NaN to
  integer».
- **Equidistancia conserva los huecos de la cara** (#537): un anillo sobre
  cuatro muros volvía como un cuadrado lleno; hacia dentro, una
  equidistancia que entraría en un hueco se rechaza con un mensaje.
- **Un rectángulo dibujado sobre una cara con hueco en un modelo 3D**
  rellena el hueco en vez de apilar una cara encima (#538); y dibujar en el
  plano de un agujero pasante ya no lo tapa.
- **El aro superior de un cilindro empujado vuelve a ser una curva**
  (#626): un clic tomaba un solo segmento de 24.
- **Intersecar ignora los cruces más cortos que la tolerancia de
  soldadura** (una esfera de Sígueme atravesando un cubo) y, si aun así se
  rechaza, lo dice en vez de anunciar las aristas añadidas.
- **La casilla de medidas muestra lo tecleado tras Intro** (#607): un
  rectángulo de «1 3/8";1 9/16"» se dibujaba bien, pero la casilla seguía
  enseñando la medida del ratón y parecía que se había ignorado.
- **Una coma tras un decimal pasa al valor siguiente** (#598, @pkoska):
  «0.9,2.1» se leía 0,921.
- **Cambiar de herramienta a media rotación con Mover ya no deja Rotar
  activo** en el siguiente M (#480, @pkoska).
- **El mapa para elegir ubicación ya no descarga teselas mientras se
  pinta** (#327, @pkoska), lo que cerraba el programa en Windows al pulsar
  «Ir a la ubicación».
- **Un componente clicado en «En el modelo» se queda resaltado** (#636).
- **Navegador**: los componentes anidados aparecen en «En el modelo»
  (#599); un grupo bloqueado ya no se puede seleccionar, mover ni abrir;
  Hacer único da un nombre propio («Silla #2», #620); al editar un grupo el
  resto se atenúa a gris; un archivo abierto al arrancar ya no se queda en
  5 % detrás de la pregunta de unidades (Gabriel Rodríguez).
- **Flatpak: el Navegador ya no cierra el programa al arrancar** en
  algunos equipos (#658): sus botones usaban caracteres que pocas fuentes
  tienen; ahora son iconos dibujados.
- **OBJ/MTL en UTF-8 en todas las plataformas** (APBureauEtude): en Windows
  «Mármol» salía con caracteres rotos y algunos archivos no se podían
  importar.
- **Texto 3D: el texto entero y sus letras coinciden en Windows y macOS**:
  la escala del bloque salía de otra forma de colocar los glifos. En Linux
  no cambia nada.
- **Mensajes del importador GLB traducidos** («Recolectando geometría…»,
  «Suavizando aristas…» salían en inglés).
- **Reabrir un `.igz` con identificadores de curva en texto** ya no falla
  (borborborja).
- **macOS: el paquete no lleva el `dwg2dxf` de Linux** y `--check` ya no
  dice que lo encontró (SebWell).
- **El instalador de Windows sigue el idioma de Windows también al
  actualizar** (#591): las instalaciones anteriores a la 0.5.3 dejaban el
  asistente en español.
- **El texto copiado desde Acerca de** ya no mezcla palabras del idioma del
  sistema y dice si es Flatpak o AppImage.
- **macOS: elegir Blender.app para renderizar funciona** desde cualquier
  carpeta (#328).

### Traducciones
- **Ruso** (#399, @RomanErshow): 2252 frases de su traducción y las 705
  nuevas con su terminología.
- Alemán al día (Alex Joedt, @Aaron1992); todos los idiomas llevan todas
  las frases nuevas.

### Créditos
- AUTHORS, Ayuda ▸ Acerca de y el README nombran a las 24 personas que han
  aportado desde el 05-10, con una estrella para quienes más dieron.

### Para desarrolladores
- **La suite pasa en Windows sin `PYTHONUTF8`** y ya no escribe en el
  `ingetrazo-errors.log` real del usuario (ronda Windows 0.5.9).
- `scripts/bench_engine.py`: dónde gasta el tiempo el motor del modelo,
  con perfiles.

## [0.5.8] — 2026-10-12

**Gestor de extensiones, unidades para todo el documento y un Navegador del
modelo.** Las extensiones del catálogo se instalan, actualizan y desactivan
desde el programa; el documento trabaja en metros, milímetros, imperial o a
medida; y un árbol muestra todos los grupos y componentes. Editar dentro de
grupos grandes y empujar en terreno es varias veces más rápido, y los modelos
enormes abren, guardan y pesan bastante menos (formato 3: un modelo grande
guardado con esta versión no abre en las anteriores). Además, más de cuarenta
arreglos de herramientas, inferencias y láminas, y los nueve idiomas
completos.

### Añadido
- **Gestor de extensiones** (Extensiones → Gestionar extensiones…, #452,
  @kagehak): explora el catálogo de ingetrazo.com con búsqueda, etiquetas
  y filtro de revisadas; instala, actualiza, desactiva y desinstala con un
  clic. Cada descarga se comprueba con el SHA-256 del catálogo antes de
  instalar nada; se ven la licencia, el repositorio y si esa versión exacta
  fue revisada por quien mantiene IngeTrazo («Comunidad» si no). Avisa
  cuando hace falta reiniciar y, si una extensión falla al cargar, ofrece
  desactivarla o abrir su carpeta. Si la misma extensión ya estaba
  instalada a mano con otro nombre de carpeta, lo detecta y ofrece apartar
  esa copia (se renombra, no se borra) para que no se cargue dos veces.
  Las extensiones **instaladas a mano** con la 0.5.7 o antes también se
  gestionan: aparecen en «Instaladas», se pueden desinstalar (se apartan
  con un punto delante del nombre, nunca se borran) y, si están en el
  catálogo, **reemplazar por la versión del catálogo**, que desde entonces
  se actualiza, desactiva y desinstala con normalidad.
  Las **extensiones de ejemplo** (Niveles, Propiedades del polígono,
  Windowizer) se instalan ahora desde el gestor, no desde un submenú propio:
  las que están en el catálogo como cualquier otra, y Windowizer como
  «Incluida con IngeTrazo», desde la copia que trae el programa. Así se
  activan, desactivan y desinstalan igual que las demás, y el menú
  Extensiones queda más corto.
- **Navegador (el Outliner)**: una pestaña nueva de la barra
  lateral con todos los grupos y componentes del modelo en árbol, a
  cualquier profundidad, bajo el nombre del documento. Cada fila lleva un
  icono por tipo (grupo, componente, imagen, texto 3D, elemento con clase
  IFC), un ojo, un candado, su tipo (con el número de copias de un
  componente) y su capa; clic derecho en la cabecera muestra además
  Material, Copias y Clase IFC, y la columna de nombres se ensancha
  arrastrando su borde (todo se recuerda). Un clic selecciona en la vista
  y abre los grupos que lo contienen; doble clic o Intro abre el grupo;
  Espacio oculta; F2 renombra; Esc sale un nivel; lo seleccionado en la
  vista se encuentra en el árbol y los grupos abiertos se leen en negrita.
  El filtro busca por nombre, tipo, clase IFC o capa y conserva la ruta
  hasta cada resultado; el pie cuenta grupos, componentes y ocultos.
  - **Reorganizar**: arrastrar filas sobre un grupo las mete en él,
    soltarlas entre filas las deja junto a ellas, Tab / Mayús+Tab meten en
    el grupo de arriba o sacan un nivel. Nada se mueve en el mundo, aunque
    el grupo de destino esté movido o girado; los componentes conservan su
    definición (no se mete ni se saca nada de uno).
  - **Bloquear** (el candado): un grupo bloqueado se sigue viendo, pero no
    se puede elegir, seleccionar ni abrir; el bloqueo se guarda en el
    `.igz`.
  - **Aislar** oculta todo menos lo seleccionado y lo que lo contiene;
    **Mostrar todos los grupos** lo devuelve.
  - **Varias filas a la vez**: llevarlas a una capa (o a una nueva),
    pintarlas con el material activo o quitarles la pintura.
  - **Planos de sección**: una carpeta del árbol con cada plano en uno de
    cuatro modos — corte y cuadro, solo corte (el cuadro oculto, el modelo
    sigue cortado), solo cuadro o apagado —, F2 para su nombre y su
    símbolo, y el relleno del corte: el general del estilo (se enciende y
    cambia de color desde ahí) o uno propio por plano — sólido, achurado a
    45°, achurado cruzado o ninguno, con su color y la separación del
    achurado escrita como cualquier medida. La fila de la carpeta lleva
    los interruptores de Ver ▸ Planos de sección y Cortes de sección.
  - **Planta de un grupo** (clic derecho ▸ Crear planta de este grupo…):
    corta a la altura indicada sobre su base (1,20 m por defecto), guarda
    una escena mirando desde arriba en paralela y, si se quiere, la pone
    en una lámina nueva que se abre en el compositor. **Vista de un
    corte** (clic derecho en un plano ▸ Crear vista de este corte…): lo
    mismo mirando el corte de frente — un corte si el plano es vertical.
  Cada cambio es un paso de deshacer. Parte del plugin Project Structure
  de @fafecm (#87) y del alcance que escribió @roymendezcastro (#219)
  (@canalsecuario-blip).
- **La barra lateral del modelo, como la del compositor**: las pestañas
  (Propiedades, BIM, Terreno, Navegador, las de las
  extensiones) van arriba y con su nombre completo, con flechas cuando no
  caben; se reordenan arrastrándolas, y al arrastrar una fuera de su barra
  aparecen dos zonas en los bordes de la vista («Lado izquierdo», «Lado
  derecho»): soltada en una, se acopla a ese lado junto a las que haya
  (también sobre las pestañas de ese lado, o con clic derecho ▸ Mover al
  otro lado). Arrastrando desde la parte vacía de la barra se lleva la
  barra lateral entera, con todas sus pestañas. Cada lado se pliega con su asa: Ctrl+F5 el derecho, Ctrl+F6
  el izquierdo; dónde queda cada pestaña se guarda con la ventana.
  **Paneles por defecto**: un primer arranque abre Propiedades y, en la
  pestaña siguiente, el Navegador, lo que casi todo el trabajo
  necesita, con IA y Renderizar detrás; BIM y Terreno esperan en Ventana ▸
  Paneles, y lo que se abre o cierra ahí se recuerda, como siempre.
  Ventana ▸ Paneles ▸ Restablecer paneles vuelve a esa disposición de
  fábrica. Los paneles de una extensión se abren en pestaña junto a
  Propiedades — también uno que la extensión crea más tarde, que antes
  quedaba oculto —, y una extensión puede pedir que el suyo empiece
  cerrado: `app.add_panel(…, start_hidden=True)`.
- **Pestañas a ambos lados del compositor**: Diseño, la nueva Vistas y
  láminas, Elementos y Propiedades empiezan juntas a la derecha; se
  reordenan arrastrándolas y pasan al lado izquierdo arrastradas allí (se
  abre mientras se arrastra) o con clic derecho ▸ Mover al otro lado.
  Cada lado se pliega con su asa (Ctrl+F5 y Ctrl+F6), uno que se queda
  sin pestañas se pliega solo, la disposición se recuerda y clic derecho
  ▸ Restablecer pestañas la devuelve a la de fábrica.
- **Vistas y láminas, en el compositor**: una pestaña con
  las escenas del modelo (con su miniatura) y las láminas con sus vistas.
  Una escena arrastrada a la página queda colocada donde se suelta, a la
  escala estándar que la hace caber en el marco (doble clic: en un hueco
  libre), deshaciéndose con el propio compositor. Cada escena dice en qué
  láminas está y las que no están en ninguna se ven en cursiva; una vista
  cuya escena se borró se marca. Las láminas se abren, renombran,
  duplican, borran y reordenan (Alt+↑/↓) desde ahí, y las seleccionadas se
  exportan juntas a un PDF. El compositor se entera, abierto, de las
  láminas y escenas que se crean o se deshacen desde el modelo.
- **Extensiones**: `app.add_outliner_kind(fn)` deja que una extensión diga
  qué son sus grupos en el navegador (tipo en la columna Tipo,
  propiedades en su tooltip, y el filtro lo encuentra); el ejemplo
  Windowizer muestra sus ventanas como «Window» con paños, ancho, alto y
  marco (docs/plugins.md).
- **Panel de unidades** (Ventana ▸ Unidades…, **Ctrl+U**, o Preferencias ▸
  Unidades): perfil métrico, milimétrico, imperial o a medida; longitud
  con decimales o con la fracción más chica, área y volumen por la
  longitud o con unidad propia, ángulo y separador decimal, con vista
  previa. Las medidas se muestran y se leen en un solo sitio, así que la
  unidad elegida llega a todas las herramientas y cuadros (giros de Rotar,
  Transportador y Arco, volúmenes de Info de entidad y del modelo). Se
  guarda en el documento; los archivos de antes abren igual. Y **al
  empezar un documento nuevo** se pregunta en qué unidades trabajar
  (metros, milímetros, imperial o a medida), con «No mostrar al inicio»
  (#6 de Gabriel Rodríguez, @canalsecuario-blip).
- **Materiales recientes**: el panel Materiales guarda, bajo «Activo», los
  seis últimos materiales con los que pintaste, el más nuevo primero. Un
  clic vuelve a dejarlo activo tal como lo usaste (imagen con su tamaño,
  giro y tinte, o el color; transparencia; nombre), sin buscar el mismo
  ladrillo en la biblioteca cada vez (#263, @canalsecuario-blip).
- **Botones Paralela / Perspectiva / Dos puntos** en la barra de vistas
  estándar: un clic en vez de ir al menú Cámara. Siguen a la proyección
  la cambie quien la cambie (Mayús+P, una escena, una vista guardada)
  (#292, @canalsecuario-blip).
- **Editar componentes con el resto apartado** (Cámara ▸ Edición de
  componentes): **Alt+Q** oculta el resto del modelo y lo vuelve a mostrar
  como estaba, y **Alt+W** quita de la vista y de la selección las otras
  copias del componente que editas (#237, @canalsecuario-blip).
- **Arcos: el número de segmentos antes de dibujar**, como los lados del
  círculo: un número tecleado antes del primer clic fija los segmentos de
  los arcos de dos y tres puntos, del arco por centro y del sector, y
  «Ns» lo cambia en cualquier momento; el número se queda para los
  siguientes arcos. El ángulo del arco por centro ya no se lee como una
  longitud, y al redondear una esquina la casilla dice «Radio» (#290,
  @canalsecuario-blip; #298, @pacaeiro).
- **Reemplazar componente**: con el clic derecho, «Seleccionar ▸ Todas
  las copias» y «Reemplazar componente…» cambian de una vez todas las
  copias de un componente por otro (la silla provisional por la
  definitiva), conservando su posición, giro, escala, capa y material.
  La lista «En el modelo» de la bandeja trae miniaturas, filtro por
  nombre, renombrar todas las copias y **Guardar en el archivo** para
  conservar un componente aunque no quede ninguna copia colocada; y
  «Componentes de archivo…» trae los de otro `.igz` como biblioteca. Un
  documento con componentes guardados así los pierde si se abre en una
  versión anterior (@canalsecuario-blip, ingetrazo-dev#4).
- **Redondear 3D también bisela** (Mayús+F): chaflán, curva ajustable,
  perfiles de escalones, cornisa y moldura, o uno dibujado a mano; cuatro
  formas de medir (radio, distancia en cada cara, ancho o profundidad);
  esquinas rellenas o en muesca; y biselar solo los vértices. Un panel
  abajo a la izquierda reúne todos los ajustes con vista previa en vivo.
  Con los ajustes de siempre redondea exactamente como antes
  (@canalsecuario-blip, ingetrazo-dev#5).
- **Edición ▸ Seleccionar nada (Ctrl+T)**, la pareja de Seleccionar todo;
  no marca el documento como modificado (#367, @pacaeiro, #349).
- **Mover, Rotar y Voltear muestran un + en el cursor** mientras Ctrl hace
  una copia, como la Cinta y el Transportador con sus guías: antes solo lo
  decía la barra de estado y se descubría después del clic si se había
  movido el original o una copia (#262, @vicc3d).
- **Compositor: la vista previa de la cota en cadena y desde línea base**
  es la cota que se va a colocar (líneas de referencia, extremos y valor),
  también recta cuando Mayús la fuerza horizontal o vertical (#351,
  @tonfdd).
- **El Inspector de sólidos repara**, y ahora es una pestaña de la
  bandeja lateral (Extensiones ▸ Inspector de sólidos la trae al
  frente), así el modelo queda a la vista: además de bordes abiertos,
  aristas sueltas y sobreconectadas, ahora encuentra **caras internas**
  (una cara repetida o un tabique sin marcar) y **caras invertidas** en
  un objeto cerrado. **Reparar** y **Reparar todo** hacen, en un solo
  paso que se deshace, lo que tiene una única respuesta: borran aristas
  sueltas y caras repetidas, cierran los huecos de borde plano, marcan
  los tabiques como interiores y giran hacia fuera las caras invertidas,
  también en un grupo sin entrar en él. Un hueco que no es plano queda
  en la lista y dice por qué. Un clic en un objeto de la lista muestra
  su primer problema, listo para repararlo; **Resaltar problemas** los
  pinta todos a la vez, con una leyenda de colores; **Siguiente /
  Anterior problema** recorren sus problemas uno por uno, encuadrados y
  pintados en pantalla con un color por tipo (también dentro de un
  grupo), y **Reparar este problema** arregla solo ese y pasa al
  siguiente. Con caras invertidas ya no muestra un volumen equivocado.

### Cambiado
- **Atajos nuevos**: **Ctrl+1…7** para las vistas estándar (Superior,
  Frontal, Derecha, Isométrica, Posterior, Izquierda, Inferior: las cuatro
  de cada día bajo la mano izquierda), **Mayús+F** para Redondear 3D (F
  sigue siendo Equidistancia) y **Ctrl+H / Ctrl+Mayús+H** para Ocultar y
  Mostrar todo (#258, #259, #261, @canalsecuario-blip).
- **Empujar/Tirar: el toque de Ctrl se arma al soltar la tecla**, y la
  barra de estado dice si deja la cara de partida, así Ctrl+Z u otro atajo
  ya no lo cambian por el camino (#322, #345, @pacaeiro).
- **Asistente IA con modelos locales** (#461, vídeo de revisión de
  Rafael): el modelo de Ollama por defecto es ahora `qwen2.5-coder:7b`, un
  modelo de código, en vez de `llama3.2`; la primera petición avisa de que
  el servidor local está cargando el modelo y, si el elegido es pequeño,
  sugiere uno de código. Tras **3 intentos fallidos seguidos** el
  asistente se detiene y devuelve el control (antes reintentaba hasta 12
  veces); «continúa» lo retoma. Nueva receta **`box()`** para cajas y
  cubos, y el recetario pide usar `box` y `house` antes que armar a mano.
- **Empujar responde al gesto completo**: soltar el botón después de
  arrastrar confirma la extrusión, como en las herramientas clásicas, y el
  ritmo clic-clic de siempre sigue intacto; Ctrl (empujar una copia) se lee
  en el instante exacto de soltar. Cuando la distancia es demasiado pequeña,
  el intento de confirmar —clic o soltada— avisa una vez por arrastre
  («Empuje demasiado pequeño — arrastra más o escribe una distancia») en vez
  de no hacer nada en silencio.
- **La distancia sigue caliente tras confirmar**: teclear un número y Enter
  justo después de un empuje lo sustituye — positivo mantiene el sentido,
  negativo lo invierte — y la operación sigue ocupando un solo paso de
  deshacer por muchos retipados, el mismo contrato que Rotar y Escalar.
- **La línea de referencia, a la vista**: durante el arrastre, una línea
  discontinua del color de su inferencia (verde = vértice, rojo = arista,
  azul = cara) une el punto de referencia con la tapa que se mueve: se ve
  por qué la distancia se detiene donde se detiene.
- **Empujar arranca sobre la cara seleccionada**: con una sola cara
  seleccionada, activar Push/Pull (P) la deja lista — sombreada, sin que
  pasar el cursor por otra se la robe — y el primer clic, caiga donde
  caiga, arranca el empuje sobre ella: el flujo clásico de preselección.

### Rendimiento
- **Editar dentro de un grupo grande, casi 3× más rápido**: dibujar una
  línea dentro de un grupo de 25 000 caras pasa de 1,9 s a unos 0,7 s. El
  visor ya no vuelve a preparar las caras que la edición no tocó, ni
  reescribe la caché de disco mientras el grupo está abierto; y el motor
  solo busca cruces, caras partidas y duplicados entre lo que está cerca de
  la línea. El resultado es idéntico (comprobado cara a cara).
- **Empujar/Tirar ya no rehace planos lejos del empuje**: tras cada empuje se
  rehacían todos los planos con alguna arista abierta del grupo — en un
  modelo importado, cientos y lejos de donde se empujaba. Ahora solo los que
  el empuje pudo dejar abiertos: una cara enorme de la plaza pasa de no
  terminar en 5 minutos a unos 3, y nada lejano se recalcula.
- **Empujar/Tirar en mallas grandes, hasta 9× más rápido**: en un grupo
  grande que forma una sola pieza (un terreno o un modelo importado),
  decidir qué lado de cada cara es «fuera» lanzaba cientos de miles de
  rayos contra todos los triángulos — un empuje cualquiera podía congelar
  IngeTrazo 3–4 minutos. Ahora cada rayo solo prueba los triángulos cerca
  de su trayectoria (un índice por bloques, como el de Blender): 21–31 s en
  esos casos, y el resto del empuje (aristas sueltas, cosido, cara opuesta)
  ya no recorre todo el grupo — 1,5 s → 0,8 s en una cara normal. El
  resultado es idéntico: misma malla, cara a cara, en 12 empujes de prueba.
- **Editar ya no paga los paneles laterales**: la lista «En el modelo» de
  Componentes y el Navegador se refrescaban tras cada edición, aunque
  estuvieran plegados u ocultos (+20 ms por edición en un modelo como la
  plaza). Ahora, ocultos, esperan a mostrarse; a la vista, se refrescan una
  vez 300 ms después de la última edición de una ráfaga.
- **Los modelos enormes abren 3× más rápido, guardan 3,6× más rápido y
  pesan un tercio**: el `.igz` gana el **formato 3**. En un documento
  grande (más de 20 000 caras y aristas) cada malla pesada guarda sus
  puntos una sola vez, en binario dentro del mismo ZIP; la estructura
  (grupos, capas, materiales) sigue en JSON. Con el modelo de la #158:
  abrir 61 → 19 s y 9,7 → 4,3 GB de memoria, guardar 51 → 14 s, archivo
  171 → 54 MB; en la plaza, guardar 2,3 → 0,9 s y abrir 1,9 → 1,1 s.
  Comprobado malla por malla que se reabre igual que guardado en JSON
  (vértices, aristas, caras, huecos, atributos y su orden). Los
  documentos pequeños no cambian y siguen siendo JSON legible; los `.igz`
  de antes abren igual. Un documento en formato 3 **no abre en versiones
  anteriores** (avisan de que es más nuevo): actualiza antes de compartir
  un modelo grande (@pacaeiro).
- **Orbitar un modelo con miles de componentes es 11× más fluido**: con la
  planta industrial de la #158 (21 406 copias) cada cuadro pasaba de 1,3 s
  a 0,12 s. Las siluetas de las copias se calculan por pieza en una sola
  pasada de NumPy en vez de copia por copia, y su intervalo se adapta a lo
  que cuestan (en un modelo pequeño no cambia nada); y el visor deja de
  recorrer todas las copias en cada cuadro para firmarlas, expandirlas,
  buscar figuras de frente o leer sus matrices: lo hace solo cuando algo
  cambia. En la plaza, pintar −10 % y orbitar −8 % (@pacaeiro, Ronilson).
- **El zoom y el giro ya no se cuelgan la primera vez en un modelo
  enorme**: para saber qué punto hay bajo el cursor leen la profundidad de
  la imagen en pantalla (unos 15 ms) en vez de construir el índice de
  selección, que horneaba todas las copias — minutos y 8 GB en el primer
  giro de rueda con el modelo de la #158.
- **Seleccionar y dibujar con snap sobre un modelo enorme ya no agota la
  memoria**: cuando las copias de componentes pasan del millón de caras,
  el índice de selección solo hornea las que quedan cerca del cursor (y
  delante de lo que se ve), con un tope, y suelta las que dejan de usarse.
  Con el modelo de la #158, pasar el ratón con Seleccionar pasó de colgarse
  por encima de 18 GB a 32 ms por movimiento y 11,7 GB; con Línea, 71 ms.
  Los modelos normales usan el índice de siempre.

- **Pasar el cursor con Línea y arrastrar con Mover, hasta 2× más rápido
  en modelos grandes**: la distancia a las aristas de los grupos se mide
  solo en las celdas de pantalla cercanas al cursor, la oclusión de los
  candidatos se pregunta por lotes y el centro de un círculo se busca en
  el registro de la malla. En una ciudad de 331 000 caras: pasar el cursor
  con Línea 103 → 60 ms por movimiento, arrastrar con Mover 101 → 49 ms;
  los puntos que se enganchan son los mismos (#312, @orianbsilva).
- **Mover un objeto muy pesado dentro de un modelo grande**: los grupos de
  más de 8 192 triángulos se dividen en celdas, y un rayo solo prueba las
  que cruza. Arrastrar un sofá de 107 000 triángulos en una sala de
  306 000 caras pasó de 565 a 134 ms por paso (mediana) (#346,
  @orianbsilva).
- **Primera persona fluida en edificios grandes**: los sensores de pared
  solo preguntan hasta donde alcanzan. Caminar mirando alrededor en un
  edificio de 1,1 millones de caras pasó de 38 a 64 fotogramas por
  segundo, sin tirones (#361, @orianbsilva).
- **Una escena que solo mueve la cámara ya no redibuja el modelo entero** ni
  marca el documento como modificado (~120 ms menos por escena en un
  edificio de 1,1 millones de caras) (#360, @orianbsilva).
- **La caja de edición de un grupo ya no hunde los fotogramas al acercar
  mucho la vista**: sus trazos los dibuja el sombreador en vez de
  recalcularse en cada cuadro (#247, @FG-RVT).
- **Abrir un documento enorme ya no deja la ventana «sin responder»**: el
  documento se lee en segundo plano mientras avanza la barra de progreso,
  el dibujo se prepara bajo el mismo cuadro («Preparando el dibujo…») y el
  zoom ya no da tirones entre giro y giro de la rueda. Los documentos
  grandes se guardan compactos y se comprimen más rápido: en la plaza,
  guardar 2,3 → 1,6 s solo por esto (#158, @pacaeiro).

### Corregido
- **Trazar siguiendo un eje hasta una arista vuelve a caer justo en la
  arista**: con el eje enganchado, el punto «En arista» quedaba callado y
  una línea o un arco de un borde al opuesto de una cara terminaba 1–2 mm
  dentro o fuera según el píxel, dejando aristas sueltas. Ahora se ofrece el
  cruce del eje con la arista bajo el cursor: el punto sigue sobre el eje y
  cae exacto en la arista, como en la 0.5.7.
- **Activar MultiView (u otra extensión que mueva el visor) cerraba
  IngeTrazo**: al pasar el visor a otra ventana, Qt recrea su contexto de
  OpenGL, y los objetos que el visor crea al primer uso (planos de imagen,
  vista previa, fantasma de los grupos, búferes de escena y de profundidad,
  componentes instanciados) seguían apuntando al contexto viejo. Ahora se
  rehacen en el contexto nuevo.
- **Un atajo con Mayús y un número se guarda como tal** (#493,
  @pacaeiro): Mayús+5 quedaba como «Mayús+%», el símbolo que escribe la
  tecla, en vez de la tecla pulsada.
- **Esc durante un arrastre en el compositor lo deshace** (#504,
  @pacaeiro): una vista (o cualquier elemento) arrastrada o redimensionada
  vuelve a donde estaba al pulsar Esc, sin dejar paso de deshacer; antes
  se quedaba donde la pillaba la tecla.
- **Importar un GLB hecho con IngeTrazo lo trae a su tamaño**: un modelo
  de más de 40 m se tomaba por uno en pulgadas y llegaba encogido 39
  veces. Los GLB de otros programas siguen adivinando la unidad.
- **El panel de la cota de radio del compositor vuelve a funcionar**:
  cambiar el radio, el tipo, el texto o el estilo de una cota de radio o
  diámetro ya colocada daba un error y no hacía nada.
- **Las herramientas que vienen con IngeTrazo conservan sus atajos**: con
  la carga diferida de extensiones, una extensión instalada (Point Cloud
  Splat) le quitaba `Ctrl+Shift+P` a la consola de Python. Ahora los atajos
  de lo incluido se reservan antes de cargar ninguna extensión.
- **Empujar/Tirar muestra el resultado real mientras arrastras** (#434,
  #458, PR #487 de @FG-RVT): al empujar o tirar parte de una cara partida,
  las caras viejas ya no tapan el hueco ni quedan aristas cruzando las
  paredes nuevas; la vista previa es la operación misma, aplicada una vez al
  empezar y estirada en cada cuadro, y al soltar se confirma sin repetir el
  cálculo.
- **Orbitar con mucho zoom ya no pierde la cámara ni impide guardar** (#485,
  #383): muy de cerca, el punto «bajo el cursor» que lee el búfer de
  profundidad salía a distancias absurdas por falta de precisión; la órbita
  giraba alrededor de él, la vista se iba al fondo y, con la cámara en NaN,
  el guardado se negaba («Where: scene › camera › target[0]»). Ahora ese
  punto se descarta, la órbita nunca deja una cámara inválida y, si la
  vista llegara a romperse, el modelo se guarda igual: el archivo abre
  encuadrado en el modelo.
- **Exportar a GLB, DAE u OBJ fallaba con cualquier modelo hecho por la
  IA** («too many values to unpack», #462, @blackflash73): el recetario y
  el puente MCP pintan con `(r, g, b, 1.0)` y los exportadores leían tres
  canales. Ahora toman el RGB (la transparencia sigue viniendo de la
  opacidad).
- **El asistente IA ya no rompe la vista al añadir dos veces un grupo**:
  si el modelo hacía `groups.append(...)` con lo que `house()` o `box()`
  ya habían agregado, el grupo quedaba repetido o, con `house()`, entraba
  una lista y el visor dejaba de dibujar.
- **Una textura grande ya tiene su miniatura en Materiales** (#460,
  @tomlai-git): una imagen de más de 256 MB descomprimida se pintaba bien
  pero no aparecía en el panel, porque la miniatura la leía con el límite
  de memoria de Qt, que el visor sí quita.
- **El Flatpak arranca más rápido** (#440, @cdblue999): el programa corre
  desde su código en una carpeta de solo lectura, así que Python lo volvía
  a compilar entero en cada arranque. Ahora se compila una vez al construir
  el paquete (en un portátil antiguo, importar el programa pasa de 1,2 a
  0,26 s).
- **La ventana aparece antes aunque tengas muchas extensiones** (#440):
  las extensiones se cargan justo después de que la ventana está en
  pantalla, no antes (con 26 extensiones instaladas, el arranque esperaba
  2,5 s por ellas). Sus paneles y barras vuelven a su sitio guardado, y un
  archivo abierto con doble clic se abre después de cargarlas, por si una
  extensión es la que sabe abrirlo.
- **Información de entidad muestra el área en las unidades del documento**
  (#432, #406, @dns-0): el área de una cara salía siempre en m², aunque el
  modelo estuviera en pies y pulgadas; ahora sale en ft² (y en las demás
  unidades, la que corresponda). El área en planta de un polígono de
  terreno también, sin perder las hectáreas.
- **Empujar ya no salta a referencias que no se ven** (#270, #384,
  @FG-RVT): la distancia que Empujar/Tirar deduce a mitad de arrastre leía
  cualquier vértice o arista bajo el cursor, aunque estuviera tapado por
  geometría o cortado por un plano de sección, y la extrusión se lanzaba de
  pronto a un canto invisible al cruzarlo. Ahora aplica las mismas dos
  reglas que los enganches: lo que la sección corta no se pulsa ni se
  encaja, y lo que hay delante esconde; en Rayos X y alambre todo sigue
  siendo referencia.
- **Renombrar un elemento en la lista de Elementos del compositor ya no
  puede cerrar el programa**: la lista se reconstruía dentro del propio
  cambio de la fila y borraba la fila que Qt seguía editando.
- **Una vista de lámina cuya escena ya no existe lo dice**: antes dibujaba
  la cámara del modelo (una axonométrica sin corte, donde iba una planta
  o un corte), sin explicar por qué; ahora muestra un aviso con el nombre
  de la escena que falta, en pantalla y al exportar.
- **El relleno de sección cubre solo la geometría cortada**: antes era un
  truco por píxel (el plano se pintaba donde se veía la cara trasera de
  algo) y rellenaba también caras sueltas vistas por detrás, caras
  invertidas o la figura 2D, aunque el plano no las cortara. Ahora se
  construye con el propio corte, como el relleno vectorial de las láminas:
  los segmentos que el plano saca de cada sólido se unen en contornos
  cerrados, los huecos quedan huecos (un muro hueco, el interior de una
  habitación) y una superficie abierta no se rellena. Mientras se arrastra
  un plano, las líneas de corte se mueven en vivo y el relleno aparece al
  soltarlo.
- **Renombrar una escena ya no deja huérfanas sus vistas en las láminas**:
  el marco de una lámina guarda el nombre de la escena que muestra, y al
  renombrarla (en el panel Escenas o en el Navegador) ahora
  sus vistas la siguen; antes se quedaban apuntando a un nombre que ya no
  existía.
- **Alejar mucho con la rueda dejaba el modelo sin poder guardarse**:
  pasado el límite de 10 km, el punto al que mira la cámara seguía
  alejándose un 11 % por paso; la vista se volvía lenta y blanca y al
  final la cámara tomaba un valor inválido que el guardado rechazaba.
  Ahora el zoom se detiene en el límite, la cámara nunca toma un valor
  inválido y, si lo tuviera, el guardado conserva la última vista buena
  (#383, probablemente también #242).
- **Al alejar un modelo grande desaparecía su parte del fondo** y volvía
  al acercar: el visor no dibujaba nada a más de 10 km del ojo. El límite
  lejano crece ahora con la distancia de la cámara; a distancias normales
  no cambia nada (#340).
- **Invertir caras dentro de un grupo no se veía** hasta borrar la cara y
  deshacer: la cara sí se invertía, pero el visor seguía dibujando el
  grupo como estaba, porque invertir no cambia ni el número de caras ni
  sus coordenadas, que es lo que el visor vigilaba. Ahora se ve al
  instante, también al deshacer (#197, @fafecm, @joejivaros).
- **Las preferencias de General se perdían al reiniciar**: el tema volvía
  siempre a oscuro, y si habías desactivado el autoguardado o la copia
  `.bak`, o cambiado el intervalo, los pasos de deshacer o el servidor
  gráfico, volvían a su valor por defecto. Se guardaban bien, pero se
  buscaban con un nombre que Qt solo reconoce dentro de la misma sesión.
  Ahora se leen también los valores que ya guardaste con versiones
  anteriores (#266, diagnosticado por @parampreetss).
- **Una cara suelta delante de un grupo no se podía seleccionar**: el
  clic se lo llevaba el grupo de detrás (una caja dentro de un componente
  cóncavo, una pieza suelta delante de un mueble agrupado). Ahora gana lo
  que se ve, también con el clic derecho, que ya no cambia la selección
  por el grupo de detrás ni quita «Crear grupo» del menú; igual en Mover y
  en el Borrador (#276, #363, #378).

- **Un sólido nuevo salía con la cara de abajo invertida si en el modelo
  había otra pieza abierta** (un cubo al que le borraste una cara): la
  corrección de orientación miraba si TODO el modelo estaba cerrado, así
  que una sola pieza abierta la apagaba para todos; agrupar el cubo
  abierto lo «arreglaba» y explotarlo lo volvía a romper. Ahora se decide
  por cada sólido. Por prudencia, en un modelo con piezas abiertas una
  corrección solo se queda si deja el sólido más coherente que antes
  (probado con la plaza: corrige cuatro sólidos y deja intacto un quinto
  que habría estropeado) (#230, @Rainjalin).
- **Restar un tercer sólido a un muro con dos puertas fallaba** con «Ese
  sólido tiene un fallo que la operación no puede leer»: con dos huecos
  alineados, la cara del muro se triangula con una arista larga que pasa
  por las esquinas de los dos huecos, lo que para dibujar está bien pero
  la operación de sólidos no lo acepta. Ahora, solo cuando la operación lo
  rechaza, esos triángulos se parten en esas esquinas y se reintenta; lo
  que ya funcionaba se procesa exactamente igual (#227, @fafecm).
- **En Windows, «Ir a la ubicación» del panel Terreno cerraba la
  aplicación** sin aviso (en algunos equipos con gráfica AMD): el visor
  arrancaba la conexión de red para descargar el mapa base desde dentro
  del dibujado de OpenGL. Ahora las descargas empiezan justo después; las
  teselas ya guardadas en el disco se siguen leyendo al momento, así que
  las láminas y las exportaciones no salen sin mapa (#327, diagnosticado
  por @timwelchnz; arreglo de @PINYOPATTANAWASANPORN).
- **Rehacer con Ctrl+Shift+Z no funcionaba en Linux (KDE y GNOME)**, y
  Ctrl+Y no estaba: el atajo de fábrica salía repetido («Ctrl+Shift+Z;
  Ctrl+Shift+Z»), porque la tecla estándar de Rehacer de esos escritorios
  ya es Ctrl+Shift+Z, y una tecla repetida no responde. Ahora Rehacer
  lleva Ctrl+Y y Ctrl+Shift+Z en todos los sistemas (#313, diagnosticado
  por @RaphaelNunes10).
- **Importar un archivo de atajos podía dejar teclas muertas**: si el
  archivo daba la misma tecla a dos comandos (Z para la herramienta Zoom y
  para Zoom a la selección, al copiar los atajos de otro programa), ninguno
  respondía. Ahora la tecla se queda con el primero y el aviso de la
  importación dice cuáles se quitaron (#323, @tomlai-git).
- **Las medidas del rectángulo con coma y espacio no se leían** y el
  rectángulo salía del tamaño del cursor: en `1 3/8", 1 3/16"` o
  `1220, 2440` la coma se tomaba por decimal (las pulgadas mixtas siempre
  llevan un espacio). Ahora una coma junto a un espacio, o tras una marca
  o una unidad, separa las dos medidas; `2,5` sigue siendo 2,5. Y se leen
  las comillas tipográficas que pone el Mac (`”`, `’`) y las fracciones de
  un solo carácter (`⅜`, `½`), que antes ni entraban en la casilla (#189,
  @smcardle, @Loonster83).
- **El Texto 3D pedía la altura y la extrusión en metros** aunque el
  documento estuviera en milímetros: ahora las casillas muestran y leen
  la unidad del documento (mm, cm, m, pulgadas o pies), con el panel de
  unidades (#287, @ea2ehc).
- **Copiar con Mover+Ctrl una pieza entera no dividía las caras donde
  caía**: las aristas de una cara copiada (la tapa de una tabla bajada
  1 cm, o una matriz de copias con `4/`) no partían la pared sobre la que
  quedaban, mientras una línea dibujada ahí sí. Ahora se planifican como
  las de la herramienta Línea, una vez pegadas las caras copiadas, sin
  duplicarlas (#379, visto en la reseña de @Jrobredo3D).
- **Bajar una arista sobre otra dejaba vértices dobles**: al hacer una
  rampa con Mover, cada esquina caía sobre otra pero quedaban dos vértices
  en el mismo punto, con una cara sin área que hacía fallar Crear grupo y
  Crear componente. Ahora las esquinas se funden y queda un sólido limpio
  (#341, @pacaeiro).
- **Ctrl+Z cambiaba en silencio el modo Ctrl** del Transportador (guías),
  Escalar (desde el centro) y Rectángulo (desde el centro), igual que el
  de copia en Mover, Rotar y Voltear: un Ctrl que resulta ser parte de un
  atajo ya no cuenta (#342, @pacaeiro; #262, @vicc3d).
- **Deshacer dejaba aristas sueltas**: al deshacer una cara añadida (la
  copia de un giro o de un movimiento, un pegado) quedaba su contorno; ahora
  se van también las aristas y esquinas que trajo (#355, @pacaeiro).
- **Una esquina limpia se anunciaba como «Intersección»** en vez de
  «Extremo» a unos píxeles de ella; era el mismo punto con otro nombre
  (#357, diagnosticado por @kellytait).
- **Al mover una arista, «Desde el punto» le ganaba al eje**: tras pausar
  en la esquina de partida, arrastrar por el eje rojo decía «Desde el
  punto» todo el camino y desplazaba el punto unos centímetros del cursor
  (#368, @pacaeiro).
- **El GLB conserva la estructura del modelo**: cada grupo y componente
  sale como un objeto con su nombre y su posición, anidado como en el
  modelo, y las copias de un componente comparten una sola malla (en la
  plaza el archivo pasa de 24,4 a 19,5 MB). Antes todo salía fundido en
  un único objeto «IngeTrazo» (#304, @arthurarquitetoamb). Las figuras
  de escala ya no se pierden: salen de pie mirando a la vista Frontal y
  sin espejar, también dentro de un grupo, donde salían cortadas y
  espejadas. Con algo seleccionado, Exportar ▸ glTF/GLB pregunta si se
  exporta todo o solo la selección (#353, @SPMech). Y un color guardado
  con transparencia ya no impide exportar el archivo entero. El COLLADA
  (.dae) sigue saliendo en una sola pieza.
- **Exportar a COLLADA, glTF/GLB, OBJ o STL podía incluir triángulos sin
  área**, que otros programas rechazan (una puerta entera por 56 de 3 884);
  ya no se escriben y la superficie exportada no cambia (#314,
  @ales-limon).
- **No se podía teclear «16s»** para los segmentos de un círculo o un arco:
  la «s» nunca llegaba a la casilla de medidas (#252, Discussion #267,
  Arthur031221).
- **El cuentagotas no actualizaba la muestra «Activo»** del panel
  Materiales (#47, #264, @canalsecuario-blip).
- **Voltear no hacía nada con un grupo formado por otros grupos** (un
  mueble con sus piezas agrupadas): la herramienta medía la caja del grupo
  solo con su malla propia, que en ese caso está vacía, así que no había
  planos que elegir. Ahora mide también las piezas de dentro; voltear una
  copia (Ctrl) también las lleva (#380).
- **El resaltado de una cara dentro de un componente se dibujaba lejos de
  la pieza** en un componente colocado y luego explotado (#246,
  @felixriestra).

- **Una extensión que construye sus herramientas en `setup(app)` no
  cargaba**: el cargador intentaba crear cada herramienta por su cuenta,
  sin argumentos, y si pedía alguno descartaba la extensión entera, panel
  incluido. Ahora esas herramientas se dejan a la extensión (planArq, de
  José Castro Basso).

### Seguridad
- **Un `.igz` manipulado podía meter un archivo privado en el siguiente
  guardado o exportación**, nombrándolo como textura (por ejemplo, una
  clave SSH): solo se guardan o copian archivos que de verdad son imágenes
  (@vicc3d).
- **Un servidor de biblioteca en línea comprometido podía escribir fuera de
  su caché** (por ejemplo, un complemento que se cargaría al arrancar): los
  nombres de modelo que no son nombres simples se rechazan (@vicc3d).
- **Una página web abierta en el mismo equipo podía enviar órdenes al
  puente de IA**, incluida la ejecución de código, mientras estaba
  encendido: el puente cierra la conexión en la primera línea que no es una
  orden suya (#335, @WatchmanReeves).

### Traducciones
- **Francés** (#295, @YannFR81) y **alemán** (#365, @PESI3D), completados
  con las frases añadidas después.
- **Los nueve idiomas, completos**: chino, italiano, indonesio, polaco y
  portugués reciben también todas las frases nuevas de esta versión.
- **El español habla de «tú» en todo el programa** y recupera las tildes
  que faltaban (#352, @kant).

### Para desarrolladores
- **La suite rápida pasa en Windows** (fuentes para la plataforma
  offscreen, lecturas en UTF-8, una ruta POSIX) (#288, @orianbsilva).
- **`scripts/bench_interaction.py`**: un banco que mide lo que siente la
  mano en el ratón (cada evento hasta que su fotograma está en pantalla),
  con mediana y p95 por gesto (#308, @orianbsilva).
- Interruptores para diagnosticar: `INGETRAZO_NO_SNAP_FAST=1`,
  `INGETRAZO_SCENE_ALWAYS_BUMP=1` e `INGETRAZO_NO_WALK_REACH=1` devuelven
  el comportamiento anterior de cada optimización (@orianbsilva).

## [0.5.7] — 2026-09-30

**Ventanas paramétricas, la selección con puntos y una semana de pedidos
atendidos.** Llega Windowizer, la primera extensión de ejemplo aportada por
un usuario: ventanas con marco y vidrios a partir de una cara, que abren el
muro y lo vuelven a cerrar. La selección se marca con puntos en vez de un
tinte, el modo Rayos X deja ver qué aristas tienen una cara delante, las
aristas traseras (K) se dibujan en discontinua sobre el modelo opaco, las
pinzas de Escalar enganchan otros objetos, cada comando explica qué hace y
F3 se abre al instante. Los modelos con miles de copias espejadas abren sin
agotar la memoria y cerrar es instantáneo. Renderizar con Blender funciona
en el Flatpak, IngeTrazo habla indonesio, y se resolvieron los pedidos
pequeños que llegaron por correo y por GitHub.

### Añadido
- **Windowizer, extensión de ejemplo** (Extensiones ▸ Extensiones de
  ejemplo ▸ Windowizer), de Bane Andreev, arquitecto: ventanas paramétricas
  a partir de caras dibujadas en un muro, con filas y columnas (o
  proporciones como `1,3,1`), marco, parteluces y vidrios. Cada ventana es
  un grupo etiquetado `IfcWindow` con sus piezas «Marco» y «Vidrio n», así
  que el panel Piezas sirve de cuadro de vidrios; el muro se atraviesa (o
  lleva derrames si es de un solo plano), **Editar ventana** la reconstruye
  en su sitio aunque se haya movido, y **Borrar ventana** vuelve a cerrar
  el muro. En los seis idiomas. Es una adaptación del clásico Windowizer 3
  de Rick Wilson (2004-2005).
- **La selección se marca con puntos** en vez de un tinte: las caras
  seleccionadas llevan puntos naranjas y la cara bajo el cursor los mismos
  puntos, así se distingue también una cara vista por detrás; sobre una
  cara naranja o roja los puntos salen azules (#218, @canalsecuario-blip).
- **Rayos X: las aristas detrás de una cara se atenúan** hacia el fondo y
  las que no tienen nada delante conservan su color; mirando una caja desde
  arriba se sabe si tiene tapa (#223, @canalsecuario-blip).
- **Cada comando dice qué hace**, como las descripciones de Blender: una
  frase breve en el recuadro del buscador F3, en la barra de estado al
  pasar por un menú y bajo el nombre y el atajo en el globo de los botones
  de las barras de herramientas. Cubre los comandos de la ventana
  principal, los del compositor de láminas y los complementos incluidos
  (un complemento propio puede dar la suya con `description` o con
  `tip=` en `add_menu_action`) (#213, @canalsecuario-blip).
- **Aristas traseras** (Cámara ▸ Estilo ▸ Aristas traseras, **K**): el
  modelo sigue opaco y las aristas que quedan detrás de una cara se dibujan
  en discontinua, para ver por dónde sigue una barra o un perfil en un
  plano de taller. Lo guarda el estilo (también las escenas y el `.igz`) y
  tiene casilla en el panel Estilos; el Rectángulo girado deja la K y se
  queda sin atajo (#234, @ales-limon).
- **Las pinzas de Escalar enganchan puntos de otros objetos**: con la pinza
  tomada, pasar por un extremo, un punto medio o una arista de otra pieza
  deja la pinza a su altura, así se escala «hasta» otro objeto sin
  teclear la medida; lo que se escala no se engancha a sí mismo (#233,
  @ales-limon).
- **Alt+X alterna Rayos X** y vuelve al estilo en el que estabas, con sus
  ajustes (#228, @canalsecuario-blip).
- **Propiedades del polígono, extensión de ejemplo** (Extensiones ▸
  Extensiones de ejemplo), de Rony Leonel Janampa Monago: área, perímetro,
  centroide, momentos de inercia respecto al centroide y a los ejes,
  momentos principales con su ángulo, radios de giro y caja envolvente de
  las caras seleccionadas; descuenta los huecos y toma varias caras
  coplanares como una sola sección, en las unidades del documento (#229).
- **Campo Nombre en Info de entidad** para el grupo o componente
  seleccionado: se escribe y Enter, un paso de deshacer (#214).
- **Clic derecho ▸ Voltear en ▸ Eje rojo / verde / azul**: refleja la
  selección en su sitio con un clic, como en los tutoriales (#178,
  reportado por Esteban Penzo).
- **Luces del render en el visor**: con Seleccionar, un clic en el foquito
  selecciona la luz (también en la lista del panel) y Supr la borra, un
  paso de deshacer (#205). Moverlas con M llega más adelante.
- **Preferencias ▸ Atajos de teclado ▸ Exportar… / Importar…**: los atajos
  viajan en un archivo a otro equipo, sistema o persona, y valen en
  cualquier idioma (#142, @pacaeiro).
- **Preferencias ▸ General ▸ «Poner la figura de escala en los documentos
  nuevos»**: sin ella, cada documento nuevo empieza vacío (#221).
- **Traducción al indonesio** (Bahasa Indonesia), el sexto idioma de
  IngeTrazo (#216, #217, @Rainjalin).
- **Para extensiones:** `window.import_igz_path(ruta, at=None)` y
  `app.import_igz` insertan un `.igz` como componente sin el diálogo, al
  ratón o en un punto (#179, pedido de Georges Le Roux);
  `app.add_menu(título)` da un submenú propio en Extensiones,
  `app.add_context_menu(fn)` añade entradas al clic derecho,
  `app.add_pickable(...)` deja seleccionar y borrar objetos propios, y
  `group.ext` guarda parámetros de la extensión en sus grupos (se copian y
  se guardan, aparte de la etiqueta BIM). Todo en `docs/plugins.md`.
- **Puente MCP desde un contenedor:** el cliente lee `INGETRAZO_AI_HOST`
  para llegar al puente por un túnel; el puente sigue escuchando solo en
  local (#130).

### Corregido
- **El compositor de láminas acotaba en metros aunque el documento estuviera en pies** (#403): una cota, una cota de radio o diámetro y una cota de nivel nuevas nacen en la unidad y la precisión del documento. Cada una guarda la suya; cambiar el documento después no reescribe las que ya están en la lámina. La cota de nivel muestra y edita Nivel y Datum en esa unidad (pies y pulgadas se editan en pies decimales; el texto de la lámina sigue en forma de carpintero). Una lámina vieja, sin unidad guardada, sigue leyendo «+0.15».
- **Renderizar con Blender no generaba imagen en el Flatpak** («Python file
  … could not be opened»), ni en el AppImage con el Blender de Flathub: el
  script de render ahora viaja junto al trabajo, en una carpeta que Blender
  siempre ve.
- **Un número a medio escribir se tragaba los atajos con Alt**: Alt+1
  añadía un «1» en vez de cambiar la vista, y repitiéndolo se llegaba a un
  número gigante que dejaba la geometría con coordenadas NaN. Ctrl y Alt
  ya no escriben en el cuadro de medidas y se rechazan los números
  desorbitados (#185, diagnosticado por Alejandro Limón).
- **Un documento con una sola coordenada NaN no se podía abrir**: ahora
  abre, deja fuera solo las piezas dañadas y avisa para guardarlo
  reparado (#185).
- **Editar un material no cambiaba los grupos pintados enteros**: la cara
  suelta cambiaba y la caja agrupada se quedaba con el color viejo (#155,
  @fafecm).
- **Un punto enganchado fuera del plano de dibujo ya no aplasta la forma**:
  al llenar el hueco de una ventana del punto medio de una jamba al de la
  otra, el Rectángulo salía «0.00 × 2.41 m». Rectángulo, Círculo, Polígono
  y los tres Arcos toman el plano de los puntos enganchados; el cursor
  libre y el bloqueo con flechas siguen como antes (#206,
  @canalsecuario-blip).
- **Snaps con el bloqueo paralelo/perpendicular** (flecha abajo): ya
  enganchan extremos, cruces y alineaciones con esquinas, también sobre
  aristas oblicuas (#209, #215, @pacaeiro).
- **Rectángulo bloqueado como cuadrado**: un solo valor tecleado basta
  (#210, #212, @pacaeiro).
- **El buscador de comandos (F3) aparece al instante**: recuerda lo ya
  preparado y calcula la lista de comandos mientras la ventana está
  quieta; se dibuja en unos 20 ms, la primera vez incluida (#211,
  @canalsecuario-blip).
- **Los atajos propios de acciones con «/» en el nombre se conservan**
  al reiniciar: Empujar / Tirar, Alternar perspectiva / paralela, glTF /
  GLB… se guardaban anidados y volvían a su tecla de fábrica en el
  siguiente arranque; los ya guardados así se recuperan (#236,
  @zhang-922).
- **Una línea bloqueada en un eje toma la altura de una guía**: con Shift
  o la flecha arriba sobre el eje azul, pasar por una línea guía que la
  vertical no toca no daba nada; el punto de la guía bajo el cursor se
  calculaba sin perspectiva y caía metros fuera de la pantalla (#166,
  @pacaeiro).
- **Cerrar IngeTrazo con un modelo grande es instantáneo**: el proceso
  seguía vivo, con sus gigabytes, mientras Python liberaba objeto por
  objeto — 27 s → 1,2 s con el modelo de la #158 (@pacaeiro).
- **Modelos con muchas copias espejadas abren y se dibujan**: cada copia
  espejada de un componente se horneaba entera en memoria, y las demás se
  horneaban igual para leer su caja y su silueta. Una planta industrial de
  21 406 grupos (6 203 espejados, 14 millones de caras) pasaba de 14,5 GB
  en el primer cuadro; ahora abre y se dibuja en 9,7 GB (#158). Seleccionar
  con el ratón en un modelo así sigue pendiente.
- **Los globos de ayuda sobre un botón de color se leen**: en Estilos y en
  el compositor tomaban el color del botón como fondo (#213).
- **Editar el color de un material de color liso**: la fila Color del panel
  Materiales lo recolorea al instante, también en lo ya pintado; antes
  solo cambiaba el tinte de una textura, que un color liso no tiene.
- **El selector de color es el mismo en todos los sistemas** (el de Qt):
  el nativo de algunos escritorios Linux no devolvía el color elegido al
  abrirse desde un menú.
- **Las descripciones de los menús llegan a la barra de estado** también
  en los menús que Qt dibuja por su cuenta.

### Pruebas antes de publicar
`scripts/release_check.sh v0.5.6.1` sobre `plaza.igz`
(`benchmarks/results/0.5.7.json`): el visor sin cambios (pintar 8,28 →
8,29 ms, orbitar 8,08 → 8,28 ms, rehacer los búferes 32,9 → 33,0 ms),
arranque 0,80 → 0,78 s, abrir la plaza 3,98 → 3,79 s, ningún objeto
filtrado en seis reaperturas; suite rápida 3562 y lenta 804 correctas. La
comprobación cazó dos cosas antes de publicar: la apertura más lenta por la
comprobación de NaN (#185; ahora solo recorre el documento si el archivo
trae algún NaN) y rehacer los búferes 19 % más lento por las siluetas de
las copias (ahora la caja y la matriz de cada copia se guardan). Y la
prueba a mano con dos monitores cazó un parpadeo de la ventana en Wayland
que el buscador F3 provocaba al preparar su ventana por adelantado: ya no
la prepara.

## [0.5.6.1] — 2026-09-29

**Las extensiones nuevas cargan en Windows, macOS y los paquetes de Linux.**
Versión de corrección de la 0.5.6.

### Corregido
- **El Asistente IA, el puente MCP y Renderizar con Blender salían como
  «error al cargar»** en el instalador y el portable de Windows, el `.dmg`
  de macOS, el AppImage y el `.tar.gz` (#208, reportado por @fafecm y
  @blender3darchitect). Un módulo nuevo que sólo usan esas tres extensiones
  quedaba fuera del paquete. Ahora el empaquetado reúne solo todo lo que
  importan las extensiones, y `--check` carga cada una en la CI: un paquete
  con una extensión rota ya no puede publicarse. El Flatpak y el Snap no
  estaban afectados.

### Cambiado
- **IngeTrazo se describe por sí mismo** en la interfaz, las fichas de
  Flatpak y Snap, el instalador y la documentación. El formato se llama
  «SKP (.skp)» en Archivo ▸ Importar, y si un `.skp` no se puede leer, el
  aviso sugiere exportarlo como COLLADA u OBJ desde el programa de origen.

## [0.5.6] — 2026-09-29

**Render con Blender, una pestaña para la IA y los aportes de la comunidad.**
IngeTrazo renderiza imágenes fotorrealistas con el Blender que ya tengas
instalado, de día o de noche con luces propias, y puede renderizar sola la
vista cada vez que te detienes al recorrer el modelo. El Asistente IA y el
puente MCP viven ahora en una pestaña de la barra lateral, y Ventana ▸ Paneles
deja ocultar las pestañas que no uses. De la comunidad llegan el buscador de
comandos F3, la API de extensiones 2, importar STL, Pegar en su lugar y Zoom a
la selección. Y una tanda de reportes resueltos, incluido el transportador que
en milímetros o pulgadas no daba el ángulo tecleado.

### Añadido
- **Renderizar con Blender** (#181), una pestaña de la barra lateral:
  - Usa el Blender del sistema (EEVEE o Cycles); si no lo encuentra, explica
    cómo instalarlo según el paquete (Windows, Mac, AppImage, Flatpak).
  - **Ambiente** de día (el sol del panel Sombras, con su intensidad), de
    noche o nublado.
  - **Luces puntuales y focos** que se colocan con un clic sobre el modelo,
    con temperatura de color (Kelvin), potencia, apertura y orientación; se
    guardan en el documento y se deshacen con Ctrl+Z.
  - **Acabados para el render** en cada material (vidrio, agua, metal,
    brillante…), desde el clic derecho sobre la muestra; «Automático»
    lo adivina por el nombre.
  - Las figuras que miran a la cámara (Sumari, árboles de imagen) salen de
    frente y recortadas.
  - La imagen se abre en su propia ventana, con zoom, Guardar y Abrir carpeta.
  - **Sincronizar con la vista**: con Blender abierto en segundo plano, cada
    vez que la cámara se detiene sale un borrador de lo que ves en uno o dos
    segundos; editar el modelo recarga la escena.
- **Pestaña IA**: el Asistente IA y el puente MCP en la barra lateral. El
  prompt admite varias líneas (Enter envía, Mayús+Enter salta de línea);
  Ctrl+Mayús+A trae la pestaña aunque esté oculta.
- **Ventana ▸ Paneles**: todas las pestañas de la barra lateral, también las
  de extensiones, para ocultarlas o mostrarlas; la misma lista con clic
  derecho sobre las pestañas. Lo oculto se recuerda al reabrir.
- **Buscador de comandos (F3)**, como el F3 de Blender o la línea de
  comandos de Rhino: se escriben unas letras y
  Enter ejecuta el comando. Encuentra cualquier acción de la ventana
  (menús, herramientas, paneles, complementos) en el idioma de los menús
  o en inglés, por su ruta de menú, por iniciales («rf» → Invertir caras,
  en inglés *Reverse Faces*) y aunque tenga una errata («orinetar»), sin
  importar tildes ni mayúsculas. Cada resultado es una sola fila, como en
  Blender (ruta atenuada ▸ icono y nombre, atajo a la derecha), el cuadro
  se abre bajo el ratón, dentro del área de modelado y sin tapar las
  barras laterales ni superiores, con diez filas a la vista, clic derecho ▸
  Cambiar atajo… lleva a Preferencias, y una letra escrita con un menú
  abierto busca solo en ese menú. Al dejar el ratón sobre un resultado
  aparece, como en Blender, un recuadro con el nombre, qué hace y su atajo,
  sin textos cortados. También en Ayuda ▸ Buscar comandos… y en el
  compositor de láminas, con sus propios comandos (#168,
  @canalsecuario-blip). La barra de estado lo menciona al abrir el programa.
- **Las herramientas del compositor tienen nombre corto** («Cota en
  cadena»); la explicación larga queda en el recuadro de ayuda.
- **Importar STL** (binario y de texto) con la unidad del modelo y la unión
  de caras planas, leído en segundo plano; y **Edición ▸ Simplificar malla**
  (#161, @kagehak).
- **API de extensiones 2**: varios paneles con nombre por extensión que
  vuelven a su lugar, dibujo sobre el visor con `world_to_pixels`, tipos de
  archivo propios y espacios de trabajo (#141, @felixriestra). Además, varias
  extensiones pueden compartir una pestaña y añadir entradas al menú
  Extensiones; la guía explica dónde conviene poner la interfaz de cada una.
- **Pegar en su lugar** (Ctrl+Alt+V), dentro de cualquier grupo (#188), y
  **Zoom a la selección** (#193) (@canalsecuario-blip).
- **Supr borra la arista o cara bajo el cursor**, sin seleccionarla; Retroceso
  borra sólo la selección (#98, @canalsecuario-blip).
- **Importar DWG en Windows, macOS y el Flatpak**: el conversor de LibreDWG
  va dentro de todos los paquetes (#101, #180).
- **Traducción al italiano** (#182, @deedend) y portugués de Brasil al día
  (#186, @dafrobozao).
- En Ayuda ▸ Acerca de, los créditos se detienen al pasar el ratón y se
  recorren con la rueda.

### Corregido
- **Un ángulo, un factor de escala o un número de lados tecleado se escalaba
  con la unidad del documento**: en milímetros, «45» en Rotar giraba 0,045°
  (#176, reporte de Esteban Penzo).
- **Una arista copiada con Mover a través de una cara no la dividía** (#177,
  reporte de Lefteris Schetakis).
- **Ctrl+Z a mitad de una línea** deja la cadena en el vértice anterior en vez
  de seguir desde un punto que ya no existe (#175, @pacaeiro).
- **La Cinta métrica cambiaba de modo con Ctrl+Z**: ahora sólo con un toque de
  Ctrl (#183); no crea guías de longitud cero ni recorta su vista previa
  (#173, #174, @pacaeiro).
- **El pan era lentísimo con el zoom al máximo**: se mide por la profundidad
  de lo que está bajo el cursor (#184).
- **Valores no finitos** (un número enorme en el cuadro de medidas) ya no
  bloquean las herramientas ni se guardan en el documento (#185, primera
  parte). Reportes de Alejandro Limón.
- **La cota en cadena del compositor** seguía cortándose tras cada tramo
  (#187, @tonfdd).
- **La barra de herramientas muestra el atajo configurado**, no el de
  fábrica (#171, @pacaeiro).
- **Rectángulo**: la inferencia de cuadrado engancha (#169, #170, @pacaeiro).
- **El cursor de Empujar/Tirar desaparecía en Windows** tras usarlo (#191).
- **El Asistente IA en Mac no conectaba** (`CERTIFICATE_VERIFY_FAILED`): usa
  los certificados del sistema, sin desactivar la verificación (#198,
  diagnóstico de @troya2).
- El diálogo de cambios sin guardar y los botones estándar de Qt salen en el
  idioma del programa (#154, @canalsecuario-blip).

### Antivirus
- El instalador de Windows se construye con un cargador de PyInstaller
  compilado por nosotros, lo que reduce los falsos positivos de Windows
  Defender (#162). La firma digital (SignPath) está en trámite.

### Pruebas antes de publicar
`scripts/release_check.sh v0.5.5` sobre `plaza.igz`
(`benchmarks/results/0.5.6.json`): el visor sin cambios (pintar 9,63 → 9,99
ms, orbitar 10,31 → 9,69 ms), abrir la plaza 4,74 → 4,72 s, arranque 0,82 →
0,91 s (las pestañas nuevas), ningún objeto filtrado en seis reaperturas;
suite rápida 3444 y lenta 804 correctas.

## [0.5.5] — 2026-09-28

**Íconos renovados y lo que los usuarios pidieron.** IngeTrazo se queda solo
con piezas libres: el enlace a un conversor externo de `.skp` y la
exportación a `.skp` se retiran, y los `.skp` se siguen abriendo con el
lector libre integrado. Los íconos se actualizan para mantenerlos coherentes
en toda la interfaz. Y una tanda
de reportes resueltos: la órbita gira alrededor de lo que miras, Empujar/Tirar
se detiene en las guías de la Cinta, rotar cae exacto en el punto enganchado,
guardar ya no deja un «cambios sin guardar» fantasma, y las medidas salen en
las unidades del documento.

### Retirado
- **El enlace a un conversor externo de `.skp`.** Nunca formó parte de
  IngeTrazo: ningún paquete lo incluía; IngeTrazo solo ofrecía descargarlo
  aparte para ejecutarlo bajo Wine. Ese enlace y la descarga se retiran.
  Los `.skp` se abren con el lector libre integrado (OpenSKP);
  si uno no se puede leer, IngeTrazo lo dice y sugiere exportarlo como
  COLLADA u OBJ desde el programa de origen.
- **Exportar a `.skp`**: el molde en blanco que usaba el escritor ya no se
  distribuye en ningún paquete (PyInstaller, Flatpak, Snap), y `--check`
  falla un paquete que todavía lo traiga. Para llevar un modelo a otro
  programa, exporta COLLADA (.dae), OBJ o glTF.
- Las pruebas y la herramienta de validación que dependían de ese
  conversor; `scripts/skp_diff.py` compara ahora contra un `.dae` de
  referencia.
- **Ayuda ▸ Obtener más modelos** enlaza a Poly Haven, ambientCG y
  Sketchfab.

### Cambiado
- **Íconos actualizados para mantenerlos coherentes con el resto de la
  interfaz**:
  Caminar son dos huellas, Mirar alrededor una cabeza vista desde arriba con
  su cono de visión, las herramientas de sólidos dos discos que se cruzan, el
  texto una T en un marco, el zoom a la extensión cuatro esquinas alrededor
  de la lupa, y las cotas terminan en puntos. **Situar cámara es una
  camarita** con el lente naranja y una marca debajo, y **el borrador una
  goma inclinada** con su punta naranja. Las **vistas estándar siguen siendo
  la casita** con la pared que se mira en naranja.
- **IngeTrazo se presenta por sí mismo**: el README, la ficha del Flatpak y
  la del Snap lo describen con su lema, *traza como a mano*, y dicen cómo
  se pronuncia su nombre (in-je-TRA-so: *inge*niería + *trazo*; sugerencia
  de @pacaeiro).

### Añadido
- **Repetir el último comando con Mayús+R**, y como primera entrada del menú
  del clic derecho (#145, @canalsecuario-blip).

### Corregido
- **Rotar y Transportador enganchan el eje rojo aunque la línea de
  referencia esté a pocos grados de él** (#140, @pacaeiro). El brazo se
  quedaba pegado a la dirección de la propia referencia («A través del
  punto») y la extensión de otras aristas movía el ángulo según la
  distancia del cursor. El brazo del transportador ya no usa las
  inferencias de dibujar líneas (a través del punto, extensión, desde el
  punto): solo puntos y ejes.
- **La extensión ya no sale de un segmento de círculo, arco o superficie
  suavizada, ni de una arista oculta** (#140): lanzaba líneas de trazos a
  través de la esfera.
- **La órbita gira alrededor de lo que estás mirando** (#164, @mariuseng-dot):
  el punto del modelo bajo el cursor al empezar a arrastrar, o el modelo a la
  vista si apuntas al cielo, y ese punto se queda bajo el cursor. Antes
  giraba alrededor del objetivo de la cámara, lejísimos en un modelo grande.
- **Empujar/Tirar se detiene en los puntos y líneas guía de la Cinta**
  (#165, @ewertondiaseng-byte), con el aviso «Punto guía» / «En línea».
- **Rotar cae exacto en el punto enganchado** (#163, @fafecm): con el
  segundo clic enganchado a un punto, se aplicaba el ángulo redondeado a 0,1°
  de la etiqueta (−70,3°) y la arista quedaba ~0,7 mm al costado a 2 m del
  pivote. Además la vista previa ya no acumula error: se calcula siempre
  desde una copia tomada al empezar, y cancelar deja todo idéntico.
- **Guardar y cerrar ya no pregunta por cambios sin guardar** (#159,
  @pacaeiro): cualquier cambio de selección después de guardar contaba como
  una modificación.
- **Círculo, polígono, empalme y recorrido muestran las medidas en las
  unidades del documento** (#149, @xyont): en milímetros decían metros. Lo
  que tecleas en el cuadro de valores se ve con la unidad en que se leerá, y
  «lados»/«segmentos» se traducen.
- **El Rectángulo acepta `200,100`** (sin espacio) como ancho y alto
  (#152, @xyont). `200, 100` y `200;100` siguen valiendo; en las demás
  herramientas la coma sigue siendo el decimal.
- **Una cara invertida sigue invertida al seguir dibujando**
  (#144, @canalsecuario-blip).
- **Todas las pestañas de la bandeja derecha caben en los 240 px mínimos**
  (#139, @felixriestra): los botones de Capas y los combos de Terreno se
  cortaban.


## [0.5.4] — 2026-09-26

**Un día de reportes, resuelto.** Tirar hacia arriba contra una pared (la
#94, que se nos resistía), esferas con Sígueme, guías exactas al milímetro,
componentes cuyas copias comparten lo de dentro, grupos que ya no saltan al
explotarlos y líneas sueltas en el `.skp`. Las láminas ganan líneas ocultas
a trazos, una lista de elementos como la de QGIS y los dos clics que se
perdían. Atajos de teclado propios en Preferencias, el ratón 3D con cada
eje invertible, IngeTrazo en chino y el instalador de Windows en tres
idiomas. El Ingeniero es la nueva figura de escala.

### Cambiado
- **En KDE Plasma con Wayland, IngeTrazo arranca en X11 (XWayland)** (#136,
  @leo-smi): ahí los menús flotantes de Qt salen rotos. Preferencias ▸
  General ▸ Servidor gráfico sigue permitiendo elegir Wayland.
- **El instalador de Windows habla inglés, español y portugués** (#135,
  @xyont), según el idioma de Windows.
- **La figura de escala de un documento nuevo es el Ingeniero** (1,70 m,
  casco y chaleco), dibujado de nuevo de pie y con los dos pies en el
  suelo. Sumari sigue en la biblioteca de personas.

### Añadido
- **Atajos de teclado propios** (#138, @pacaeiro): Preferencias ▸ Atajos
  de teclado lista todas las acciones con su atajo, con buscador; eliges una y
  pulsas las teclas nuevas. Si otra acción ya las usaba, te lo pregunta y se
  las quita (dos acciones con la misma tecla no funcionarían ninguna). Botón
  para volver al de fábrica, de una o de todas. Se recuerdan aunque cambies
  de idioma.
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
  sola curva.
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
  es de su definición; un grupo que sale de una copia
  (Explotar) se vuelve suyo al abrirlo y no toca a las demás.
- **Sumari ya no se cuela en un diseño recién abierto** (#75, @pacaeiro): el
  visor guardaba datos de las figuras por su dirección en memoria, que Python
  reutiliza; tres de esas cachés no se vaciaban al abrir otro documento.
- **Tirar hacia arriba contra una pared** (#94, @xyont): un área dibujada en
  el peldaño de abajo de un escalón, pegada a la contrahuella, no se podía
  tirar hacia arriba («rompería el sólido»), y bajarla sí. La franja donde el
  lado nuevo queda pegado a la pared ahora desaparece. De
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
- **Archivos `.skp` de 2018 (y anteriores) que abrían incompletos**: una
  cota anclada a un punto dentro de grupos anidados desalineaba la lectura y
  se perdía casi todo lo que venía después en la raíz del modelo (una casa
  abría con 2 de sus 72 objetos: solo muros y césped). Ahora abren enteros
  (2384 colocaciones en vez de 12) y también se leen esas cotas. Arreglo
  propuesto a OpenSKP (iamahsanmehmood/openskp#384) y aplicado en IngeTrazo
  mientras tanto. Gracias a Juan José Noriega por los modelos.

## [0.5.3] — 2026-09-25

**Lo que pidieron los usuarios, y extensiones para lo que solo algunos
necesitan.** Pinzas de rotación en Mover y un menú Seleccionar; copias `5x10m`; el ratón 3D; y los fallos que destaparon vuestros
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

- **Estilos: Color trasero** (PR #99, Gabriel Rodríguez):
  junto al Color frontal, el color de las caras vistas por detrás (el
  interior de un sólido, una cara invertida). Sin elegir, sigue el de
  siempre o el que traiga un `.skp`; se guarda en el documento, en las
  escenas y en la biblioteca de estilos.

- **Copias con cantidad y separación en una sola entrada** (#111): al mover
  con Ctrl, escribir `5x10m` hace cinco copias separadas 10 m en la dirección
  del cursor; justo después de una copia, recoloca las copias con esa
  separación. `3x` y `/3` siguen igual.

- **Clic derecho ▸ Seleccionar** (#106): todo lo
  conectado, aristas delimitantes, todo con el mismo material y todo en la
  misma capa. Actúa dentro del grupo que se está editando, como Seleccionar
  todo.
- **Ratón 3D (SpaceMouse de 3Dconnexion)** (#108): se sostiene el modelo
  (mover, subir, acercar, inclinar y girar la
  tapa). En Linux lo lee `spacenavd`; en Windows, Raw Input junto al
  controlador de 3Dconnexion. Los dos botones ajustan el modelo a la vista.
  Preferencias ▸ Ratón 3D: velocidad, invertir cada grupo y «solo desplazar
  y zoom» para dibujar en planta. Sin probar aún con un dispositivo real;
  macOS todavía no.

- **Pinzas de rotación en Mover** (#115): al pasar Mover
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
  Rodríguez): selecciona lo que no estaba seleccionado en
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
  hacia las esquinas, para que se
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
  Caeiro, #80): el dibujo conserva su escala, el borde nuevo
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
- **Un `.skp` vacío abre vacío** (#103): una plantilla `.skp` sin nada
  dibujado se mandaba al conversor externo, así que en Windows pedía
  instalarlo para abrir una hoja en blanco. Ahora abre y la barra de
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
- **Perspectiva de dos puntos** (José Castro Basso, FADU–UDELAR):
  **Cámara ▸ Perspectiva de dos puntos** mantiene verticales
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
    para editarla se hace única.
  - En **.skp** un grupo de grupos sale como grupo y sus
    subgrupos como grupos (comprobado con archivos de referencia). Los `.igz`
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
- **Orientar caras** (#77, @pacaeiro): clic derecho sobre
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
- **«Deshacer grupo» se llama ahora «Explotar»**: el
  nombre anterior se confundía con Deshacer.
- **Redondeo 3D daba «Conflicting cuts» en un cubo girado y aplastado**
  (#74, @pacaeiro). Al girar la pieza fuera de los ejes, las dos aristas de
  cada esquina calculaban el mismo punto con una milésima de milímetro de
  diferencia por redondeo numérico, justo lo que el programa tomaba como
  dos puntos distintos. Ahora redondea igual que el cubo recto, en
  cualquier orden de aristas.
- **Zoom extensión encuadra también las figuras** como el muñeco de escala:
  en un documento nuevo, donde
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

**Sólidos, ejes locales y Mac.** Las herramientas de sólidos
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
- **Ejes locales en grupos y componentes** (#44, @pacaeiro):
  cada grupo recuerda hacia dónde mira cuando se mueve, gira, escala,
  voltea, copia o explota, y se guarda en el `.igz`. Al entrar a editarlo
  se ven SUS ejes, en su origen, y la inferencia de eje, las flechas, el
  suelo, el rectángulo, círculos y arcos y las vistas estándar los siguen,
  nivel por nivel en grupos anidados. Crear grupo o componente dentro de
  uno girado sale alineado con él. El cuadro de selección y la caja de
  Escala se alinean a los ejes del objeto. Clic derecho ▸ **Cambiar ejes**
  (origen, rojo, verde) sin mover la geometría; en un componente cambia la
  definición y todas sus copias se quedan en su sitio.
- **Herramientas de sólidos** (pedidas por Rafael y en la
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
  caras — la forma clásica de recortar sin sólidos.
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

- **Rectángulo rotado con transportadores** (#70,
  @pacaeiro): uno en la primera esquina para la dirección de la primera
  arista (marcas cada 15° cerca del borde; el cuadro acepta `largo` o
  `largo;ángulo`) y otro perpendicular a esa arista para el ancho y su
  inclinación, que ahora se lee sobre el plano del transportador — antes
  solo salía tumbado (0°/180°) salvo cambiando la vista. Shift fija la
  inclinación. De paso, un ángulo tecleado en un documento en milímetros
  ya no se lee como longitud (`3;90` daba 0,09°).

### Cambiado
- **Alt alterna el cuentagotas de Pintar**:
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
deshacer, el scroll de las listas, Pintar con la regla de siempre
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
  cuartos). Las caras que bordean reciben los vértices
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
  que la dibujó**: una cara cerrada con Línea o el
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
  punto de partida, el «segmento guía» que él usa para
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
  tal como la describió: el material de una cara va por
  delante del del contenedor; solo las caras con el material por defecto
  visten el del grupo, por las dos caras; y al explotar, esas se quedan
  con él. El material del contenedor viaja en el `.igz`, sobrevive a
  copiar/pegar, y dos instancias del mismo componente pueden ir de
  colores distintos. El cuentagotas sobre una cara por defecto de un
  grupo pintado toma el color del grupo. Al exportar a `.skp` el material
  va en el grupo o la instancia. Pendiente: las
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
  clic ya empieza el desfase. Una cadena recta se
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
  Lo decide dónde tiras la línea de cota: en escuadra
  con el segmento, alineada; pasado un extremo hacia un lado, la vertical
  (la extensión en Y); por encima o por debajo, la horizontal (en X); y en
  3D lo mismo con Z. La vista previa ya enseña cuál va a salir y el texto
  mide lo que corresponde. Viaja en el .igz (`axis`); los documentos
  anteriores no cambian. Y el segundo punto ya no se queda pegado a la cara
  bajo el cursor cuando vas casi por un eje: el imán lo sube al eje.
- **El Transportador soltaba todo menos el bloqueo de plano al
  recargarlo** (issue #48, @pacaeiro: «define a Hard Axis (Z) and Reload
  the command (Shift+H) — the Hard Axis keeps active»). Volver a pulsar
  Shift+H con la herramienta en la mano es el «empezar de nuevo»
  y ahora suelta también la flecha; Esc igual.
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
  líneas de referencia se estiran desde sus vértices.
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
editable** letra a letra, y una inferencia nueva: la
ventana de la pared de al lado **a la altura** de la primera. Y de propina,
la issue #34 de @pacaeiro sobre los snaps bajo bloqueo, cazada el mismo día
con el arnés recién ampliado — sexto punto ciego que le encuentra a esa red.
Marco probó cada fase en vivo antes de cerrarla («me encanta»).

### Añadido
- **Cámara de paseo: Situar cámara, Caminar y Mirar alrededor**, las
  tres herramientas de paseo (Rafael, 13:00: «pasitos» para mirar los interiores),
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
  ocultan (Marco: «también puedes ocultar caras»); sus
  aristas se quedan.
- **Cámara ▸ Objetos ocultos / Geometría oculta**, los dos interruptores
  de siempre: lo oculto se dibuja como una **rejilla transparente** (las
  aristas, punteadas) y vuelve a poder seleccionarse, que es el camino a
  **Edición ▸ Mostrar ▸ Seleccionado** y al «Mostrar» del clic derecho.
  Los dos interruptores viajan en el documento y en las escenas.
- **Cambiar de capa donde se busca** (Rafael, 39:00: «no sé cómo cambiar
  el objeto de capa… las propiedades… botón derecho… no lo veo»). **Info
  de entidad** tiene ahora el campo **Capa**: muestra la de la
  selección («(varias)» si mezcla) y elegir otra la mueve. El **clic
  derecho** gana un submenú **Capa** con las del documento, la actual
  marcada, y «Capa nueva…». El botón **Asignar selección** del panel de
  capas hace lo mismo y, cuando no hay capa marcada o nada seleccionado,
  lo dice en vez de callar (es lo que le «funcionó a la segunda»). Los
  tres caminos pasan por un mismo comando con deshacer, y una capa que no
  existe se crea al asignarla.
- **Posicionar textura: un transportador en el pin verde**
  (Rafael, 04:30: «te bloquea a los 0, a los 45 y a los 90… si
  no es un poco a ojo»; Marco trajo capturas y una grabación, y se calcó
  fotograma a fotograma). Al arrastrar el pin verde aparece sobre el pin
  rojo el pequeño transportador azul: el disco con el brazo
  de partida cruzándolo, la cuña del ángulo barrido, un cuadradito en
  cada brazo, la línea punteada del brazo actual que atraviesa el pin
  verde y sigue, y el ángulo en la caja de medidas. El giro se pega a
  pasos de 15° desde donde empezó (0, 15, 30, 45… 90: los 0/45/90 de
  Rafael están entre ellos), esté el cursor donde esté; Ctrl mientras
  arrastras lo deja libre («Ctrl = Sin ajuste»).
- **Texto 3D: cada letra es un grupo, y el texto se
  edita.** El texto llega como un componente con un grupo por letra
  («que cada letra aparezca como grupo»), así que
  una letra se empuja, se pinta o se mueve sola: doble clic entra al texto
  como a cualquier grupo, y dentro, doble clic en la
  letra. Y el texto **sigue siendo texto**: clic derecho ▸ **Editar texto
  3D…** reabre el cuadro con lo que se escribió —texto, fuente, negrita,
  cursiva, altura, extrusión— y lo regenera en el mismo sitio, con el mismo
  giro y la misma escala. Deshacer lo devuelve como estaba. El `.igz`
  guarda los parámetros, así que un texto de hace un mes se reabre igual
  de editable. Rafael lo pidió sabiendo que es poco común.
  Y una salvaguarda: **si tocas una letra a mano** —la empujas, la pintas,
  la borras, la mueves sola— el texto pasa a ser geometría y «Editar texto
  3D…» se apaga con el motivo; regenerarlo habría tirado ese trabajo.
  Mover o girar el texto entero no cuenta.
- **Editar grupo** en el menú contextual: la misma
  puerta que el doble clic.
- **«A la altura del punto»: la ventana de la pared de al lado, a la misma
  altura que la primera** (Rafael, 02:20: «que la línea guía se extendiera
  por aquí y yo pudiera fijar la ventana aquí»). Memoriza la esquina de una ventana —el mouse quieto un
  instante encima— y ve a **otra pared**, perpendicular o la de enfrente:
  al pasar a su altura, el cursor se engancha a una línea punteada que
  recorre esa pared a esa altura, con el rótulo **A la altura del punto**.
  Dos guías llevan el ojo desde la esquina hasta el cursor: por su pared
  hasta la esquina del cuarto y desde ahí por la nueva, cada una del color
  de su eje. El «Desde el punto» clásico no lo hace porque es la LÍNEA
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
  bloqueos. Antes no hacía nada.
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
  «Invertir caras» del usuario no cambia: es el de siempre.
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
El lector de `.skp` pasa de nuestro fork a la versión oficial 1.3.0, y
con ella un modelo que llevaba tiempo sin abrir —`edificio.skp`, de
la versión 8— abre. Se midió archivo por archivo antes de dar el salto: 214
del corpus de Marco, 212 idénticos, uno rescatado, ninguno perdido, y el
`.skp` que exportamos sale igual, comprobado con archivos de referencia.
Lo demás son las cuatro issues que @pacaeiro abrió probando IngeTrazo,
y la vista en perspectiva que Marco pidió para sus
láminas.

### Añadido
- **Una lámina puede llevar una vista en PERSPECTIVA, con su propio sol.**
  Hasta ahora todo marco era paralelo: bueno para plantas y cortes, pero
  una isométrica no se ve «como en campo». El marco tiene ahora casilla de
  perspectiva con distancia de cámara y ángulo de visión, y sombras e hora
  propias, independientes del modelo. En perspectiva no hay escala, así que
  el rótulo dice «SIN ESCALA» en vez de inventar un 1:N.
- **Girar + Ctrl: «3x» y «/3» reparten copias en círculo** (issue #24). La
  matriz polar, hermana de la que Mover estrenó en la 0.4.2:
  con Ctrl pulsado, teclear `3x` deja tres copias a múltiplos del ángulo y
  `/3` tres que lo dividen. Re-teclear rehace la matriz y todo cabe en un
  solo deshacer.
- **Ctrl en la Cinta y el Transportador: medir, o medir Y marcar**
  (issue #29). En la Cinta, Ctrl recorre tres modos —líneas
  guía, puntos guía, medida sola— y los puntos guía son una entidad que no
  teníamos. En el Transportador alterna guía sí/no. Es un modo, no un
  modificador de un solo clic: se mantiene entre operaciones y vuelve a
  guías al recoger la herramienta, como el original. El `+` junto al cursor
  dice en cuál estás antes de hacer clic, y es toda la
  interfaz de este conmutador.
- **La barra de estado lleva los modificadores de la herramienta**, no solo
  su nombre: la Cinta muestra «Ctrl = [líneas guía] / puntos guía / medida»
  con el modo activo entre corchetes, y durante una operación aparece el
  «Alt = inferencias (…)» con su estado. Uno por fase
  — apilarlos no cabía en la barra.
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
  Con ella abre `edificio.skp`, de la versión 8, que caía en el lector de
  archivos grandes. Verificado sobre 214 archivos del corpus de Marco:
  212 idénticos, ese rescatado, ninguno perdido. El que queda no abre con
  ninguna de las dos versiones y no cuenta como corpus: es salida de
  nuestro propio exportador de cuando estaba roto. Y la exportación a `.skp`
  produce el mismo archivo comprobado con archivos de referencia (179 trozos, 35
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
  tiene sentido, y el conmutador dura esa operación y no la sesión.
  Se actúa en la PULSACIÓN y se traga la suelta: es la suelta la que hace
  que la barra de menús tome el foco, y por ahí se perdían cinco de cada
  seis toques.
- **Exportar ▸ `.skp` con un grupo clásico dentro de un contenedor** ya
  no revienta: sin matriz propia, la colocación es la identidad.
- **Una capa apagada en el archivo .skp llega apagada.** Se leía un atributo
  que no existe en openskp, así que todas entraban visibles.
- **Las guías quedan tapadas por la geometría que tienen delante**
  (issue #23), en vez de atravesarla.
- **El Transportador y Girar enseñan la inclinación mientras arrastras**
  (issue #25), no solo al soltar.

## [0.4.2] — 2026-09-16

**Lo que pidió Pedro Caeiro, y exportar a `.skp` otra vez.** @pacaeiro,
delineante, prueba IngeTrazo y anota cada gesto que
no responde como espera: aquí caen sus cuatro pendientes de inferencia y
herramientas. Y el arreglo que no podía
esperar: Exportar ▸ `.skp` moría en el .exe, el AppImage, el tar y el
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
- **El transportador se inclina con clic y arrastre** (issue #10):
  clic en el vértice y arrastre fijan el eje del instrumento a lo
  largo del arrastre, fuera de los planos ortogonales; el ángulo se mide y
  la guía se coloca en ese plano inclinado. Rotar ya tenía el gesto; ahora
  lo comparten. Un clic seco conserva el plano inferido.
- **Flecha «abajo»: el círculo perpendicular a una arista** (issue #10,
  segunda parte). El bloqueo magenta en el círculo, el
  polígono, el rectángulo, el rectángulo girado y los arcos: antes del
  primer clic, `↓` con el cursor sobre una arista fija el plano de dibujo
  perpendicular a ella, y sobre una cara, paralelo a ella; `↓` otra vez lo
  libera y una flecha de eje lo sustituye. El anillo del cursor se pinta
  magenta mientras dura. Es el flujo de las tuberías de Pedro: la línea
  inclinada del eje, `↓` sobre ella, centro en su extremo, radio y Sígueme,
  sin rotar el círculo después.

### Arreglado
- **Exportar ▸ `.skp` volvía «[Errno 2] No such file or directory:
  …\_internal\openskp\_scaffold\blank_v17.skp»** en el instalador de
  Windows, el AppImage, el tar y el snap (solo el Flatpak se salvaba).
  openskp escribe cada .skp sobre un andamio que carga como dato del
  paquete, y el empaquetado llevaba sus módulos pero no sus datos; roto
  desde la 0.3.5, reportado desde Windows con la 0.4.1. Ahora se incluyen
  los datos y el `--check` de cada paquete exige el andamio, así que la CI
  del release atrapa esta clase de olvido.
- **Mover y Rotar ya no infieren contra sí mismos** (issue #19). Lo que se
  está arrastrando o girando queda fuera de los candidatos del snap, así que arrastrar una
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

**La inferencia al día, el visor más rápido, y las tres
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
- **Redondear (fillet)**. Clic en una
  arista (o las aristas seleccionadas), mueve el cursor para fijar el radio o
  tecléalo, clic: la arista se convierte en una tira tangente a las dos caras;
  las tapas reciben el arco, las aristas encadenadas (el borde de una losa) se
  unen a inglete y en las esquinas de tres aristas (una caja) aparece el
  parche esférico. Cóncavas también. Lo que no se puede redondear lo dice y no
  toca el modelo. «Ns» fija los segmentos.
- **Posicionar textura** (clic derecho en una cara con imagen ▸ Textura ▸
  Posicionar): los cuatro pines — rojo mueve, verde escala y
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
- **Arco que redondea esquinas**: al empezar sobre una arista la
  vista previa es el arco tangente (cian, «Tangente a la arista»); en la arista
  contigua, a la misma distancia del vértice, se clava y se vuelve magenta;
  doble clic ahí dibuja el arco y **recorta la esquina sola**; doble clic
  cerca de otra esquina repite el mismo radio; Alt deja los tramos.
  «Semicírculo» en la fase de curvatura y «Ns» segmentos (también rehace el
  arco recién dibujado).
- **Inferencia**: rectángulo, círculo, polígono y arcos
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
- **Barra de estado más clara**: una sola pista para la herramienta y el
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
versión hace lo habitual: el modelo se queda en sus ejes y el que gira
es el mapa. Y llegan los tres primeros arreglos de un colaborador externo,
@pacaeiro, con sus issues: el bloqueo de eje con Shift, las guías
punteadas y los iconos grandes.

### Añadido
- **Norte del proyecto: el mapa gira bajo el modelo, no el modelo bajo el
  mapa.** En el panel Terreno/Mapa base, el campo **Norte** dice hacia dónde
  queda el norte verdadero, en grados en sentido horario desde el eje verde
  (0° = el verde apunta al norte; la convención habitual del norte solar).
  Al cambiarlo giran por debajo el mapa base, el terreno 3D, las
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
  Cinta de medir trazaba sus guías continuas, sin el punteado fino
  esperado. El lápiz siempre fue `Qt.DashLine`: lo que fallaba era la ESCALA.
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
grupos anidados, la pileta, el arco, la luminaria y
el campesino traídos de sus propios archivos como componentes, y las caras
con dos lados. Casi todo lo de abajo lo reportó Marco usándolo, con captura
o con el modelo vivo delante; el rendimiento se midió antes de publicar
(`scripts/bench_session.py`): +0,3 ms por cuadro, nada que se sienta.

### Añadido
- **Grupos anidados.** Un grupo puede contener grupos, y
  se entra a ellos por niveles: doble clic para bajar, Esc o clic afuera
  para subir uno, con la ruta a la vista en la barra de estado («Editando
  Plaza ▸ Jardinera ▸ Banca»). Dentro de un grupo, un clic selecciona a su
  HIJO —no al contenedor entero— y no se puede agarrar el resto del modelo.
  «Crear grupo» ya no se niega cuando hay grupos en la selección: los adopta,
  y la parte suelta pasa a ser la malla del contenedor.

  Hasta ahora entrar a un contenedor lo **horneaba**: sus hijos se fundían
  en una sola malla. Marco lo vivió con su plaza — nueve grupos convertidos
  en 17 577 caras de una sola pieza, perdiendo de paso los nueve chunks
  independientes y el instanciado. El modelo de datos ya sostenía el árbol
  desde agosto; lo que faltaba era la edición por niveles, y es esto.
- **Importar otro documento .igz como componente.** Archivo ▸ Importar ▸
  «Documento IngeTrazo como componente (.igz)…»: el archivo entero llega
  como UN componente que se coloca con un clic, como el Import de un .skp
  — la pérgola, el arco y la luminaria dibujados en sus propios
  archivos entran en la plaza con sus grupos (anidados, como estaban), sus
  materiales y sus capas. Se sostiene por su origen, así que las zapatas
  dibujadas bajo el suelo quedan bajo el suelo. Los face-me del archivo
  vienen con él (el torito sobre el arco); solo el muñeco de escala de la
  app se queda fuera. Un material cuyo nombre ya usa OTRA receta entra como
  «nombre (2)».
- **El .igz conserva los nombres de los grupos.** Nunca los escribía: cada
  documento reabierto renumeraba sus grupos y una «Pérgola» volvía como
  «Group 7» (pendiente conocido). Los nuevos no repiten un número guardado.
- **Inferencia «Centro».** Al pasar el cursor por la
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
  que queda detrás, y sigue sin poderse seleccionar. Con
  «Ocultar» el resto del modelo, lo que no se dibuja tampoco atrae al
  cursor.

- **Las caras tienen dos lados, y se pinta el que se clica.**
  El cubo pinta el lado bajo el cursor, y el otro conserva el
  color de reverso del estilo (el azul grisáceo que delata una cara al
  revés). Un material translúcido —cristal, agua, una malla raschel, una
  hoja calada— se ve igual por los dos lados.
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
  copias. Se escribió como una mejora en junio; usándolo en obra
  resultó ser lo contrario, porque el modelo cambia donde no apuntaste
  (Marco, 2026-09-10). Ahora la cara de un grupo cerrado ni se sombrea al
  pasar por encima —sombrearla es prometer un empuje que no va a ocurrir— y
  el clic responde diciendo qué hacer: abrir el grupo con doble clic y
  empujar adentro. Dentro del grupo no cambia nada, incluido que
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
  deshacible. Nació de un import de `.skp` del que se borró casi todo: las
  capas del dibujo grande seguían ahí cuando ya no quedaba ni una cara suya.
  Las capas vuelven a su posición original al deshacer, no al final de la
  lista.
- **Tinte de textura**: cambiarle el color a un material texturizado, como un
  colorize. Tono y saturación del color elegido sobre la
  luminosidad de la imagen; el original se guarda al lado, así que se puede
  cambiar el tinte cuantas veces se quiera o quitarlo. Viaja dentro del
  `.igz`.
- **El tercer paso del rectángulo rotado es anchura Y ÁNGULO**, como el
  transportador: con la base tumbada, escribir `3;90` levanta el
  rectángulo de pie. Era la única forma de dibujar un rectángulo
  perpendicular y no estaba.
- **Equidistancia hacia adentro de verdad.** Al meterse hacia adentro de una
  forma cóncava hay segmentos que se cruzan y desaparecen; el trazado ingenuo
  los conservaba y salía un nudo. Ahora la forma se reconstruye con el motor
  de arreglo planar: lo que colapsa se elimina, y si la figura se parte en
  dos —una U estrecha— salen las dos piezas.
- **Invertir caras en el menú del botón derecho.** Estaba solo en el menú
  Edición, que no es donde se busca: va sobre la propia cara.

### Corregido
- **Tres teclas no hacían nada: `H`, `O` y `F2`.** Lo reportó `@pacaeiro`
  (PR #11): el Transportador y Desplazar compartían la `H`. Cuando dos
  acciones de la misma ventana piden el mismo atajo, Qt no elige una — lo
  marca ambiguo y **no dispara ninguna**, así que la tecla queda muerta
  para las dos. Al medirlo aparecieron dos más del mismo molde: `O` la
  peleaban el Arco por centro y Orbitar, y `F2` estaba registrada dos
  veces, una por el botón de la barra y otra por la entrada del menú
  Cámara. Ahora las teclas de cámara son las habituales — Orbitar `O`,
  Desplazar `H`, Zoom `Z` y **Zoom a extensión `Mayús+Z`**, que aquí
  faltaba (`F2` sigue valiendo). Las dos herramientas que
  cedieron su tecla quedan en `Mayús+H` el Transportador y `Mayús+O` el Arco por
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
- **`P` es Empujar/Tirar** (pedido de Marco). Era `U`, y
  la `P` estaba gastada en alternar perspectiva/paralela. La `U` no se tira: sigue valiendo como segundo
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
  Blender o FreeCAD — y al revés que el propio encuadre de
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
de la cota que se arrastra, la línea de terreno, el fondo
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
- **El texto de la cota se mueve.** Se arrastra con el
  ratón agarrándolo por las letras y se queda donde lo dejes; la línea
  de cota no se mueve (arrastrar la línea sigue moviendo la cota entera).
  En el panel, «A lo largo de la línea» lo pone sobre el centro, fuera
  del inicio o fuera del final (el texto al lado de la cota, a izquierda
  o derecha), y «Devolver el texto a su sitio» deshace el arrastre. Un
  texto centrado solo abre la línea cuando está en su sitio automático
  (Marco, 2026-09-08: «me refería al lado de la cota, ya sea derecho o
  izquierdo; es más, en otros programas se puede mover el texto de la
  cota»). Además, «Posición del texto» gana «al costado de la línea» y
  «al otro costado»: la etiqueta entera a un lado de la línea sin
  cruzarla, útil en cotas verticales con texto horizontal.
- **Las flechas fijan el plano de dibujo del círculo, polígono,
  rectángulo y arcos**: antes del primer clic, → fija
  el plano normal a X (YZ), ← el normal a Y (XZ), ↑ el normal a Z (XY);
  la misma flecha otra vez lo libera y Esc también. Una etiqueta arriba a
  la izquierda, del color del eje, lo indica. La figura gasta el
  bloqueo, y tras el primer clic las flechas vuelven a ser el bloqueo de
  eje de siempre (Marco, 2026-09-08: «quiero dibujar un círculo en el
  plano ZX… en otros programas me restringe a qué plano quiero dibujar apretando
  las teclas de desplazamiento»).
- **Shift fija en horizontal o vertical el segundo punto de una cota** (y
  de una línea, flecha, línea de terreno o el siguiente punto de una cota
  en cadena): el Orto de AutoCAD. Gana el
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
  regla de AutoCAD. Mayús alterna, Ctrl añade, Mayús+Ctrl
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
- **Mayús+clic ahora quita de la selección** (pedido de
  Marco: «debería haber una opción para deseleccionar ciertas líneas o
  planos»). Con la herramienta Seleccionar, **Mayús+clic alterna** lo que
  toca — una arista o cara ya seleccionada sale de la selección, una que
  no lo estaba entra —, **Ctrl+clic añade** siempre y **Mayús+Ctrl+clic
  quita** siempre. La caja de selección lee los mismos modificadores, y un
  clic con modificador en el vacío ya no borra la selección que estabas
  armando (antes Mayús solo sumaba y no había forma de descartar algo sin
  empezar de cero).

## [0.3.12] — 2026-09-05

**La release de las láminas profesionales y del `.skp` que se puede
guardar.** Una sesión entera sobre la lámina real de la pileta de Yanque:
el estilo vectorial dibuja con tres plumas y rellena los cortes, el marco
lleva rótulo numerado, la planta marca por dónde va cada sección, y llegan
las cotas de nivel, las cotas en cadena, las llamadas de detalle y las
fotos en círculo con borde desvanecido. Por debajo, el exportador `.skp`
que el programa de destino abre, muestra con las texturas en su sitio y **guarda** — con
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
  perfil (siluetas y contornos contra el fondo, los «perfiles»)
  o arista entre dos caras, y cada clase sale con su pluma (0,50 / 0,35 /
  0,18 mm por defecto, ajustables por marco en el panel). Donde el plano de
  sección corta un sólido cerrado, el marco rellena el corte (sólido o
  achurado a 45°, color y paso configurables); las superficies abiertas
  quedan en blanco. Las cuerdas colineales del corte se fusionan en una
  sola línea y las verticales vistas de canto ya no dejan puntos. La
  exportación DXF de la vista reparte las clases en capas `VISTA`,
  `VISTA-PERFIL` y `VISTA-CORTE` para la tabla de plumas de IngeCAD.
- **Rótulo de vista profesional.** El título del marco (antes una línea
  centrada «Planta — 1:100») tiene ahora tres estilos: el de burbuja
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
  desaparecían al abrirlo. Ahora salen como componentes en la convención del
  formato (pies en el origen, frente hacia −Y, colocados en su ancla) y, si
  el escritor de openskp lo admite, con el comportamiento «siempre mirar a la
  cámara»; con el escritor actual quedan de pie mirando a −Y.
- **Las aristas ocultas viajan al `.skp`.** El exportador nunca marcaba una
  arista como oculta, así que el programa de destino dibujaba un marco negro alrededor de
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
  definición colocada N veces. La piscina baja de 70 a
  27 MB con las mismas caras en los mismos sitios.
- **Solo viajan las capas en uso.** Al guardar el archivo en el programa de destino, Purgar
  tiraba 8 de las 10 capas de la piscina, todas vacías, y la capa por
  defecto de IngeTrazo ya es la «Layer0» del formato. El resto del ahorro
  que se ve al volver a guardarlo es el formato comprimido: nuestros archivos
  llevan las mismas caras, definiciones y texturas.

### Corregido
- **Compositor: la selección sobrevive a cada cambio del panel.** Cambiar la
  escala, el ancho o un campo del cajetín deseleccionaba el marco y había que
  volver a clicarlo para el siguiente ajuste: el auto-render reconstruía el
  lienzo y la selección vivía en los ítems que se destruían. Ahora la
  reconstrucción recuerda qué modelos estaban seleccionados y los vuelve a
  seleccionar.
- **Un `.skp` exportado ya se puede GUARDAR.** Los archivos abrían bien
  pero cualquier intento de guardarlos acababa
  en «Guardado fallido». El escritor de openskp numeraba los identificadores
  persistentes de cada sección desde 1 y dejaba corto el contador de la
  cabecera, así que el lector encontraba duplicados al cargar, los renumeraba
  y luego no podía serializar el modelo. Cazado con archivos de referencia a partir de un caso
  mínimo (una definición de 1 cara seguida de otra de 3). El escritor del fork
  numera en una sola secuencia (arreglo propuesto a upstream); mientras tanto
  IngeTrazo corrige el contador del archivo al guardar y escribe las figuras
  al final, con lo que la pileta y la piscina se guardan.
### Corregido
- **Las texturas de un `.skp` exportado se ven donde IngeTrazo
  las dibujó.** Tres causas, cazadas comparando con archivos de
  referencia. Dos están en el escritor de openskp y se compensan hasta
  que upstream las arregle (una sonda lo comprueba en cada exportación): la
  matriz de cada cara pineada se escribía en la base «primera arista» y
  el formato la lee en la base «Z × normal», así que cada cara salía girada el
  ángulo de su primera arista (el tronco de la palmera, miles de caras, hecho
  añicos); y los UV pineados no se multiplicaban por el tamaño aplicado del
  material, que el lector divide al leer, así que una textura de 2 m salía 78
  veces más grande (el agua de la pileta, un azul plano). La tercera era de
  IngeTrazo: la proyección por defecto del visor usaba otra base que la del
  formato y en muros que miran a +Y o −X la textura se veía girada 180°
  respecto de lo que sale en el archivo. Ahora hay una sola receta
  (`core.texture.projection_basis`, la del formato) para el visor, los
  exportadores OBJ/glTF/DAE, la vista previa de pegar y el importador.
- **Un `.skp` exportado ya no muestra caras lavanda.** IngeTrazo
  pinta las dos caras de una superficie y el formato solo la que nombra el
  archivo, así que toda cara vista desde atrás (las bancas, el bajo del
  techo, las hojas de la palmera) salía con el color de reverso por defecto.
  Ahora el reverso lleva el mismo material y la misma posición de textura
  que el frente, o el suyo propio cuando la cara venía pintada distinta por
  cada lado.
- **Las caras horizontales ya no salen con la textura girada 90°.**
  La base de proyección del formato (Z × normal) es discontinua
  justo en la vertical, y la normal de una cara horizontal calculada en
  float32 traía un ruido de hasta 6e-4 que la mandaba a la base equivocada
  (Marco: encimeras, pisos y losas de la piscina). Medido con archivos de referencia:
  el formato usa los ejes del mundo mientras la inclinación es menor que 1e-3.
  Ahora la receta única usa esa misma tolerancia, la normal de cada cara se
  acumula en doble precisión y el exportador expresa los pins contra el
  plano que el propio escritor guarda en el archivo.
  Y las caras que miran hacia abajo (el bajo de losas, bancas y encimeras)
  salían 180° giradas: el formato les da la base (−X, +Y), no la (X, −Y) que
  asumía el lector; medido igual y corregido en la misma receta.

## [0.3.11] — 2026-09-04

**Release de Windows y de intercambio.** Todo lo que salió al probar la
0.3.10 en la máquina de un amigo de Marco: un `.igz` con texturas que no
abría, un `.skp` exportado que no abría, el visor arrastrándose
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
- **El `.skp` exportado por la 0.3.10 no abría cuando una
  textura venía de la caché con nombre apilado.** Mismo origen que el fallo
  de Windows: el nombre de 250 caracteres caía en la carpeta temporal, la
  ruta superaba el límite de 255 del escritor de openskp y este fallaba con
  la imagen ya escrita a medias; el «respaldo a color» se escribía encima y
  el archivo entero quedaba ilegible. Ahora cada textura se
  copia a una carpeta temporal con su nombre corto antes de entregarla al
  escritor, la ruta de tu máquina ya no viaja dentro del `.skp`, y una
  imagen ilegible pasa a color sin tocar el escritor. Las texturas BMP, TIFF
  o GIF (las que traen los modelos `.skp` importados) se reconvierten a
  PNG en vez de perderse.
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
programa, y cualquier modelo con una figura «face-me» de malla (la Susan de los
`.skp`) dejaba el visor en blanco. Además entra todo lo trabajado desde
entonces sobre las láminas y el modelado de Marco.

### Añadido
- **Componentes: editas uno, cambian todos.** Entrar en una copia de un
  componente (doble clic) edita su definición compartida: al salir, el
  cambio llega a todas las copias, y toda la sesión se deshace en un solo
  paso. Empujar/Tirar sobre una copia desde fuera también edita la
  definición. Para cambiar una sola copia, antes: clic derecho ▸ Hacer
  único. Mirar dentro y salir sin tocar nada no cambia nada.
- **Medidas en pulgadas y pies junto a metros**: `2"`, `2in`,
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
  figura «face-me» de malla (la Susan y similares, importadas
  del .skp): al dibujarla faltaba una coordenada del ancla y el pintado
  fallaba en cada frame. Se veían las etiquetas y los ejes, nada más.
- **El zoom «se trababa» cerca del modelo**: con la distancia de órbita en
  su mínimo (2 cm), acercar no hacía nada y alejar retrocedía milímetros
  por muesca hasta un Zoom extensión. Ahora alejar retrocede al menos un
  1 % del tamaño del modelo por muesca y acercar sigue deslizando la vista
  hacia el punto del cursor.
- **Una línea dibujada sobre la cara de un grupo no se podía seleccionar**:
  el clic siempre tomaba el grupo. La línea visible gana
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
reales de la pileta de Yanque: el compositor se puso a la altura de un programa de láminas
profesional, y Sígueme también.

### Añadido
- **Sígueme: arrastra y ve la extrusión.** Haz clic en el
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
- **La sesión de láminas del compositor.** Auto-render de los marcos cuando el
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
- **Anotaciones con capa** en el modelo (cotas y textos guía), :
  una capa «Anotaciones» oculta en una escena da el modelo
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
  oculta TU lado: lo que hay detrás queda hasta que lo metes
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
  perpendicular al perfil y consume el perfil.
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
  ahora mide la distancia proyectada en el plano de la vista.
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
probó en vivo antes de darse por buena.

### Añadido
- **Sombras con el sol de verdad.** No una luz de adorno: la posición solar
  se calcula con las ecuaciones de la NOAA para la geolocalización del
  modelo (o Arequipa si no tiene), por fecha y hora — un **estudio de
  asoleamiento**, el entregable que otros cobran. Panel de Sombras:
  fecha con slider del año por meses, hora acotada de
  amanecer a atardecer (imposible dejar el sol bajo el horizonte sin darse
  cuenta), oscuridad, zona horaria automática por longitud, y «Añadir
  localización…» sobre el mapa. Las reglas finas también son las
  habituales: **el vidrio (opacidad <70 %) no proyecta**, los personajes 2D
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
- **Escalar**: el cajón amarillo con agarraderas por esquina
  (uniforme), arista (2 ejes) y cara (1 eje), Ctrl desde el centro, Shift
  uniforme, factor negativo para espejar, y el VCB acepta factor, `a;b` por
  eje o medida absoluta con unidad.
- **Ocultar/mostrar aristas** (Edición y clic derecho), con **Mayús+goma**
  para ocultar de pasada.
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
  OpenSKP normalized what a coedge's flag carries — the file's raw storage
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
the file gave it inside itself, which is what makes the files we write
small again — and, hunting that through a real modelling session, three
long-standing freezes fell with it.

### Added
- **Nested placements**: a group owns placements of shared prototype
  meshes, drawn, picked, saved and exported as part of it — one object
  to you, however deep the tree. An imported component no longer arrives
  flattened, so a hedge stored as 9600 faces placed 48 times stays that
  way instead of becoming 230400 real ones.
- **Eyedropper parity (Paint ▸ Alt)**: sampling a face now carries its
  material to the next click — image, applied
  size, rotation, translucency and the material identity. A face with an
  explicit world→UV map hands it on only within its own plane, where it
  keeps the pattern lined up; a face on another plane takes the material
  with its own projection at the same size (copying the map across
  planes smeared the image into stripes). The pointer becomes an
  eyedropper while Alt is down.

### Fixed
- **`.skp` files were five times too big.** Saving Marco's pool wrote
  80 MB against the original's 14. Not textures (6.7 MB embedded there
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

**Sections, the tool parity batch, AI modelling, and the performance
marathon** — a full real-world modelling session (a 280k-face pool
project) hunted down every freeze it hit.

### Added
- **Section planes** (complete): place the active
  cut with hover plane inference (arrow keys / Shift to lock), one
  active cut per context, GPU-clipped model with **thick cut edges**,
  **section fill**, corner symbol balloons and the Sections toolbar.
  Sections move/rotate/delete like geometry, reverse and "Align View"
  from the context menu, picks and snaps ignore the clipped side, and
  scenes + `.igz` remember the active cut. The composer's hidden-line
  pass clips too and draws the cut chords — real plans and sections on
  sheets.
- **Tool parity batch**: **Flip** (2023-style axis planes,
  Ctrl = flip a copy, classic context-menu entries), **Make Component**
  (G, shared definitions + Make Unique), **Freehand** (sampled,
  RDP-simplified, selects as one contour), **Pie** arc (closes the
  wedge with a face) and chord bulge / radius suffixes in the
  Measurements box. "Offset" is now **Equidistancia** (the usual
  Spanish name).
- **AI Assistant** (Extensions menu): chat with an AI provider from
  inside IngeTrazo — provider picker with per-provider API key and
  model memory; every AI edit lands as ONE undoable command with full
  rollback on failure. Plus the **AI Bridge (MCP)**: model with Claude
  from outside the app over the Model Context Protocol.
- **Native glTF/GLB import** (PBR materials mapped to the paint
  system).
- **Starter components and textures**: CC0/CC-BY sedan, oak, bush and
  a scale figure standing at its real offset; texture library
  additions (bark, rock, river pebbles, lawn, concrete pavers, water);
  glass paints translucent end-to-end (library → paint → face).
- Drawing axes recalibrated (fine-dot negative
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
upload, every drag/hover frame is a translated MVP — smooth
dragging of a 230k-face group) · Merge Groups fuses group-to-group
without the loose-mesh detour · one Newell per face on edit frames ·
group copies go through the bulk-weld pass · **pasting a huge classic
group stamps an O(1) sibling of the clipboard prototype** (component
semantics: copies share the definition until edited) — stamping the
230k-face group went from ~12 s to instant, rotating a pasted copy
from seconds to 0.1 s.

## [0.3.4] — 2026-08-25

**The dogfooding release: a real modelling session's bug hunt, plus
tool-parity work.** Everything here came from drawing an actual
model and comparing, tool by tool, against the expected behaviour.

### Added
- **Display styles** (Camera → Style), scoped to what
  serves printing: Default, Architectural (textures on white), Shaded
  (materials as their texture's average colour), Hidden line (the plan
  style), Monochrome, Wireframe and X-ray — plus Edges/Profiles toggles.
  Scenes remember their style; `.igz` persists it.
- **Composer frames pick any style** (per-frame viewports): each
  sheet frame can render in any of the styles above, the model's active
  style, or the exact vector hidden-line pass.
- **Copy/paste for groups and components** (Ctrl+C/X/V, context menu):
  instances paste as siblings of the same prototype; attrs (colours,
  textures, layers, BIM tags) travel; positioned textures re-anchor to
  the paste point. Paste previews the SOLID model — colours and
  textures riding under the cursor — and stamps once, returning to
  Select.
- **Protractor rebuilt**: plane
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

**The complete `.skp` round trip.** IngeTrazo now writes native `.skp`
(File → Export → `.skp`) and opens Marco's entire 13-year real-project
corpus — 186 of 186 files, 2013–2026 — natively. Annotations travel BOTH
ways: dimensions and leader texts drawn in IngeTrazo appear in the `.skp`,
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
  decoded byte-exact against reference files with known values ("Rosetta"
  files) and human-drawn corpus records.
- **Material registry** — materials have NAMES that survive editing:
  painting keeps identity, right-click a named swatch to edit-and-restamp
  every use, Model Info reports per-material quantities (m²), and OBJ/DAE/
  glTF/SKP exports carry the real names (`Concreto_visto`, not `mat0`).
- **Leader-text lifecycle**: select by clicking the text itself (glyphs
  outrank geometry), move with the anchor pinned (leader stretches, live
  preview), edit on double-click, delete with
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
  the format's default material instead of turning white.
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
  whether the optional external converter is present. CI gates the
  bundle, the AppImage and the extracted tarball on it.
- `core/paths.py` (`app_root()`): the six runtime resource lookups that
  derived paths from `__file__` now go through it, so a frozen build fails
  loudly at `--check` instead of at first shader load if the bundle layout
  ever drifts.

### Changed
- Composer: big models no longer freeze the sheet tools.
- Repository references updated from `tuxiasumari/ingetrazo` to
  `ingelibre/ingetrazo` (About dialog, tile-fetcher user agents, and the
  external converter's download URL, which only worked through GitHub's rename
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
    label re-measured (the exact 3D distance). Placement:
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

Native pure-Python `.skp` import for ALL `.skp` eras (our OpenSKP fork:
VFF walker + legacy MFC parser), validated for exact parity on real
models; the external converter becomes an emergency fallback only. See the GitHub
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
  `.igz` (native), `.dae` (COLLADA) and `.skp`. On Linux a
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

Open `.skp` files directly: File ▸ Import ▸ `.skp`…

### Added
- **Direct `.skp` import** through an optional external converter — run as
  a separate process, never part of IngeTrazo. The `.dae` and its texture folder land next to the `.skp`, then the
  existing COLLADA importer takes over (groups, components, textures,
  face-me sprites). On Linux the converter runs via Wine.
- **One-click converter install**: if the external converter is missing,
  the import dialog offers to download it separately. No terminal required.
  It is not bundled with IngeTrazo.

### Fixed
- `.skp` files stored under accented paths (`Imágenes`, `ñ`…) failed with a
  UTF-8 decode error — Wine re-encodes command-line arguments to the
  Windows ANSI codepage. The conversion now routes through an ASCII
  temporary path and tolerates any output encoding.

## [0.2.0] — 2026-07-15

The BIM release: the IFC bridge to IngePresupuestos is validated end to end,
`.skp` models migrate with textures and components, the terrain workflow
takes real field data — and the UI grew into its own skin.

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

### Bring your models
- **COLLADA (.dae) import with real textures**: per-face UV maps from the
  file's TEXCOORDs, texture-tolerant coplanar fusion (no dirty
  triangulations), representative colours when the image folder is missing.
- **The original group structure survives**: one Group per assembly (a plaza
  imports as 291 groups, not one blob) — click selects the lamppost, not
  the world; edit by entering the small group.
- **Components import as shared instances**: one prototype mesh, N
  transforms (16 instances/6 prototypes saved 59k faces on a real nursery
  project; import went 24.7 → 10.8 s).
- **Face-me sprites recovered**: the cutout people/trees exported
  without the flag turn toward the camera again, with proper
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
  clicked edge's length, face's area, or point coordinates;
  occluded leaders, selectable, saved in `.igz`.
- **3D Text**: real extruded geometry from any system font — one watertight
  solid per letter (counters preserved), smooth thickness, glued to the
  face under the cursor (a relief sign on a wall, text lying on a slab).
- **Hi-res image export** (File ▸ Export ▸ Image): the current view at any
  pixel width through the exact render pipeline, presentation overlays
  included — 4K sheets straight from the program.
- **Component placement with the cursor**: inserts follow the mouse and
  settle on the ground plane (or any face you point at); Esc discards.

### UI
- Menu bar reorganized: **Archivo · Edición · Cámara ·
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

The first release. A usable, free, Linux-first 3D modeler for
civil engineering and architecture — draw → model → tag → take off → export.

### Modeling engine
- Shared-vertex non-manifold topology engine: sticky
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
- Import: COLLADA `.dae` (components, Y-up/inches
  conversion), OBJ (+MTL colours), KML/GeoJSON.
- Export: IFC4, STL (3D printing), OBJ (+MTL, textures with UVs).

### Experience
- Bilingual UI (English source, full Spanish), movable
  icon toolbars, QGIS-style panels (Properties | BIM | Georef tabs),
  sky/ground horizon, paper-white maquette shading with face culling,
  infinite dashed axes.
- Scale figure: the author himself (1.65 m) as a face-me billboard cutout,
  plus generic 2D/3D people, tree, bush, car components — and "insert your
  own transparent PNG at real height".
- Desktop launcher + icon installer (`scripts/install_desktop.sh`);
  the icon is the author's mark: his tri-blade wrapped around the cube.

[0.1.0]: https://github.com/tuxiasumari/ingetrazo/releases/tag/v0.1.0
