# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sample settings from a style collection and apply them one category at a time."""
from __future__ import annotations

import json

from PySide6.QtCore import QMimeData, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from core.i18n import tr
from core.style import BUILTIN_STYLES, user_styles
from core.style_mix import STYLE_CATEGORIES
from views.icons import tool_icon
from views.style_preview import style_preview
from views.theme import style as theme_style

_MIME = "application/x-ingetrazo-style-source"


class _SourceList(QListWidget):
    def mimeData(self, items):
        mime = QMimeData()
        if items:
            mime.setData(_MIME, json.dumps(items[0].data(Qt.UserRole)).encode("utf-8"))
        return mime

    def supportedDropActions(self):
        return Qt.CopyAction


class _CategoryTarget(QToolButton):
    def __init__(self, resolve_source, apply_source, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._resolve = resolve_source
        self._apply = apply_source

    def dragEnterEvent(self, event):
        if self._resolve(event.mimeData()) is not None:
            self.setDown(True)
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            self.setDown(False)
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self.setDown(False)
        event.accept()

    def dropEvent(self, event):
        self.setDown(False)
        source = self._resolve(event.mimeData())
        if source is not None:
            self._apply(source)
            event.setDropAction(Qt.CopyAction)
            event.accept()


class StyleMixPanel(QWidget):
    def __init__(self, categories, apply_category, parent=None):
        super().__init__(parent)
        self._apply_category = apply_category
        self._source = None
        self._source_key = None
        self._styles = {}
        self._signature = None
        self._updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        notice = QLabel(tr("Choose a source style below, then click a category or drag the style onto it."))
        notice.setWordWrap(True)
        theme_style(notice, "color:{muted};")
        layout.addWidget(notice)
        source_row = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(56, 44)
        source_row.addWidget(self.preview)
        self.source_label = QLabel()
        self.source_label.setTextFormat(Qt.PlainText)
        self.source_label.setWordWrap(True)
        source_row.addWidget(self.source_label, 1)
        layout.addLayout(source_row)
        self.targets = {}
        for category, (title, icon) in zip(STYLE_CATEGORIES, categories):
            button = _CategoryTarget(self._resolve_drop,
                                     lambda source, key=category: self._apply(key, source), self)
            button.setText(tr(title))
            button.setIcon(tool_icon(icon))
            button.setProperty("icon_key", icon)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda _checked=False, key=category: self._apply(key))
            self.targets[category] = button
            layout.addWidget(button)
        self.collection = QComboBox()
        self.collection.addItem(tr("Built-in styles"), "builtin")
        self.collection.addItem(tr("My styles"), "user")
        self.collection.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.collection)
        self.browser = _SourceList()
        self.browser.setAccessibleName(tr("Source styles"))
        self.browser.setViewMode(QListWidget.IconMode)
        self.browser.setResizeMode(QListWidget.Adjust)
        self.browser.setMovement(QListWidget.Static)
        self.browser.setIconSize(QSize(64, 52))
        self.browser.setGridSize(QSize(102, 86))
        self.browser.setMinimumHeight(96)
        self.browser.setDragEnabled(True)
        self.browser.setDefaultDropAction(Qt.CopyAction)
        self.browser.currentItemChanged.connect(self._select_source)
        layout.addWidget(self.browser, 1)
        self.empty_hint = QLabel(tr("No saved styles yet. Use Save style… to add the current style here."))
        self.empty_hint.setWordWrap(True)
        theme_style(self.empty_hint, "color:{muted};")
        layout.addWidget(self.empty_hint)
        self.refresh()

    def refresh(self, *_args):
        users = user_styles()
        collection = self.collection.currentData()
        signature = (collection, tuple(style.to_dict() for style in users))
        if signature != self._signature:
            self._signature = signature
            self._updating = True
            try:
                self.browser.clear()
                presets = BUILTIN_STYLES if collection == "builtin" else users
                self._styles = {(collection, style.name): style.copy() for style in presets}
                for style in presets:
                    label = tr(style.name) if collection == "builtin" else style.name
                    item = QListWidgetItem(QIcon(style_preview(style, QSize(64, 52))), label)
                    item.setToolTip(label)
                    item.setData(Qt.UserRole, (collection, style.name))
                    self.browser.addItem(item)
                    if (collection, style.name) == self._source_key:
                        self.browser.setCurrentItem(item)
                if self._source_key not in self._styles:
                    self._source_key = None
            finally:
                self._updating = False
        self.empty_hint.setVisible(collection == "user" and not users)
        self._select_source()

    def _select_source(self, *_args):
        if self._updating:
            return
        item = self.browser.currentItem()
        self._source_key = tuple(item.data(Qt.UserRole)) if item else None
        source = self._styles.get(self._source_key)
        self._source = source.copy() if source is not None else None
        if source is None:
            self.preview.clear()
            self.source_label.setText(tr("Select a source style."))
        else:
            label = tr(source.name) if self._source_key[0] == "builtin" else source.name
            self.source_label.setText(tr("Source style: {name}", name=label))
            self.preview.setPixmap(style_preview(source, self.preview.size()))
        for button in self.targets.values():
            button.setEnabled(source is not None)

    def _resolve_drop(self, mime):
        if not mime.hasFormat(_MIME):
            return None
        try:
            key = json.loads(bytes(mime.data(_MIME)).decode("utf-8"))
            if not isinstance(key, list) or len(key) != 2 or not all(isinstance(x, str) for x in key):
                return None
            source = self._styles.get(tuple(key))
            return source.copy() if source is not None else None
        except (ValueError, UnicodeError):
            return None

    def _apply(self, category, source=None):
        source = source if source is not None else self._source
        if source is not None:
            self._apply_category(category, source.copy())
