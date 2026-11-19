# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""macOS driver ABI, callback threading, focus and cleanup without hardware."""
import ctypes
import struct
import threading

import pytest
from PySide6.QtCore import QObject, Qt, Signal, QCoreApplication

from core.ndof import NdofSettings
from views import ndof_input, ndof_macos


class _Function:
    def __init__(self, impl):
        self.impl = impl

    def __call__(self, *args):
        return self.impl(*args)


class _Framework:
    def __init__(self, handler_error=0, client_id=42, control_error=0):
        self.calls = []
        self.callbacks = None
        self.SetConnexionHandlers = _Function(self._handlers)
        self.CleanupConnexionHandlers = _Function(lambda: self.calls.append("cleanup"))
        self.RegisterConnexionClient = _Function(self._register)
        self.UnregisterConnexionClient = _Function(
            lambda client: self.calls.append(("unregister", client)))
        self.SetConnexionClientButtonMask = _Function(
            lambda *args: self.calls.append(("buttons", *args)))
        self.ConnexionClientControl = _Function(self._control)
        self.handler_error = handler_error
        self.client_id = client_id
        self.control_error = control_error

    def _handlers(self, *args):
        self.callbacks = args[:3]
        self.calls.append(("handlers", args[3]))
        return self.handler_error

    def _register(self, *args):
        self.calls.append(("register", *args))
        return self.client_id

    def _control(self, client, command, param, result):
        self.calls.append(("control", client, command))
        return self.control_error

    def send(self, data, message=ndof_macos.DEVICE_STATE_MESSAGE):
        buf = ctypes.create_string_buffer(data)
        self.callbacks[0](1, message, ctypes.addressof(buf))
        # The driver owns this memory only until the callback returns.
        ctypes.memset(ctypes.addressof(buf), 0, len(data))


class _App(QObject):
    applicationStateChanged = Signal(object)

    def __init__(self):
        super().__init__()
        self.state = Qt.ApplicationActive

    def applicationState(self):
        return self.state

    def focus(self, state):
        self.state = state
        self.applicationStateChanged.emit(state)


def _packet(command=3, client=42, axis=(0, 0, 0, 0, 0, 0), buttons=0,
            version=0x6D33, buttons8=0):
    # Pack independently of ctypes: a wrong ABI offset must fail the test.
    return struct.pack("=HHHhiQ8sH6hHI", version, client, command, 0, 0, 0,
                       bytes(8), buttons8, *axis, 0, buttons)


def test_platform_dispatch_selects_macos_backend():
    from views.ndof_hid import HidBackend
    assert ndof_input._backends_for("darwin") == [ndof_macos.MacConnexionBackend, HidBackend]
    assert ndof_input._backends_for("win32") == [ndof_input.RawInputBackend]
    assert ndof_input._backends_for("linux") == [ndof_input.SpnavBackend]


@pytest.fixture
def driver(monkeypatch):
    framework = _Framework()
    app = _App()
    monkeypatch.setattr(ndof_macos.ctypes, "CDLL", lambda _path: framework)
    monkeypatch.setattr(ndof_macos, "QGuiApplication", type(
        "Application", (), {"instance": staticmethod(lambda: app)}))
    settings = NdofSettings()
    monkeypatch.setattr(ndof_input, "_settings_cache", settings)
    monkeypatch.setattr(ndof_input, "_backends_for", lambda _platform: [
        ndof_macos.MacConnexionBackend])
    owner = ndof_input.NdofInput()
    yield owner, framework, app, settings
    owner.stop()
    QCoreApplication.processEvents()


def test_macos_registration_abi_and_cleanup(driver):
    owner, lib, _app, _settings = driver
    state = ndof_macos.ConnexionDeviceState
    assert ctypes.sizeof(state) == 48
    assert state.time.offset == 12 and state.axis.offset == 30
    assert state.buttons.offset == 44
    assert owner.start() and owner.backend_name == "3Dconnexion (macOS)"
    assert ("handlers", True) in lib.calls
    assert ("register", ndof_macos.MANUAL_CLIENT, b"\x09IngeTrazo", 1, 0x3FFF) in lib.calls
    assert ("buttons", 42, 0xFFFFFFFF) in lib.calls
    assert lib.RegisterConnexionClient.restype is ctypes.c_uint16
    assert lib.ConnexionClientControl.argtypes[-1] == ctypes.POINTER(ctypes.c_int32)
    owner.stop()
    owner.stop()
    assert lib.calls[-2:] == [("unregister", 42), "cleanup"]
    assert lib.calls.count("cleanup") == 1


def test_callbacks_copy_data_and_deliver_motion_on_gui_thread(driver):
    owner, lib, _app, _settings = driver
    assert owner.start()
    got = []
    owner.motion.connect(lambda sample, dt: got.append((sample, dt, threading.get_ident())))
    gui_thread = threading.get_ident()
    thread = threading.Thread(target=lib.send, args=(
        _packet(axis=(350, -350, -350, -350, 0, -350)),))
    thread.start()
    thread.join()
    assert got == []  # queued; no work happens on the driver's thread
    QCoreApplication.processEvents()
    sample, dt, callback_thread = got[0]
    assert callback_thread == gui_thread and dt == pytest.approx(1 / 60)
    assert (sample.right, sample.up, sample.forward, sample.tilt, sample.spin) == (1,) * 5
    lib.send(_packet())  # release resets the timing for the next movement
    QCoreApplication.processEvents()
    assert got[-1][0].is_idle() and owner._last_t is None


def test_buttons_transitions_foreign_clients_and_legacy_messages(driver):
    owner, lib, _app, _settings = driver
    assert owner.start()
    got, motions = [], []
    owner.button.connect(lambda n, down: got.append((n, down)))
    owner.motion.connect(lambda *args: motions.append(args))
    lib.send(_packet(client=7, axis=(350, 0, 0, 0, 0, 0)))
    lib.send(_packet(axis=(350, 0, 0, 0, 0, 0)), message=0)
    lib.send(_packet(command=2, buttons=0x80000003))
    lib.send(_packet(command=2, buttons=0x80000003))  # no repeated presses
    lib.send(_packet(command=2, version=0x6D32, buttons8=2))
    QCoreApplication.processEvents()
    assert not motions
    assert got == [(0, True), (1, True), (31, True), (0, False), (31, False)]
    lib.callbacks[2](1)  # unplug releases held buttons and resets motion
    QCoreApplication.processEvents()
    assert got[-1] == (1, False) and motions[-1][0].is_idle()


def test_focus_and_disabled_setting_release_driver(driver):
    owner, lib, app, settings = driver
    assert owner.start()
    app.focus(Qt.ApplicationInactive)
    assert lib.calls[-1] == ("control", 42, ndof_macos.DEACTIVATE_CLIENT)
    got = []
    owner.motion.connect(lambda *args: got.append(args))
    lib.send(_packet(axis=(350, 0, 0, 0, 0, 0)))
    QCoreApplication.processEvents()
    assert not got
    app.focus(Qt.ApplicationActive)
    assert lib.calls[-1] == ("control", 42, ndof_macos.ACTIVATE_CLIENT)
    settings.enabled = False
    owner._backend.refresh_activation()
    assert lib.calls[-1] == ("control", 42, ndof_macos.DEACTIVATE_CLIENT)
    assert not owner._backend._active


def test_saving_preferences_updates_driver_activation(driver, monkeypatch):
    owner, lib, _app, settings = driver
    assert owner.start()
    monkeypatch.setattr(ndof_input, "_shared", owner)
    settings.enabled = False
    ndof_input.save_settings(settings)
    assert lib.calls[-1] == ("control", 42, ndof_macos.DEACTIVATE_CLIENT)
    settings.enabled = True
    ndof_input.save_settings(settings)
    assert lib.calls[-1] == ("control", 42, ndof_macos.ACTIVATE_CLIENT)


@pytest.mark.parametrize("failure", ["missing", "handlers", "registration", "mask"])
def test_unavailable_driver_and_partial_startup_cleanup(driver, monkeypatch, failure):
    owner, lib, _app, _settings = driver
    if failure == "missing":
        def missing(_path):
            raise OSError("driver not installed")
        monkeypatch.setattr(ndof_macos.ctypes, "CDLL", missing)
    elif failure == "handlers":
        lib.handler_error = -1
    elif failure == "registration":
        lib.client_id = 0
    else:
        def broken(*args):
            raise RuntimeError("button mask failed")
        lib.SetConnexionClientButtonMask.impl = broken
    assert not owner.start() and owner.backend_name is None
    assert lib.calls.count("cleanup") == (1 if failure in ("registration", "mask") else 0)
    if failure == "mask":
        assert ("unregister", 42) in lib.calls


def test_queued_events_are_ignored_after_stop_and_connection_can_restart(driver):
    owner, lib, _app, _settings = driver
    assert owner.start()
    got = []
    owner.motion.connect(lambda *args: got.append(args))
    lib.send(_packet(axis=(350, 0, 0, 0, 0, 0)))
    owner.stop()
    QCoreApplication.processEvents()
    assert not got
    assert owner.start()


def test_activation_failure_does_not_accept_motion(driver):
    owner, lib, _app, _settings = driver
    lib.control_error = -1
    assert owner.start()
    assert not owner._backend._active
    got = []
    owner.motion.connect(lambda *args: got.append(args))
    lib.send(_packet(axis=(350, 0, 0, 0, 0, 0)))
    QCoreApplication.processEvents()
    assert not got


def test_modal_dialog_releases_buttons_and_discards_pending_motion(driver, monkeypatch):
    owner, lib, _app, _settings = driver
    modal = [None]
    monkeypatch.setattr(ndof_macos.QApplication, "activeModalWidget", lambda: modal[0])
    assert owner.start()
    buttons, motion = [], []
    owner.button.connect(lambda *args: buttons.append(args))
    owner.motion.connect(lambda *args: motion.append(args))
    lib.send(_packet(command=2, buttons=1))
    QCoreApplication.processEvents()
    lib.send(_packet(axis=(350, 0, 0, 0, 0, 0)))
    modal[0] = object()
    QCoreApplication.processEvents()
    assert buttons == [(0, True), (0, False)]
    assert motion and all(sample.is_idle() for sample, _dt in motion)
    assert not owner._backend._active
    modal[0] = None
    owner._backend.refresh_activation()
    assert owner._backend._active


def test_missing_driver_retries_and_stop_cancels_retry(driver):
    owner, lib, _app, _settings = driver
    lib.handler_error = -1
    assert not owner.start() and owner._retry.isActive()
    lib.handler_error = 0
    owner._retry.timeout.emit()
    assert owner.backend_name == "3Dconnexion (macOS)"
    assert not owner._retry.isActive()
    owner.disconnected()
    assert owner.backend_name is None and owner._retry.isActive()
    owner.stop()
    assert not owner._retry.isActive()
