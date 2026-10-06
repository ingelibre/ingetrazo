# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Optional macOS SpaceMouse connection through the installed 3DxWare driver.

Only the public client ABI is described here; no SDK or driver is bundled.
The packed state layout and function signatures follow ConnexionClient.h
and ConnexionClientAPI.h shipped with 3DconnexionClient.framework.
"""
from __future__ import annotations

import ctypes

from PySide6.QtCore import QObject, Qt, Signal, Slot, QTimer, QEvent
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from core.ndof import NdofSample, from_hid

FRAMEWORK_PATH = "/Library/Frameworks/3DconnexionClient.framework/3DconnexionClient"
DEVICE_STATE_MESSAGE = 0x33645352
AXIS_COMMAND = 3
BUTTON_COMMAND = 2
MANUAL_CLIENT = 0x2B2B2B2B
ACTIVATE_CLIENT = 0x33646163
DEACTIVATE_CLIENT = 0x33646463


class ConnexionDeviceState(ctypes.Structure):
    """The 48-byte, two-byte-aligned public driver message (version 3)."""

    _pack_ = 2
    _fields_ = [
        ("version", ctypes.c_uint16), ("client", ctypes.c_uint16),
        ("command", ctypes.c_uint16), ("param", ctypes.c_int16),
        ("value", ctypes.c_int32), ("time", ctypes.c_uint64),
        ("report", ctypes.c_uint8 * 8), ("buttons8", ctypes.c_uint16),
        ("axis", ctypes.c_int16 * 6), ("address", ctypes.c_uint16),
        ("buttons", ctypes.c_uint32),
    ]


_MessageCallback = ctypes.CFUNCTYPE(None, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p)
_DeviceCallback = ctypes.CFUNCTYPE(None, ctypes.c_uint32)


def _load_framework():
    lib = ctypes.CDLL(FRAMEWORK_PATH)
    signatures = {
        "SetConnexionHandlers": (ctypes.c_int16,
                                 [_MessageCallback, _DeviceCallback,
                                  _DeviceCallback, ctypes.c_bool]),
        "CleanupConnexionHandlers": (None, []),
        "RegisterConnexionClient": (ctypes.c_uint16,
                                    [ctypes.c_uint32, ctypes.c_char_p,
                                     ctypes.c_uint16, ctypes.c_uint32]),
        "SetConnexionClientButtonMask": (None, [ctypes.c_uint16, ctypes.c_uint32]),
        "UnregisterConnexionClient": (None, [ctypes.c_uint16]),
        "ConnexionClientControl": (ctypes.c_int16,
                                   [ctypes.c_uint16, ctypes.c_uint32,
                                    ctypes.c_int32, ctypes.POINTER(ctypes.c_int32)]),
    }
    for name, (result, args) in signatures.items():
        func = getattr(lib, name)
        func.restype, func.argtypes = result, args
    return lib


class MacConnexionBackend(QObject):
    """Receive driver events and keep device ownership aligned with app focus."""

    name = "3Dconnexion (macOS)"
    _state_received = Signal(bytes)
    _device_removed = Signal()

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.owner = owner
        self.lib = None
        self.client_id = 0
        self._handlers_installed = False
        self._callbacks = None
        self._buttons = 0
        self._active = False
        self._app = None
        self._activation_timer = QTimer(self)
        self._activation_timer.setInterval(100)
        self._activation_timer.timeout.connect(self.refresh_activation)
        # The driver has its own thread. Copy its ephemeral message before
        # returning and process it on this QObject's (GUI) thread.
        self._state_received.connect(self._on_state, Qt.QueuedConnection)
        self._device_removed.connect(self._on_removed, Qt.QueuedConnection)

    def open(self) -> bool:
        """Register with the driver; return whether a client was created."""
        if self.client_id:
            return True
        try:
            self.lib = _load_framework()
            self._callbacks = (_MessageCallback(self._message),
                               _DeviceCallback(lambda _device: None),
                               _DeviceCallback(lambda _device: self._device_removed.emit()))
            if self.lib.SetConnexionHandlers(*self._callbacks, True) != 0:
                self.close()
                return False
            self._handlers_installed = True
            # Manual activation follows Qt focus, including when launched
            # as python main.py rather than as a named macOS app bundle.
            self.client_id = self.lib.RegisterConnexionClient(
                MANUAL_CLIENT, b"\x09IngeTrazo", 1, 0x3FFF)
            if not self.client_id:
                self.close()
                return False
            self.lib.SetConnexionClientButtonMask(self.client_id, 0xFFFFFFFF)
            self._app = QGuiApplication.instance()
            if self._app is not None:
                self._app.applicationStateChanged.connect(self.refresh_activation)
                self._app.installEventFilter(self)
            self.refresh_activation()
            self._activation_timer.start()
            return True
        except Exception:
            self.close()
            raise

    def refresh_activation(self, *_args) -> None:
        """Activate the focused app outside modal dialogs when input is enabled."""
        from views.ndof_input import current_settings

        active = (self._app is not None
                  and self._app.applicationState() == Qt.ApplicationActive
                  and QApplication.activeModalWidget() is None
                  and current_settings().enabled)
        if self.lib is None or not self.client_id:
            return
        if active == self._active:
            return
        result = ctypes.c_int32()
        error = self.lib.ConnexionClientControl(
            self.client_id, ACTIVATE_CLIENT if active else DEACTIVATE_CLIENT,
            0, ctypes.byref(result))
        was_active = self._active
        self._active = active and error == 0
        if was_active and not self._active:
            self._reset()

    def eventFilter(self, watched, event) -> bool:
        # Reject queued device input as soon as a modal widget is shown;
        # the timer also handles its close, once Qt clears the modal stack.
        if event.type() in (QEvent.Show, QEvent.Hide):
            self.refresh_activation()
        return False

    def _message(self, _device: int, message: int, argument: int) -> None:
        if message == DEVICE_STATE_MESSAGE and argument:
            self._state_received.emit(ctypes.string_at(
                argument, ctypes.sizeof(ConnexionDeviceState)))

    @Slot(bytes)
    def _on_state(self, data: bytes) -> None:
        self.refresh_activation()
        if not self.client_id or not self._active:
            return
        state = ConnexionDeviceState.from_buffer_copy(data)
        # Driver messages are broadcast; another client's input is never ours.
        if state.client != self.client_id:
            return
        if state.command == AXIS_COMMAND:
            self.owner._emit_motion(from_hid(*state.axis))
        elif state.command == BUTTON_COMMAND:
            mask = state.buttons if state.version == 0x6D33 else state.buttons8
            self._emit_buttons(mask)

    def _emit_buttons(self, mask: int) -> None:
        changed = self._buttons ^ mask
        self._buttons = mask
        for bit in range(32):
            if changed >> bit & 1:
                self.owner._emit_button(bit, bool(mask >> bit & 1))

    def _reset(self) -> None:
        self._emit_buttons(0)
        self.owner._emit_motion(NdofSample())

    @Slot()
    def _on_removed(self) -> None:
        if self.client_id:
            self._reset()

    def close(self) -> None:
        """Release the client, callbacks and application focus connection."""
        self._activation_timer.stop()
        self._active = False
        if self._app is not None:
            try:
                self._app.removeEventFilter(self)
                self._app.applicationStateChanged.disconnect(self.refresh_activation)
            except RuntimeError:  # QApplication may already be gone at atexit.
                pass
            self._app = None
        client, self.client_id = self.client_id, 0
        try:
            if self.lib is not None and client:
                self.lib.UnregisterConnexionClient(client)
        finally:
            if self.lib is not None and self._handlers_installed:
                self.lib.CleanupConnexionHandlers()
            self._handlers_installed = False
            # Retain ctypes callbacks until the driver has stopped calling them.
            self._callbacks = None
            self.lib = None
            self._buttons = 0
