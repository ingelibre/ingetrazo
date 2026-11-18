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
   127.0.0.1, puerto 4763; `INGETRAZO_AI_PORT` lo cambia). **Detener
   puente** lo apaga.
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
3. Pídele cosas: *"dibuja una casita de 6×4 m con techo a dos aguas,
   agrúpala y píntala de ladrillo; muéstrame cómo quedó"*.

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

- **IngeTrazo dentro de WSL2** (AppImage o `.tar.gz` con WSLg) y el
  contenedor con `--network host`: funciona tal cual, porque comparten
  `127.0.0.1`.
- **En cualquier otro caso**, lleva el puerto hasta el agente con un túnel
  que tú controlas (`ssh -L 4763:127.0.0.1:4763 usuario@equipo`, `socat`…)
  y dile al cliente MCP dónde está el otro extremo:

      INGETRAZO_AI_HOST=host.docker.internal INGETRAZO_AI_PORT=4763 \
          python3 /ruta/a/app/scripts/ingetrazo_mcp.py

  `INGETRAZO_AI_HOST` (por defecto `127.0.0.1`) solo cambia a dónde se
  conecta el cliente; el puente no deja de escuchar únicamente en local.

## Herramientas expuestas

| Tool | Qué hace |
|---|---|
| `run_python` | Ejecuta Python sobre el documento vivo (scope: `scene`, `mesh`, `selection`, `groups`, `bim`, `QVector3D`… y los constructores `revolve(perfil)` / `extrude(contorno, z0, z1)`: una línea → un grupo sólido, suave y orientado). Un undo por llamada; rollback total si falla. |
| `query_model` | Conteos, nombres de grupos/componentes, materiales, capas, bounds. |
| `screenshot` | Renderiza el viewport real — el agente mira e itera. |
| `undo` / `redo` | La historia de siempre. |
| `document_info` | Ruta del documento, si tiene cambios sin guardar, formato de guardado, láminas, escenas y qué está permitido. |
| `open_document` | Abre un archivo; error si no se pudo. |
| `save_document` | Guarda (en su ruta o en otra `.igz`, `format`: `auto` o `json`). **Solo si el usuario lo permite** (ver abajo). |
| `export_view` | Una escena (vista guardada) a PNG; la cámara vuelve a donde estaba. |
| `export_pdf` | Las láminas (todas o las nombradas) a un PDF. |
| `shutdown` | Cierra un IngeTrazo sin ventana arrancado con `--allow-shutdown`. |

Sin el puente encendido, las tools responden con el aviso de cómo
encenderlo. El servidor acepta un cliente a la vez y nunca escucha fuera
de localhost.

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

| Opción | Qué hace |
|---|---|
| `--headless` | Ninguna ventana en pantalla (la vista se sigue dibujando en una ventana oculta). Ningún diálogo espera respuesta: todos se cancelan. |
| `--ai-bridge` | Enciende el puente (solo 127.0.0.1). |
| `--open ARCHIVO` | Abre el documento. **Si no se puede abrir, IngeTrazo termina al instante** con el código 3, antes de encender el puente. |
| `--port N` | Puerto del puente (por defecto `INGETRAZO_AI_PORT` o 4763; `0` = uno libre). |
| `--ready-file RUTA` | Escribe ahí el puerto cuando el documento ya está abierto y el puente escucha (también se imprime `INGETRAZO_BRIDGE_PORT=<n>`). |
| `--allow-save` | El agente puede usar `save_document`. |
| `--save-format auto\|json` | Cómo se guarda: `auto` (como siempre) o `json` (ver abajo). |
| `--allow-shutdown` | El agente puede usar `shutdown`. Solo por línea de comandos. |
| `--exit-on-stdin-eof` | Termina (código 5) cuando se cierra su entrada estándar: para un proceso padre que podría morir. |

Sin ventana no se hacen copias `.igz.bak` al guardar: el historial es Git.

**Códigos de salida**

| Código | Significa |
|---|---|
| 0 | El agente llamó a `shutdown` — el único final limpio. |
| 2 | Línea de comandos incorrecta. |
| 3 | El documento de `--open` no se pudo abrir. |
| 4 | El puente no pudo escuchar (puerto ocupado…). |
| 5 | Terminó de otra forma: señal, entrada estándar cerrada… |

En Windows, un proceso terminado desde fuera (`TerminateProcess`) sale con
el código que pone quien lo mata (1 con `Popen.terminate`) — nunca 0.

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
(`save_document(format="auto")`) sí lo cambia. Los formatos de siempre (1, 2
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
