# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Help ▸ Check for Updates…, and the same look once a day at start.

The look at start never interrupts: it runs off the GUI thread, says nothing
when up to date or offline, and its window neither blocks the model nor takes
the keyboard from a tool in use.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from core import update_check
from core.i18n import tr
from core.version import __version__

#: While a modal question is up (units at start, a save prompt), wait.
_RETRY_MS = 5000


class UpdateDialog(QDialog):
    """A newer version: its notes, and what to do about it."""

    def __init__(self, release, parent=None, current: str = __version__):
        super().__init__(parent)
        self.release = release
        self.setWindowTitle(tr("Updates"))
        self.setModal(False)
        self.resize(560, 460)
        col = QVBoxLayout(self)

        title = QLabel(tr("IngeTrazo {version} is available",
                          version=release.version))
        font = title.font()
        font.setPointSizeF(font.pointSizeF() * 1.3)
        font.setBold(True)
        title.setFont(font)
        col.addWidget(title)
        col.addWidget(QLabel(tr("You have version {current}. Published on {date}.",
                                current=current, date=release.date)))

        col.addWidget(QLabel(tr("What's new:")))
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMarkdown(release.notes)
        col.addWidget(self.notes, 1)

        row = QHBoxLayout()
        self.skip_button = QPushButton(tr("Skip This Version"))
        self.skip_button.clicked.connect(self._skip)
        row.addWidget(self.skip_button)
        row.addStretch(1)
        self.later_button = QPushButton(tr("Remind Me Later"))
        self.later_button.clicked.connect(self.reject)
        row.addWidget(self.later_button)
        self.download_button = QPushButton(tr("Download"))
        self.download_button.setDefault(True)
        self.download_button.clicked.connect(self._download)
        row.addWidget(self.download_button)
        col.addLayout(row)

    def _skip(self) -> None:
        update_check.skip_version(QSettings(), self.release.version)
        self.reject()

    def _download(self) -> None:
        from core.desktop_open import open_url
        open_url(self.release.url)
        self.accept()


class _Check(QObject):
    """Carries the answer from the worker thread back to the GUI thread."""

    answered = Signal(object, str)

    def __init__(self, window, quiet: bool, current: str):
        super().__init__(window)
        self.window = window
        self.quiet = quiet
        self.current = current
        # A bound method of this QObject, so Qt queues it onto the GUI thread.
        self.answered.connect(self._on_answer, Qt.QueuedConnection)

    def run(self, fetch) -> None:
        def work():
            try:
                result, error = fetch(), ""
            except update_check.UpdateCheckError as exc:
                result, error = None, str(exc) or "error"
            try:
                self.answered.emit(result, error)
            except RuntimeError:  # the window closed meanwhile
                pass
        threading.Thread(target=work, daemon=True).start()

    @Slot(object, str)
    def _on_answer(self, release, error: str) -> None:
        self.deleteLater()
        settings = QSettings()
        if error:
            if not self.quiet:
                QMessageBox.warning(self.window, tr("Updates"), tr(
                    "Could not check for updates. Check your internet "
                    "connection and try again."))
            return
        update_check.mark_checked(settings)
        if not update_check.is_newer(release.version, self.current):
            if not self.quiet:
                QMessageBox.information(self.window, tr("Updates"), tr(
                    "You have the latest version ({version}).",
                    version=self.current))
            return
        if self.quiet and update_check.is_skipped(settings, release.version):
            return
        show_release(self.window, release, self.quiet, self.current)


def show_release(window, release, quiet: bool, current: str = __version__) -> None:
    if quiet and QApplication.activeModalWidget() is not None:
        QTimer.singleShot(_RETRY_MS, window, lambda: show_release(
            window, release, quiet, current))
        return
    old = getattr(window, "_update_dialog", None)
    if old is not None:
        old.close()
        old.deleteLater()
    dialog = UpdateDialog(release, window, current)
    if quiet:
        dialog.setAttribute(Qt.WA_ShowWithoutActivating)
    window._update_dialog = dialog
    dialog.show()


def start_check(window, quiet: bool, fetch=None, current: str = __version__) -> None:
    """``quiet``: the look at start, subject to Preferences and once a day."""
    if quiet and not update_check.should_check_at_start(QSettings()):
        return
    _Check(window, quiet, current).run(fetch or update_check.fetch_latest)
