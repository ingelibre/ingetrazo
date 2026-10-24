# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Blueprint startup screen shown while the workspace is prepared."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QWidget

from core.i18n import tr
from core.paths import app_root
from core.version import __version__


class StartupSplash(QWidget):
    """A branded, progress-reporting cover for the first workspace layout."""

    _BASE_WIDTH = 1000
    _ASPECT = 1.5

    def __init__(self) -> None:
        flags = (Qt.WindowType.SplashScreen
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint)
        super().__init__(None, flags)
        self.setWindowTitle("IngeTrazo")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        root = app_root() / "resources"
        self._art = QPixmap(str(root / "ui" / "startup_blueprint.png"))
        self._logo = QPixmap(str(root / "icons" / "ingetrazo_512.png"))
        self._scaled_art = QPixmap()
        self._art_size = None
        self._version = f"v{__version__}"
        self._heading = tr("Preparing workspace")
        self._detail = tr("Getting things ready…")
        self._progress: int | None = 4
        self.setFixedSize(*self._initial_size())
        if not self._art.isNull():
            self._scaled_art = self._art.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            self._art_size = (self.width(), self.height())
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.center().x() - self.width() // 2,
                      area.center().y() - self.height() // 2)

    def _initial_size(self) -> tuple[int, int]:
        screen = QApplication.primaryScreen()
        if screen is None:
            return 720, 480
        area = screen.availableGeometry()
        width = min(864, int(area.width() * 0.738))
        height = min(int(width / self._ASPECT), int(area.height() * 0.738))
        width = int(height * self._ASPECT)
        return max(540, width), max(360, height)

    def set_progress(self, heading: str, value: int | None,
                     detail: str = "") -> None:
        """Update the visible phase and progress without pumping app events."""
        self._heading = heading
        self._progress = None if value is None else max(0, min(100, int(value)))
        self._detail = detail
        self.repaint()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        size = event.size()
        key = (size.width(), size.height())
        if self._art.isNull() or key == self._art_size:
            return
        self._scaled_art = self._art.scaled(
            size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation)
        self._art_size = key

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        scale = self.width() / self._BASE_WIDTH
        inset = max(7, round(9 * scale))
        frame = QRectF(inset, inset, self.width() - 2 * inset,
                       self.height() - 2 * inset)
        clip = QPainterPath()
        clip.addRoundedRect(frame, 14 * scale, 14 * scale)
        painter.setClipPath(clip)
        painter.fillRect(self.rect(), QColor("#06162c"))

        if not self._scaled_art.isNull():
            x = (self.width() - self._scaled_art.width()) // 2
            y = (self.height() - self._scaled_art.height()) // 2
            painter.drawPixmap(x, y, self._scaled_art)

        # A dark left veil gives the logo and status enough contrast while
        # leaving the plan and the illuminated blueprint visible underneath.
        veil = QLinearGradient(0, 0, self.width() * 0.69, 0)
        veil.setColorAt(0.0, QColor(3, 15, 32, 225))
        veil.setColorAt(0.58, QColor(4, 20, 40, 178))
        veil.setColorAt(1.0, QColor(4, 20, 40, 0))
        painter.fillRect(self.rect(), veil)

        # Fine double edge, in the blueprint blue used by the official mark.
        painter.setClipping(False)
        painter.setPen(QPen(QColor("#3689e6"), max(1, scale)))
        painter.drawRoundedRect(frame.adjusted(0.5, 0.5, -0.5, -0.5),
                                14 * scale, 14 * scale)

        # Official bundled IngeTrazo cube icon, kept as-is.
        logo_size = round(76 * scale)
        logo_x, logo_y = round(70 * scale), round(76 * scale)
        if not self._logo.isNull():
            painter.drawPixmap(logo_x, logo_y, logo_size, logo_size, self._logo)

        wordmark_x = round(164 * scale)
        wordmark_y = round(129 * scale)
        wordmark_font = QFont("Segoe UI", max(20, round(43 * scale)),
                              QFont.Weight.DemiBold)
        painter.setFont(wordmark_font)
        painter.setPen(QColor("#f5f8fc"))
        painter.drawText(wordmark_x, wordmark_y, "Inge")
        inge_width = painter.fontMetrics().horizontalAdvance("Inge")
        painter.setPen(QColor("#4d9df0"))
        painter.drawText(wordmark_x + inge_width, wordmark_y, "Trazo")

        tagline_font = QFont("Segoe UI", max(8, round(10 * scale)))
        tagline_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                                      2.4 * scale)
        painter.setFont(tagline_font)
        painter.setPen(QColor(184, 207, 229, 195))
        painter.drawText(wordmark_x + 2, round(155 * scale),
                         tr("DESIGN  •  MODEL  •  BUILD"))

        left = round(78 * scale)
        bar_width = round(414 * scale)
        bar_y = round(self.height() * 0.707)
        title_font = QFont("Segoe UI", max(11, round(15 * scale)),
                           QFont.Weight.Medium)
        painter.setFont(title_font)
        painter.setPen(QColor("#f4f7fb"))
        painter.drawText(left, bar_y - round(18 * scale), self._heading)

        bar = QRectF(left, bar_y, bar_width, max(8, 10 * scale))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(116, 151, 180, 82))
        painter.drawRoundedRect(bar, bar.height() / 2, bar.height() / 2)
        if self._progress is None:
            # The short moving segment keeps an unmeasurable startup phase
            # visibly alive without inventing a percentage.
            fill_width = bar.width() * 0.24
        else:
            fill_width = bar.width() * self._progress / 100
        if fill_width > 0:
            fill = QRectF(bar.left(), bar.top(), fill_width, bar.height())
            fill_gradient = QLinearGradient(fill.topLeft(), fill.topRight())
            fill_gradient.setColorAt(0, QColor("#2874cc"))
            fill_gradient.setColorAt(1, QColor("#4d9df0"))
            painter.setBrush(fill_gradient)
            painter.drawRoundedRect(fill, bar.height() / 2, bar.height() / 2)

        label_font = QFont("Segoe UI", max(8, round(10 * scale)))
        painter.setFont(label_font)
        painter.setPen(QColor(218, 230, 242, 210))
        percent = "—" if self._progress is None else f"{self._progress}%"
        painter.drawText(round(left + bar_width + 14 * scale),
                         round(bar_y + 8 * scale), percent)

        detail_font = QFont("Segoe UI", max(9, round(11 * scale)))
        painter.setFont(detail_font)
        painter.setPen(QColor(171, 194, 215, 220))
        detail_rect = QRectF(left, bar_y + round(21 * scale),
                             self.width() * 0.52, round(32 * scale))
        painter.drawText(detail_rect, Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignVCenter, self._detail)

        footer_y = self.height() - round(39 * scale)
        painter.setPen(QPen(QColor(54, 137, 230, 180), max(1, scale)))
        painter.drawLine(left, footer_y - round(8 * scale),
                         left + round(34 * scale), footer_y - round(8 * scale))
        footer_font = QFont("Segoe UI", max(7, round(8 * scale)))
        footer_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                                     1.6 * scale)
        painter.setFont(footer_font)
        painter.setPen(QColor(179, 200, 220, 195))
        painter.drawText(left + round(45 * scale), footer_y,
                         tr("IDEAS INTO REAL SPACES"))
        version_font = QFont("Segoe UI", max(7, round(8 * scale)))
        painter.setFont(version_font)
        painter.setPen(QColor(177, 199, 219, 205))
        painter.drawText(self.width() - round(96 * scale), footer_y,
                         self._version)
        painter.end()
