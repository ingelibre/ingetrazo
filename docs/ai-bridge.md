# AI Bridge — modelling with Claude (MCP)

*English · [Español](ai-bridge.es.md)*

IngeTrazo can be driven by an AI agent (Claude Code, Claude
Desktop) through the [Model Context Protocol](https://modelcontextprotocol.io):
the agent draws, queries and **sees** the model live — and every action it
takes is one transactional undo step (if its code fails, the whole document
is rolled back; the watertightness guard validates its recipes).

## Usage

1. In IngeTrazo: the sidebar's **AI** tab ▸ **AI bridge (MCP)** section ▸
   **Start bridge** (or **Extensions ▸ AI bridge (MCP)**, which
   opens that section and starts it) — this launches a local server (only
   127.0.0.1, port 4763; `INGETRAZO_AI_PORT` changes it). **Stop
   bridge** shuts it down.
2. Once it is running, the section shows the exact lines for
   your system, with a **Copy** button. You do not need Python installed: the
   package ships the MCP server.

   | Installation | MCP server command |
   |---|---|
   | Windows (installer or zip) | `C:\Program Files\IngeTrazo\ingetrazo-mcp.exe` |
   | Linux AppImage / tarball / Flatpak / snap | `<IngeTrazo executable> --mcp` |
   | From the repository | `python3 /path/to/app/scripts/ingetrazo_mcp.py` |

   **Claude Code** (in a terminal):

       claude mcp add ingetrazo -- "C:\Program Files\IngeTrazo\ingetrazo-mcp.exe"

   **Claude Desktop**: paste this into its configuration file
   (`%APPDATA%\Claude\claude_desktop_config.json` on Windows,
   `~/.config/Claude/claude_desktop_config.json` on Linux) and restart
   Claude Desktop:

       {
         "mcpServers": {
           "ingetrazo": {
             "command": "C:\\Program Files\\IngeTrazo\\ingetrazo-mcp.exe",
             "args": []
           }
         }
       }

   If Claude does not respond: check that IngeTrazo is still open with the
   bridge running (the AI bridge (MCP) section says "Listening on…"),
   that the command path exists, and, in Claude Desktop, that the server
   shows up under Settings ▸ Developer ▸ MCP without an error.
3. Ask it for things: *"draw a 6×4 m little house with a gable roof,
   group it and paint it brick; show me how it turned out"*.

### The agent inside a container (Docker, WSL2)

The bridge listens **only on `127.0.0.1`** of the machine where IngeTrazo
runs, and it stays that way: it has no password and `run_python` executes
code inside the application, so opening it to the network would leave the
model (and the computer) at the mercy of anyone on it.

Listening locally is not enough against a browser on the same machine: a web
page can send a `POST` to `http://127.0.0.1:4763` without the browser
asking for permission (`fetch` with `mode: "no-cors"` and a text body). That is
why the bridge drops the connection on the first line that is not a JSON
request — the first line of any HTTP request is `POST / HTTP/1.1` — and the
body is never read. Even so, **stop the bridge when you are not using it**.

- **IngeTrazo inside WSL2** (AppImage or `.tar.gz` with WSLg) and the
  container with `--network host`: works as is, because they share
  `127.0.0.1`.
- **In any other case**, bring the port to the agent through a tunnel
  you control (`ssh -L 4763:127.0.0.1:4763 user@host`, `socat`…)
  and tell the MCP client where the other end is:

      INGETRAZO_AI_HOST=host.docker.internal INGETRAZO_AI_PORT=4763 \
          python3 /path/to/app/scripts/ingetrazo_mcp.py

  `INGETRAZO_AI_HOST` (default `127.0.0.1`) only changes where the client
  connects to; the bridge still listens on localhost only.

## Exposed tools

There are two ways to work. With `run_python` the agent writes Python
recipes against the document. The **named tools** have a schema and run no
code, so a client that does not allow `run_python` can still work. Each one
calls an order of the bridge that reuses what the menus use: the same
importers and exporters, the Scenes panel, the camera and the composer.
There is one tool for each job.

Common rules:

- What changes the document (importing, painting, showing or hiding
  layers) is **one undo step**, like `run_python`. The camera, the
  selection and the scene shown are the view, not the document: they stay
  out of the history, as in the app.
- File paths must be **absolute** (`~` is accepted). A relative path is
  refused.
- Nobody is at the screen to answer a dialog: the bridge cancels it, and if
  the step failed, the error repeats what it said.
- Without OpenGL, `screenshot`, `export_view`, `render_sheet` and
  `export_pdf` with rendered views return an error that explains why. They
  never hang.

| Tool | What it does | Example arguments |
|---|---|---|
| `run_python` | Runs Python against the live document (scope: `scene`, `mesh`, `selection`, `groups`, `bim`, `QVector3D`… and the builders `revolve(profile)` / `extrude(outline, z0, z1)`: one line → one solid, smooth, correctly oriented group). One undo per call; full rollback on failure. | `{"code": "extrude([(0,0),(4,0),(4,3),(0,3)], 0, 2.5, name='Shed')"}` |
| `query_model` | Counts, group/component names, materials, layers, bounds. | `{}` |
| `document_info` | The document's path, whether it has unsaved changes (`modified`), the save format, sheets, scenes and what is allowed (`saving_allowed`, `shutdown_allowed`). | `{}` |
| `get_scene_info` | What `query_model` and `document_info` give, plus the scenes, the sheets (with their title-block number), the layers with their visibility, the georeference and whether it can render. The first call to make. | `{}` |
| `get_object_info` | One group or component by name or id: box (min, max, size), layer, material, children and BIM (IFC) tag. | `{"name": "Shed"}` or `{"id": "3f2a9c0d1e4b5a67"}` |
| `list_layers` | The layers: name, visible, locked, folder; and the active one. | `{}` |
| `set_layer_visibility` | Shows or hides layers (one undo step). | `{"layers": ["Furniture"], "visible": false}` |
| `list_scenes` | The saved scenes and the one shown. | `{}` |
| `show_scene` | Shows a scene as a click on its row does: camera, layers, style and hidden objects. | `{"name": "Plan"}` |
| `set_camera` | A standard view (`top`, `bottom`, `front`, `back`, `left`, `right`, `iso`) or `eye`/`target` (Z up, metres); projection `perspective`, `parallel` or `two_point`; `fov` in degrees; `zoom_extents` frames everything. | `{"view": "iso", "zoom_extents": true}` or `{"eye": [20, -15, 8], "target": [0, 0, 1], "projection": "perspective"}` |
| `select` | Selects groups or components by `names` or `ids` (`mode`: `replace`, `add`, `remove` or `toggle`), or clears the selection with `clear`. | `{"names": ["Bench 1", "Bench 2"]}` or `{"clear": true}` |
| `screenshot` | Renders the view. The agent looks at it and iterates; with `path` it also keeps the PNG (or JPG) there. | `{"width": 1280, "height": 720}` |
| `export_view` | Renders a saved scene to PNG and the agent looks at it; with `path` it is kept there. The user's view (camera, layers, style, hidden objects) is put back and a saved document stays saved. | `{"view": "3D view", "path": "/home/ana/site/view.png"}` |
| `render_sheet` | A PNG of a sheet, painted by the composer as its image export does. The sheet is given by name, by title-block number (`L-02`) or by place (1 = the first); `width` in pixels or `dpi`. | `{"sheet": "L-02", "width": 1600}` |
| `export_pdf` | The sheets (all, or those in `sheets`: name, title-block number or place) into one PDF. | `{"path": "/home/ana/site/plaza.pdf"}` or `{"path": "/home/ana/site/L-02.pdf", "sheets": ["L-02"]}` |
| `open_document` | Opens a document (`.igz`, `.dae`, `.skp`, `.dxf`, `.dwg`) in place of the one in front. If that one has unsaved changes it returns an error instead of a «save changes?» dialog, unless `discard_changes` is given. | `{"path": "/home/ana/site/plaza.igz"}` |
| `save_document` | Saves the document; with `path` (an `.igz`), saves it as that file; `format`: `auto` or `json`. **Only if the user allows it** (see below). | `{}` or `{"path": "/home/ana/site/plaza-v2.igz", "format": "json"}` |
| `import_file` | Imports into the document (one undo step): `.igz` (as a component), `.dae`, `.glb`/`.gltf`, `.skp`, `.obj`, `.stl`, `.dxf`, `.dwg`. `unit` (`m`, `cm`, `mm`, `in`, `ft`) for OBJ, STL and DXF; `make_faces` for DXF/DWG. | `{"path": "/home/ana/furniture/bench.obj", "unit": "cm"}` |
| `export_file` | Exports the model by the file's extension: `.ifc` (the objects tagged in BIM), `.glb`, `.dae`, `.stl` (`unit`, mm by default), `.obj` and `.dxf` (the view's lines). `selection_only` for GLB. Sheets go through `export_pdf`, pictures through `screenshot`, `export_view` and `render_sheet`. | `{"path": "/home/ana/site/plaza.ifc"}` |
| `list_materials` | The document's materials: name, colour, texture, opacity. | `{}` |
| `apply_material` | Paints the named objects (`names`/`ids`) as a whole with one of the document's materials, or else the selection. One undo step. | `{"material": "Brick", "names": ["North wall"]}` |
| `undo` / `redo` | The usual history. | `{}` |
| `shutdown` | Ends a window-less IngeTrazo started with `--allow-shutdown`. Refused with unsaved changes unless `discard_changes` is given. | `{}` |

Without the bridge running, the tools reply with a notice explaining how to
start it. The server accepts one client at a time and never listens outside
localhost.

IFC export uses the current exporter. A lossless IFC round trip comes in
0.6.4.

**Saving from the agent** is off by default: in the window, the checkbox
**Allow the agent to save the document** in the AI bridge (MCP) section;
without a window, `--allow-save`. Without permission the agent can change
the model but never the file. (Remember that `run_python` runs code inside
the application: the permission prevents accidents, it is not a security
barrier.)

## Without a window: automation and version control

IngeTrazo can run **without a window** so that an agent works on a document
from start to finish — for example on a CI runner that opens an `.igz` from
a Git repository, lets Claude make changes, saves and opens a pull request
for review.

    ingetrazo --headless --ai-bridge --open House.igz \
              --allow-save --save-format json --allow-shutdown \
              --port 0 --ready-file port.txt

The short form `ingetrazo --server [House.igz] [--port N] [options…]` is
the same as `--headless --ai-bridge --open House.igz`: the same mode, with
the same options and exit codes.

| Option | What it does |
|---|---|
| `--headless` | No window on screen (the view is still drawn in a hidden window). No dialog waits for an answer: all are cancelled. |
| `--ai-bridge` | Starts the bridge (127.0.0.1 only). |
| `--open FILE` | Opens the document. **If it cannot be opened, IngeTrazo ends at once** with code 3, before the bridge starts. |
| `--port N` | The bridge's port (default `INGETRAZO_AI_PORT` or 4763; `0` = a free one). |
| `--ready-file PATH` | Writes the port there once the document is open and the bridge listens (`INGETRAZO_BRIDGE_PORT=<n>` is printed too, and a line on standard error says whether OpenGL is available). |
| `--allow-save` | The agent may use `save_document`. |
| `--save-format auto\|json` | How it saves: `auto` (as always) or `json` (see below). |
| `--allow-shutdown` | The agent may use `shutdown`. Command line only. |
| `--exit-on-stdin-eof` | Ends (code 5) when its standard input closes: for a parent process that might die. |

Without a window no `.igz.bak` copies and no recovery copies are made on
saving: the history is Git. It does not use the single instance, so an open
IngeTrazo is not disturbed.

**Exit codes**

| Code | Meaning |
|---|---|
| 0 | The agent called `shutdown` — the only clean end. |
| 2 | Bad command line. |
| 3 | The `--open` document could not be opened. |
| 4 | The bridge could not listen (port taken…). |
| 5 | It ended some other way: a signal (`Ctrl+C`, SIGTERM), standard input closed… |

On Windows a process ended from outside (`TerminateProcess`) exits with the
code its killer sets (1 with `Popen.terminate`) — never 0.

**OpenGL.** `screenshot`, `export_view` and sheets with rendered views need
an OpenGL context. The other tools work without it. Without a context, the
line on standard error says so and those tools return an error that
explains why. Sheets drawn with lines only (vector style) render all the
same. On Linux without a display (a container, an ssh session) the
window-less mode picks the `offscreen` platform by itself; with it, OpenGL
depends on the machine's drivers. For a sure GL:

- **Xvfb**, a virtual display:

      xvfb-run -a -s "-screen 0 1920x1080x24" ingetrazo --server plaza.igz

  or by hand: `Xvfb :99 -screen 0 1920x1080x24 &` and then
  `DISPLAY=:99 QT_QPA_PLATFORM=xcb ingetrazo --server plaza.igz`.
- **On a desktop**: `QT_QPA_PLATFORM=xcb ingetrazo --server …` uses the
  real display without showing the window. You can also open IngeTrazo
  normally, minimise it and start the bridge from the AI tab.
- On Windows and macOS the window-less mode uses the system's display
  without showing the window.

### One command for the MCP client

The MCP server can start its own window-less IngeTrazo: there is no need to
have IngeTrazo open first.

    claude mcp add ingetrazo-headless -- ingetrazo --mcp --headless \
        --open /path/House.igz --allow-save --save-format json --allow-shutdown

(On Windows: `ingetrazo-mcp.exe --headless --open …`; from the repository:
`python3 scripts/ingetrazo_mcp.py --headless --open …`.) The server finds a
free port, waits until the document is open and ends its IngeTrazo when the
client goes. If the document does not open, the server ends with the same
code (3) without serving. After a `shutdown`, it ends with 0.

### Runner example

When the script needs the exit code, start IngeTrazo separately and point
the normal MCP server at its port:

    ingetrazo --headless --ai-bridge --open House.igz --allow-save \
        --save-format json --allow-shutdown --port 0 \
        --ready-file /tmp/port &
    PID=$!
    while [ ! -s /tmp/port ]; do
        kill -0 $PID 2>/dev/null || { wait $PID; exit $?; }   # did not open
        sleep 0.2
    done
    INGETRAZO_AI_PORT=$(cat /tmp/port) claude -p \
        "Add a 1×1 m window in the south wall, save and call shutdown" \
        --mcp-config ingetrazo-mcp.json --allowedTools "mcp__ingetrazo__*"
    wait $PID || exit 1                     # 0 only if the agent ended well
    git checkout -b ai/south-window && git add House.igz House.assets
    git commit -m "South window (Claude)" && gh pr create --fill

### Plain JSON format

With **Preferences ▸ General ▸ Save format ▸ Plain JSON** (or
`--save-format json`) the `.igz` is always indented JSON text, whatever its
size, so `git diff` shows what changed. Images (textures, the photo survey)
do not fit in text: they go to a folder beside the document,
`House.assets/`, which has to be versioned with it. An image no longer used
is deleted from that folder on saving; anything else in it is left alone.
It is a format-1 `.igz` with the mark `"layout": "plain-json"`: a document
opened with that mark **keeps being saved as plain JSON** even when the
chosen format is Automatic, so that it does not turn into a ZIP in the
repository; asking for another format by name
(`save_document(format="auto")`) does change it. Plain JSON carries no
picture of the model for the file manager (a PNG that changes on every save
would be noise in every diff). The usual formats (1, 2 and 3) do not change:
**Automatic** is still the default. A very large model in plain JSON takes
more space and opens more slowly than in the automatic format.

## AI assistant (inside the app)

For users who do not use Claude Code: the sidebar's **AI** tab
(Ctrl+Shift+A brings it to the front, even when hidden) is a chat
INSIDE IngeTrazo. Paste your API key — the
provider is detected from the prefix alone, following the IngePresupuestos convention:

| Prefix | Provider | Default model |
|---|---|---|
| `sk-ant-` | Anthropic | claude-sonnet-5 |
| `gsk_` | Groq (free) | llama-3.3-70b-versatile |
| `sk-or-` | OpenRouter | anthropic/claude-sonnet-5 |
| `AIza` | Gemini | gemini-2.5-flash |
| `sk-` | OpenAI | gpt-4o |
| *(empty)* | Local Ollama | qwen2.5-coder:7b |

Type what you want ("draw a 6×4 house with a gable roof") and the
assistant acts through transactional Python recipes — each action is one
undo step, and with vision-capable providers it receives viewport screenshots
to SEE what it built and iterate. The model is editable, and the key is
stored in the local configuration.

### Modelling from a photo

With the **Photo…** button you attach a picture of an object (a fountain, a
piece of furniture, a facade) and the assistant interprets it and recreates it piece by piece,
each piece as a named group, comparing its screenshots against the photo.
Give it the real measurements in the message ("the basin is 4 m in diameter, the
total height 2.30") — a photo carries no dimensions, and whatever the assistant
estimates by eye it states as an assumption so you can correct it. The photo is
rescaled to 1280 px and travels as a JPEG in that message only. It needs a
vision-capable provider (Anthropic, OpenAI, Gemini, OpenRouter).
