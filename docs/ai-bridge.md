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

| Tool | What it does |
|---|---|
| `run_python` | Runs Python against the live document (scope: `scene`, `mesh`, `selection`, `groups`, `bim`, `QVector3D`… and the builders `revolve(profile)` / `extrude(outline, z0, z1)`: one line → one solid, smooth, correctly oriented group). One undo per call; full rollback on failure. |
| `query_model` | Counts, group/component names, materials, layers, bounds. |
| `screenshot` | Renders the real viewport — the agent looks and iterates. |
| `undo` / `redo` | The usual history. |

Without the bridge running, the tools reply with a notice explaining how to
start it. The server accepts one client at a time and never listens outside
localhost.

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
