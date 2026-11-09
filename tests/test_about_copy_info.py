"""Help ▸ About: "Copy to clipboard" puts what a bug report needs (#476)."""
from __future__ import annotations

import platform

import pytest

from PySide6.QtWidgets import QApplication

from core.i18n import current_language, set_language
from views.about_dialog import AboutDialog, system_info

_app = QApplication.instance() or QApplication([])

_GL = "NVIDIA Corporation · RTX 9999/PCIe · OpenGL 4.6.0"


def test_the_info_names_program_system_python_qt_and_gl():
    text = system_info("9.8.7", _GL)
    assert text.splitlines()[0].startswith("IngeTrazo 9.8.7")
    from views.about_dialog import _os_name
    assert f"OS: {_os_name()} ({platform.machine()})" in text
    assert f"Python: {platform.python_version()}" in text
    assert "Qt: " in text and "PySide6: " in text
    assert f"OpenGL: {_GL}" in text
    assert "Screen: " in text
    assert f"Language: {current_language()}" in text


def test_without_a_gl_line_there_is_no_empty_opengl_row():
    assert "OpenGL" not in system_info("9.8.7")


def test_the_info_stays_in_english_whatever_the_interface_language():
    before = current_language()
    try:
        set_language("es")
        text = system_info("9.8.7", _GL)
    finally:
        set_language(before)
    assert "Language: es" in text
    assert "OS: " in text and "Screen: " in text


def test_the_button_copies_the_info_to_the_clipboard():
    QApplication.clipboard().setText("something else")
    dlg = AboutDialog(None, "9.8.7", _GL)
    dlg.copy_button.click()
    assert QApplication.clipboard().text() == system_info("9.8.7", _GL)
    dlg.close()


def test_the_button_says_it_copied():
    dlg = AboutDialog(None, "9.8.7")
    label = dlg.copy_button.text()
    dlg.copy_button.click()
    assert dlg.copy_button.text() != label
    dlg.close()


def test_the_os_line_has_nothing_the_locale_translated(monkeypatch):
    """``uname -p`` answers in the user's language: a Spanish Linux put
    «desconocido» in the line meant to stay English (caza 2, 16-10)."""
    monkeypatch.setattr(platform, "processor", lambda: "desconocido")
    monkeypatch.setattr(platform, "uname", lambda: platform.uname_result(
        "Linux", "host", "7.0.0", "#1", "x86_64"))
    os_line = next(line for line in system_info("9.8.7").splitlines()
                   if line.startswith("OS:"))
    assert "desconocido" not in os_line
    assert platform.system() in os_line and platform.machine() in os_line


@pytest.mark.parametrize("env, label", [
    ({"FLATPAK_ID": "com.ingetrazo.IngeTrazo"}, "(Flatpak)"),
    ({"APPIMAGE": "/tmp/IngeTrazo.AppImage"}, "(AppImage)"),
    ({}, "(from source)"),
])
def test_the_first_line_says_how_this_copy_runs(monkeypatch, env, label):
    for key in ("FLATPAK_ID", "APPIMAGE"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert system_info("9.8.7").splitlines()[0] == f"IngeTrazo 9.8.7 {label}"
