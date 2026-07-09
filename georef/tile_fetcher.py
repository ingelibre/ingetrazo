# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Async tile fetching (Track G, G1) — cache-first, over the network.

The Qt-net half of the tile layer: :class:`TileFetcher` wraps a
``QNetworkAccessManager``, serves cached tiles instantly and downloads the rest
in the background, emitting :attr:`TileFetcher.tileReady` when an image lands.
The pure slippy/source/cache logic lives in :mod:`georef.tiles`; this module is
the only tile piece that needs Qt-net + a running event loop.

Deps: only Qt (``QtNetwork`` + ``QtGui.QImage``) — no new pip (invariant #4).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QStandardPaths, Signal, Qt
from PySide6.QtGui import QImage
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

from georef.tiles import TileCache, TileSource


# Slippy-map etiquette: identify the client and don't hammer servers. OSM's
# usage policy in particular requires a real User-Agent.
_USER_AGENT = b"IngeTrazo/0.0.1 (https://github.com/tuxiasumari/ingetrazo)"


def default_cache_dir() -> Path:
    """``<AppLocalData>/tiles`` — the on-disk tile cache location.

    Uses Qt's per-user data location (honours the app/org name set in
    ``main.py``); falls back to ``~/.cache/ingetrazo`` if Qt returns nothing.
    """
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation)
    if not base:
        base = str(Path.home() / ".cache" / "ingetrazo")
    return Path(base) / "tiles"


class TileFetcher(QObject):
    """Cache-first async tile provider.

    Call :meth:`request` with a source + tile index; the tile arrives via the
    :attr:`tileReady` signal (immediately for cache hits, later for downloads).
    Duplicate in-flight requests for the same tile are coalesced.
    """

    #: ``(source_id, x, y, z, image)`` — a decoded tile is available.
    tileReady = Signal(str, int, int, int, QImage)
    #: ``(source_id, x, y, z, reason)`` — the tile could not be fetched.
    tileFailed = Signal(str, int, int, int, str)

    def __init__(self, cache: TileCache | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cache = cache if cache is not None else TileCache(default_cache_dir())
        self._nam = QNetworkAccessManager(self)
        # (source_id, x, y, z) -> QNetworkReply, so repeated asks coalesce.
        self._inflight: dict[tuple[str, int, int, int], QNetworkReply] = {}

    @property
    def cache(self) -> TileCache:
        return self._cache

    def request(self, source: TileSource, x: int, y: int, z: int) -> QImage | None:
        """Ask for tile ``(x, y, z)`` of ``source``.

        Returns the :class:`QImage` synchronously on a cache hit (and does not
        emit); otherwise returns ``None`` and emits :attr:`tileReady` once the
        download finishes. Out-of-range zooms are refused.
        """
        if z < 0 or z > source.max_zoom:
            return None
        key = (source.id, x, y, z)
        cached = self._cache.get(source.id, x, y, z)
        if cached is not None:
            img = QImage()
            if img.loadFromData(QByteArray(cached)):
                return img
            # Corrupt cache entry — fall through and re-download.
        if key in self._inflight:
            return None  # already downloading; the pending reply will emit
        self._start_download(source, x, y, z)
        return None

    def _start_download(self, source: TileSource, x: int, y: int, z: int) -> None:
        req = QNetworkRequest(source.url(x, y, z))
        req.setRawHeader(b"User-Agent", _USER_AGENT)
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                         QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        reply = self._nam.get(req)
        key = (source.id, x, y, z)
        self._inflight[key] = reply
        reply.finished.connect(
            lambda: self._on_finished(source.id, x, y, z, reply))

    def _on_finished(self, source_id: str, x: int, y: int, z: int,
                     reply: QNetworkReply) -> None:
        self._inflight.pop((source_id, x, y, z), None)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.tileFailed.emit(source_id, x, y, z, reply.errorString())
                return
            data = bytes(reply.readAll())
            img = QImage()
            if not data or not img.loadFromData(QByteArray(data)):
                self.tileFailed.emit(source_id, x, y, z, "undecodable tile data")
                return
            self._cache.put(source_id, x, y, z, data)
            self.tileReady.emit(source_id, x, y, z, img)
        finally:
            reply.deleteLater()

    def cancel_all(self) -> None:
        """Abort every in-flight download (e.g. when the source changes)."""
        for reply in list(self._inflight.values()):
            reply.abort()
        self._inflight.clear()
