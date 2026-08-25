# AI Bridge — modelar con Claude (MCP)

IngeTrazo puede ser dirigido por un agente de IA (Claude Code, Claude
Desktop) mediante el [Model Context Protocol](https://modelcontextprotocol.io):
el agente dibuja, consulta y **ve** el modelo en vivo — y cada acción suya
es un paso de undo transaccional (si su código falla, el documento se
revierte entero; el guard de hermeticidad valida sus recetas).

## Uso

1. En IngeTrazo: **Extensiones ▸ Puente IA (MCP)** — arranca un servidor
   local (solo 127.0.0.1, puerto 4763; `INGETRAZO_AI_PORT` lo cambia).
   El mismo menú lo detiene.
2. Registra el servidor MCP en Claude Code:

       claude mcp add ingetrazo -- python3 /ruta/a/app/scripts/ingetrazo_mcp.py

   (En Claude Desktop: agrega el mismo comando en la config de MCP.)
3. Pídele cosas: *"dibuja una casita de 6×4 m con techo a dos aguas,
   agrúpala y píntala de ladrillo; muéstrame cómo quedó"*.

## Herramientas expuestas

| Tool | Qué hace |
|---|---|
| `run_python` | Ejecuta Python sobre el documento vivo (scope: `scene`, `mesh`, `selection`, `groups`, `bim`, `QVector3D`…). Un undo por llamada; rollback total si falla. |
| `query_model` | Conteos, nombres de grupos/componentes, materiales, capas, bounds. |
| `screenshot` | Renderiza el viewport real — el agente mira e itera. |
| `undo` / `redo` | La historia de siempre. |

Sin el puente encendido, las tools responden con el aviso de cómo
encenderlo. El servidor acepta un cliente a la vez y nunca escucha fuera
de localhost.
