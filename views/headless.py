# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""IngeTrazo with nobody at the screen: the window-less command line
(``-i … -p``), ``--headless`` (an instance an agent drives over the AI
bridge) and the bridge's own ``open_document``.

The sheets' views and the agent's screenshots are GL renders, so the main
window is still built and "shown" — that is what gives the viewport its GL
context — but with ``WA_DontShowOnScreen``: nothing reaches the desktop.
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer


class DialogRefuser(QObject):
    """Every dialog shown while it is installed is answered «Cancel» at
    once, as Escape would, and its text kept in :attr:`refused` — with
    nobody at the screen, ``exec()`` would otherwise wait for good."""

    def __init__(self) -> None:
        super().__init__()
        self.refused: list[str] = []

    def eventFilter(self, obj, event):  # noqa: N802 — Qt override
        if event.type() == QEvent.Show:
            from PySide6.QtWidgets import QDialog, QMessageBox
            if isinstance(obj, QDialog):
                text = obj.windowTitle()
                if isinstance(obj, QMessageBox) and obj.text():
                    text = f"{text}: {obj.text()}" if text else obj.text()
                self.refused.append(text or type(obj).__name__)
                # Not from inside the Show: exec() only enters its loop
                # after show() returns, and a reject before that is lost.
                QTimer.singleShot(0, obj, obj.reject)
        return False


def build_hidden_window(app):
    """The main window, built and "shown" off screen, extensions loaded,
    with no progress bar on any open. Returns it."""
    from views.main_window import MainWindow
    window = MainWindow(defer_extensions=True)
    window.setAttribute(Qt.WA_DontShowOnScreen, True)
    window.show()
    app.processEvents()
    # A real progress dialog that never shows (the DWG import sets its
    # range and its Cancel; a stand-in without them broke it).
    window._import_progress = lambda title: _silent_progress(window, title)
    window.load_extensions()
    return window


def _silent_progress(window, title):
    """A real progress dialog (the DWG import sets its range and its
    Cancel) that never shows itself: its minimum duration never passes."""
    from PySide6.QtWidgets import QProgressDialog
    dlg = QProgressDialog(title, "", 0, 100, window)
    dlg.setMinimumDuration(2 ** 31 - 1)
    dlg.setAutoClose(False)
    dlg.reset()
    return dlg, lambda frac, text: None


@contextlib.contextmanager
def quiet(window):
    """Opening and importing without anyone at the screen: no progress bar
    (one the bridge cancelled would abort the open — the bar's close is the
    user's close, #1269) and no «recover the auto-saved copy?» question,
    whose cancel deletes that copy. The file on disk is what is opened,
    and the auto-saved copy stays for the user — what ``ingetrazo -p``
    does too."""
    from core import autosave
    had = "_import_progress" in window.__dict__
    before = window.__dict__.get("_import_progress")
    pending = autosave.pending
    window._import_progress = lambda title: _silent_progress(window, title)
    # Only a FILE's recovery question: a new tab still asks which
    # untitled numbers are taken, or it would write over their slots.
    autosave.pending = (lambda path, untitled=1:
                        pending(path, untitled) if path is None else None)
    try:
        yield
    finally:
        autosave.pending = pending
        if had:
            window._import_progress = before
        else:
            window.__dict__.pop("_import_progress", None)


def open_quietly(window, path: Path) -> bool:
    """Open ``path`` in ``window`` with no question asked (see
    :func:`quiet`): the file on disk is what opens. True when it did. A
    failure's message box is answered by whatever refuses dialogs at the
    time (the bridge's guard, or :class:`DialogRefuser`)."""
    with quiet(window):
        return bool(window.open_path(Path(path)))


def attach_console() -> None:
    """A windowed Windows exe has no sys.stdout: borrow the console of
    the shell that started us, so the messages are seen there."""
    import os
    if sys.stdout is not None and sys.stderr is not None:
        return
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.AttachConsole(-1)   # ATTACH_PARENT_PROCESS
            sys.stdout = open("CONOUT$", "w", encoding="utf-8")
            sys.stderr = sys.stdout
            return
        except (OSError, AttributeError):
            pass
    # Nobody to talk to: the messages go nowhere instead of raising.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = sys.stdout
