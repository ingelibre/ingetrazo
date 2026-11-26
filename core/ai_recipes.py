# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The recipe book the model reads — ONE text behind the two AI doors.

IngeTrazo has two of them: the in-app Asistente IA (``plugins/ai_assistant``,
which pastes this into its system prompt) and the MCP bridge
(``scripts/ingetrazo_mcp``, which pastes it into ``run_python``'s description
and the handshake's ``instructions``). They drifted: the assistant's prompt
taught ``revolve``/``extrude``/``house`` and ``f.attrs["color"]``, the MCP
description taught ``mesh.add_face`` and nothing else.

What that cost, measured (2026-09-21, Antigravity CLI + Gemini 3.8 Flash,
"una mesa de comedor de 1,60 × 0,90 × 0,75 con cuatro sillas"): the model
built it correctly — exact sizes, 462 faces, not one normal inward — in
**81 tool calls, 46 of them pure introspection**. It ran ``dir()``,
``inspect.signature``, and ``dis`` over ``material_sig``'s bytecode to find
out that a colour is ``f.attrs["color"]``, and spent 34 s reasoning about
the winding of a box that ``prism()`` returns in one line. Nine calls
actually built something.

So: stdlib-only, no imports, no Qt — the MCP server is a bare stdio process
that must import this from a checkout, a PyInstaller bundle, an AppImage and
a Flatpak alike.
"""
from __future__ import annotations

#: What is bound in the execution scope. Same names through both doors.
SCOPE = (
    "En el scope tienes: scene, mesh, selection, groups, layers, "
    "viewport, QVector3D, Mesh, Group, Edge, Face, Layer, bim.")

#: The one-line builders. Hand-rolling these is the single biggest waste of
#: turns we have measured — every model that was not told reinvented a
#: ring-of-quads lathe, faceted and wrongly wound.
RECIPES = """Recetario (usa PRIMERO estas funciones; existen ya, no las \
definas):
- CAJA / CUBO: g = box((x,y,z), (dx,dy,dz), name="Cubo", color=(r,g,b,1.0)) \
— esquina inferior y medidas. Un cubo de 6 m es box((0,0,0), (6,6,6)). \
Crea el grupo y lo agrega (igual que revolve, extrude, prism, wall y \
house): NO hagas groups.append.
- CASA COMPLETA: ver house(...) más abajo — para «una casa» úsala SIEMPRE \
en vez de armar muros y techo a mano.
- TORNO (prefiérelo para toda pieza redonda): g = revolve([(radio,z), ...], \
name="Columna", color=(r,g,b,1.0), segments=32, scallop=None, closed=False) \
— perfil de abajo a arriba; abierto se tapa solo; closed=True si el perfil \
es una sección cerrada (p.ej. la pared de una taza); scallop=(profundidad, \
lóbulos) talla festones/gallones en el borde. Crea el grupo y lo agrega.
- PRISMA: g = extrude([(x,y), ...], z0, z1, name="Base", color=...) — \
contorno en planta extruido; crea el grupo y lo agrega. Una caja \
(tablero, pata, larguero, peldaño) es box(...): no la armes cara por cara.
- LOSA / PLANCHA: g = prism([puntos 3D de un polígono plano], (dx,dy,dz), \
holes=[[...]], name=..., color=...) — barre el polígono (con agujeros) \
a lo largo del vector.
- MURO: g = wall((x,y), (x,y), height=3, thickness=0.2, openings=[(offset, \
alféizar, ancho, alto)], peak=None) — crece a la IZQUIERDA de a→b; \
alféizar 0 = puerta (muesca), >0 = ventana (agujero).
- CASA COMPLETA: gs = house(width=6, depth=4, wall_height=3, thickness=0.2, \
roof="gable"|"hip"|"flat", ridge_height=None, overhang=0.4, ridge="x", \
doors=[("S", offset, ancho, alto)], windows=[("S", offset, alféizar, ancho, \
alto)], origin=(0,0), name="Casa") — muros con espesor, puertas con hoja, \
ventanas con vidrio y techo, en grupos «Casa · Paredes/Techo/Carpintería». \
Lados S (frente, y=y0), E, N, W; offset a lo largo del muro en sentido \
antihorario desde su primera esquina. Medidas típicas: puerta 0.9×2.1, \
ventana 1.2×1.0 con alféizar 1.0, pendiente 30°.
- Cara suelta: f = mesh.add_face([QVector3D(x,y,z), ...])  (lazo \
antihorario visto desde afuera); f.attrs["color"] = (r, g, b, 1.0)  (0..1)
- Arista: mesh.add_edge(QVector3D(...), QVector3D(...))
- Grupo manual: m = Mesh(); m.add_face([...]); g = Group(m, name="..."); \
groups.append(g)
- Pintar un grupo entero: g.material = {"color": (r,g,b), "opacity": 1.0} \
— NO toques scene.materials (es el registro de materiales del documento).
- Mover un grupo: for v in list(g.mesh.vertices): g.mesh.move_vertex(v, \
QVector3D(dx,dy,dz))  — y si g.xform is not None (instancia de \
componente), compón la traslación en g.xform en vez de tocar vértices.
- Cámara: viewport.camera.target/distance/yaw/pitch (RADIANES); \
viewport.update()
- LÁMINA (hoja del compositor para imprimir; «lámina»/«sheet»/«layout», \
NO es una capa): c = sheet("Planta", paper="A3", landscape=True) — la crea \
con un marco de vista y aparece sola en las pestañas de láminas. Borrar: \
scene.compositions.remove(c) (queda al menos una si había).
- CAPA / ETIQUETA: ly = Layer("Muros"); layers.append(ly); g.layer = \
"Muros". En layers solo van objetos Layer, nunca textos.
- print(...) para reportar datos (breve: el resultado viaja cada turno)."""

#: What the engine guarantees, and what the model should not waste turns on.
#: ``{unit}`` is what one execution is called at this door — a ``bloque`` of
#: code for the in-app assistant, a tool ``llamada`` over MCP.
HOW_IT_RUNS = """Cada {unit} es UN paso de undo: si lanza una excepción se \
revierte POR COMPLETO, y el Ctrl+Z del usuario deshace tu paso entero. El scope \
PERSISTE entre {unit}s: las variables y funciones que definas siguen \
disponibles — no las redefinas.
NO explores la API con dir(), inspect ni dis: lo que necesitas está en este \
recetario, y cada sondeo es un turno perdido. Si algo falta, escríbelo \
directo y lee el error.
Un pedido sencillo (una casa, una mesa, un poste) va COMPLETO de una sola \
vez, con detalles razonables aunque no te los pidan; los grandes, por \
pasos. Verifica con las capturas del viewport e itera.
La figura de persona de un documento nuevo se llama «Ingeniero» \
(«Engineer» si la interfaz está en inglés) y es la ESCALA (1,70 m, un \
billboard): no la borres ni la muevas salvo que te lo pidan, y no la tomes \
por el modelo."""

#: Model conventions. First line of everything the model reads.
UNITS = ("IngeTrazo es un modelador 3D libre de empujar/tirar: Z arriba, "
         "unidades en METROS, ángulos en RADIANES.")


# ---- English edition ---------------------------------------------------------
# The MCP door speaks English: its tool names, schemas and errors are
# English, and an MCP client may be any agent in any language. The in-app
# assistant keeps the Spanish book above. Both editions teach the SAME
# helpers with the SAME signatures — tests/test_ai_bridge.py compares the
# code in them, so a helper taught in one and not the other fails a test.

SCOPE_EN = (
    "In scope you have: scene, mesh, selection, groups, layers, "
    "viewport, QVector3D, Mesh, Group, Edge, Face, Layer, bim.")

RECIPES_EN = """Recipe book (use these functions FIRST; they already \
exist, do not define them):
- BOX / CUBE: g = box((x,y,z), (dx,dy,dz), name="Cube", color=(r,g,b,1.0)) \
— lower corner and sizes. A 6 m cube is box((0,0,0), (6,6,6)). \
It creates the group and adds it (like revolve, extrude, prism, wall and \
house): do NOT groups.append it.
- WHOLE HOUSE: see house(...) below — for «a house» ALWAYS use it \
instead of building walls and roof by hand.
- LATHE (prefer it for every round part): g = revolve([(radius,z), ...], \
name="Column", color=(r,g,b,1.0), segments=32, scallop=None, closed=False) \
— profile from bottom to top; an open one is capped on its own; \
closed=True if the profile is a closed section (e.g. the wall of a cup); \
scallop=(depth, lobes) carves scallops/gadroons into the rim. Creates the \
group and adds it.
- PRISM: g = extrude([(x,y), ...], z0, z1, name="Base", color=...) — \
plan outline extruded; creates the group and adds it. A box \
(table top, leg, rail, step) is box(...): do not build it face by face.
- SLAB / PLATE: g = prism([3D points of a planar polygon], (dx,dy,dz), \
holes=[[...]], name=..., color=...) — sweeps the polygon (with holes) \
along the vector.
- WALL: g = wall((x,y), (x,y), height=3, thickness=0.2, openings=[(offset, \
sill, width, height)], peak=None) — grows to the LEFT of a→b; \
sill 0 = door (notch), >0 = window (hole).
- WHOLE HOUSE: gs = house(width=6, depth=4, wall_height=3, thickness=0.2, \
roof="gable"|"hip"|"flat", ridge_height=None, overhang=0.4, ridge="x", \
doors=[("S", offset, width, height)], windows=[("S", offset, sill, width, \
height)], origin=(0,0), name="House") — walls with thickness, doors with \
leaves, windows with glass, and a roof, in groups «House · \
Paredes/Techo/Carpintería» (walls/roof/joinery). Sides S (front, y=y0), \
E, N, W; offset along the wall counter-clockwise from its first corner. \
Typical sizes: door 0.9×2.1, window 1.2×1.0 with sill 1.0, pitch 30°.
- Loose face: f = mesh.add_face([QVector3D(x,y,z), ...])  (loop \
counter-clockwise seen from outside); f.attrs["color"] = (r, g, b, 1.0)  \
(0..1)
- Edge: mesh.add_edge(QVector3D(...), QVector3D(...))
- Manual group: m = Mesh(); m.add_face([...]); g = Group(m, name="..."); \
groups.append(g)
- Paint a whole group: g.material = {"color": (r,g,b), "opacity": 1.0} \
— do NOT touch scene.materials (it is the document's material registry).
- Move a group: for v in list(g.mesh.vertices): g.mesh.move_vertex(v, \
QVector3D(dx,dy,dz))  — and if g.xform is not None (a component \
instance), compose the translation into g.xform instead of moving vertices.
- Camera: viewport.camera.target/distance/yaw/pitch (RADIANS); \
viewport.update()
- SHEET (a composer page to print; «sheet»/«layout»/«lámina», it is NOT \
a layer): c = sheet("Plan", paper="A3", landscape=True) — creates it with \
a view frame and it shows up in the sheet tabs on its own. Delete: \
scene.compositions.remove(c) (at least one stays if there was one).
- LAYER / TAG: ly = Layer("Walls"); layers.append(ly); g.layer = \
"Walls". Only Layer objects go into layers, never strings.
- print(...) to report data (keep it short: the result travels every \
turn)."""

HOW_IT_RUNS_EN = """Each {unit} is ONE undo step: if it raises an exception \
it is rolled back COMPLETELY, and the user's Ctrl+Z undoes your whole step. \
The scope PERSISTS between {unit}s: the variables and functions you define \
stay available — do not redefine them.
Do NOT explore the API with dir(), inspect or dis: what you need is in this \
recipe book, and every probe is a wasted turn. If something is missing, \
write it directly and read the error.
A simple request (a house, a table, a post) goes in COMPLETE in one go, \
with reasonable details even if not asked for; big ones, in steps. Verify \
with viewport captures and iterate.
The person figure of a new document is called «Engineer» («Ingeniero» \
when the interface is in Spanish) and is the SCALE (1.70 m, a \
billboard): do not delete or move it unless asked, and do not take it \
for the model."""

UNITS_EN = ("IngeTrazo is a free push/pull 3D modeller: Z up, units in "
            "METRES, angles in RADIANS.")

_EDITIONS = {
    "es": (UNITS, SCOPE, RECIPES, HOW_IT_RUNS),
    "en": (UNITS_EN, SCOPE_EN, RECIPES_EN, HOW_IT_RUNS_EN),
}


def reference(unit: str = "llamada", lang: str = "es") -> str:
    """Everything, in reading order — what a door hands the model.
    ``lang``: ``"es"`` (the in-app assistant's) or ``"en"`` (the MCP
    door's)."""
    units, scope, recipes, how = _EDITIONS[lang]
    return "\n".join((units, scope, recipes, how.format(unit=unit)))
