# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The notice of a newer version: what counts as newer, when it looks, what
the window does. No test here touches the network."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from core import update_check as uc
from views import update_dialog as ud


class Store:
    """QSettings' value/setValue, without the user's settings."""

    def __init__(self, **values):
        self.values = {k.replace("__", "/"): v for k, v in values.items()}

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(monkeypatch):
    store = Store()
    monkeypatch.setattr(ud, "QSettings", lambda: store)
    return store


def _wait(ms=120):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


#: Windows stay alive to the end: a thread's answer may still be on its way.
_WINDOWS = []


def _window():
    _WINDOWS.append(QMainWindow())
    return _WINDOWS[-1]


RELEASE = uc.Release("0.6.2", "2026-11-17", "## Fixed\n- **a thing**",
                     uc.RELEASES_PAGE + "/tag/v0.6.2")


@pytest.mark.parametrize("remote,local,newer", [
    ("0.6.1", "0.6.0", True),
    ("v0.6.1", "0.6.0", True),
    ("0.6.10", "0.6.9", True),      # as numbers, not as text
    ("0.7", "0.6.9", True),
    ("0.6.0", "0.6.0", False),
    ("0.6", "0.6.0", False),
    ("0.5.12", "0.6.0", False),
    ("garbage", "0.6.0", False),
    ("0.6.1-rc1", "0.6.0", False),  # a pre-release is not an update
])
def test_is_newer(remote, local, newer):
    assert uc.is_newer(remote, local) is newer


def test_parse_release_reads_the_answer():
    r = uc.parse_release({
        "tag_name": "v0.6.1", "published_at": "2026-11-10T13:17:01Z",
        "body": "notes", "html_url": uc.RELEASES_PAGE + "/tag/v0.6.1"})
    assert r == uc.Release("0.6.1", "2026-11-10", "notes",
                           uc.RELEASES_PAGE + "/tag/v0.6.1")


def test_download_never_goes_outside_the_project():
    r = uc.parse_release({"tag_name": "v0.6.1",
                          "html_url": "https://example.com/evil"})
    assert r.url == uc.RELEASES_PAGE + "/latest"


@pytest.mark.parametrize("payload", [{}, {"tag_name": "latest"}, ["x"]])
def test_a_strange_answer_is_an_error(payload):
    with pytest.raises(uc.UpdateCheckError):
        uc.parse_release(payload)


NOW = 1_800_000_000.0


@pytest.mark.parametrize("store,frozen,env,looks", [
    ({}, True, {}, True),
    ({}, False, {}, False),                                  # from source
    ({}, True, {"FLATPAK_ID": "x"}, False),
    ({}, True, {"SNAP": "/snap/x"}, False),
    ({"updates__check_at_start": "0"}, True, {}, False),     # Preferences
    ({"updates__last_check": NOW - 3600}, True, {}, False),  # today already
    ({"updates__last_check": NOW - 25 * 3600}, True, {}, True),
    ({"updates__last_check": NOW + 9e6}, True, {}, True),    # clock went back
    ({"updates__last_check": "bad"}, True, {}, True),
])
def test_when_it_looks_at_start(store, frozen, env, looks):
    assert uc.should_check_at_start(Store(**store), now=NOW, frozen=frozen,
                                    environ=env) is looks


def test_a_newer_version_opens_the_window_without_blocking(app, settings):
    win = _window()
    ud._Check(win, True, "0.6.1").run(lambda: RELEASE)
    _wait()
    dialog = win._update_dialog
    assert dialog is not None and dialog.isVisible()
    assert not dialog.isModal()
    assert "a thing" in dialog.notes.toPlainText()
    assert "**" not in dialog.notes.toPlainText()  # the notes are rendered
    assert uc.KEY_LAST in settings.values
    dialog.close()
    win.close()


@pytest.mark.parametrize("current", ["0.6.2", "0.6.3"])
def test_quiet_and_up_to_date_says_nothing(app, settings, current):
    win = _window()
    ud._Check(win, True, current).run(lambda: RELEASE)
    _wait()
    assert getattr(win, "_update_dialog", None) is None


def test_quiet_and_offline_says_nothing_and_tries_again(app, settings):
    def fails():
        raise uc.UpdateCheckError("offline")
    win = _window()
    ud._Check(win, True, "0.6.1").run(fails)
    _wait()
    assert getattr(win, "_update_dialog", None) is None
    assert uc.KEY_LAST not in settings.values


def test_a_skipped_version_stays_quiet_but_the_menu_still_shows_it(app, settings):
    uc.skip_version(settings, "0.6.2")
    win = _window()
    ud._Check(win, True, "0.6.1").run(lambda: RELEASE)
    _wait()
    assert getattr(win, "_update_dialog", None) is None
    ud._Check(win, False, "0.6.1").run(lambda: RELEASE)
    _wait()
    assert win._update_dialog is not None
    win._update_dialog.close()
    win.close()


def test_the_menu_says_when_up_to_date_and_when_offline(app, settings, monkeypatch):
    said = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a: said.append(("info", a[2])))
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a: said.append(("warn", a[2])))
    win = _window()
    ud._Check(win, False, "0.6.2").run(lambda: RELEASE)
    _wait()

    def fails():
        raise uc.UpdateCheckError("offline")
    ud._Check(win, False, "0.6.2").run(fails)
    _wait()
    assert [kind for kind, _ in said] == ["info", "warn"]
    assert "0.6.2" in said[0][1]


def test_skip_and_download_buttons(app, settings, monkeypatch):
    opened = []
    monkeypatch.setattr("core.desktop_open.open_url", opened.append)
    dialog = ud.UpdateDialog(RELEASE, _window(), "0.6.1")
    dialog.skip_button.click()
    assert uc.is_skipped(settings, "0.6.2")
    dialog = ud.UpdateDialog(RELEASE, _window(), "0.6.1")
    dialog.download_button.click()
    assert opened == [RELEASE.url]


def test_a_quiet_notice_waits_for_a_modal_question(app, settings, monkeypatch):
    win = _window()
    monkeypatch.setattr(ud, "_RETRY_MS", 30)
    monkeypatch.setattr(QApplication, "activeModalWidget", lambda: win)
    ud.show_release(win, RELEASE, True, "0.6.1")
    assert getattr(win, "_update_dialog", None) is None
    monkeypatch.setattr(QApplication, "activeModalWidget", lambda: None)
    _wait()
    assert win._update_dialog is not None
    win._update_dialog.close()
    win.close()


def test_start_check_respects_should_check(app, settings, monkeypatch):
    monkeypatch.setattr(uc, "should_check_at_start", lambda s: False)
    called = []
    ud.start_check(_window(), True, fetch=lambda: called.append(1))
    _wait(40)
    assert not called
