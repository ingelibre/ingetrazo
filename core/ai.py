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
import sys
import traceback
import urllib.error
import urllib.request

from core.history import SnapshotImport
from core.version import __version__

#: Cloudflare fronts several providers (Groq above all) and rejects
#: urllib's default "Python-urllib/3.x" agent with HTTP 403 error 1010 —
#: caught on the user's first real Groq key. Always send a real identity.
USER_AGENT = f"IngeTrazo/{__version__} (+https://ingetrazo.com)"

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
    return scope


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

DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4o",
    "gemini": "gemini-2.5-flash",
    "openrouter": "anthropic/claude-sonnet-5",
    "deepseek": "deepseek-chat",
    "ollama": "llama3.2",
}

#: Providers whose default models take viewport screenshots.
VISION = {"anthropic", "openai", "gemini", "openrouter"}


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


def build_request(provider: str, model: str, api_key: str,
                  system: str, messages: list,
                  ollama_url: str = "http://localhost:11434",
                  max_tokens: int = 4096):
    """(url, headers, payload-bytes) for one chat turn.

    ``messages``: [{"role": "user"/"assistant", "text": str,
    "image_png_b64": optional}] — images ride only on user turns.
    """
    if provider == "anthropic":
        content_msgs = []
        for m in messages:
            blocks = [{"type": "text", "text": m["text"]}]
            if m.get("image_png_b64"):
                blocks.insert(0, {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png",
                               "data": m["image_png_b64"]}})
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
        if m.get("image_png_b64"):
            oai_msgs.append({"role": m["role"], "content": [
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + m["image_png_b64"]}},
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


def chat(provider: str, model: str, api_key: str, system: str,
         messages: list, ollama_url: str = "http://localhost:11434",
         timeout: float = 180.0) -> str:
    """One blocking chat turn. Raises with a readable message on failure —
    callers run this in a worker thread, never on the UI thread."""
    url, headers, payload = build_request(
        provider, model, api_key, system, messages, ollama_url)
    req = urllib.request.Request(url, data=payload, headers=headers,
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return parse_reply(provider, resp.read())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode()[:400]
        except OSError:
            pass
        raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"sin conexión: {exc.reason}")


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
