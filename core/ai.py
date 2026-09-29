# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""AI plumbing shared by the AI plugins (invariant #5: the AI orchestrates
ACTIONS over the deterministic engine, never raw meshes).

Two halves:

- :func:`run_transactional` — execute agent Python against the live
  document with the Python Console's guarantees: one undo step per call,
  whole-rollback on error, no undo entry for inspect-only runs. Used by the
  AI Bridge (MCP) and the in-app Asistente IA.
- A provider layer mirroring IngePresupuestos' ``ai_specs``: ONE API key,
  provider auto-detected by its prefix (gsk_ → Groq, sk-ant- → Anthropic,
  AIza → Gemini, sk-or- → OpenRouter, sk- → OpenAI) plus local Ollama.
  Anthropic speaks its native Messages API; everyone else goes through
  their OpenAI-compatible endpoint — two wire formats cover them all,
  images (viewport screenshots) included, stdlib urllib only.
"""
from __future__ import annotations

import io
import json
import math
import sys
import traceback
import urllib.error
import time
import urllib.request

from core.history import SnapshotImport
from core.version import USER_AGENT as _UA, __version__

#: Cloudflare fronts several providers (Groq above all) and rejects
#: urllib's default "Python-urllib/3.x" agent with HTTP 403 error 1010 —
#: caught on the user's first real Groq key. Always send a real identity.
USER_AGENT = _UA

# ---- Transactional executor -------------------------------------------------


def build_scope(viewport, scope: dict | None = None) -> dict:
    """(Re)bind the live objects an agent scripts against."""
    from PySide6.QtGui import QVector3D
    from core import bim
    from core.group import Group
    from core.mesh import Edge, Face, Mesh, Vertex
    scope = scope if scope is not None else {"__name__": "__ai__"}
    scope.update(
        viewport=viewport, scene=viewport.scene, model=viewport.scene,
        mesh=viewport.scene.mesh, selection=viewport.scene.selection,
        groups=viewport.scene.groups, layers=viewport.scene.layers, bim=bim,
        QVector3D=QVector3D, Mesh=Mesh, Group=Group, Vertex=Vertex,
        Edge=Edge, Face=Face)
    scope.update(_recipe_helpers(viewport.scene))
    return scope


def _recipe_helpers(scene) -> dict:
    """One-line geometry builders for AI recipes. Watching real sessions,
    every model hand-rolled its own ring-of-quads lathe per piece — 40
    error-prone lines and a token bill each time, with faceted results
    (no soft edges, wrong winding). These build correct solids instead."""
    from PySide6.QtGui import QVector3D
    from core.group import Group
    from core.mesh import Mesh
    from core.orient import orient_outward

    def _soften(mesh, deg=42.0):
        cos_t = math.cos(math.radians(deg))
        for e in mesh.edges:
            if len(e.faces) == 2 and QVector3D.dotProduct(
                    e.faces[0].normal(), e.faces[1].normal()) > cos_t:
                e.soft = True

    def _finish(mesh, color, name):
        if color is not None:
            for f in mesh.faces:
                f.attrs["color"] = tuple(color)
        orient_outward(mesh)
        _soften(mesh)
        group = Group(mesh, name=name)
        scene.groups.append(group)
        return group

    def revolve(profile, segments=32, scallop=None, closed=False,
                name=None, color=None):
        """Solid of revolution around Z from an (radius, z) profile,
        bottom to top. Open profiles get end caps; ``closed=True`` treats
        the profile as a closed cross-section ring (e.g. a basin wall).
        ``scallop=(depth, lobes)`` carves festones INTO the radius, scaled
        by r/r_max so rims wave and centers stay put."""
        amp, lobes = scallop or (0.0, 0)
        rmax = max(r for r, _z in profile) or 1.0
        rows = []
        for r, z in profile:
            ring = []
            for i in range(segments):
                th = 2.0 * math.pi * i / segments
                rr = r
                if lobes:
                    rr += (amp * 0.5 * (math.cos(lobes * th) - 1.0)
                           * (r / rmax))
                ring.append(QVector3D(rr * math.cos(th),
                                      rr * math.sin(th), z))
            rows.append(ring)
        mesh = Mesh()
        m = len(rows)
        for j in range(m if closed else m - 1):
            a, b = rows[j], rows[(j + 1) % m]
            for i in range(segments):
                i2 = (i + 1) % segments
                quad = [a[i], a[i2], b[i2], b[i]]
                if ((quad[0] - quad[3]).length() < 1e-6
                        and (quad[1] - quad[2]).length() < 1e-6):
                    continue
                mesh.add_face(quad)
        if not closed:
            if profile[0][0] > 1e-6:
                mesh.add_face(list(reversed(rows[0])))
            if profile[-1][0] > 1e-6:
                mesh.add_face(rows[-1])
        return _finish(mesh, color, name)

    def extrude(outline, z0, z1, name=None, color=None):
        """Solid prism: an (x, y) outline swept from z0 up to z1."""
        lo = [QVector3D(x, y, z0) for x, y in outline]
        hi = [QVector3D(x, y, z1) for x, y in outline]
        mesh = Mesh()
        n = len(lo)
        for i in range(n):
            j = (i + 1) % n
            mesh.add_face([lo[i], lo[j], hi[j], hi[i]])
        mesh.add_face(list(reversed(lo)))
        mesh.add_face(hi)
        return _finish(mesh, color, name)

    def _pt(p, z=None):
        if hasattr(p, "x"):
            return QVector3D(p)
        if len(p) == 2:
            return QVector3D(p[0], p[1], 0.0 if z is None else z)
        return QVector3D(p[0], p[1], p[2])

    def _prism_mesh(mesh, loop, vec, holes=()):
        """Add a closed solid to ``mesh``: the planar polygon ``loop`` (3D
        points, optional hole loops) swept along ``vec``."""
        v = _pt(vec)
        lo = [_pt(p) for p in loop]
        hole_lo = [[_pt(p) for p in h] for h in holes or ()]
        mesh.add_face(lo, hole_lo)
        mesh.add_face([p + v for p in reversed(lo)],
                      [[p + v for p in reversed(h)] for h in hole_lo])
        for ring in (lo, *hole_lo):
            n = len(ring)
            for i in range(n):
                a, b = ring[i], ring[(i + 1) % n]
                mesh.add_face([a, b, b + v, a + v])

    def prism(loop, vec, holes=None, name=None, color=None):
        """Solid from a flat polygon (3D points, optional hole loops) swept
        along ``vec``: a slab, a wall with a window, a roof plank."""
        mesh = Mesh()
        _prism_mesh(mesh, loop, vec, holes or ())
        return _finish(mesh, color, name)

    def _wall_mesh(mesh, a, b, height, thickness, openings=(), z0=0.0,
                   peak=None):
        """One wall into ``mesh``: base line a→b (x, y), the solid grows to
        the LEFT of a→b by ``thickness`` (walk the footprint counter-
        clockwise and the inside is the left). ``openings`` are
        ``(offset, sill, width, height)`` along the wall from ``a``; a sill
        at 0 is a door (a notch in the outline), above 0 a window (a hole).
        ``peak=(offset, rise)`` raises the top to a gable point."""
        ax, ay = a[0], a[1]
        bx, by = b[0], b[1]
        length = math.hypot(bx - ax, by - ay)
        if length < 1e-9:
            return
        ux, uy = (bx - ax) / length, (by - ay) / length
        nx, ny = -uy, ux                      # left of a→b
        top = z0 + height

        def P(s, z):
            return QVector3D(ax + ux * s, ay + uy * s, z)
        doors = sorted((o for o in openings if o[1] <= 1e-6), key=lambda o: o[0])
        windows = [o for o in openings if o[1] > 1e-6]
        outline = [P(0.0, z0)]
        for off, _sill, w, h in doors:
            s0, s1 = max(off, 0.0), min(off + w, length)
            if s1 - s0 < 1e-6:
                continue
            outline += [P(s0, z0), P(s0, z0 + h), P(s1, z0 + h), P(s1, z0)]
        outline.append(P(length, z0))
        outline.append(P(length, top))
        if peak is not None:
            outline.append(P(peak[0], top + peak[1]))
        outline.append(P(0.0, top))
        # Drop the doubled corner when a door starts at 0.
        clean = []
        for q in outline:
            if not clean or (q - clean[-1]).length() > 1e-9:
                clean.append(q)
        if (clean[0] - clean[-1]).length() < 1e-9:
            clean.pop()
        holes = []
        for off, sill, w, h in windows:
            s0, s1 = max(off, 0.0), min(off + w, length)
            zt = min(z0 + sill + h, top - 0.05)
            if s1 - s0 < 1e-6 or zt - (z0 + sill) < 1e-6:
                continue
            holes.append([P(s0, z0 + sill), P(s0, zt), P(s1, zt), P(s1, z0 + sill)])
        _prism_mesh(mesh, clean, (nx * thickness, ny * thickness, 0.0), holes)

    def wall(a, b, height=3.0, thickness=0.2, openings=(), z0=0.0,
             peak=None, name=None, color=None):
        """A wall with thickness and openings — see ``house`` for the
        conventions. ``openings=[(offset, sill, width, height), ...]``."""
        mesh = Mesh()
        _wall_mesh(mesh, a, b, height, thickness, openings, z0, peak)
        return _finish(mesh, color, name)

    def house(width=6.0, depth=4.0, wall_height=3.0, thickness=0.2,
              roof="gable", ridge_height=None, overhang=0.4, ridge="x",
              doors=(), windows=(), origin=(0.0, 0.0), name="Casa",
              wall_color=(0.90, 0.87, 0.80, 1.0),
              roof_color=(0.55, 0.27, 0.20, 1.0),
              door_color=(0.45, 0.28, 0.15, 1.0),
              glass_color=(0.60, 0.80, 0.95, 1.0)):
        """A whole house in one call: four walls with thickness, doors and
        windows cut through them (with a door leaf and a glass pane), and
        a roof — ``"gable"`` (two slopes, ridge along ``"x"`` or ``"y"``),
        ``"hip"`` (four slopes) or ``"flat"``. Sides are ``"S"`` (y = y0,
        the front), ``"E"``, ``"N"``, ``"W"``; an opening's ``offset`` runs
        along the wall counter-clockwise from its first corner (S from
        x0, E from y0, N from x1 back, W from y1 back). ``doors=[(side,
        offset, width, height)]``, ``windows=[(side, offset, sill, width,
        height)]``. Returns the groups: walls, floor, carpentry, roof."""
        x0, y0 = float(origin[0]), float(origin[1])
        x1, y1 = x0 + float(width), y0 + float(depth)
        H, t = float(wall_height), float(thickness)
        if ridge_height is None:
            half = (depth if ridge == "x" else width) / 2.0
            ridge_height = half * math.tan(math.radians(30.0))
        rh = float(ridge_height)
        lines = {"S": ((x0, y0), (x1, y0)), "E": ((x1, y0), (x1, y1)),
                 "N": ((x1, y1), (x0, y1)), "W": ((x0, y1), (x0, y0))}
        # E and W sit between S and N, so the corners are not doubled.
        lines["E"] = ((x1, y0 + t), (x1, y1 - t))
        lines["W"] = ((x0, y1 - t), (x0, y0 + t))
        shift = {"S": 0.0, "N": 0.0, "E": -t, "W": -t}
        ops: dict = {k: [] for k in lines}
        leaves: list = []          # (side, offset, sill, w, h, kind)
        for side, off, w, h in doors:
            ops[side.upper()].append((off + shift[side.upper()], 0.0, w, h))
            leaves.append((side.upper(), off + shift[side.upper()], 0.0, w, h, "door"))
        for side, off, sill, w, h in windows:
            ops[side.upper()].append((off + shift[side.upper()], sill, w, h))
            leaves.append((side.upper(), off + shift[side.upper()], sill, w, h, "glass"))
        gable_sides = ()
        if roof == "gable":
            gable_sides = ("E", "W") if ridge == "x" else ("S", "N")
        walls_mesh = Mesh()
        for side, (a, b) in lines.items():
            peak = None
            if side in gable_sides:
                seg = math.hypot(b[0] - a[0], b[1] - a[1])
                peak = (seg / 2.0, rh)
            _wall_mesh(walls_mesh, a, b, H, t, ops[side], 0.0, peak)
        out = [_finish(walls_mesh, wall_color, f"{name} · Paredes")]
        # A floor slab just inside the walls (a hair short of them, so no
        # two faces share a plane), or the house reads hollow from below.
        floor = Mesh()
        e = t + 0.01
        _prism_mesh(floor, [QVector3D(x0 + e, y0 + e, 0.0), QVector3D(x1 - e, y0 + e, 0.0),
                            QVector3D(x1 - e, y1 - e, 0.0), QVector3D(x0 + e, y1 - e, 0.0)],
                    (0.0, 0.0, 0.1))
        out.append(_finish(floor, (0.75, 0.72, 0.66, 1.0), f"{name} · Piso"))
        # Carpentry: a door leaf and a glass pane in every opening.
        carp = Mesh()
        for side, off, sill, w, h, kind in leaves:
            a, b = lines[side]
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            nx, ny = -uy, ux
            d = t * 0.5
            s0, s1 = off, off + w
            base = [QVector3D(a[0] + ux * s0 + nx * d, a[1] + uy * s0 + ny * d, sill),
                    QVector3D(a[0] + ux * s1 + nx * d, a[1] + uy * s1 + ny * d, sill),
                    QVector3D(a[0] + ux * s1 + nx * d, a[1] + uy * s1 + ny * d, sill + h),
                    QVector3D(a[0] + ux * s0 + nx * d, a[1] + uy * s0 + ny * d, sill + h)]
            if kind == "door":
                _prism_mesh(carp, base, (nx * 0.04, ny * 0.04, 0.0))
                for f in carp.faces:
                    f.attrs.setdefault("color", tuple(door_color))
            else:
                f = carp.add_face(base)
                f.attrs["color"] = tuple(glass_color)
                f.attrs["opacity"] = 0.4
        if carp.faces:
            out.append(_finish(carp, None, f"{name} · Carpintería"))
        # Roof.
        roof_mesh = Mesh()
        ov = float(overhang)
        if roof == "flat":
            _prism_mesh(roof_mesh, [QVector3D(x0 - ov, y0 - ov, H), QVector3D(x1 + ov, y0 - ov, H),
                                    QVector3D(x1 + ov, y1 + ov, H), QVector3D(x0 - ov, y1 + ov, H)],
                        (0.0, 0.0, 0.2))
        elif roof == "hip":
            L, W = x1 - x0, y1 - y0
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            s = rh / (min(L, W) / 2.0)
            ze = H - s * ov
            b0, b1, b2, b3 = (QVector3D(x0 - ov, y0 - ov, ze), QVector3D(x1 + ov, y0 - ov, ze),
                              QVector3D(x1 + ov, y1 + ov, ze), QVector3D(x0 - ov, y1 + ov, ze))
            if L >= W:
                r0, r1 = QVector3D(cx - (L - W) / 2.0, cy, H + rh), QVector3D(cx + (L - W) / 2.0, cy, H + rh)
                faces = [[b0, b1, r1, r0], [b2, b3, r0, r1], [b1, b2, r1], [b3, b0, r0]]
            else:
                r0, r1 = QVector3D(cx, cy - (W - L) / 2.0, H + rh), QVector3D(cx, cy + (W - L) / 2.0, H + rh)
                faces = [[b1, b2, r1, r0], [b3, b0, r0, r1], [b0, b1, r0], [b2, b3, r1]]
            for f in faces:
                roof_mesh.add_face(f)
            roof_mesh.add_face([b3, b2, b1, b0])
        else:                                   # gable: a bent slab
            th = 0.15
            if ridge == "x":
                s = rh / ((y1 - y0) / 2.0)
                ze, yc = H - s * ov, (y0 + y1) / 2.0
                dz = th / math.cos(math.atan(s))
                sec = [QVector3D(x0 - ov, y0 - ov, ze), QVector3D(x0 - ov, yc, H + rh),
                       QVector3D(x0 - ov, y1 + ov, ze), QVector3D(x0 - ov, y1 + ov, ze - dz),
                       QVector3D(x0 - ov, yc, H + rh - dz), QVector3D(x0 - ov, y0 - ov, ze - dz)]
                _prism_mesh(roof_mesh, sec, (x1 - x0 + 2 * ov, 0.0, 0.0))
            else:
                s = rh / ((x1 - x0) / 2.0)
                ze, xc = H - s * ov, (x0 + x1) / 2.0
                dz = th / math.cos(math.atan(s))
                sec = [QVector3D(x0 - ov, y0 - ov, ze), QVector3D(xc, y0 - ov, H + rh),
                       QVector3D(x1 + ov, y0 - ov, ze), QVector3D(x1 + ov, y0 - ov, ze - dz),
                       QVector3D(xc, y0 - ov, H + rh - dz), QVector3D(x0 - ov, y0 - ov, ze - dz)]
                _prism_mesh(roof_mesh, sec, (0.0, y1 - y0 + 2 * ov, 0.0))
        out.append(_finish(roof_mesh, roof_color, f"{name} · Techo"))
        return out

    return {"revolve": revolve, "extrude": extrude, "prism": prism,
            "wall": wall, "house": house}


def run_transactional(viewport, code: str, scope: dict) -> dict:
    """Execute ``code`` exactly like the Python Console: one undoable step,
    rolled back whole on error, no undo entry if nothing changed. Returns
    {stdout, stderr, error, changed}."""
    build_scope(viewport, scope)
    history = viewport.history
    out_buf, err_buf = io.StringIO(), io.StringIO()

    def mutate(_scene) -> None:
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out_buf, err_buf
        try:
            try:
                compiled = compile(code, "<ai>", "eval")
            except SyntaxError:
                compiled = None
            if compiled is None:
                exec(compile(code, "<ai>", "exec"), scope)
            else:
                result = eval(compiled, scope)
                if result is not None:
                    scope["_"] = result
                    print(repr(result))
        except Exception:
            traceback.print_exc(file=err_buf)
            raise
        finally:
            sys.stdout, sys.stderr = old_out, old_err

    cmd = SnapshotImport(mutate)
    saved_redo = list(history.redo_stack)
    history.execute(cmd)
    error = history.last_error
    changed = True
    if error is None:
        unchanged = (cmd.before == cmd.after
                     and not cmd.added_groups and not cmd.added_layers
                     and not cmd.added_views and not cmd.added_dims
                     and not cmd.added_texts)
        if (unchanged and history.undo_stack
                and history.undo_stack[-1] is cmd):
            history.undo_stack.pop()
            history.redo_stack[:] = saved_redo
            changed = False
    else:
        changed = False
    viewport.notify_scene_changed()
    return {"stdout": out_buf.getvalue(), "stderr": err_buf.getvalue(),
            "error": error, "changed": changed}


# ---- Provider layer (mirrors IngePresupuestos ai_specs) ---------------------

PROVIDERS = ("groq", "anthropic", "openai", "gemini", "openrouter",
             "deepseek", "ollama")

#: OpenAI-compatible chat endpoints; Anthropic goes through its native API.
_OPENAI_BASES = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek": "https://api.deepseek.com/v1",
}

#: Providers ROTATE their catalogs: Groq retired llama-3.3-70b-versatile
#: for free/dev tiers on 2026-06-17 (HTTP 404 model_not_found) and points
#: to openai/gpt-oss-120b. list_models() exists so the UI never guesses.
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4o",
    "gemini": "gemini-2.5-flash",
    "openrouter": "anthropic/claude-sonnet-5",
    "deepseek": "deepseek-chat",
    "ollama": "llama3.2",
}

#: Providers whose default models take viewport screenshots.
VISION = {"anthropic", "openai", "gemini", "openrouter"}

#: Model-name tags that mark a vision-capable model on providers whose
#: DEFAULT model is text-only: Groq serves Llama 4 Scout/Maverick
#: (multimodal) on its free tier, Ollama runs llava/qwen-vl locally.
_VISION_TAGS = ("llama-4", "scout", "maverick", "llava", "vision",
                "-vl", "vl-", "gemma3", "gemma-3", "pixtral")


def supports_vision(provider: str, model: str) -> bool:
    """Whether this provider+model pair can look at images."""
    if provider in VISION:
        return True
    m = (model or "").lower()
    return any(t in m for t in _VISION_TAGS)


_IMAGE_KEYS = ("image_b64", "image_mime", "image_png_b64")


def slim_messages(messages: list, vision: bool = True) -> list:
    """Request-time diet for a convo that is resent WHOLE every turn: keep
    every user photo (``image_b64`` — the reference being modeled) but only
    the LATEST viewport screenshot (``image_png_b64``). Older screenshots
    are stale views of a model that has changed, and k rounds would
    otherwise ship k-1 dead images per request — the free-tier killer.

    ``vision=False`` strips EVERY image instead: a text-only model must
    never receive image content — Groq answers HTTP 400 ("content must be
    a string") and, since the convo keeps the photo, every retry fails the
    same way (seen live). The photo stays stored, so switching to a vision
    model brings it back. Returns copies; the stored convo is untouched."""
    if not vision:
        return [{k: v for k, v in m.items() if k not in _IMAGE_KEYS}
                for m in messages]
    last_shot = -1
    for i, m in enumerate(messages):
        if m.get("image_png_b64"):
            last_shot = i
    return [
        ({k: v for k, v in m.items() if k != "image_png_b64"}
         if m.get("image_png_b64") and i != last_shot else m)
        for i, m in enumerate(messages)
    ]


def detect_provider(api_key: str) -> str:
    """The IngePresupuestos rule: the key's prefix names the provider."""
    if not api_key:
        return "ollama"
    if api_key.startswith("gsk_"):
        return "groq"
    if api_key.startswith("sk-ant-"):
        return "anthropic"
    if api_key.startswith("AIza"):
        return "gemini"
    if api_key.startswith("sk-or-"):
        return "openrouter"
    if api_key.startswith("sk-"):
        return "openai"
    return "anthropic"


def _message_image(m: dict) -> tuple[str | None, str]:
    """(base64, mime) of a message's image. ``image_b64``+``image_mime`` is
    the generic form (user photos ride as JPEG — a re-encoded PNG would be
    ~10× the payload PER TURN, since the whole convo is resent every turn);
    ``image_png_b64`` stays as the screenshot shorthand."""
    if m.get("image_b64"):
        return m["image_b64"], m.get("image_mime", "image/png")
    shot = m.get("image_png_b64")
    # The screenshot shorthand carries JPEG now (a quarter of the bytes
    # of the PNG it used to be); the base64 header tells which.
    mime = "image/jpeg" if shot and shot.startswith("/9j/") else "image/png"
    return shot, mime


def build_request(provider: str, model: str, api_key: str,
                  system: str, messages: list,
                  ollama_url: str = "http://localhost:11434",
                  max_tokens: int = 4096):
    """(url, headers, payload-bytes) for one chat turn.

    ``messages``: [{"role": "user"/"assistant", "text": str,
    "image_png_b64" / "image_b64"+"image_mime": optional}] — images ride
    only on user turns.
    """
    if provider == "anthropic":
        content_msgs = []
        for m in messages:
            blocks = ([{"type": "text", "text": m["text"]}]
                      if m["text"].strip() else [])
            img, mime = _message_image(m)
            if img:
                blocks.insert(0, {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime,
                               "data": img}})
            if blocks:
                content_msgs.append({"role": m["role"], "content": blocks})
        payload = {"model": model, "max_tokens": max_tokens,
                   "system": system, "messages": content_msgs}
        return ("https://api.anthropic.com/v1/messages",
                {"Content-Type": "application/json",
                 "User-Agent": USER_AGENT,
                 "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"},
                json.dumps(payload).encode())

    base = (ollama_url.rstrip("/") + "/v1" if provider == "ollama"
            else _OPENAI_BASES[provider])
    oai_msgs = [{"role": "system", "content": system}]
    for m in messages:
        img, mime = _message_image(m)
        if img:
            oai_msgs.append({"role": m["role"], "content": [
                {"type": "image_url", "image_url": {
                    "url": f"data:{mime};base64," + img}},
                {"type": "text", "text": m["text"]},
            ]})
        else:
            oai_msgs.append({"role": m["role"], "content": m["text"]})
    headers = {"Content-Type": "application/json",
               "User-Agent": USER_AGENT}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {"model": model, "max_tokens": max_tokens,
               "messages": oai_msgs}
    return (f"{base}/chat/completions", headers,
            json.dumps(payload).encode())


def parse_reply(provider: str, raw: bytes) -> str:
    data = json.loads(raw)
    if provider == "anthropic":
        return "".join(b.get("text", "") for b in data.get("content", []))
    choices = data.get("choices") or []
    if not choices:
        raise ValueError(str(data)[:400])
    return choices[0].get("message", {}).get("content", "") or ""


#: HTTP statuses worth another try: the provider is busy or rate-limited
#: (Gemini's 503 «high demand», 429, the 5xx family, Anthropic's 529).
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 529})
#: Seconds before retry n (1-based): 2, 4, 8, 16 — capped.
RETRY_BACKOFF = (2.0, 4.0, 8.0, 16.0)


def _urlopen(url: str, headers: dict, payload: bytes | None = None,
             timeout: float = 180.0, retries: int = 0, on_retry=None,
             sleep=time.sleep) -> bytes:
    """One HTTP round trip with the readable error shaping every caller
    wants (the raw body is the useful part of a provider error).

    With ``retries``, a busy provider (:data:`RETRY_STATUSES`, or no
    answer at all) is tried again after a growing pause; ``on_retry(n,
    total, wait, reason)`` is told each time so a chat panel can say so.
    Marco asked for a house and Gemini's 503 «high demand» cut it short
    at the walls (2026-09-15): one spike must not end the recipe."""
    from core.tls import https_context
    context = https_context()            # a packaged Python's CA bundle (#198)
    attempt = 0
    while True:
        req = urllib.request.Request(url, data=payload, headers=headers,
                                     method="POST" if payload else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=context) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode()[:400]
            except OSError:
                pass
            reason = f"HTTP {exc.code}: {detail or exc.reason}"
            if exc.code not in RETRY_STATUSES or attempt >= retries:
                if attempt:
                    reason += f" (tras {attempt + 1} intentos)"
                raise RuntimeError(reason)
        except urllib.error.URLError as exc:
            reason = f"sin conexión: {exc.reason}"
            if attempt >= retries:
                raise RuntimeError(reason)
        wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
        attempt += 1
        if on_retry is not None:
            on_retry(attempt, retries, wait, reason)
        sleep(wait)


def chat(provider: str, model: str, api_key: str, system: str,
         messages: list, ollama_url: str = "http://localhost:11434",
         timeout: float = 180.0, max_tokens: int = 4096,
         retries: int = 4, on_retry=None) -> str:
    """One blocking chat turn. Raises with a readable message on failure —
    callers run this in a worker thread, never on the UI thread. A busy
    provider is retried ``retries`` times (see :func:`_urlopen`)."""
    url, headers, payload = build_request(
        provider, model, api_key, system, messages, ollama_url, max_tokens)
    return parse_reply(provider, _urlopen(url, headers, payload, timeout,
                                          retries=retries, on_retry=on_retry))


#: Substrings of model ids that are not chat models (speech, safety,
#: embeddings, image/video generation) — hidden from the model picker.
_NON_CHAT = ("whisper", "tts", "embed", "guard", "moderation", "imagen",
             "veo", "aqa", "audio", "transcribe", "image", "dall-e",
             # Groq's agentic "compound" systems run their own tools and
             # answer with prose about what they "did" — no recipe ever
             # reaches IngeTrazo (Marco, 2026-09-15).
             "compound")


def list_models(provider: str, api_key: str,
                ollama_url: str = "http://localhost:11434",
                timeout: float = 20.0) -> list[str]:
    """The chat-capable model ids the key can ACTUALLY use, sorted.

    Every provider exposes a models endpoint (Anthropic native, the rest
    OpenAI-compatible); offering the live list beats hardcoding names that
    rot when catalogs rotate. Run it on a worker thread."""
    if provider == "anthropic":
        url = "https://api.anthropic.com/v1/models?limit=100"
        headers = {"User-Agent": USER_AGENT, "x-api-key": api_key,
                   "anthropic-version": "2023-06-01"}
    else:
        base = (ollama_url.rstrip("/") + "/v1" if provider == "ollama"
                else _OPENAI_BASES[provider])
        url = f"{base}/models"
        headers = {"User-Agent": USER_AGENT}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    data = json.loads(_urlopen(url, headers, timeout=timeout))
    ids = [str(m.get("id", "")) for m in data.get("data", [])]
    # Gemini's OpenAI-compat endpoint prefixes ids with "models/"; chat
    # accepts the bare name (it's what DEFAULT_MODELS already uses).
    ids = [i.removeprefix("models/") for i in ids]
    return sorted(i for i in ids
                  if i and not any(t in i.lower() for t in _NON_CHAT))


#: UI metadata: (label, where to get the key). Mirrors IngePresupuestos.
PROVIDER_INFO = {
    # "gratis, con clave", not "gratis": Rafael read the bare word as "no
    # key needed", pressed Test connection with the field empty and got a
    # raw HTTP 401 (Revisión 3, 2026-09-20). The quota is free; the key is
    # not optional.
    "groq": ("Groq (gratis, con clave)", "https://console.groq.com/keys"),
    "anthropic": ("Anthropic (Claude)",
                  "https://console.anthropic.com/settings/keys"),
    "openai": ("OpenAI", "https://platform.openai.com/api-keys"),
    "gemini": ("Google Gemini (gratis, con clave)",
               "https://aistudio.google.com/app/apikey"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/keys"),
    "deepseek": ("DeepSeek", "https://platform.deepseek.com/api_keys"),
    "ollama": ("Local: Ollama / LM Studio", "https://ollama.com/download"),
}


def probar_conexion(provider: str, model: str, api_key: str,
                    ollama_url: str = "http://localhost:11434"):
    """One tiny round trip: (ok, message). Run it on a worker thread."""
    try:
        reply = chat(provider, model, api_key,
                     "Responde únicamente: OK",
                     [{"role": "user", "text": "ping"}],
                     ollama_url=ollama_url, timeout=30.0)
    except Exception as exc:  # noqa: BLE001 — the message IS the result
        return False, str(exc)
    return True, (reply or "").strip()[:80] or "OK"


def extract_code(text: str) -> str | None:
    """The first fenced ```python block of a reply (the agent's recipe)."""
    marker = "```python"
    start = text.find(marker)
    if start < 0:
        marker = "```py"
        start = text.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end = text.find("```", start)
    if end < 0:
        return None
    code = text[start:end].strip("\n")
    return code or None


#: What an executed recipe's code collapses to in old turns. Spanish on
#: purpose: it is read by the model inside a Spanish conversation.
CODE_STUB = "[receta ya ejecutada — código omitido]"


def compact_messages(messages: list, keep_last: int = 2) -> list:
    """The other half of the convo diet: every turn resends every PAST
    recipe verbatim (~500 tokens each), but an executed recipe's effect is
    already in the document — its code is dead weight. Replace the fenced
    block of all but the last ``keep_last`` assistant turns with CODE_STUB,
    keeping the prose (intent) and the feedback turns (results, errors).
    Recent turns stay whole so the model can still build on its own code.
    Returns copies; the stored convo is untouched."""
    coded = [i for i, m in enumerate(messages)
             if m.get("role") == "assistant" and extract_code(m["text"])]
    stub = set(coded[:-keep_last] if keep_last else coded)
    out = []
    for i, m in enumerate(messages):
        if i in stub:
            text = m["text"]
            marker = "```python"
            start = text.find(marker)
            if start < 0:
                marker = "```py"
                start = text.find(marker)
            end = text.find("```", start + len(marker))
            tail = text[end + 3:] if end >= 0 else ""
            m = {**m, "text": (text[:start] + CODE_STUB + tail).strip()}
        out.append(m)
    return out


_THOUGHT_TAGS = ("thought", "thinking", "think")


def strip_thoughts(text: str) -> str:
    """Remove the <thought>/<thinking>/<think> blocks some models leak
    into their visible text (Gemma, live). They are internal monologue:
    resending them with the convo every turn is pure token burn. Handles
    an unclosed opener (drop to the end) and a stray closer whose opener
    fell in an earlier chunk (drop the prefix)."""
    for tag in _THOUGHT_TAGS:
        open_t, close_t = f"<{tag}>", f"</{tag}>"
        while True:
            s = text.find(open_t)
            if s < 0:
                break
            e = text.find(close_t, s)
            text = text[:s] + (text[e + len(close_t):] if e >= 0 else "")
        e = text.find(close_t)
        if e >= 0 and open_t not in text[:e]:
            text = text[e + len(close_t):]
    return text.strip()


def truncated_code(text: str) -> bool:
    """True when a reply opens a ```python fence and never closes it — the
    signature of a reply cut by max_tokens. Callers must NOT treat such a
    reply as "no code, we're done": half a recipe was on its way (seen live
    with gemini-2.5-flash: the loop ended silently, nothing drawn)."""
    for marker in ("```python", "```py"):
        start = text.find(marker)
        if start >= 0:
            return text.find("```", start + len(marker)) < 0
    return False
