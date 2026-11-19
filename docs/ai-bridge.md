# AI Bridge — modelar con Claude (MCP)

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
el ID anterior. Guardar o Guardar como conservan el ID. Al cambiar de
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
web puede mandar un `POST` a `http://127.0.0.1:4763` sin que el navegador
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
exportadores, el panel de escenas, la cámara y el compositor.

Reglas comunes:

- Lo que cambia el documento (importar, pintar, mostrar u ocultar capas)
  es **un paso de deshacer**, como `run_python`. La cámara, la selección
  y la escena mostrada son la vista, no el documento: quedan fuera del
  historial, como en la aplicación.
- Las rutas de archivo deben ser **absolutas**. Una ruta relativa se
  rechaza.
- Nadie está frente a la pantalla para responder un diálogo: el puente lo
  cancela, y si el paso falló, el error repite lo que decía.
- Sin OpenGL, `screenshot`, `render_sheet` y las exportaciones que
  necesitan una imagen devuelven un error que explica el motivo. Nunca se
  cuelgan.

| Herramienta | Qué hace | Ejemplo de argumentos |
|---|---|---|
| `list_documents` | Ventanas compartidas y metadatos de sus documentos vivos; no necesita un ID. Es la primera llamada (#892). | `{}` |
| `run_python` | Ejecuta Python sobre el documento vivo (scope: `scene`, `mesh`, `selection`, `groups`, `bim`, `QVector3D`… y los constructores `revolve(perfil)` / `extrude(contorno, z0, z1)`: una línea → un grupo sólido, suave y orientado). Un undo por llamada; rollback total si falla. | `{"code": "extrude([(0,0),(4,0),(4,3),(0,3)], 0, 2.5, name='Caseta')"}` |
| `query_model` | Conteos, nombres de grupos/componentes, materiales, capas, bounds. | `{}` |
| `get_scene_info` | Lo de `query_model` más el archivo, si hay cambios sin guardar, las escenas, las láminas (con su número del cajetín), las capas con su visibilidad, la georreferencia y si puede renderizar. Es la primera tras `list_documents`. | `{}` |
| `get_object_info` | Un grupo o componente por nombre o identificador: caja (mín., máx., tamaño), capa, material, hijos y etiqueta BIM (IFC). | `{"name": "Caseta"}` o `{"id": "3f2a9c0d1e4b5a67"}` |
| `list_layers` | Las capas: nombre, visible, bloqueada, carpeta; y la activa. | `{}` |
| `set_layer_visibility` | Muestra u oculta capas (un paso de deshacer). | `{"layers": ["Mobiliario"], "visible": false}` |
| `list_scenes` | Las escenas guardadas y la que se muestra. | `{}` |
| `show_scene` | Muestra una escena como un clic en su fila: cámara, capas, estilo y objetos ocultos. | `{"name": "Planta"}` |
| `set_camera` | Vista estándar (`top`, `bottom`, `front`, `back`, `left`, `right`, `iso`) o `eye`/`target` (Z arriba, metros); proyección `perspective`, `parallel` o `two_point`; `fov` en grados; `zoom_extents` encuadra todo. | `{"view": "iso", "zoom_extents": true}` o `{"eye": [20, -15, 8], "target": [0, 0, 1], "projection": "perspective"}` |
| `select` | Selecciona grupos o componentes por `names` o `ids` (`mode`: `replace`, `add`, `remove` o `toggle`), o vacía la selección con `clear`. | `{"names": ["Banca 1", "Banca 2"]}` o `{"clear": true}` |
| `screenshot` | Renderiza la vista. El agente la mira e itera. Con `scene` renderiza esa escena y deja la vista del usuario como estaba; con `path` guarda además el PNG ahí. | `{"width": 1280, "height": 720, "scene": "Vista 3D"}` |
| `render_sheet` | PNG de una lámina, pintado por el compositor como su exportación de imagen. La lámina se indica por nombre, por número del cajetín (`L-02`) o por posición (1 = la primera); `width` en píxeles o `dpi`. | `{"sheet": "L-02", "width": 1600}` |
| `open_file` | Abre un documento (`.igz`, `.dae`, `.skp`, `.dxf`, `.dwg`) en lugar del que está al frente. Si ese tiene cambios sin guardar, devuelve un error y no muestra el diálogo «¿guardar cambios?», salvo con `discard_changes`. | `{"path": "/home/ana/obra/plaza.igz"}` |
| `save_file` | Guarda el documento; con `path` (un `.igz`), lo guarda como ese archivo. | `{}` o `{"path": "/home/ana/obra/plaza-v2.igz"}` |
| `import_file` | Importa al documento (un paso de deshacer): `.igz` (como componente), `.dae`, `.glb`/`.gltf`, `.skp`, `.obj`, `.stl`, `.dxf`, `.dwg`. `unit` (`m`, `cm`, `mm`, `in`, `ft`) para OBJ, STL y DXF; `make_faces` para DXF/DWG. | `{"path": "/home/ana/muebles/banca.obj", "unit": "cm"}` |
| `export_file` | Exporta según la extensión: `.ifc` (los objetos etiquetados en BIM), `.glb`, `.dae`, `.stl` (`unit`, por defecto mm), `.obj`, `.dxf` (las líneas de la vista), `.pdf` (una lámina con `sheet`, o todas) y `.png`/`.jpg` (la vista, `width`). `selection_only` para GLB. | `{"path": "/home/ana/obra/plaza.ifc"}` o `{"path": "/home/ana/obra/L-02.pdf", "sheet": "L-02"}` |
| `list_materials` | Los materiales del documento: nombre, color, textura, opacidad. | `{}` |
| `apply_material` | Pinta con un material del documento los objetos nombrados (`names`/`ids`) como un todo, o si no, la selección. Un paso de deshacer. | `{"material": "Ladrillo", "names": ["Muro norte"]}` |
| `undo` / `redo` | La historia de siempre. | `{}` |

Salvo `list_documents`, todas requieren `document_id`. Sin puentes activos,
la lista está vacía y las operaciones indican cómo encender el puente y
volver a descubrir los documentos. Cada ventana ejecuta las peticiones en
su hilo principal de Qt, acepta una conexión a la vez y solo escucha en
localhost.

La exportación a IFC usa el exportador actual. La ida y vuelta de IFC sin
pérdidas llegará en la 0.6.4.

## Modo servidor (sin ventana)

    ingetrazo --server [archivo.igz] [--port N]

Arranca IngeTrazo **sin mostrar la ventana principal**, abre el archivo si
se indica y enciende el puente. Cuando está listo, escribe en la salida de
errores una línea como esta:

    IngeTrazo server ready on 127.0.0.1:4763 — plaza.igz

`--port 0` toma un puerto libre, que aparece en esa línea. Sin `--port`,
se usa `INGETRAZO_AI_PORT` o, si no está definida, 4763. `Ctrl+C`
(SIGINT) o SIGTERM lo cierran limpio, sin preguntar nada: guarda antes
con `save_file` lo que quieras conservar. El modo servidor no usa la instancia única, así que un
IngeTrazo abierto no se entera, y no escribe en la configuración del
usuario nada que la aplicación normal no escriba.

Desde el repositorio: `python3 main.py --server plaza.igz`. Luego conecta
el cliente MCP de siempre (`ingetrazo --mcp`, `ingetrazo-mcp.exe` o
`scripts/ingetrazo_mcp.py`) al mismo puerto (`INGETRAZO_AI_PORT`).

**OpenGL.** La captura y las láminas con vistas renderizadas necesitan un
contexto OpenGL. El resto de las herramientas funciona sin él. Si no hay
contexto, la línea «ready» lo dice y esas herramientas devuelven un error
que explica el motivo. Las láminas dibujadas solo con líneas (estilo
vectorial) se renderizan igual. En Linux sin pantalla (un contenedor, una
sesión ssh), el modo servidor elige solo la plataforma `offscreen`. Con
ella, OpenGL depende de los controladores de la máquina. Para tener GL
seguro:

- **Xvfb**, una pantalla virtual:

      xvfb-run -a -s "-screen 0 1920x1080x24" ingetrazo --server plaza.igz

  o, a mano: `Xvfb :99 -screen 0 1920x1080x24 &` y luego
  `DISPLAY=:99 QT_QPA_PLATFORM=xcb ingetrazo --server plaza.igz`.
- **En un escritorio**: `QT_QPA_PLATFORM=xcb ingetrazo --server …` usa la
  pantalla real sin mostrar la ventana. También puedes abrir IngeTrazo
  normalmente, minimizarlo y encender el puente desde la pestaña IA.
- En Windows y macOS, el modo servidor usa la pantalla del sistema sin
  mostrar la ventana.

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
