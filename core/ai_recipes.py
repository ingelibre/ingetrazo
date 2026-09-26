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
    "viewport, QVector3D, Mesh, Group, Edge, Face, bim.")

#: The one-line builders. Hand-rolling these is the single biggest waste of
#: turns we have measured — every model that was not told reinvented a
#: ring-of-quads lathe, faceted and wrongly wound.
RECIPES = """Recetario:
- TORNO (prefiérelo para toda pieza redonda): g = revolve([(radio,z), ...], \
name="Columna", color=(r,g,b,1.0), segments=32, scallop=None, closed=False) \
— perfil de abajo a arriba; abierto se tapa solo; closed=True si el perfil \
es una sección cerrada (p.ej. la pared de una taza); scallop=(profundidad, \
lóbulos) talla festones/gallones en el borde. Crea el grupo y lo agrega.
- PRISMA: g = extrude([(x,y), ...], z0, z1, name="Base", color=...) — \
contorno en planta extruido; crea el grupo y lo agrega. Una CAJA (tablero, \
pata, larguero, peldaño) es un extrude de cuatro puntos: no la armes cara \
por cara.
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
UNITS = ("IngeTrazo es un modelador 3D libre estilo SketchUp: Z arriba, "
         "unidades en METROS, ángulos en RADIANES.")


def reference(unit: str = "llamada") -> str:
    """Everything, in reading order — what a door hands the model."""
    return "\n".join((UNITS, SCOPE, RECIPES, HOW_IT_RUNS.format(unit=unit)))
