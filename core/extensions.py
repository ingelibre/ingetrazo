# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
# Engine design contributed by Ahsan Mehmood (PR #1), hardened here.
"""Runtime plugin discovery — the engine behind the Extensions menu.

A plugin is a Python file (or a package directory) dropped into one of two
places:

- ``<app_root>/plugins/`` — plugins bundled with the application. Read-only
  in a frozen install (AppImage mount, Program Files), listed in
  ``ingetrazo.spec`` so they actually travel with the installers.
- the per-user directory (``%APPDATA%/ingetrazo/plugins`` on Windows,
  ``$XDG_DATA_HOME/ingetrazo/plugins`` — default ``~/.local/share/...`` —
  elsewhere): where third-party plugins are installed without touching the
  app install.

Candidates are imported BY FILE PATH (``importlib.util``), never by package
name: ``import plugins.x`` only resolves while the repo layout happens to be
on ``sys.path``, which is exactly what a PyInstaller bundle does not
guarantee (the ``core/paths.py`` lesson). Loading by path behaves the same
from the repo, the AppImage and the Windows build — and never puts a plugin
directory on ``sys.path``, so a user file named ``json.py`` cannot shadow a
stdlib module for the whole app.

The contract ``views/main_window.py`` relies on:

- A broken plugin NEVER breaks startup. Import errors, constructor errors —
  every failure is logged, returned as a :class:`PluginError` and shown as a
  disabled menu entry; the application opens regardless.
- A module-level ``setup(app)`` is called once with a
  :class:`views.extension_api.ExtensionApp` (document data, a side panel,
  viewport overlays and inferences); if it raises, the plugin shows as a
  load error like an import failure.
- Only ``Tool`` subclasses *defined in the plugin's own module* are
  registered. A plugin that imports ``LineTool`` (to reuse or subclass it)
  must not duplicate the built-in in the menu or clone its shortcut.
- Two plugins with the same stem: the first directory wins (app-bundled
  before user), the loser is logged and skipped.
"""
from __future__ import annotations

import glob
import importlib.util
import inspect
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from core.paths import app_root

log = logging.getLogger("ingetrazo.plugins")


@dataclass
class LoadedPlugin:
    """One plugin file that imported cleanly and produced tools."""
    stem: str                       # file / package name, e.g. "model_info"
    path: Path
    tools: list = field(default_factory=list)   # instantiated Tool objects
    #: The module's ``setup(app)`` (views.extension_api), or None — a plugin
    #: may have tools, a setup, or both.
    setup: object = None


@dataclass
class PluginError:
    """One plugin file that failed; surfaces as a disabled menu entry."""
    stem: str
    path: Path
    error: str                      # "ExcType: message", for the tooltip


def user_plugins_dir() -> Path:
    """The per-user plugin directory. May not exist yet — that is fine."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA")
                    or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME")
                    or (Path.home() / ".local" / "share"))
    return base / "ingetrazo" / "plugins"


def plugin_dirs() -> list[Path]:
    """Candidate directories, app-bundled first (first stem wins)."""
    return [app_root() / "plugins", user_plugins_dir()]


def note_failure(what: str) -> None:
    """Append the exception being handled to the error log. A windowed
    Windows build has no stderr: without this a failing extension leaves no
    trace at all, and «Open logs folder» shows nothing (#1152)."""
    import time
    import traceback
    from core.paths import user_log_dir
    try:
        with open(user_log_dir() / "ingetrazo-errors.log", "a",
                  encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {what}\n"
                    f"{traceback.format_exc()}")
    except OSError:
        pass


def _misplaced_module(folder: Path) -> str | None:
    """Where the extension is inside a folder that is not a package itself,
    or None. A folder without ``__init__.py`` does not load, and it said
    nothing: copying the folder a ZIP extracts to (``x/x/__init__.py``) or a
    repository's folder of loose modules looked like an extension that
    refused to load, with not a word anywhere."""
    for pattern in ("*.py", "*/__init__.py", "*/*/__init__.py"):
        found = sorted(glob.glob(os.path.join(glob.escape(str(folder)),
                                              pattern)))
        if found:
            path = Path(found[0])
            inner = path if path.name != "__init__.py" else path.parent
            return inner.relative_to(folder).as_posix()
    return None


def _candidates(p_dir: Path):
    """Yield ``(stem, file, error)``: loose ``x.py`` files and
    ``x/__init__.py`` packages, skipping dunders, dotfiles and non-Python
    clutter (README). ``error`` says why a candidate cannot be loaded at all.

    ``os.path`` and not ``Path.is_file``: up to Python 3.13 the latter RAISES
    on a folder that cannot be read, and the first such folder ended the
    whole scan (#1152)."""
    try:
        entries = sorted(p_dir.iterdir())
    except OSError as exc:
        log.warning("cannot read the plugin folder %s: %s", p_dir, exc)
        return
    for entry in entries:
        if entry.name.startswith(("_", ".")):
            continue
        if os.path.isdir(entry):
            try:
                os.listdir(entry)
            except OSError as exc:
                yield entry.name, entry, f"{type(exc).__name__}: {exc}"
                continue
            init = entry / "__init__.py"
            if not os.path.isfile(init):
                inner = _misplaced_module(entry)
                if inner is not None:
                    yield entry.name, entry, (
                        "This folder is not an extension: IngeTrazo needs "
                        "__init__.py directly inside it. Move "
                        f"{inner} straight into the extensions folder.")
                continue
            if os.path.isfile(entry / ".disabled"):
                log.info("plugin %r is disabled by the extension manager",
                         entry.name)
                continue
            yield entry.name, init, None
        elif entry.suffix == ".py" and os.path.isfile(entry):
            yield entry.stem, entry, None


def _import_by_path(stem: str, file: Path):
    """Import ``file`` under a private module name, off ``sys.path``."""
    mod_name = f"ingetrazo_plugin_{stem}"
    spec = importlib.util.spec_from_file_location(
        mod_name, file,
        submodule_search_locations=(
            [str(file.parent)] if file.name == "__init__.py" else None))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build an import spec for {file}")
    mod = importlib.util.module_from_spec(spec)
    # Registered so dataclasses / pickling / introspection inside the
    # plugin resolve their own module; unregistered again on failure.
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(mod_name, None)
        raise
    return mod


def discover_plugins(dirs=None):
    """Scan ``dirs`` (default :func:`plugin_dirs`) and load every plugin.

    Returns ``(plugins, errors)`` and never raises: each failing candidate
    becomes a :class:`PluginError` instead of an exception, because the one
    thing a plugin system must not do is keep the host from starting.
    """
    from tools.base import Tool     # deferred: core stays Qt-import-light

    plugins: list[LoadedPlugin] = []
    errors: list[PluginError] = []
    seen: set[str] = set()

    for p_dir in (list(dirs) if dirs is not None else plugin_dirs()):
        if not os.path.isdir(p_dir):
            continue
        for stem, file, problem in _candidates(p_dir):
            if stem in seen:
                log.warning("plugin %r at %s shadowed by an earlier one; "
                            "skipped", stem, file)
                continue
            seen.add(stem)
            if problem is not None:
                log.warning("plugin %r at %s: %s", stem, file, problem)
                errors.append(PluginError(stem, file, problem))
                continue
            try:
                mod = _import_by_path(stem, file)
                tools = [
                    obj() for _n, obj in inspect.getmembers(mod,
                                                            inspect.isclass)
                    if (issubclass(obj, Tool) and obj is not Tool
                        and obj.__module__ == mod.__name__     # defined here
                        and not inspect.isabstract(obj)
                        and _builds_bare(obj))
                ]
                setup = getattr(mod, "setup", None)
            # SystemExit too: an extension calling sys.exit() must not close
            # the whole application.
            except (Exception, SystemExit) as exc:  # noqa: BLE001 — contract
                log.exception("failed to load plugin %r from %s", stem, file)
                note_failure(f"failed to load plugin {stem!r} from {file}")
                errors.append(PluginError(
                    stem, file, f"{type(exc).__name__}: {exc}"))
                continue
            if not callable(setup):
                setup = None
            if tools or setup is not None:
                plugins.append(LoadedPlugin(stem, file, tools, setup))
                for t in tools:
                    log.info("loaded plugin tool %r from %s", t.name, file)
    return plugins, errors


def _builds_bare(cls) -> bool:
    """Whether the loader can make ``cls`` on its own — no required
    argument. A tool that needs one (the app, a mode) is the extension's to
    build in its ``setup(app)``; making it here raised and threw away the
    whole extension, setup and panel included (planArq, José Castro)."""
    try:
        sig = inspect.signature(cls.__init__)
    except (TypeError, ValueError):
        return True
    params = list(sig.parameters.values())[1:]           # past ``self``
    return all(p.default is not p.empty
               or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
               for p in params)
