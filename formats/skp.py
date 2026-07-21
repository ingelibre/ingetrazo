# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SKP import seam — pluggable parser backends with a skp2dae fallback.

IngeTrazo aims to open ANY ``.skp`` (old → recent). Two eras of the format
exist: the legacy MFC binary (SketchUp v8–v20, ~2010–2020) and the ZIP/VFF
container (v2021+). This module is the single seam between IngeTrazo and *how*
an ``.skp`` is read, so the parser can evolve independently of the app:

  1. **A pure-Python backend** (OpenSKP — https://github.com/iamahsanmehmood/
     openskp — or a maintained downstream fork). Offline, Linux-native, no
     Wine, no proprietary DLL. Preferred; its version coverage grows over time.
  2. **The skp2dae converter** (Trimble's ``SketchUpAPI.dll`` via Wine). The
     full-coverage fallback for versions the pure backend can't read yet. It is
     a SEPARATE program (the proprietary DLL never enters GPL IngeTrazo), so its
     dialog/subprocess flow lives in ``views.main_window``, not here.

Backends are tried in order; the first that is both *available* (its parser
imports) and *supports* the file's format wins. When no pure backend can handle
the file, :func:`load_skp` raises :class:`NeedsConverter` and the UI runs the
skp2dae path. This keeps IngeTrazo decoupled from the parser choice: swapping
OpenSKP for a fork, or widening version coverage, touches only this file.

Nothing here imports a parser at module load — a missing OpenSKP is not an
error, just an unavailable backend. Today no pure backend is wired, so every
file cascades to the converter (identical to the previous behaviour).
"""
from __future__ import annotations

from pathlib import Path


class NeedsConverter(Exception):
    """No pure backend can read this ``.skp`` — the caller should fall back to
    the external skp2dae converter. Carries the path and detected format."""

    def __init__(self, path, fmt: str) -> None:
        super().__init__(f"No pure SKP backend for {path} (format={fmt})")
        self.path = Path(path)
        self.format = fmt


def detect_format(path) -> str:
    """Best-effort container detection from the file's first bytes, with no
    parser involved:

    * ``"vff"``     — ZIP container (``PK\\x03\\x04``), SketchUp 2021+.
    * ``"legacy"``  — pre-2021 MFC binary blob.
    * ``"unknown"`` — unreadable / empty.

    Used to route to a backend and to report what a file is even when nothing
    can parse it yet.
    """
    try:
        head = Path(path).read_bytes()[:8]
    except OSError:
        return "unknown"
    if head[:4] == b"PK\x03\x04":
        return "vff"
    if head:
        return "legacy"
    return "unknown"


class _OpenSkpBackend:
    """Pure-Python OpenSKP (or a maintained fork). A stub until the parser is
    vendored: ``available()`` stays False behind ``_WIRED`` so a merely-present
    ``openskp`` package does not hijack the cascade before the Scene adapter in
    :meth:`load` is written and pinned to a known API."""

    name = "openskp"
    #: Flip to True once :meth:`load` is implemented against a pinned OpenSKP.
    _WIRED = False

    def available(self) -> bool:
        if not self._WIRED:
            return False
        try:  # pragma: no cover - depends on an optional dependency
            import openskp  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return True

    def supports(self, fmt: str) -> bool:
        # Upstream OpenSKP reads the VFF container (2021+). A fork that adds the
        # legacy MFC decoder widens this to include ``"legacy"``.
        return fmt == "vff"

    def load(self, scene, path, progress=None) -> None:  # pragma: no cover
        # Adapter: OpenSKP model → IngeTrazo Scene (meshes → groups, materials
        # → attrs, component instances → shared prototypes). Written when the
        # parser is vendored and its API pinned; see docs/skp-backend.md.
        raise NotImplementedError(
            "OpenSKP backend not wired yet — vendor the parser first")


# Ordered list of pure-Python backends. Extend/replace as coverage grows.
_BACKENDS: list = [_OpenSkpBackend()]


def backends_status() -> list[tuple[str, bool]]:
    """``(name, available)`` for each pure backend — for diagnostics / an
    About-style report of what can be opened without the converter."""
    return [(b.name, b.available()) for b in _BACKENDS]


def can_handle(path) -> bool:
    """True when a pure backend can read ``path`` directly (no converter).
    The UI checks this before deciding between the pure path and skp2dae, so a
    failing pure import never leaves a half-applied edit."""
    fmt = detect_format(path)
    return any(b.available() and b.supports(fmt) for b in _BACKENDS)


def load_skp(scene, path, progress=None) -> str:
    """Load ``path`` (.skp) into ``scene`` with the first pure backend that
    supports it; returns the backend name used. Raises :class:`NeedsConverter`
    when no pure backend can read this file's format — the caller then runs the
    external skp2dae converter."""
    path = Path(path)
    fmt = detect_format(path)
    for backend in _BACKENDS:
        if backend.available() and backend.supports(fmt):
            backend.load(scene, path, progress=progress)
            return backend.name
    raise NeedsConverter(path, fmt)
