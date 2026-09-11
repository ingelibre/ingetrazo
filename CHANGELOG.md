# Changelog

All notable changes to IngeTrazo are documented here.
Format inspired by [Keep a Changelog](https://keepachangelog.com); versions
follow [SemVer](https://semver.org).

## [Sin publicar]

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
