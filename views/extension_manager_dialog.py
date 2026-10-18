# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Searchable community extension catalog and installer."""
from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

from PySide6.QtCore import (QEvent, QObject, QPoint, QRunnable, Qt,
                            QStandardPaths,
                            QThreadPool, QTimer, QUrl, Signal)
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.i18n import current_language, tr
from core.extension_manager import (
    Extension,
    ExtensionManagerError,
    bundled_extensions,
    compatible_with_current,
    display_name,
    display_summary,
    extension_startup_state,
    hand_installed_ident,
    hand_installed_plugins,
    install_extension,
    installed_info,
    is_extension_enabled,
    is_reviewed,
    installation_conflict,
    load_cached_catalog,
    refresh_catalog,
    remove_hand_installed,
    replace_hand_installed,
    restart_required,
    set_extension_enabled,
    tested_version_is_old,
    uninstall_extension,
)
from views.tray import FlowLayout

log = logging.getLogger("ingetrazo.extensions")
_SCREENSHOT_BASE = (
    "https://raw.githubusercontent.com/ingelibre/"
    "ingetrazo-extensions/main/screenshots/")
#: The same files through the website (Cloudflare-cached), as its own
#: extensions page shows them: the second try when GitHub fails.
_SCREENSHOT_MIRROR = "https://ingetrazo.com/extensiones-img/"
#: A screenshot that failed is asked for again on its own — before, it
#: stayed «Preview unavailable» until the list was scrolled (caza 2).
_SCREENSHOT_RETRIES = 3
_SCREENSHOT_RETRY_MS = 2000
_MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024
_IMAGE_SIZE = (256, 160)  # 16:10
#: The screenshots already scaled for a card, kept while IngeTrazo runs, by
#: source file, its mtime and size. The manager is built anew each time it
#: opens, and each opening decoded the full screenshots again (some over
#: 3000 px wide): the cards came up «Preview unavailable» and filled in a
#: moment later (Marco, 18-10). Images, not pixmaps: they outlive dialogs.
_SCALED_SHOTS: dict[tuple, QImage] = {}
#: Between openings and runs, the scaled card image lives on disk beside
#: the screenshots: a few KB read at once instead of the full picture.
_THUMBS_DIR = "thumbs"
#: The rest of the screenshots already on disk are scaled in the
#: background a few at a time, once the visible ones are in, so scrolling
#: and the next opening find them ready.
_PREFETCH_DELAY_MS = 150
_PREFETCH_BATCH = 4
_ROW_MAX_HEIGHT = 300
_ROW_MAX_WIDTH = 660
#: The width a column of cards asks for: two at the usual size, three on a
#: maximised Full HD window, more on a wider one — no empty band at the
#: right (Marco, 09-10).
_COLUMN_WIDTH = 560
#: Windows shows a new window, white, through its opening animation and
#: until the first paint — ~0.4 s for this dialog on Marco's machine
#: (#555, his recording of 12-10). It opens transparent and appears once
#: painted, dark and complete.
_HIDE_UNTIL_PAINTED = sys.platform == "win32"

#: Everything a card wears, set ONCE on each page's card area (below the
#: page's own «background: palette(window)», which would win from above). Each card used to set
#: about a dozen style sheets of its own, and on Windows every
#: setStyleSheet builds and applies a style: 24 ms per card, over a second
#: with the app frozen before the manager could appear (#555, Marco's
#: measurement of 12-10). Each rule names the card, so it wins over the
#: card's own QLabel rule exactly as the widget's own sheet did.
_ROW = "QWidget#extensionRow"
_CARD_RULES = {
    "": "background: palette(base); border: 1px solid palette(midlight);",
    " QLabel": "background: transparent; border: none; "
               "color: palette(text);",
    " QLabel#extImage": "background: palette(alternate-base); "
                        "color: palette(text); border: none;",
    " QWidget#extImageDetails": "background: transparent;",
    " QLabel#extByline": "color: palette(text); font-size: 13px;",
    " QPushButton#extRepository":
        "color: palette(link); background: palette(base); "
        "border: 1px solid palette(midlight); border-radius: 4px; "
        "padding: 3px 7px; font-size: 11px;",
    " QPushButton#extRepository:hover":
        "color: palette(link); background: palette(alternate-base); "
        "border-color: palette(mid);",
    " QLabel#extChip": "color: palette(link); "
                       "background: palette(alternate-base); "
                       "border-radius: 8px; padding: 2px 6px; "
                       "font-size: 10px;",
    " QLabel#extLicense": "color: palette(text); font-weight: bold; "
                          "font-size: 13px;",
    " QLabel#extVersions": "color: palette(text); font-size: 10px; "
                           "font-weight: bold;",
    " QLabel#extBadge": "color: palette(link); "
                        "border: 1px solid palette(link); "
                        "border-radius: 3px; padding: 2px 5px; "
                        "font-size: 9px; font-weight: bold;",
    " QLabel#extTitle": "font-weight: bold; font-size: 15px; "
                        "color: palette(text); background: transparent;",
    " QLabel#extCommunity": "color: palette(link); font-size: 11px;",
    " QLabel#extRestart": "color: palette(link); font-weight: bold; "
                          "font-size: 11px;",
    " QLabel#extWarning": "color: palette(link);",
    " QLabel#extError": "color: palette(bright-text); font-weight: bold;",
    " QLabel#extHandTitle": "font-weight: bold; font-size: 15px;",
    " QLabel#extHandWhere": "color: palette(mid); font-size: 11px;",
}
_CARD_STYLE = "".join(f"{_ROW}{selector} {{ {rule} }}"
                      for selector, rule in _CARD_RULES.items())



#: The catalog's fixed tags (tools/catalog.py TAGS), named as the web page
#: names them; an unknown tag falls back to its own words.
_TAG_LABELS = {
    "architecture": "Architecture", "bim": "BIM", "structures": "Structures",
    "terrain": "Terrain", "drawing": "Drawing", "analysis": "Analysis",
    "import-export": "Import/export", "rendering": "Rendering",
    "fabrication": "Fabrication", "productivity": "Productivity",
    "education": "Education", "other": "Other",
}


def _screenshot_key(source: Path) -> tuple | None:
    try:
        stat = source.stat()
    except OSError:
        return None
    return (str(source), stat.st_mtime_ns, stat.st_size)


def _tag_label(tag: str) -> str:
    return tr(_TAG_LABELS.get(tag, tag.replace("-", " ").title()))

class _CatalogWorker(QObject):
    completed = Signal(object, object)

    def refresh(self) -> None:
        try:
            self.completed.emit(refresh_catalog(), None)
        except (ExtensionManagerError, OSError) as exc:
            self.completed.emit(None, exc)
        except Exception as exc:
            log.exception("unexpected error refreshing extension catalog")
            self.completed.emit(None, exc)


class _CatalogTask(QRunnable):
    def __init__(self) -> None:
        super().__init__()
        self.signals = _CatalogWorker()

    def run(self) -> None:
        self.signals.refresh()


class ExtensionManagerDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Manage extensions") + " — IngeTrazo")
        self.resize(1400, 860)
        self.setMinimumSize(1000, 650)
        self.setStyleSheet(
            "QDialog { background: palette(window); color: palette(window-text); }"
            "QScrollArea { background: palette(window); border: none; }"
            "QScrollArea > QWidget > QWidget { "
            "background: palette(window); }")
        self._extensions: list[Extension] = []
        self._reviewed: dict[str, dict] = {}
        self._catalog_snapshot = None
        self._catalog_worker = None
        startup_state = getattr(parent, "_extension_startup_state", None)
        self._startup_state = (startup_state if startup_state is not None
                               else extension_startup_state())
        self._requested_images: set[str] = set()
        self._image_failures: dict[str, int] = {}
        # Screenshots already decoded and scaled, by extension id: a card
        # built again (a filter, an install) is born with its image instead
        # of «Preview unavailable» and then the picture (#555).
        self._screenshots: dict[str, QPixmap] = {}
        self._unreadable_shots: set[str] = set()
        # Which cards are on screen is asked once the layout has placed
        # them; asked right after building, every card still sat at the
        # top-left and all the screenshots were decoded at once (#555).
        self._images_timer = QTimer(self)
        self._images_timer.setSingleShot(True)
        self._images_timer.setInterval(0)
        self._images_timer.timeout.connect(self._load_visible_images)
        self._prefetch_timer = QTimer(self)
        self._prefetch_timer.setSingleShot(True)
        self._prefetch_timer.setInterval(_PREFETCH_DELAY_MS)
        self._prefetch_timer.timeout.connect(self._prefetch_screenshots)
        self._waiting_first_paint = _HIDE_UNTIL_PAINTED
        if self._waiting_first_paint:
            self.setWindowOpacity(0.0)
        self._network = QNetworkAccessManager(self)
        self._pages: dict[str, dict] = {}

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        heading = QLabel(tr("Extensions"))
        heading.setStyleSheet("font-size: 24px; font-weight: bold")
        header.addWidget(heading)
        header.addStretch(1)
        self._catalog_info = QLabel(tr("Loading extension catalog…"))
        self._catalog_info.setStyleSheet(
            "color: palette(text); font-size: 11px")
        header.addWidget(self._catalog_info)
        self._refresh = QPushButton(tr("Refresh"))
        self._refresh.clicked.connect(self._load)
        header.addWidget(self._refresh)
        layout.addLayout(header)

        intro = QLabel(tr(
            "Tools the community adds to IngeTrazo. All are free software "
            "with published code; install only the ones you need."))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_page("browse"), tr("Browse"))
        self._tabs.addTab(self._build_page("installed"), tr("Installed"))
        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs, 1)

        footer = QHBoxLayout()
        warning = QLabel(tr(
            "Extensions are Python code. Only install extensions you trust."))
        warning.setWordWrap(True)
        footer.addWidget(warning, 1)
        close = QPushButton(tr("Close"))
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)
        self._load()

    def _build_page(self, key: str) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 8, 0, 0)

        search = QLineEdit()
        search.setPlaceholderText(tr("Search extensions…"))
        search.setStyleSheet(
            "QLineEdit { background: palette(base); color: palette(text); "
            "border: 1px solid palette(midlight); border-radius: 5px; "
            "padding: 7px 9px; }"
            "QLineEdit:focus { border-color: palette(link); }")
        search_timer = QTimer(page)
        search_timer.setSingleShot(True)
        search_timer.setInterval(180)
        search_timer.timeout.connect(lambda page_key=key:
                                     self._render_page(page_key))
        search.textChanged.connect(lambda _text, timer=search_timer:
                                   timer.start())

        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 10, 0)
        filters.addWidget(search, 1)
        reviewed = QCheckBox(tr("Reviewed only"))
        if key != "browse":
            # Hide only. setVisible(True) on a widget with no parent yet
            # makes it a window of its own and shows it (#555).
            reviewed.hide()
        reviewed.toggled.connect(
            lambda _checked, page_key=key: self._render_page(page_key))
        filters.addWidget(reviewed)
        sort = QComboBox()
        sort.addItem(tr("Catalog order"), "catalog")
        sort.addItem(tr("Recently updated"), "recent")
        sort.addItem(tr("Name A–Z"), "name")
        sort.addItem(tr("Reviewed first"), "reviewed")
        sort.addItem(tr("Installed first"), "installed")
        sort.addItem(tr("Updates available"), "updates")
        sort.setStyleSheet(
            "QComboBox { color: palette(text); background: palette(base); "
            "border: 1px solid palette(midlight); border-radius: 5px; "
            "padding: 5px 8px; }"
            "QComboBox:hover { color: palette(text); "
            "background: palette(base); }"
            "QComboBox QAbstractItemView { color: palette(text); "
            "background: palette(base); "
            "selection-color: palette(highlighted-text); "
            "selection-background-color: palette(highlight); }"
            "QComboBox QAbstractItemView::item:hover { "
            "color: palette(text); background: palette(alternate-base); }")
        sort.currentIndexChanged.connect(
            lambda _index, page_key=key: self._render_page(page_key))
        filters.addWidget(sort)
        page_layout.addLayout(filters)

        tags_scroll = QScrollArea()
        tags_scroll.setFrameShape(QFrame.NoFrame)
        tags_scroll.setWidgetResizable(True)
        tags_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        tags_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tags_scroll.setFixedHeight(42)
        tags_scroll.setStyleSheet(
            "QScrollArea { background: palette(window); }")
        tags_content = QWidget()
        tags_content.setMinimumHeight(38)
        tags_content.setStyleSheet("background: palette(window);")
        tags_layout = QHBoxLayout(tags_content)
        tags_layout.setContentsMargins(1, 2, 1, 2)
        tags_layout.setSpacing(8)
        tags_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        tags_group = QButtonGroup(page)
        tags_group.setExclusive(True)
        tags_scroll.setWidget(tags_content)
        page.setStyleSheet("background: palette(window);")
        page_layout.addWidget(tags_scroll)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Plain)
        divider.setStyleSheet("color: palette(midlight);")
        page_layout.addWidget(divider)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.verticalScrollBar().valueChanged.connect(
            self._images_timer.start)
        cards = QWidget()
        cards.setStyleSheet(_CARD_STYLE)
        grid = QGridLayout(cards)
        grid.setContentsMargins(2, 2, 2, 12)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(18)
        grid.setAlignment(Qt.AlignTop)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        scroll.setWidget(cards)
        scroll.viewport().installEventFilter(self)   # columns follow width
        page_layout.addWidget(scroll, 1)

        self._pages[key] = {
            "search": search,
            "search_timer": search_timer,
            "filters": filters,
            "tags_scroll": tags_scroll,
            "tags_layout": tags_layout,
            "tags_group": tags_group,
            "tag": "",
            "reviewed": reviewed,
            "sort": sort,
            "divider": divider,
            "scroll": scroll,
            "cards": cards,
            "grid": grid,
            "image_labels": {},
            "shown": 0,
            "total": 0,
        }
        return page

    def _load(self) -> None:
        if self._catalog_worker is not None:
            return
        cached = load_cached_catalog()
        if cached is not None:
            self._apply_catalog(cached)
        elif not self._extensions:
            self._catalog_info.setText(tr("Loading extension catalog…"))
        self._refresh.setEnabled(False)
        worker = _CatalogTask()
        worker.signals.completed.connect(
            self._catalog_loaded, Qt.QueuedConnection)
        self._catalog_worker = worker
        QThreadPool.globalInstance().start(worker)

    def _apply_catalog(self, snapshot) -> None:
        previous = self._catalog_snapshot
        self._catalog_snapshot = snapshot
        if (previous is not None
                and snapshot.extensions == previous.extensions
                and snapshot.reviewed == previous.reviewed):
            # The refresh brought the catalog already on screen (the usual
            # case: the cached copy shows first): only the date changes.
            # Rebuilding both pages repainted the whole window (#555).
            self._show_count(self._active_page_key())
            return
        self._extensions = self._with_bundled(snapshot.extensions)
        self._reviewed = snapshot.reviewed
        for key in self._pages:
            recent_index = self._pages[key]["sort"].findData("recent")
            if recent_index >= 0:
                recent_item = self._pages[key]["sort"].model().item(
                    recent_index)
                has_update_dates = any(
                    extension.updated_at for extension in self._extensions)
                recent_item.setEnabled(has_update_dates)
            else:
                recent_item = None
            if recent_item is not None and not recent_item.isEnabled():
                self._pages[key]["sort"].setItemData(
                    recent_index,
                    tr("The catalog does not include per-extension update "
                       "dates."),
                    Qt.ToolTipRole)
            self._populate_tags(key)
            self._render_page(key)

    def _catalog_loaded(self, snapshot, error) -> None:
        self._catalog_worker = None
        self._refresh.setEnabled(True)
        if snapshot is not None:
            self._apply_catalog(snapshot)
        elif self._catalog_snapshot is None:
            # Offline with no cached catalog: what ships with IngeTrazo
            # still installs from here.
            self._extensions = self._with_bundled([])
            for key in self._pages:
                self._render_page(key)
            self._catalog_info.setText(
                tr("Could not load extensions: {error}", error=str(error)))
        else:
            self._catalog_info.setText(tr(
                "Could not refresh catalog. Showing the last cached catalog "
                "from {date}. {error}",
                date=self._catalog_snapshot.fetched_at, error=str(error)))

    @staticmethod
    def _with_bundled(catalog: list) -> list:
        """The catalog plus the extensions shipped with IngeTrazo that
        it does not list (Windowizer); a catalog entry wins over a bundled
        one with the same id (Levels, Polygon properties)."""
        known = {e.id for e in catalog}
        return list(catalog) + [b for b in bundled_extensions()
                                if b.id not in known]

    def _active_page_key(self) -> str:
        return "browse" if self._tabs.currentIndex() == 0 else "installed"

    def _active_page(self) -> dict:
        return self._pages[self._active_page_key()]

    def _populate_tags(self, key: str) -> None:
        page = self._pages[key]
        layout = page["tags_layout"]
        group = page["tags_group"]
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                group.removeButton(widget)
                widget.deleteLater()
        tags = sorted({tag for extension in self._extensions
                       for tag in extension.tags})
        self._add_tag_button(key, tr("All"), "")
        for tag in tags:
            self._add_tag_button(key, _tag_label(tag), tag)
        tags_content = page["tags_scroll"].widget()
        tags_content.adjustSize()
        tags_content.setFixedWidth(max(
            page["tags_scroll"].viewport().width(),
            tags_content.layout().sizeHint().width()))
        if page["tag"] and page["tag"] not in tags:
            page["tag"] = ""
        for button in group.buttons():
            if button.property("tag") == page["tag"]:
                button.setChecked(True)

    def _add_tag_button(self, key: str, label: str, tag: str) -> None:
        page = self._pages[key]
        button = QToolButton()
        button.setText(label)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setCheckable(True)
        button.setProperty("tag", tag)
        button.setStyleSheet(
            "QToolButton { color: palette(text); background: palette(base); "
            "border: 1px solid palette(midlight); border-radius: 12px; "
            "padding: 4px 10px; }"
            "QToolButton:checked { background: palette(highlight); "
            "color: palette(highlighted-text); "
            "border-color: palette(highlight); }")
        button.clicked.connect(
            lambda _checked=False, page_key=key, selected=tag:
            self._select_tag(page_key, selected))
        page["tags_group"].addButton(button)
        page["tags_layout"].addWidget(button)
        if tag == page["tag"]:
            button.setChecked(True)

    def _select_tag(self, key: str, tag: str) -> None:
        self._pages[key]["tag"] = tag
        self._render_page(key)

    def _clear_cards(self, key: str) -> None:
        page = self._pages[key]
        grid = page["grid"]
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Out of the layout is not off the screen: until deleteLater
                # runs, the old card would be painted under the new ones.
                widget.hide()
                widget.deleteLater()
        page["image_labels"].clear()

    def _filtered_extensions(self, key: str | None = None) -> list[Extension]:
        key = key or self._active_page_key()
        page = self._pages[key]
        query = page["search"].text().strip().casefold()
        installed_only = key == "installed"
        result = []
        for extension in self._extensions:
            info = installed_info(extension.id)
            if (installed_only and info is None
                    and not installation_conflict(extension.id)):
                continue
            if page["tag"] and page["tag"] not in extension.tags:
                continue
            if page["reviewed"].isChecked() and not is_reviewed(
                    extension, self._reviewed):
                continue
            searchable = " ".join((
                extension.id, extension.author, extension.license,
                extension.version, " ".join(extension.name.values()),
                " ".join(extension.summary.values()),
                " ".join(extension.tags),
            )).casefold()
            if query and query not in searchable:
                continue
            result.append(extension)
        sort_key = page["sort"].currentData()
        if sort_key == "name":
            result.sort(key=lambda ext: display_name(
                ext, current_language()).casefold())
        elif sort_key == "reviewed":
            result.sort(key=lambda ext: (
                not is_reviewed(ext, self._reviewed),
                display_name(ext, current_language()).casefold()))
        elif sort_key == "installed":
            result.sort(key=lambda ext: (
                installed_info(ext.id) is None,
                display_name(ext, current_language()).casefold()))
        elif sort_key == "updates":
            result.sort(key=lambda ext: (
                not self._update_available(ext),
                display_name(ext, current_language()).casefold()))
        elif sort_key == "recent":
            result.sort(key=lambda ext: (
                ext.updated_at is not None, ext.updated_at or ""),
                reverse=True)
        return result

    @staticmethod
    def _update_available(extension: Extension) -> bool:
        info = installed_info(extension.id)
        return info is not None and info.get("sha256") != extension.sha256

    def _render_page(self, key: str, *_args) -> None:
        page = self._pages[key]
        cards = page["cards"]
        # One repaint for the whole swap, not one per card taken out and
        # put in: on Windows the half-built page showed as a flash (#555).
        cards.setUpdatesEnabled(False)
        try:
            self._clear_cards(key)
            extensions = self._filtered_extensions(key)
            language = current_language()
            rows = [self._make_row(extension, language, cards, key)
                    for extension in extensions]
            unknown = self._hand_only(key) if key == "installed" else []
            rows += [self._make_hand_row(path, cards) for path in unknown]
            self._place_cards(key, rows)
        finally:
            cards.setUpdatesEnabled(True)
        page["shown"] = len(extensions) + len(unknown)
        page["total"] = (sum(installed_info(e.id) is not None
                             or installation_conflict(e.id)
                             for e in self._extensions)
                         + len(self._hand_only(key, filtered=False))
                         if key == "installed" else len(self._extensions))
        if key == self._active_page_key():
            self._show_count(key)
            self._images_timer.start()

    def _show_count(self, key: str) -> None:
        page = self._pages[key]
        self._catalog_info.setText(
            tr("{shown} of {total} extensions",
               shown=page["shown"], total=page["total"])
            + self._catalog_status_suffix())

    def _columns(self, key: str) -> int:
        """How many columns of cards fit the page's width."""
        width = self._pages[key]["scroll"].viewport().width()
        return max(1, width // _COLUMN_WIDTH)

    def _place_cards(self, key: str, rows: list) -> None:
        """Lay the cards out in as many columns as fit, in order."""
        grid = self._pages[key]["grid"]
        columns = self._columns(key)
        for column in range(max(columns, grid.columnCount())):
            grid.setColumnStretch(column, 1 if column < columns else 0)
        for index, row in enumerate(rows):
            grid.addWidget(row, index // columns, index % columns)
        self._pages[key]["columns"] = columns

    def eventFilter(self, obj, event) -> bool:
        # A wider or narrower card area: the same cards, in the columns
        # that fit now — moved, not rebuilt (their images stay).
        if event.type() == QEvent.Resize:
            for key, page in getattr(self, "_pages", {}).items():
                if (obj is page["scroll"].viewport()
                        and self._columns(key) != page.get("columns")):
                    grid = page["grid"]
                    rows = [grid.itemAt(i).widget()
                            for i in range(grid.count())]
                    for row in rows:
                        grid.removeWidget(row)
                    self._place_cards(key, rows)
        return super().eventFilter(obj, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._images_timer.start()
        if self._waiting_first_paint:
            # Never left invisible, whatever happens to the first paint.
            QTimer.singleShot(600, self._reveal)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._waiting_first_paint:
            # After this paint reaches the screen, not inside it.
            self._waiting_first_paint = False
            QTimer.singleShot(0, self._reveal)

    def _reveal(self) -> None:
        self.setWindowOpacity(1.0)

    def _on_tab_changed(self, _index: int) -> None:
        # Both pages are rebuilt whenever what they show changes (catalog,
        # install, enable, their own filters), so a tab change only shows
        # the other one. Rebuilding it here, on every switch, was the
        # flash between the two tabs (#555).
        key = self._active_page_key()
        self._show_count(key)
        self._images_timer.start()

    def _make_row(self, extension: Extension, language: str,
                  parent: QWidget, page_key: str) -> QWidget:
        info = installed_info(extension.id)
        managed = info is not None
        enabled = is_extension_enabled(extension.id) if managed else False
        current = managed and info.get("sha256") == extension.sha256
        compatible = compatible_with_current(extension)
        reviewed = is_reviewed(extension, self._reviewed)
        conflict = installation_conflict(extension.id)
        load_error = getattr(self.parent(), "_extension_load_errors", {}).get(
            extension.id)
        update_available = managed and not current

        row = QWidget(parent)
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.setMinimumWidth(400)
        row.setMaximumHeight(_ROW_MAX_HEIGHT)
        row.setMaximumWidth(_ROW_MAX_WIDTH)
        row.setObjectName("extensionRow")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(10, 10, 10, 8)
        row_layout.setSpacing(8)
        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)

        image = QLabel(tr("Preview unavailable"))
        image.setAlignment(Qt.AlignCenter)
        image.setFixedSize(*_IMAGE_SIZE)
        image.setObjectName("extImage")
        self._pages[page_key]["image_labels"][extension.id] = image
        cached = self._screenshots.get(extension.id)
        if cached is None:
            cached = self._remembered_screenshot(extension)
        if cached is not None:
            image.setPixmap(cached)
            image.setText("")

        image_details = QWidget()
        image_details.setFixedWidth(_IMAGE_SIZE[0])
        image_details.setAutoFillBackground(False)
        image_details.setObjectName("extImageDetails")
        image_column = QVBoxLayout(image_details)
        image_column.setContentsMargins(0, 0, 0, 0)
        image_column.setSpacing(6)
        image_column.addWidget(image, 0, Qt.AlignTop)
        author_row = QHBoxLayout()
        author_row.setSpacing(6)
        byline = QLabel(tr("by {author}", author=extension.author))
        byline.setWordWrap(True)
        byline.setObjectName("extByline")
        author_row.addWidget(byline, 1)
        repository = QPushButton(tr("Repository ↗"))
        repository.setCursor(Qt.PointingHandCursor)
        repository.setObjectName("extRepository")
        # The catalog's check only admits https:// — enforced here too, so
        # a tampered cache cannot hand the browser a file:// or app link.
        repository.setEnabled(extension.repository.startswith("https://"))
        if extension.bundled:
            # Hide only: setVisible(True) here, before the button is in the
            # card, made it a window of its own and showed it — on Windows
            # 43 little windows flashed while the manager was built, ~0.8 s
            # of the 0.9 s it took (#555, measured on Marco's machine).
            repository.hide()
        repository.clicked.connect(
            lambda _checked=False, url=extension.repository:
            QDesktopServices.openUrl(QUrl(url)))
        author_row.addWidget(repository)
        image_column.addLayout(author_row)
        tags_row = FlowLayout(spacing=5)
        for tag in extension.tags:
            chip = QLabel(_tag_label(tag))
            chip.setWordWrap(True)
            chip.setMaximumWidth(_IMAGE_SIZE[0])
            chip.setObjectName("extChip")
            tags_row.addWidget(chip)
        image_column.addLayout(tags_row)
        license_label = QLabel(
            tr("Included with IngeTrazo") if extension.bundled
            else tr("License: {license}", license=extension.license))
        license_label.setWordWrap(True)
        license_label.setObjectName("extLicense")
        image_column.addWidget(license_label)
        content.addWidget(image_details, 0, Qt.AlignTop)

        details = QVBoxLayout()
        details.setSpacing(5)
        version_row = QHBoxLayout()
        version_row.addStretch(1)
        versions = QLabel(
            tr("Ships with IngeTrazo {version}", version=extension.version)
            if extension.bundled else
            tr("v{version} · Tested with IngeTrazo {tested}",
               version=extension.version, tested=extension.minimum_version))
        versions.setObjectName("extVersions")
        version_row.addWidget(versions, 0, Qt.AlignTop)
        if reviewed or extension.bundled:
            badge = QLabel(tr("INCLUDED") if extension.bundled
                           else tr("REVIEWED"))
            badge.setObjectName("extBadge")
            version_row.addWidget(badge, 0, Qt.AlignTop)
        details.addLayout(version_row)

        title_row = QHBoxLayout()
        title = QLabel(display_name(extension, language))
        title.setWordWrap(False)
        title.setObjectName("extTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        details.addLayout(title_row)

        summary = QLabel(display_summary(extension, language))
        summary.setWordWrap(True)
        summary.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        summary.setMaximumHeight(100)
        details.addWidget(summary)
        if not reviewed and not extension.bundled:
            community = QLabel(tr(
                "Community extension — not reviewed by an IngeTrazo "
                "maintainer."))
            community.setWordWrap(True)
            community.setObjectName("extCommunity")
            details.addWidget(community)
        if restart_required(extension.id, self._startup_state):
            restart = QLabel(tr("Restart required to apply changes"))
            restart.setObjectName("extRestart")
            restart.setWordWrap(True)
            details.addWidget(restart)
        if not compatible:
            warning = QLabel(tr("Requires IngeTrazo {version} or later.",
                                version=extension.minimum_version))
            warning.setWordWrap(True)
            details.addWidget(warning)
        elif tested_version_is_old(extension):
            warning = QLabel(tr(
                "Compatibility is uncertain: this extension was tested with "
                "IngeTrazo {version}.",
                version=extension.minimum_version))
            warning.setWordWrap(True)
            warning.setObjectName("extWarning")
            details.addWidget(warning)
        if load_error:
            error_label = QLabel(tr("Failed to load at startup"))
            error_label.setObjectName("extError")
            details.addWidget(error_label)
            error_button = QPushButton(tr("View load error"))
            error_button.clicked.connect(
                lambda _checked=False, e=extension, failure=load_error:
                self._show_load_error(e, failure))
            details.addWidget(error_button)

        details.addStretch(1)
        if managed:
            if update_available:
                state = tr("Update available: v{installed} → v{available}",
                           installed=info.get("version", tr("unknown")),
                           available=extension.version)
            else:
                state = tr("Up to date · v{version}",
                           version=extension.version)
            if not enabled:
                state += " · " + tr("Disabled")
            details.addWidget(QLabel(state))
        elif conflict:
            hand = QLabel(tr("Installed by hand, outside the extension "
                             "manager."))
            hand.setWordWrap(True)
            details.addWidget(hand)

        actions = QHBoxLayout()
        if conflict and not managed:
            # Installed by hand before the manager existed (or copied in):
            # the catalog version replaces it, or it is set aside.
            if compatible:
                replace = QPushButton(
                    tr("Replace with the version included with IngeTrazo")
                    if extension.bundled
                    else tr("Replace with the catalog version"))
                replace.clicked.connect(
                    lambda _checked=False, e=extension: self._replace(e))
                actions.addWidget(replace)
            remove = QPushButton(tr("Uninstall"))
            remove.clicked.connect(
                lambda _checked=False, e=extension:
                self._uninstall_hand_ident(e.id, display_name(
                    e, current_language())))
            actions.addWidget(remove)
        elif compatible:
            install = QPushButton(
                tr("Update") if update_available
                else tr("Up to date") if managed
                else tr("Install") if extension.bundled
                else tr("Download"))
            install.setEnabled(not current and (managed or not conflict))
            install.clicked.connect(
                lambda _checked=False, e=extension: self._install(e))
            actions.addWidget(install)
        if managed:
            if enabled or compatible:
                toggle = QPushButton(tr("Disable") if enabled else tr("Enable"))
                if load_error:
                    toggle.setText(tr("Disable extension"))
                toggle.clicked.connect(
                    lambda _checked=False, e=extension: self._toggle(e))
                actions.addWidget(toggle)
            uninstall = QPushButton(tr("Uninstall"))
            uninstall.clicked.connect(
                lambda _checked=False, e=extension: self._uninstall(e))
            actions.addWidget(uninstall)
        if load_error:
            folder_button = QPushButton(tr("Open extension folder"))
            folder_button.clicked.connect(
                lambda _checked=False, e=extension:
                self._open_extension_folder(e.id))
            actions.addWidget(folder_button)
            logs_button = QPushButton(tr("Open logs folder"))
            logs_button.clicked.connect(self._open_logs_folder)
            actions.addWidget(logs_button)
        actions.addStretch(1)
        details.addLayout(actions)
        content.addLayout(details, 1)
        content.setAlignment(details, Qt.AlignTop)
        row_layout.addLayout(content)

        # Names, summaries, authors and versions come from the catalog,
        # where a known author's entry publishes with no human in between:
        # as rich text, «<b>REVIEWED</b>» in a summary would pass for the
        # real badge. Every label on the card shows its text as written.
        for label in row.findChildren(QLabel):
            label.setTextFormat(Qt.PlainText)
        return row

    def _catalog_status_suffix(self) -> str:
        snapshot = self._catalog_snapshot
        if snapshot is None:
            return ""
        date = snapshot.fetched_at.replace("T", " ").replace("+00:00", " UTC")
        if snapshot.from_cache:
            return tr(" · Cached catalog from {date}", date=date)
        return tr(" · Refreshed {date}", date=date)

    def _show_load_error(self, extension: Extension, failure: dict) -> None:
        error = failure.get("error", tr("Unknown extension loading error"))
        path = failure.get("path")
        QMessageBox.warning(
            self, tr("Extension failed to load"),
            tr("{name} could not be loaded at startup.\n\n{error}\n\n"
               "Disable it or open its folder to investigate.",
               name=display_name(extension, current_language()),
               error=error)
            + (f"\n\n{path}" if path else ""))

    def _open_extension_folder(self, ident: str) -> None:
        from core.extensions import user_plugins_dir
        folder = user_plugins_dir() / ident
        if not folder.exists():
            folder = user_plugins_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _open_logs_folder(self, _checked=False) -> None:
        from core.paths import user_log_dir
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(user_log_dir())))


    def _screenshot_cache(self, extension: Extension) -> Path | None:
        if not extension.screenshot:
            return None
        if extension.bundled:
            # Shipped beside the extension: read from disk, never fetched.
            local = Path(extension.screenshot)
            return local if local.is_file() else None
        base = Path(QStandardPaths.writableLocation(
            QStandardPaths.AppLocalDataLocation))
        return base / "extension-screenshots" / extension.screenshot

    def _load_visible_images(self, *_args) -> None:
        page = self._active_page()
        if not page["scroll"].isVisible():
            return   # showEvent asks again once there is a screen to fill
        # Place the cards first: before the layout has run they all sit at
        # the top-left, every one looked visible and opening the manager
        # decoded all the screenshots (#555; ~0.25 s of white on Windows).
        page["cards"].layout().activate()
        visible = page["scroll"].viewport().rect()
        for extension in self._filtered_extensions():
            label = page["image_labels"].get(extension.id)
            if label is None or extension.id in self._screenshots:
                continue
            label_rect = label.geometry()
            label_rect.moveTopLeft(label.mapTo(
                page["scroll"].viewport(), QPoint(0, 0)))
            if not visible.intersects(label_rect):
                continue
            cache = self._screenshot_cache(extension)
            if cache is None:
                continue
            if cache.is_file():
                self._set_screenshot(extension.id, cache)
                continue
            if extension.id in self._requested_images:
                continue
            failures = self._image_failures.get(extension.id, 0)
            if failures > _SCREENSHOT_RETRIES:
                continue
            self._requested_images.add(extension.id)
            base = _SCREENSHOT_MIRROR if failures % 2 else _SCREENSHOT_BASE
            request = QNetworkRequest(QUrl(base + extension.screenshot))
            request.setAttribute(
                QNetworkRequest.RedirectPolicyAttribute,
                QNetworkRequest.NoLessSafeRedirectPolicy)
            reply = self._network.get(request)
            reply.finished.connect(
                lambda ident=extension.id, target=cache, r=reply:
                self._screenshot_finished(ident, target, r))
        self._prefetch_timer.start()

    def _screenshot_finished(self, ident: str, cache: Path, reply) -> None:
        self._requested_images.discard(ident)
        try:
            data = bytes(reply.readAll())
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if (reply.error() != QNetworkReply.NetworkError.NoError
                    or status is None or not 200 <= int(status) < 300
                    or len(data) > _MAX_SCREENSHOT_BYTES):
                log.info("could not fetch extension screenshot %s: %s",
                         ident, reply.errorString())
                self._retry_screenshot(ident)
                return
            image = QPixmap()
            if not image.loadFromData(data):
                log.warning("invalid screenshot image for extension %s", ident)
                self._retry_screenshot(ident)
                return
            cache.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache.with_suffix(cache.suffix + ".part")
            temporary.write_bytes(data)
            temporary.replace(cache)
            self._set_screenshot(ident, cache, data)
        except OSError:
            log.warning("could not cache extension screenshot %s",
                        ident, exc_info=True)
        finally:
            reply.deleteLater()

    def _retry_screenshot(self, ident: str) -> None:
        """Ask again, a little later and from the other source, while the
        tries last; the visible cards are looked at again then."""
        failures = self._image_failures.get(ident, 0) + 1
        self._image_failures[ident] = failures
        if failures <= _SCREENSHOT_RETRIES:
            QTimer.singleShot(_SCREENSHOT_RETRY_MS * failures, self,
                              self._images_timer.start)

    def _prefetch_screenshots(self) -> None:
        """Scale a few more of the screenshots already on disk, off
        screen; again a moment later while any is left."""
        if not self.isVisible():
            return
        done = 0
        for extension in self._extensions:
            if (extension.id in self._screenshots
                    or extension.id in self._unreadable_shots):
                continue
            cache = self._screenshot_cache(extension)
            if cache is None or not cache.is_file():
                continue          # downloaded only when its card is seen
            if done == _PREFETCH_BATCH:
                self._prefetch_timer.start()
                return
            self._set_screenshot(extension.id, cache)
            if extension.id not in self._screenshots:
                self._unreadable_shots.add(extension.id)
            done += 1

    @staticmethod
    def _thumb_path(source: Path) -> Path:
        base = Path(QStandardPaths.writableLocation(
            QStandardPaths.AppLocalDataLocation))
        name = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:16]
        return base / "extension-screenshots" / _THUMBS_DIR / f"{name}.png"

    def _remembered_screenshot(self, extension: Extension) -> QPixmap | None:
        """The card image scaled earlier in this run, if its screenshot
        has not changed since."""
        source = self._screenshot_cache(extension)
        key = _screenshot_key(source) if source is not None else None
        image = _SCALED_SHOTS.get(key) if key is not None else None
        if image is None:
            return None
        pixmap = QPixmap.fromImage(image)
        self._screenshots[extension.id] = pixmap
        return pixmap

    def _scaled_image(self, source: Path, data: bytes | None) -> QImage | None:
        key = _screenshot_key(source)
        if key is None:
            return None
        image = _SCALED_SHOTS.get(key)
        if image is not None:
            return image
        thumb = self._thumb_path(source)
        image = QImage()
        try:
            fresh = thumb.stat().st_mtime_ns >= key[1]
        except OSError:
            fresh = False
        if not (fresh and image.load(str(thumb)) and not image.isNull()):
            full = QImage()
            try:
                if data is None:
                    data = source.read_bytes()
            except OSError:
                log.warning("could not read extension screenshot cache %s",
                            source, exc_info=True)
                return None
            if not full.loadFromData(data):
                return None
            image = full.scaled(
                *_IMAGE_SIZE, Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation)
            try:
                thumb.parent.mkdir(parents=True, exist_ok=True)
                temporary = thumb.with_suffix(".part")
                if image.save(str(temporary), "PNG"):
                    temporary.replace(thumb)
            except OSError:
                log.warning("could not cache extension thumbnail %s",
                            thumb, exc_info=True)
        _SCALED_SHOTS[key] = image
        return image

    def _set_screenshot(self, ident: str, source: Path,
                        data: bytes | None = None) -> None:
        image = self._scaled_image(source, data)
        if image is None:
            return
        scaled = QPixmap.fromImage(image)
        self._screenshots[ident] = scaled
        for page in self._pages.values():
            label = page["image_labels"].get(ident)
            if label is not None:
                label.setPixmap(scaled)
                label.setText("")

    def _confirm_manual_copies(self, extension: Extension, paths) -> bool:
        answer = QMessageBox.question(
            self, tr("Extension manager"),
            tr("«{name}» seems to be installed by hand already, in: "
               "{folders}.\n\nIf you continue, that copy is set aside "
               "(renamed with a dot in front, not deleted) so the extension "
               "does not load twice.",
               name=display_name(extension, current_language()),
               folders=", ".join(p.name for p in paths)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        return answer == QMessageBox.Yes

    def _confirm_unreviewed(self, extension: Extension) -> bool:
        """An extension nobody reviewed is its author's Python code, run with
        the user's own permissions: say so once more before installing it,
        with No as the default. Reviewed and bundled ones go straight on."""
        if extension.bundled or is_reviewed(extension, self._reviewed):
            return True
        answer = QMessageBox.warning(
            self, tr("Install an unreviewed extension?"),
            tr("«{name}» has not been reviewed by an IngeTrazo maintainer.\n\n"
               "Extensions are Python code: once installed it runs with your "
               "permissions and can read or change your files. Install it "
               "only if you trust its author ({author}).",
               name=display_name(extension, current_language()),
               author=extension.author),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def _install(self, extension: Extension) -> None:
        if not self._confirm_unreviewed(extension):
            return
        try:
            install_extension(
                extension, confirm_manual_copies=lambda paths:
                self._confirm_manual_copies(extension, paths))
        except (ExtensionManagerError, OSError) as exc:
            QMessageBox.warning(self, tr("Extension manager"), str(exc))
            return
        QMessageBox.information(
            self, tr("Extension installed"),
            tr("«{name}» is installed. Restart IngeTrazo to load it.",
               name=display_name(extension, current_language())))
        for key in self._pages:
            self._render_page(key)

    def _uninstall(self, extension: Extension) -> None:
        answer = QMessageBox.question(
            self, tr("Uninstall extension"),
            tr("Uninstall «{name}»? Its files will be removed.",
               name=display_name(extension, current_language())),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            uninstall_extension(extension.id)
        except (ExtensionManagerError, OSError) as exc:
            QMessageBox.warning(self, tr("Extension manager"), str(exc))
            return
        QMessageBox.information(
            self, tr("Extension uninstalled"),
            tr("«{name}» is uninstalled. Restart IngeTrazo to apply the "
               "change.", name=display_name(extension, current_language())))
        for key in self._pages:
            self._render_page(key)

    # ---- Extensions installed by hand ----------------------------------
    # Until 0.5.8 an extension was installed by copying its folder into the
    # plugins folder. The manager never deletes what it did not install: it
    # sets such a copy aside (renamed with a dot in front, the loader skips
    # it), so the user can still take it back.

    def _hand_only(self, key: str, filtered: bool = True) -> list:
        """Hand-installed plugins the catalog does not know, for the
        Installed tab (the ones it knows show on their catalog card)."""
        known = {e.id for e in self._extensions}
        query = (self._pages[key]["search"].text().strip().casefold()
                 if filtered else "")
        return [path for path in hand_installed_plugins()
                if hand_installed_ident(path) not in known
                and query in hand_installed_ident(path).casefold()]

    def _make_hand_row(self, path, parent: QWidget) -> QWidget:
        name = hand_installed_ident(path)
        row = QWidget(parent)
        row.setObjectName("extensionRow")
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.setMinimumWidth(400)
        row.setMaximumWidth(_ROW_MAX_WIDTH)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(6)
        title = QLabel(name)
        title.setObjectName("extHandTitle")
        layout.addWidget(title)
        note = QLabel(tr("Installed by hand · not in the catalog"))
        note.setWordWrap(True)
        layout.addWidget(note)
        where = QLabel(str(path))
        where.setWordWrap(True)
        where.setObjectName("extHandWhere")
        layout.addWidget(where)
        actions = QHBoxLayout()
        folder = QPushButton(tr("Open extension folder"))
        folder.clicked.connect(
            lambda _checked=False, ident=name:
            self._open_extension_folder(ident))
        actions.addWidget(folder)
        remove = QPushButton(tr("Uninstall"))
        remove.clicked.connect(
            lambda _checked=False, target=path, label=name:
            self._uninstall_hand(target, label))
        actions.addWidget(remove)
        actions.addStretch(1)
        layout.addLayout(actions)
        for label in row.findChildren(QLabel):
            label.setTextFormat(Qt.PlainText)
        return row

    def _uninstall_hand_ident(self, ident: str, name: str) -> None:
        for path in hand_installed_plugins():
            if hand_installed_ident(path) == ident:
                self._uninstall_hand(path, name)
                return

    def _uninstall_hand(self, path, name: str) -> None:
        answer = QMessageBox.question(
            self, tr("Uninstall extension"),
            tr("«{name}» was installed by hand. Uninstalling sets it aside "
               "instead of deleting it: it is renamed with a dot in front, "
               "in the same folder, and IngeTrazo no longer loads it.",
               name=name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            aside = remove_hand_installed(path)
        except (ExtensionManagerError, OSError) as exc:
            QMessageBox.warning(self, tr("Extension manager"), str(exc))
            return
        QMessageBox.information(
            self, tr("Extension uninstalled"),
            tr("«{name}» is set aside as {folder}. Restart IngeTrazo to "
               "apply the change.", name=name, folder=aside.name))
        for key in self._pages:
            self._render_page(key)

    def _replace(self, extension: Extension) -> None:
        if not self._confirm_unreviewed(extension):
            return
        name = display_name(extension, current_language())
        answer = QMessageBox.question(
            self, tr("Extension manager"),
            (tr("Replace the copy of «{name}» installed by hand with the "
                "version included with IngeTrazo? The copy is set aside "
                "(renamed with a dot in front), not deleted, and the "
                "included version can then be disabled and uninstalled from "
                "here.", name=name) if extension.bundled else
             tr("Replace the copy of «{name}» installed by hand with the "
                "catalog version? The copy is set aside (renamed with a dot "
                "in front), not deleted, and the catalog version can then be "
                "updated, disabled and uninstalled from here.", name=name)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return
        try:
            replace_hand_installed(
                extension, confirm_manual_copies=lambda paths:
                self._confirm_manual_copies(extension, paths))
        except (ExtensionManagerError, OSError) as exc:
            QMessageBox.warning(self, tr("Extension manager"), str(exc))
            return
        QMessageBox.information(
            self, tr("Extension installed"),
            tr("«{name}» is installed. Restart IngeTrazo to load it.",
               name=name))
        for key in self._pages:
            self._render_page(key)

    def _toggle(self, extension: Extension) -> None:
        enabled = not is_extension_enabled(extension.id)
        try:
            set_extension_enabled(extension.id, enabled)
        except (ExtensionManagerError, OSError) as exc:
            QMessageBox.warning(self, tr("Extension manager"), str(exc))
            return
        action = tr("enabled") if enabled else tr("disabled")
        QMessageBox.information(
            self, tr("Extension changed"),
            tr("«{name}» is {state}. Restart IngeTrazo for the change to "
               "take effect.", name=display_name(extension, current_language()),
               state=action))
        for key in self._pages:
            self._render_page(key)
