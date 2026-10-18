# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The experimental Rust engine (``rust/ingetrazo_core``, built with maturin).

``native`` is the compiled module when the engine is on and loads, else
``None``. It is OFF unless Preferences ▸ General ▸ «Rust engine
(experimental)» turns it on (read once, so it applies at the next start);
``INGETRAZO_RUST=1`` / ``=0`` overrides the setting, for tests and benches.
Every caller keeps its Python code and uses it whenever ``native`` is
``None``: the kernels make things faster, never different.

``native`` is resolved on first use, not at import: the setting lives in
QSettings, which needs the application's name set first."""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

#: The General setting that turns the engine on ("1") or off ("0").
SETTING = "rust_engine"

_UNSET = object()
_module = _UNSET          # the compiled module, None, or not looked at yet


def available():
    """The compiled module if this build has it and it loads, else None —
    whatever the setting says (Preferences shows «not available»)."""
    global _module
    if _module is _UNSET:
        try:
            import ingetrazo_core as mod
        except Exception as exc:  # noqa: BLE001 — a missing module is the norm
            mod = None
            if not isinstance(exc, ImportError):
                log.warning("Rust engine failed to load, using Python: %s",
                            exc)
        _module = mod
    return _module


def wanted() -> bool:
    """Whether the engine is asked for: the environment first, then the
    saved preference (off by default)."""
    env = os.environ.get("INGETRAZO_RUST")
    if env is not None:
        return env != "0"
    try:
        from core import general_settings
        return str(general_settings.value(SETTING, "0")) == "1"
    except Exception:  # noqa: BLE001 — no Qt settings yet: stay on Python
        return False


def __getattr__(name):
    if name == "native":
        mod = available() if wanted() else None
        globals()["native"] = mod       # fixed for the whole session
        return mod
    raise AttributeError(name)


def engine() -> str:
    """«Rust» or «Python», for About and the logs."""
    import core._native as me
    return "Rust" if me.native is not None else "Python"


#: The ``std::hypot(x, y, z)`` formulas the module knows (QVector3D's
#: length() is that call, and C++ standard libraries differ in it).
_HYPOTS = ("libstdc++",)
_hypot = _UNSET


def qt_hypot():
    """The formula that reproduces this Qt's ``QVector3D::length()`` bit for
    bit — tried on a fixed sample against Qt itself, once — or ``None``:
    the kernels that go through QVector3D arithmetic then stay in Python."""
    global _hypot
    if _hypot is _UNSET:
        _hypot = None
        mod = available()
        if mod is not None and hasattr(mod, "qt_vector_probe"):
            try:
                _hypot = _probe_hypot(mod)
            except Exception as exc:  # noqa: BLE001 — then Python
                log.warning("QVector3D probe failed, using Python: %s", exc)
    return _hypot


def _probe_hypot(mod):
    import numpy as np
    from PySide6.QtGui import QVector3D
    rng = np.random.default_rng(20261017)
    rows = np.concatenate([
        rng.normal(size=(3000, 3)),
        rng.normal(size=(3000, 3)) * rng.choice([1e-6, 1e-3, 1, 1e3, 1e5],
                                                size=(3000, 1)),
        np.round(rng.normal(size=(1000, 3)) * 4) / 2,
    ]).astype(np.float32)
    qt_len = [QVector3D(*r).length() for r in rows.tolist()]
    qt_nrm = [list(QVector3D(*r).normalized().toTuple())
              for r in rows.tolist()]
    for name in _HYPOTS:
        ln, nz, _u, _v = mod.qt_vector_probe(rows, name)
        if ln.tolist() == qt_len and nz.tolist() == qt_nrm:
            return name
    log.info("No native formula matches this Qt's QVector3D length")
    return None


#: Set while a start with the engine on is under way; cleared once the
#: window has drawn. Still set at the next start: that start never got
#: there, and the engine is turned off (start_guard).
STARTING = "rust_engine_starting"
#: ``--python-engine``: this run on the normal engine, whatever is saved.
FLAG = "--python-engine"


def start_guard(argv) -> bool:
    """Before anything reads ``native``: honour ``--python-engine``, and if
    the last start with the engine on never reached its first frame, turn
    the engine off for good (the user turns it on again in Preferences).
    Returns True when it was turned off that way — the window says so."""
    if FLAG in argv:
        os.environ["INGETRAZO_RUST"] = "0"
        return False
    if os.environ.get("INGETRAZO_RUST") is not None:
        return False                    # tests and benches choose for us
    try:
        from PySide6.QtCore import QSettings
        from core import general_settings
        st = QSettings()
        on = str(general_settings.value(SETTING, "0", st)) == "1"
        pending = str(general_settings.value(STARTING, "0", st)) == "1"
        if on and pending:
            general_settings.set_value(SETTING, "0", st)
            general_settings.set_value(STARTING, "0", st)
            st.sync()
            log.warning("The last start with the Rust engine did not open "
                        "the window: back on the Python engine.")
            return True
        if on:
            general_settings.set_value(STARTING, "1", st)
            st.sync()                   # on disk before anything can crash
    except Exception as exc:  # noqa: BLE001 — never stop a start over this
        log.warning("Rust engine start guard: %s", exc)
    return False


def start_ok() -> None:
    """The window is up and has drawn: this start with the engine worked."""
    try:
        from PySide6.QtCore import QSettings
        from core import general_settings
        st = QSettings()
        if str(general_settings.value(STARTING, "0", st)) == "1":
            general_settings.set_value(STARTING, "0", st)
            st.sync()
    except Exception as exc:  # noqa: BLE001
        log.warning("Rust engine start guard: %s", exc)
