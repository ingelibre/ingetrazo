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
- Only ``Tool`` subclasses *defined in the plugin's own module* are
  registered. A plugin that imports ``LineTool`` (to reuse or subclass it)
  must not duplicate the built-in in the menu or clone its shortcut.
- Two plugins with the same stem: the first directory wins (app-bundled
  before user), the loser is logged and skipped.
"""
from __future__ import annotations

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


def _candidates(p_dir: Path):
    """Yield ``(stem, file)``: loose ``x.py`` files and ``x/__init__.py``
    packages, skipping dunders, dotfiles and non-Python clutter (README)."""
    for entry in sorted(p_dir.iterdir()):
        if entry.name.startswith(("_", ".")):
            continue
        if entry.is_file() and entry.suffix == ".py":
            yield entry.stem, entry
        elif entry.is_dir() and (entry / "__init__.py").is_file():
            yield entry.name, entry / "__init__.py"


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
        if not p_dir.is_dir():
            continue
        for stem, file in _candidates(p_dir):
            if stem in seen:
                log.warning("plugin %r at %s shadowed by an earlier one; "
                            "skipped", stem, file)
                continue
            seen.add(stem)
            try:
                mod = _import_by_path(stem, file)
                tools = [
                    obj() for _n, obj in inspect.getmembers(mod,
                                                            inspect.isclass)
                    if (issubclass(obj, Tool) and obj is not Tool
                        and obj.__module__ == mod.__name__     # defined here
                        and not inspect.isabstract(obj))
                ]
            except Exception as exc:                # noqa: BLE001 — contract
                log.exception("failed to load plugin %r from %s", stem, file)
                errors.append(PluginError(
                    stem, file, f"{type(exc).__name__}: {exc}"))
                continue
            if tools:
                plugins.append(LoadedPlugin(stem, file, tools))
                for t in tools:
                    log.info("loaded plugin tool %r from %s", t.name, file)
    return plugins, errors
