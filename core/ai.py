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

    return {"revolve": revolve, "extrude": extrude}


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
    return m.get("image_png_b64"), "image/png"


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
            blocks = [{"type": "text", "text": m["text"]}]
            img, mime = _message_image(m)
            if img:
                blocks.insert(0, {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime,
                               "data": img}})
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


def _urlopen(url: str, headers: dict, payload: bytes | None = None,
             timeout: float = 180.0) -> bytes:
    """One HTTP round trip with the readable error shaping every caller
    wants (the raw body is the useful part of a provider error)."""
    req = urllib.request.Request(url, data=payload, headers=headers,
                                 method="POST" if payload else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode()[:400]
        except OSError:
            pass
        raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"sin conexión: {exc.reason}")


def chat(provider: str, model: str, api_key: str, system: str,
         messages: list, ollama_url: str = "http://localhost:11434",
         timeout: float = 180.0, max_tokens: int = 4096) -> str:
    """One blocking chat turn. Raises with a readable message on failure —
    callers run this in a worker thread, never on the UI thread."""
    url, headers, payload = build_request(
        provider, model, api_key, system, messages, ollama_url, max_tokens)
    return parse_reply(provider, _urlopen(url, headers, payload, timeout))


#: Substrings of model ids that are not chat models (speech, safety,
#: embeddings, image/video generation) — hidden from the model picker.
_NON_CHAT = ("whisper", "tts", "embed", "guard", "moderation", "imagen",
             "veo", "aqa", "audio", "transcribe", "image", "dall-e")


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
    "groq": ("Groq (gratis)", "https://console.groq.com/keys"),
    "anthropic": ("Anthropic (Claude)",
                  "https://console.anthropic.com/settings/keys"),
    "openai": ("OpenAI", "https://platform.openai.com/api-keys"),
    "gemini": ("Google Gemini", "https://aistudio.google.com/app/apikey"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/keys"),
    "deepseek": ("DeepSeek", "https://platform.deepseek.com/api_keys"),
    "ollama": ("Ollama (local)", "https://ollama.com/download"),
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
