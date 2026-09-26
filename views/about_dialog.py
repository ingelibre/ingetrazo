# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Help ▸ About IngeTrazo, with the contributors rolling like film credits.

The list of people whose work is IN the program keeps growing — a
draftsman's reports, a reviewer's drafting norms, a translation, the Mac
package, a whole tool — and a static paragraph of names would soon push
the dialog off the screen. So they roll up slowly in a band a few lines
tall, like the credits at the end of a film, round and round: nothing to
click, several people in view at once (Marco, 23-09 — a one-at-a-time
carousel paused under the mouse and read as needing clicks). AUTHORS
says what each one gave, in full.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr

#: (name, what they gave — English source for tr(), link or "").
CONTRIBUTORS = [
    ("Pedro Caeiro",
     "Draftsman. Pull requests and dozens of issue reports from daily "
     "drafting work: much of IngeTrazo's SketchUp parity.",
     "https://github.com/pacaeiro"),
    ("Rafael García Rodríguez",
     "Draftsman and 3D reviewer. Filmed reviews of the whole program and "
     "the drafting standards for dimensions.",
     "https://youtube.com/@Rafa3D"),
    ("Ahsan Mehmood",
     "Author of OpenSKP, the free SketchUp reader behind the .skp import; "
     "his plugin work became the Extensions system.",
     "https://github.com/iamahsanmehmood"),
    ("dafrobozao",
     "Brazilian Portuguese translation of the interface.",
     "https://github.com/dafrobozao"),
    ("Félix Riestra",
     "The macOS package: IngeTrazo for Mac. Components that come apart: "
     "parts, cut list and exploded view.",
     "https://github.com/felixriestra"),
    ("Gabriel Rodríguez",
     "The Back color in Styles and Edit ▸ Invert Selection.",
     "https://github.com/canalsecuario-blip"),
    ("José Castro Basso (FADU–UDELAR)",
     "Architect and teacher of architectural representation. Two-point "
     "perspective, the current view as DXF, and the Levels extension.",
     "https://github.com/castrobasso"),
    ("Sherod Taylor",
     "The First Person tool: walk the model like a game.",
     "https://github.com/sherodtaylor"),
    ("liuandy",
     "Simplified Chinese translation of the interface.",
     "https://github.com/liujvnes"),
]

#: Roll speed: pixels per tick, and the tick.
ROLL_PX = 1
ROLL_MS = 45


def _credits_html(people) -> str:
    rows = []
    for name, role, link in people:
        who = (f"<a href='{link}'><b>{name}</b></a>" if link
               else f"<b>{name}</b>")
        rows.append(f"<p style='margin:0 0 10px 0'>{who}<br>{tr(role)}</p>")
    return "".join(rows)


class _Fade(QWidget):
    """Soft top and bottom edges over the roll, in the window's colour."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QColor, QLinearGradient, QPainter
        bg = self.palette().window().color()
        clear = QColor(bg)
        clear.setAlpha(0)
        p = QPainter(self)
        edge = min(22, self.height() // 4)
        for y0, y1, a, b in ((0, edge, bg, clear),
                             (self.height() - edge, self.height(), clear, bg)):
            g = QLinearGradient(0, y0, 0, y1)
            g.setColorAt(0.0, a)
            g.setColorAt(1.0, b)
            p.fillRect(0, y0, self.width(), y1 - y0, g)
        p.end()


class _Credits(QWidget):
    """Every contributor, rolling up slowly and looping, like film credits.
    Two copies of the list sit one above the other; when the first has
    rolled out of view the roll starts over, seamlessly."""

    LINES = 11

    def __init__(self, people, parent=None) -> None:
        super().__init__(parent)
        self._people = list(people)
        html = _credits_html(self._people)
        self._copies = []
        for _ in range(2):
            lab = QLabel(html, self)
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.RichText)
            lab.setOpenExternalLinks(True)
            lab.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self._copies.append(lab)
        self._fade = _Fade(self)
        self.setFixedHeight(self.fontMetrics().lineSpacing() * self.LINES + 8)
        self._offset = 0.0
        self._span = 1
        self._timer = QTimer(self)
        self._timer.setInterval(ROLL_MS)
        self._timer.timeout.connect(self.tick)
        self._timer.start()

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    @property
    def offset(self) -> float:
        return self._offset

    @property
    def span(self) -> int:
        return self._span

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        w = self.width()
        self._span = max(1, self._copies[0].heightForWidth(w))
        for lab in self._copies:
            lab.resize(w, self._span)
        self._fade.setGeometry(0, 0, w, self.height())
        self._place()

    def tick(self) -> None:
        self._offset = (self._offset + ROLL_PX) % self._span
        self._place()

    def _place(self) -> None:
        y = -int(self._offset)
        self._copies[0].move(0, y)
        self._copies[1].move(0, y + self._span)
        self._fade.raise_()


class AboutDialog(QDialog):
    def __init__(self, parent, version: str, gl_line: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("About IngeTrazo"))
        self.setMinimumWidth(480)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 14)
        outer.setSpacing(16)
        from PySide6.QtWidgets import QApplication
        icon = QApplication.windowIcon()
        if not icon.isNull():
            pic = QLabel(self)
            pic.setPixmap(icon.pixmap(64, 64))
            pic.setAlignment(Qt.AlignTop)
            outer.addWidget(pic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        outer.addLayout(col, 1)

        def para(html: str) -> QLabel:
            lab = QLabel(html, self)
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.RichText)
            lab.setOpenExternalLinks(True)
            col.addWidget(lab)
            return lab

        # The top is one compact block, so the credits below get the room
        # (Marco, 23-09).
        gl = f"<br><small>OpenGL: {gl_line}</small>" if gl_line else ""
        para("<b style='font-size:15px'>IngeTrazo</b> "
             f"{tr('Version')} {version}{gl}<br>"
             f"{tr('Free 3D modeler for architecture, engineering and 3D design.')}<br>"
             f"{tr('Created by')} <b>Marco Sumari Tellez</b> — "
             f"{tr('Civil Engineer — Arequipa, Peru')}")
        head = para(f"<b>{tr('With contributions from')}</b>")
        head.setContentsMargins(0, 8, 0, 0)
        self.credits = _Credits(CONTRIBUTORS, self)
        col.addWidget(self.credits)
        para(f"<small>{tr('And thanks to everyone who tries IngeTrazo and reports what they find.')}</small>")
        para(f"<small>{tr('Licensed under GPL-3.0-or-later.')} · "
             "<a href='https://github.com/ingelibre/ingetrazo'>"
             "github.com/ingelibre/ingetrazo</a></small>")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok, self)
        buttons.accepted.connect(self.accept)
        col.addWidget(buttons)
