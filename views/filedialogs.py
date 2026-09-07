# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""File dialogs that open where you last were.

Every ``QFileDialog.get…`` in the app passed ``""`` or a bare suggested
name («lamina.pdf») as the start directory, and Qt then starts in the
process's working directory — the folder the program is installed in
(Marco, 2026-09-07: «me abre por defecto la carpeta donde tengo instalado
el programa, ¿no debería abrirme la última carpeta que elegí?»).

``file_dialogs`` has the same static signatures as ``QFileDialog``: a
start directory without a folder part is joined with the last folder the
user chose in ANY of these dialogs (QSettings ``files/last_dir``), falling
back to the open document's folder, then to Documents; a start directory
that names a folder is respected. Whatever the user picks is remembered.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtWidgets import QFileDialog

_KEY = "files/last_dir"


def last_dir(fallback: str | os.PathLike | None = None) -> str:
    """The folder to start a dialog in: the last one chosen, if it still
    exists; else *fallback*; else Documents; else home."""
    saved = QSettings().value(_KEY, "")
    if saved and Path(str(saved)).is_dir():
        return str(saved)
    if fallback and Path(fallback).is_dir():
        return str(fallback)
    docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
    return docs if docs and Path(docs).is_dir() else str(Path.home())


def remember(path: str | os.PathLike | None) -> None:
    """Keep the folder of a chosen file (or the chosen folder itself)."""
    if not path:
        return
    p = Path(str(path))
    folder = p if p.is_dir() else p.parent
    if folder.is_dir():
        QSettings().setValue(_KEY, str(folder))


def start_in(directory: str | os.PathLike | None, fallback=None) -> str:
    """Resolve a dialog's start argument: nothing or a bare name goes into
    the remembered folder; a real folder (or a file inside one) stays."""
    d = str(directory or "")
    if not d:
        return last_dir(fallback)
    head, _tail = os.path.split(d)
    if head and Path(head).is_dir():
        return d                                     # the caller chose
    return os.path.join(last_dir(fallback), os.path.basename(d))


class file_dialogs:  # noqa: N801 — reads like QFileDialog at the call site
    """Drop-in for the four static QFileDialog pickers."""

    @staticmethod
    def _dir_arg(args, kwargs):
        if len(args) >= 3:
            return args[2], lambda v: (args[:2] + (v,) + args[3:], kwargs)
        return kwargs.get("dir", ""), lambda v: (args, {**kwargs, "dir": v})

    @staticmethod
    def _document_folder(parent):
        """The open document's folder, found through the dialog's parent
        (the main window, or a composer whose ``_window`` is one)."""
        for w in (parent, getattr(parent, "_window", None),
                  parent.window() if hasattr(parent, "window") else None):
            path = getattr(w, "_current_path", None)
            if path is not None:
                folder = Path(str(path)).parent
                if folder.is_dir():
                    return str(folder)
        return None

    @staticmethod
    def _run(fn, args, kwargs, pick):
        directory, put = file_dialogs._dir_arg(args, kwargs)
        parent = args[0] if args else kwargs.get("parent")
        fallback = file_dialogs._document_folder(parent) if parent is not None else None
        args, kwargs = put(start_in(directory, fallback))
        result = fn(*args, **kwargs)
        remember(pick(result))
        return result

    @staticmethod
    def getOpenFileName(*args, **kwargs):  # noqa: N802
        return file_dialogs._run(QFileDialog.getOpenFileName, args, kwargs,
                                 lambda r: r[0] if r else None)

    @staticmethod
    def getOpenFileNames(*args, **kwargs):  # noqa: N802
        return file_dialogs._run(QFileDialog.getOpenFileNames, args, kwargs,
                                 lambda r: (r[0][0] if r and r[0] else None))

    @staticmethod
    def getSaveFileName(*args, **kwargs):  # noqa: N802
        return file_dialogs._run(QFileDialog.getSaveFileName, args, kwargs,
                                 lambda r: r[0] if r else None)

    @staticmethod
    def getExistingDirectory(*args, **kwargs):  # noqa: N802
        return file_dialogs._run(QFileDialog.getExistingDirectory, args,
                                 kwargs, lambda r: r or None)
