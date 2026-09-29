# SPDX-License-Identifier: GPL-3.0-or-later
"""Connect to the installed 3Dconnexion macOS driver through its client API.

Only the ABI declarations needed for interoperability live here; the driver
framework is loaded from the user's machine, never bundled. Callbacks copy
their short-lived data into a bounded queue; Qt drains it on the GUI thread.
"""
from collections import deque
import ctypes as C

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from core.ndof import from_hid


class DeviceState(C.Structure):
    _pack_ = 2
    _layout_ = "ms"
    _fields_ = [
        ("version", C.c_uint16), ("client", C.c_uint16),
        ("command", C.c_uint16), ("param", C.c_int16),
        ("value", C.c_int32), ("time", C.c_uint64),
        ("report", C.c_uint8 * 8), ("buttons8", C.c_uint16),
        ("axis", C.c_int16 * 6), ("address", C.c_uint16),
        ("buttons", C.c_uint32),
    ]


MESSAGE = C.CFUNCTYPE(None, C.c_uint32, C.c_uint32, C.c_void_p)
DEVICE = C.CFUNCTYPE(None, C.c_uint32)
FRAMEWORK = "/Library/Frameworks/3DconnexionClient.framework/3DconnexionClient"


class ConnexionBackend:
    name = "3Dconnexion macOS driver"

    def __init__(self, owner):
        self.owner = owner
        self.library = None
        self.client = 0
        self.installed = False
        self.active = False
        self.timer = None
        self.buttons = 0
        self.queue = deque(maxlen=256)
        # Keep all C callback objects alive until after driver cleanup.
        self.message_callback = MESSAGE(self._message)
        self.added_callback = DEVICE(lambda _product: None)
        self.removed_callback = DEVICE(lambda _product: self.queue.append(None))

    def open(self):
        lib = self.library = C.CDLL(FRAMEWORK)
        signatures = {
            "SetConnexionHandlers": ([MESSAGE, DEVICE, DEVICE, C.c_bool], C.c_int16),
            "RegisterConnexionClient": ([C.c_uint32, C.c_char_p, C.c_uint16,
                                          C.c_uint32], C.c_uint16),
            "SetConnexionClientButtonMask": ([C.c_uint16, C.c_uint32], None),
            "UnregisterConnexionClient": ([C.c_uint16], None),
            "CleanupConnexionHandlers": ([], None),
            "ConnexionClientControl": ([C.c_uint16, C.c_uint32, C.c_int32,
                                         C.POINTER(C.c_int32)], C.c_int16),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(lib, name)
            fn.argtypes, fn.restype = args, result
        error = lib.SetConnexionHandlers(self.message_callback,
                                        self.added_callback,
                                        self.removed_callback, True)
        if error:
            raise OSError(f"3Dconnexion handler registration failed: {error}")
        self.installed = True
        # Manual activation avoids depending on a legacy four-letter bundle
        # signature, and relinquishes control when another app has focus.
        self.client = lib.RegisterConnexionClient(0x2B2B2B2B, b"\x09IngeTrazo",
                                                  1, 0x3FFF)
        if not self.client:
            raise OSError("3Dconnexion client registration failed")
        lib.SetConnexionClientButtonMask(self.client, 3)
        self.timer = QTimer(self.owner)
        self.timer.setInterval(8)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        self._poll()
        return True

    def _control(self, command):
        result = C.c_int32()
        return self.library.ConnexionClientControl(self.client, command, 0,
                                                   C.byref(result))

    def _message(self, _product, kind, pointer):
        if kind != 0x33645352 or not pointer or not self.client:
            return
        state = C.cast(pointer, C.POINTER(DeviceState)).contents
        if state.client == self.client and state.command in (2, 3):
            self.queue.append((state.command, tuple(state.axis), state.buttons))

    def _poll(self):
        from views.ndof_input import current_settings
        app = QApplication.instance()
        active = (app is not None
                  and app.applicationState() == Qt.ApplicationActive
                  and app.activeModalWidget() is None
                  and current_settings().enabled)
        if active != self.active:
            if self._control(0x33646163 if active else 0x33646463) == 0:
                self.active = active
            self.queue.clear()
            self.buttons = 0
            self.owner._last_t = None
        latest = None
        for _ in range(256):
            try:
                packet = self.queue.popleft()
            except IndexError:
                break
            if packet is None:
                latest = None
                self.buttons = 0
                self.owner._last_t = None
                continue
            if not active:
                continue
            command, axes, buttons = packet
            if command == 3:
                latest = from_hid(*axes)
            else:
                for bit in range(2):
                    if (buttons ^ self.buttons) & (1 << bit):
                        self.owner._emit_button(bit, bool(buttons & (1 << bit)))
                self.buttons = buttons
        if latest is not None:
            self.owner._emit_motion(latest)

    def close(self):
        if self.timer is not None:
            self.timer.stop()
            self.timer.deleteLater()
            self.timer = None
        if self.client:
            self._control(0x33646463)
            self.library.UnregisterConnexionClient(self.client)
            self.client = 0
        if self.installed:
            self.library.CleanupConnexionHandlers()
            self.installed = False
        self.active = False
        self.queue.clear()
