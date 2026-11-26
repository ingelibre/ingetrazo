# AI Bridge — modelar con Claude (MCP)

*[English](ai-bridge.md) · Español (original)*

IngeTrazo puede ser dirigido por un agente de IA (Claude Code, Claude
Desktop) mediante el [Model Context Protocol](https://modelcontextprotocol.io):
el agente dibuja, consulta y **ve** el modelo en vivo — y cada acción suya
es un paso de undo transaccional (si su código falla, el documento se
revierte entero; el guard de hermeticidad valida sus recetas).

## Uso

1. En IngeTrazo: pestaña **IA** de la barra lateral ▸ sección **Puente IA
   (MCP)** ▸ **Encender puente** (o **Extensiones ▸ Puente IA (MCP)**, que
   abre esa sección y lo enciende) — arranca un servidor local (solo
   127.0.0.1) con un puerto libre asignado automáticamente. Enciéndelo en
   **cada ventana** que quieras compartir con el agente. **Detener puente**
   deja de compartir únicamente esa ventana.
2. Al encenderlo, la sección muestra, con un botón Copiar, las líneas exactas para
   tu sistema (botón **Copiar**). No hace falta tener Python instalado: el
   paquete lleva el servidor MCP.

   | Instalación | Comando del servidor MCP |
   |---|---|
   | Windows (instalador o zip) | `C:\Program Files\IngeTrazo\ingetrazo-mcp.exe` |
   | Linux AppImage / tarball / Flatpak / snap | `<ejecutable de IngeTrazo> --mcp` |
   | Desde el repositorio | `python3 /ruta/a/app/scripts/ingetrazo_mcp.py` |

   **Claude Code** (en una terminal):

       claude mcp add ingetrazo -- "C:\Program Files\IngeTrazo\ingetrazo-mcp.exe"

   **Claude Desktop**: pega esto en su archivo de configuración
   (`%APPDATA%\Claude\claude_desktop_config.json` en Windows,
   `~/.config/Claude/claude_desktop_config.json` en Linux) y reinicia
   Claude Desktop:

       {
         "mcpServers": {
           "ingetrazo": {
             "command": "C:\\Program Files\\IngeTrazo\\ingetrazo-mcp.exe",
             "args": []
           }
         }
       }

   Si Claude no responde: comprueba que IngeTrazo sigue abierto con el
   puente encendido (la sección Puente IA (MCP) dice «Escuchando en…»),
   que la ruta del comando existe, y en Claude Desktop que el servidor
   aparece en Configuración ▸ Desarrollador ▸ MCP sin error.
3. Registra el servidor MCP **una sola vez**. Pídele que empiece con
   `list_documents`, identifique el archivo y utilice su `document_id` en
   cada llamada: *"en edificio.igz, dibuja una casita de 6×4 m con techo a
   dos aguas, agrúpala y píntala de ladrillo; muéstrame cómo quedó"*.

### Varias ventanas y documentos

Abre otra ventana con **Archivo ▸ Nueva ventana**, también en Flatpak.
Este menú ya inicia otro proceso con `--new-window`; un lanzamiento normal
entrega el archivo a la ventana existente. El puente no cambia esa conducta.

Un solo servidor MCP descubre todas las ventanas con el puente encendido.
`list_documents` devuelve `document_id`, `instance_id`, PID, nombre, ruta
completa (o `null` si no está guardado), título, estado `dirty` y revisión.
La ruta y el ID distinguen dos archivos que tengan el mismo nombre.

```python
list_documents()
query_model(document_id=id_edificio)
query_model(document_id=id_terreno)
run_python(document_id=id_edificio, code="print(len(groups))")
screenshot(document_id=id_edificio)
undo(document_id=id_edificio)
```

Todas las herramientas de documento exigen `document_id`: **no existe una
ventana activa o predeterminada para el agente**. Nueva ventana, Nuevo y
Abrir crean identidades nuevas; incluso reabrir el mismo archivo invalida
el ID anterior (`open_document` devuelve el nuevo). Guardar o Guardar como conservan el ID. Al cambiar de
documento se descartan las variables Python de la conversación anterior.
Cada documento mantiene su propia historia de undo.

Si una ventana se cierra, detiene el puente o cambia de documento, las
llamadas al ID anterior fallan sin actuar sobre otra ventana. El agente
debe volver a `list_documents` y elegir el destino. Una petición cuya
respuesta se pierde **no se repite automáticamente**: pudo haberse
ejecutado, así que hay que consultar el estado antes de volver a editar.

La detección usa registros de endpoints en una carpeta privada del usuario,
sin guardar allí nombres ni contenidos de archivos:

| Sistema | Carpeta predeterminada |
|---|---|
| Linux, incluido Flatpak | `~/.local/state/ingetrazo/ai-bridges` |
| Windows | `%LOCALAPPDATA%\\IngeTrazo\\ai-bridges` |
| macOS | `~/Library/Application Support/IngeTrazo/ai-bridges` |

`INGETRAZO_AI_REGISTRY` permite compartir otra carpeta entre la aplicación
y el servidor MCP. Las instrucciones copiadas usan la ruta absoluta del
registro publicado, aunque la carpeta se configurase con una ruta relativa.
Los registros desaparecen al detener el puente o cerrar la ventana, incluso
si cambia el directorio de trabajo de la aplicación; los endpoints que dejó
un proceso caído se omiten al consultar. Las capturas PNG viajan en la
respuesta, sin un archivo temporal común.

Después de actualizar desde el puente de un solo documento, reinicia o
reconecta el servidor MCP para recargar las herramientas. Las llamadas
antiguas sin `document_id` se rechazan.

### El agente dentro de un contenedor (Docker, WSL2)

El puente escucha **solo en `127.0.0.1`** de la máquina donde corre
IngeTrazo, y así se queda: no tiene contraseña y `run_python` ejecuta
código dentro de la aplicación, de modo que abrirlo a la red dejaría el
modelo (y el equipo) a merced de cualquiera en ella.

Escuchar en local no basta frente al navegador del mismo equipo: una página
web puede mandar un `POST` al puente (`http://127.0.0.1:<puerto>`) sin que el navegador
pida permiso (`fetch` con `mode: "no-cors"` y cuerpo de texto). Por eso el
puente corta la conexión en la primera línea que no es una petición JSON —
la primera línea de cualquier petición HTTP es `POST / HTTP/1.1` — y el
cuerpo nunca llega a leerse. Aun así, **detén el puente cuando no lo uses**.

- **Misma red y carpeta compartida**: con `--network host` (por ejemplo,
  IngeTrazo en WSL2 con WSLg), monta también la carpeta de registros en el
  contenedor. Apunta `INGETRAZO_AI_REGISTRY` a ese montaje en el servidor
  MCP; debe ver los mismos registros que la aplicación. Compartir solo
  `127.0.0.1` no basta para descubrir las ventanas.
- **Un endpoint reenviado**: para un túnel explícito, puedes fijar el puerto
  de una ventana arrancándola con `INGETRAZO_AI_PORT=4763`. Reenvía ese
  puerto (`ssh -L 4763:127.0.0.1:4763 usuario@equipo`, `socat`…) y configura
  el servidor MCP:

      INGETRAZO_AI_HOST=host.docker.internal INGETRAZO_AI_PORT=4763 \
          python3 /ruta/a/app/scripts/ingetrazo_mcp.py

  Con `INGETRAZO_AI_PORT` configurado con un puerto distinto de cero en el
  servidor MCP, `list_documents` consulta **solo ese endpoint**, aprende su
  identidad y sigue exigiendo `document_id`. Sin esa variable, o con valor
  `0`, se descubren todas las ventanas locales; en la aplicación, `0` pide
  un puerto libre automático. `INGETRAZO_AI_HOST` solo cambia el destino del
  túnel explícito; el puente nunca deja de escuchar únicamente en local.
  Las instrucciones copiadas incluyen el registro publicado y el puerto
  explícito, si se ha configurado.

## Herramientas expuestas

Hay dos maneras de trabajar. Con `run_python` el agente escribe recetas de
Python sobre el documento. Las **herramientas con nombre** tienen un
esquema y no ejecutan código, así que un cliente que no permita
`run_python` puede trabajar igual. Cada una llama a una orden del puente
que reutiliza lo mismo que usan los menús: los mismos importadores y
exportadores, el panel de escenas, la cámara y el compositor. Hay una sola
herramienta para cada trabajo.

Reglas comunes:

- Lo que cambia el documento (importar, pintar, mostrar u ocultar capas)
  es **un paso de deshacer**, como `run_python`. La cámara, la selección
  y la escena mostrada son la vista, no el documento: quedan fuera del
  historial, como en la aplicación.
- Las rutas de archivo deben ser **absolutas** (se acepta `~`). Una ruta
  relativa se rechaza.
- Nadie está frente a la pantalla para responder un diálogo: el puente lo
  cancela, y si el paso falló, el error repite lo que decía.
- Sin OpenGL, `screenshot`, `export_view`, `render_sheet` y `export_pdf`
  con vistas renderizadas devuelven un error que explica el motivo. Nunca
  se cuelgan.

| Herramienta | Qué hace | Ejemplo de argumentos |
|---|---|---|
| `list_documents` | Ventanas compartidas y metadatos de sus documentos vivos; no necesita un ID. Es la primera llamada (#892). | `{}` |
| `run_python` | Ejecuta Python sobre el documento vivo (scope: `scene`, `mesh`, `selection`, `groups`, `bim`, `QVector3D`… y los constructores `revolve(perfil)` / `extrude(contorno, z0, z1)`: una línea → un grupo sólido, suave y orientado). Un undo por llamada; rollback total si falla. | `{"code": "extrude([(0,0),(4,0),(4,3),(0,3)], 0, 2.5, name='Caseta')"}` |
| `query_model` | Conteos, nombres de grupos/componentes, materiales, capas, bounds. | `{}` |
| `document_info` | `instance_id` y `document_id` del documento (tras `open_document`, los del nuevo), ruta, si tiene cambios sin guardar (`modified`), formato de guardado, láminas, escenas y qué está permitido (`saving_allowed`, `shutdown_allowed`). | `{}` |
| `get_scene_info` | Lo de `query_model` y `document_info` más las escenas, las láminas (con su número del cajetín), las capas con su visibilidad, la georreferencia y si puede renderizar. Es la primera tras `list_documents`. | `{}` |
| `get_object_info` | Un grupo o componente por nombre o identificador: caja (mín., máx., tamaño), capa, material, hijos y etiqueta BIM (IFC). | `{"name": "Caseta"}` o `{"id": "3f2a9c0d1e4b5a67"}` |
| `list_layers` | Las capas: nombre, visible, bloqueada, carpeta; y la activa. | `{}` |
| `set_layer_visibility` | Muestra u oculta capas (un paso de deshacer). | `{"layers": ["Mobiliario"], "visible": false}` |
| `list_scenes` | Las escenas guardadas y la que se muestra. | `{}` |
| `show_scene` | Muestra una escena como un clic en su fila: cámara, capas, estilo y objetos ocultos. | `{"name": "Planta"}` |
| `set_camera` | Vista estándar (`top`, `bottom`, `front`, `back`, `left`, `right`, `iso`) o `eye`/`target` (Z arriba, metros); proyección `perspective`, `parallel` o `two_point`; `fov` en grados; `zoom_extents` encuadra todo. | `{"view": "iso", "zoom_extents": true}` o `{"eye": [20, -15, 8], "target": [0, 0, 1], "projection": "perspective"}` |
| `select` | Selecciona grupos o componentes por `names` o `ids` (`mode`: `replace`, `add`, `remove` o `toggle`), o vacía la selección con `clear`. | `{"names": ["Banca 1", "Banca 2"]}` o `{"clear": true}` |
| `screenshot` | Renderiza la vista. El agente la mira e itera; con `path` guarda además el PNG (o JPG) ahí. `view` (una vista estándar) y `fit` (encuadrar todo el modelo) apuntan la cámara solo para esta imagen y dejan la vista del usuario como estaba. | `{"width": 1280, "height": 720}` |
| `export_view` | Renderiza una escena guardada a PNG y el agente la mira; con `path` la guarda ahí. La vista del usuario (cámara, capas, estilo, ocultos) vuelve a como estaba y un documento guardado sigue guardado. | `{"view": "Vista 3D", "path": "/home/ana/obra/vista.png"}` |
| `render_sheet` | PNG de una lámina, pintado por el compositor como su exportación de imagen. La lámina se indica por nombre, por número del cajetín (`L-02`) o por posición (1 = la primera); `width` en píxeles o `dpi`. | `{"sheet": "L-02", "width": 1600}` |
| `export_pdf` | Las láminas (todas, o las de `sheets`: nombre, número del cajetín o posición) a un solo PDF. | `{"path": "/home/ana/obra/plaza.pdf"}` o `{"path": "/home/ana/obra/L-02.pdf", "sheets": ["L-02"]}` |
| `open_document` | Abre un documento (`.igz`, `.dae`, `.skp`, `.dxf`, `.dwg`) en lugar del que está al frente. Si ese tiene cambios sin guardar, devuelve un error y no muestra el diálogo «¿guardar cambios?», salvo con `discard_changes`. | `{"path": "/home/ana/obra/plaza.igz"}` |
| `save_document` | Guarda el documento; con `path` (un `.igz`), lo guarda como ese archivo; `format`: `auto` o `json`. **Solo si el usuario lo permite** (ver abajo). | `{}` o `{"path": "/home/ana/obra/plaza-v2.igz", "format": "json"}` |
| `import_file` | Importa al documento (un paso de deshacer): `.igz` (como componente), `.dae`, `.glb`/`.gltf`, `.skp`, `.obj`, `.stl`, `.dxf`, `.dwg`. `unit` (`m`, `cm`, `mm`, `in`, `ft`) para OBJ, STL y DXF; `make_faces` para DXF/DWG. | `{"path": "/home/ana/muebles/banca.obj", "unit": "cm"}` |
| `export_file` | Exporta el modelo según la extensión: `.ifc` (los objetos etiquetados en BIM), `.glb`, `.dae`, `.stl` (`unit`, por defecto mm), `.obj` y `.dxf` (las líneas de la vista). `selection_only` para GLB. Las láminas van con `export_pdf` y las imágenes con `screenshot`, `export_view` y `render_sheet`. | `{"path": "/home/ana/obra/plaza.ifc"}` |
| `list_materials` | Los materiales del documento: nombre, color, textura, opacidad. | `{}` |
| `apply_material` | Pinta con un material del documento los objetos nombrados (`names`/`ids`) como un todo, o si no, la selección. Un paso de deshacer. | `{"material": "Ladrillo", "names": ["Muro norte"]}` |
| `undo` / `redo` | La historia de siempre. | `{}` |
| `shutdown` | Cierra un IngeTrazo sin ventana arrancado con `--allow-shutdown`. Con cambios sin guardar se niega, salvo con `discard_changes`. | `{}` |

Salvo `list_documents`, todas requieren `document_id`. Sin puentes activos,
la lista está vacía y las operaciones indican cómo encender el puente y
volver a descubrir los documentos. Cada ventana ejecuta las peticiones en
su hilo principal de Qt, acepta una conexión a la vez y solo escucha en
localhost.

La exportación a IFC usa el exportador actual. La ida y vuelta de IFC sin
pérdidas llegará en la 0.6.4.

**Guardar desde el agente** está apagado por defecto: en la ventana, la
casilla **Permitir que el agente guarde el documento** de la sección Puente
IA (MCP); sin ventana, `--allow-save`. Sin permiso, el agente puede cambiar
el modelo pero nunca el archivo. (Recuerda que `run_python` ejecuta código
dentro de la aplicación: el permiso evita accidentes, no es una barrera de
seguridad.)

## Sin ventana: automatización y control de versiones

IngeTrazo puede correr **sin ventana** para que un agente trabaje un
documento de principio a fin — por ejemplo en un runner de CI que abre un
`.igz` de un repositorio Git, deja que Claude haga cambios, guarda y abre
un pull request para revisarlo.

    ingetrazo --headless --ai-bridge --open Casa.igz \
              --allow-save --save-format json --allow-shutdown \
              --port 0 --ready-file puerto.txt

La forma corta `ingetrazo --server [Casa.igz] [--port N] [opciones…]` es
lo mismo que `--headless --ai-bridge --open Casa.igz`: el mismo modo, con
las mismas opciones y códigos de salida.

| Opción | Qué hace |
|---|---|
| `--headless` | Ninguna ventana en pantalla (la vista se sigue dibujando en una ventana oculta). Ningún diálogo espera respuesta: todos se cancelan. |
| `--ai-bridge` | Enciende el puente (solo 127.0.0.1). |
| `--open ARCHIVO` | Abre el documento. **Si no se puede abrir, IngeTrazo termina al instante** con el código 3, antes de encender el puente. |
| `--port N` | Puerto del puente (por defecto `INGETRAZO_AI_PORT`, si no uno libre, publicado para que el servidor MCP lo descubra; `0` = uno libre). |
| `--ready-file RUTA` | Escribe ahí el puerto cuando el documento ya está abierto y el puente escucha (también se imprime `INGETRAZO_BRIDGE_PORT=<n>`, y en la salida de errores una línea que dice si hay OpenGL). |
| `--allow-save` | El agente puede usar `save_document`. |
| `--save-format auto\|json` | Cómo se guarda: `auto` (como siempre) o `json` (ver abajo). |
| `--allow-shutdown` | El agente puede usar `shutdown`. Solo por línea de comandos. |
| `--exit-on-stdin-eof` | Termina (código 5) cuando se cierra su entrada estándar: para un proceso padre que podría morir. |

Sin ventana no se hacen copias `.igz.bak` ni copias de recuperación al
guardar: el historial es Git. No usa la instancia única, así que un
IngeTrazo abierto no se entera.

**Códigos de salida**

| Código | Significa |
|---|---|
| 0 | El agente llamó a `shutdown` — el único final limpio. |
| 2 | Línea de comandos incorrecta. |
| 3 | El documento de `--open` no se pudo abrir. |
| 4 | El puente no pudo escuchar (puerto ocupado…). |
| 5 | Terminó de otra forma: señal (`Ctrl+C`, SIGTERM), entrada estándar cerrada… |

En Windows, un proceso terminado desde fuera (`TerminateProcess`) sale con
el código que pone quien lo mata (1 con `Popen.terminate`) — nunca 0.

**OpenGL.** `screenshot`, `export_view` y las láminas con vistas
renderizadas necesitan un contexto OpenGL. El resto de las herramientas
funciona sin él. Si no hay contexto, la línea de la salida de errores lo
dice y esas herramientas devuelven un error que explica el motivo. Las
láminas dibujadas solo con líneas (estilo vectorial) se renderizan igual.
En Linux sin pantalla (un contenedor, una sesión ssh), el modo sin ventana
elige solo la plataforma `offscreen`. Con ella, OpenGL depende de los
controladores de la máquina. Para tener GL seguro:

- **Xvfb**, una pantalla virtual:

      xvfb-run -a -s "-screen 0 1920x1080x24" ingetrazo --server plaza.igz

  o, a mano: `Xvfb :99 -screen 0 1920x1080x24 &` y luego
  `DISPLAY=:99 QT_QPA_PLATFORM=xcb ingetrazo --server plaza.igz`.
- **En un escritorio**: `QT_QPA_PLATFORM=xcb ingetrazo --server …` usa la
  pantalla real sin mostrar la ventana. También puedes abrir IngeTrazo
  normalmente, minimizarlo y encender el puente desde la pestaña IA.
- En Windows y macOS, el modo sin ventana usa la pantalla del sistema sin
  mostrar la ventana.

**Llamadas lentas.** Una llamada puede ocupar IngeTrazo 180 segundos; luego
el agente recibe `timed out on the UI thread`. Exportar las láminas de un
modelo grande dibujado por software (un contenedor con Mesa llvmpipe) puede
tardar más: define `INGETRAZO_AI_TIMEOUT` (segundos) para IngeTrazo y para
el servidor MCP, que espera 30 segundos más que el puente.

### Un solo comando para el cliente MCP

El servidor MCP puede arrancar su propio IngeTrazo sin ventana: no hace
falta tener IngeTrazo abierto antes.

    claude mcp add ingetrazo-headless -- ingetrazo --mcp --headless \
        --open /ruta/Casa.igz --allow-save --save-format json --allow-shutdown

(En Windows: `ingetrazo-mcp.exe --headless --open …`; desde el repositorio:
`python3 scripts/ingetrazo_mcp.py --headless --open …`.) El servidor busca
un puerto libre, espera a que el documento esté abierto y cierra su
IngeTrazo cuando el cliente se va. Si el documento no abre, el servidor
termina con el mismo código (3) sin llegar a servir. Tras un `shutdown`,
termina con 0.

### Ejemplo de runner

Cuando el script necesita el código de salida, conviene arrancar IngeTrazo
aparte y apuntar el servidor MCP normal a su puerto:

    ingetrazo --headless --ai-bridge --open Casa.igz --allow-save \
        --save-format json --allow-shutdown --port 0 \
        --ready-file /tmp/puerto &
    PID=$!
    while [ ! -s /tmp/puerto ]; do
        kill -0 $PID 2>/dev/null || { wait $PID; exit $?; }   # no abrió
        sleep 0.2
    done
    INGETRAZO_AI_PORT=$(cat /tmp/puerto) claude -p \
        "Añade una ventana de 1×1 m en el muro sur, guarda y llama a shutdown" \
        --mcp-config ingetrazo-mcp.json --allowedTools "mcp__ingetrazo__*"
    wait $PID || exit 1                     # 0 solo si el agente terminó bien
    git checkout -b ia/ventana-sur && git add Casa.igz Casa.assets
    git commit -m "Ventana sur (Claude)" && gh pr create --fill

### Formato JSON plano

Con **Preferencias ▸ General ▸ Formato de guardado ▸ JSON plano** (o
`--save-format json`) el `.igz` es siempre texto JSON con sangría, sea cual
sea su tamaño, así que `git diff` muestra qué cambió. Las imágenes
(texturas, el levantamiento fotogramétrico) no caben en texto: van a una
carpeta junto al documento, `Casa.assets/`, que hay que versionar con él.
Una imagen que ya no se usa se borra de esa carpeta al guardar; lo demás que
haya en ella no se toca. Es un `.igz` de formato 1 con la marca
`"layout": "plain-json"`: un documento abierto con esa marca **se sigue
guardando en JSON plano** aunque el formato elegido sea Automático, para que
no se convierta en ZIP en el repositorio; pedir otro formato por su nombre
(`save_document(format="auto")`) sí lo cambia. El JSON plano no lleva
la miniatura del modelo para el gestor de archivos (un PNG que cambia en
cada guardado sería ruido en cada diff). Los formatos de siempre (1, 2
y 3) no cambian: **Automático** sigue siendo el valor por defecto. Un modelo muy
grande en JSON plano ocupa más y abre más despacio que en el formato
automático.

## Asistente IA (dentro de la app)

Para el usuario que no usa Claude Code: la pestaña **IA** de la barra
lateral (Ctrl+Shift+A la trae al frente, aunque esté oculta) es un chat
DENTRO de IngeTrazo. Pega tu clave API — el
proveedor se detecta solo por el prefijo, la convención de IngePresupuestos:

| Prefijo | Proveedor | Modelo por defecto |
|---|---|---|
| `sk-ant-` | Anthropic | claude-sonnet-5 |
| `gsk_` | Groq (gratis) | llama-3.3-70b-versatile |
| `sk-or-` | OpenRouter | anthropic/claude-sonnet-5 |
| `AIza` | Gemini | gemini-2.5-flash |
| `sk-` | OpenAI | gpt-4o |
| *(vacía)* | Ollama local | qwen2.5-coder:7b |

Escribe qué quieres ("dibuja una casa de 6×4 con techo a dos aguas") y el
asistente actúa por recetas de Python transaccionales — cada acción es un
paso de undo, y con proveedores con visión recibe capturas del viewport
para VER lo que construyó e iterar. El modelo es editable, y la clave se
guarda en la configuración local.

### Modelar desde una foto

Con el botón **Foto…** adjuntas la imagen de un objeto (una fuente, un
mueble, una fachada) y el asistente la interpreta y lo recrea por partes,
cada una como grupo con nombre, comparando sus capturas contra la foto.
Dale las medidas reales en el mensaje ("la taza mide 4 m de diámetro, el
alto total 2,30") — una foto no trae dimensiones, y lo que el asistente
estime del ojo lo declara como supuesto para que lo corrijas. La foto se
reescala a 1280 px y viaja como JPEG solo en ese mensaje. Necesita un
proveedor con visión (Anthropic, OpenAI, Gemini, OpenRouter).
