# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional nonexclusive HIDAPI fallback for macOS SpaceMouse devices.

Adapted from Brian Russell's IngeTrazo PR #190.
"""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from views.ndof_input import NdofInput, parse_hid_report, current_settings


class HidBackend:
    name = "HIDAPI (3Dconnexion)"

    def __init__(self, owner: NdofInput) -> None:
        self.owner = owner
        self.device = None
        self.timer = None
        self.state = {}
        self._buttons = 0

    def open(self) -> bool:
        import hid
        import ctypes

        # cython-hidapi initializes HIDAPI on import but does not expose its
        # Darwin sharing option. Use the public C API exported by the same
        # extension (not a second HIDAPI instance). Do not seize the cap from
        # 3Dconnexion's driver or other CAD applications.
        library = ctypes.CDLL(hid.__file__)
        exclusive = library.hid_darwin_set_open_exclusive
        exclusive.argtypes = [ctypes.c_int]
        exclusive.restype = None
        exclusive(0)

        # Logitech made the older SpaceNavigators. Filter by usage as well
        # as vendor so ordinary Logitech mice/keyboards are never opened.
        for info in hid.enumerate():
            if (info.get("vendor_id") not in (0x046D, 0x256F)
                    or info.get("usage_page") != 1
                    or info.get("usage") != 8):
                continue
            device = hid.device()
            try:
                device.open_path(info["path"])
                device.set_nonblocking(True)
            except Exception:
                device.close()
                continue
            self.device = device
            self.timer = QTimer(self.owner)
            self.timer.setInterval(8)
            self.timer.timeout.connect(self._read)
            self.timer.start()
            return True
        return False

    def close(self) -> None:
        if self.timer is not None:
            self.timer.stop()
            self.timer.deleteLater()
            self.timer = None
        if self.device is not None:
            device, self.device = self.device, None
            device.close()
        self.state.clear()
        self._release()

    def _release(self):
        for bit in range(32):
            if self._buttons >> bit & 1:
                self.owner._emit_button(bit, False)
        self._buttons = 0
        self.owner._last_t = None

    def refresh_activation(self):
        app = QApplication.instance()
        active = (app is not None
                  and app.applicationState() == Qt.ApplicationActive
                  and app.activeModalWidget() is None
                  and current_settings().enabled)
        if not active:
            self._release()
        return active

    def _read(self) -> None:
        active = self.refresh_activation()
        latest = None
        try:
            # Drain split translation/rotation reports together, preserving
            # button edges. A bound prevents a noisy device starving Qt.
            for _ in range(64):
                report = self.device.read(64)
                if not report:
                    break
                before = self._buttons
                sample = parse_hid_report(bytes(report), self.state)
                if sample is not None:
                    latest = sample
                after = self.state.get("buttons", 0)
                if not active:
                    continue
                for bit in range(32):
                    if (before ^ after) >> bit & 1:
                        self.owner._emit_button(bit, bool(after >> bit & 1))
                self._buttons = after
        except OSError:
            self.owner.disconnected()
            return
        if not active:
            # Split reports received by another app must not contribute
            # a stale rotation/translation after focus returns.
            self.state.clear()
        # Never replay a cached deflection when no new motion arrived.
        if active and latest is not None:
            self.owner._emit_motion(latest)
