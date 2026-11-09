# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Is a newer IngeTrazo out? Asks GitHub for the latest published release.

The release page is the one thing every release already publishes, so this
adds no step to it. A draft or a pre-release is never "latest" there. Only the
version is asked for; nothing about the user or the document is sent.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from core.version import USER_AGENT, __version__

LATEST_API = "https://api.github.com/repos/ingelibre/ingetrazo/releases/latest"
RELEASES_PAGE = "https://github.com/ingelibre/ingetrazo/releases"

KEY_AUTO = "updates/check_at_start"
KEY_LAST = "updates/last_check"
KEY_SKIPPED = "updates/skipped_version"

#: At most one look a day: it is a courtesy, and GitHub limits anonymous calls.
MIN_SECONDS_BETWEEN_CHECKS = 24 * 3600
TIMEOUT = 8.0
_MAX_BYTES = 2_000_000


class UpdateCheckError(Exception):
    """The answer could not be had or could not be read."""


@dataclass(frozen=True)
class Release:
    version: str
    date: str
    notes: str
    url: str


def parse_version(text: str) -> tuple[int, ...]:
    """``v0.6.1`` → ``(0, 6, 1)``; ``()`` when it is not such a number."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    return tuple(int(n) for n in m.group(1).split(".")) if m else ()


def is_newer(remote: str, local: str = __version__) -> bool:
    """Numeric, so 0.6.10 is newer than 0.6.9; an unreadable number never is."""
    a, b = parse_version(remote), parse_version(local)
    if not a or not b:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def parse_release(payload: dict) -> Release:
    """The fields we show, from GitHub's answer. The address only comes from
    the answer when it is this project's own release page."""
    try:
        tag = payload["tag_name"]
    except (KeyError, TypeError) as exc:
        raise UpdateCheckError("no tag in the answer") from exc
    version = str(tag).lstrip("v")
    if not parse_version(version):
        raise UpdateCheckError(f"unreadable version: {tag!r}")
    url = str(payload.get("html_url") or "")
    if not url.startswith(RELEASES_PAGE + "/"):
        url = RELEASES_PAGE + "/latest"
    return Release(version=version,
                   date=str(payload.get("published_at") or "")[:10],
                   notes=str(payload.get("body") or ""),
                   url=url)


def fetch_latest(timeout: float = TIMEOUT) -> Release:
    """The latest release, or :class:`UpdateCheckError`. Runs off the GUI thread."""
    from core.tls import https_context
    request = urllib.request.Request(LATEST_API, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout,
                                    context=https_context()) as response:
            raw = response.read(_MAX_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateCheckError(str(exc)) from exc
    if len(raw) > _MAX_BYTES:
        raise UpdateCheckError("answer too large")
    try:
        return parse_release(json.loads(raw.decode("utf-8")))
    except ValueError as exc:
        raise UpdateCheckError(str(exc)) from exc


def store_managed(environ=None) -> bool:
    """Flatpak and Snap update themselves: an offer of a download would only
    lead away from what the store will install anyway."""
    env = os.environ if environ is None else environ
    return bool(env.get("FLATPAK_ID") or env.get("SNAP"))


def auto_enabled(settings) -> bool:
    return str(settings.value(KEY_AUTO, "1")) != "0"


def should_check_at_start(settings, now: float | None = None, frozen=None,
                          environ=None) -> bool:
    """Only an installed copy looks by itself: a checkout has no release to
    fall behind. Off in Preferences, no look; a failed look does not count,
    so the next start tries again."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if not frozen or store_managed(environ) or not auto_enabled(settings):
        return False
    try:
        last = float(settings.value(KEY_LAST, 0) or 0)
    except (TypeError, ValueError):
        last = 0.0
    now = time.time() if now is None else now
    return not 0 <= now - last < MIN_SECONDS_BETWEEN_CHECKS


def mark_checked(settings, now: float | None = None) -> None:
    settings.setValue(KEY_LAST, time.time() if now is None else now)


def skip_version(settings, version: str) -> None:
    settings.setValue(KEY_SKIPPED, version)


def is_skipped(settings, version: str) -> bool:
    return str(settings.value(KEY_SKIPPED, "")) == version
