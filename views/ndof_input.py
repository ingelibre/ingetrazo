# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""3D mouse input — the drivers that feed :mod:`core.ndof` (issue #108).

No SDK, no new dependency: each platform already has a plain way to read
the device.

* **Linux — spacenavd.** The free driver every distribution packages
  (``spacenavd``). It serves the device on a Unix socket in a fixed binary
  protocol: 32-byte packets of eight native ints, ``type`` first — 0 motion
  (x y z rx ry rz period), 1 button press, 2 release. Read with a
  ``QSocketNotifier``, so it never blocks the UI.
* **Windows — Raw Input.** A 3D mouse is a USB HID «multi-axis controller»
  (usage page 1, usage 8); registering for it makes Windows send
  ``WM_INPUT`` with the device's own reports, next to (not instead of) the
  3Dconnexion driver. Report 1 is translation (three int16) — or all six
  axes on the newer models, report 2 rotation, report 3 the buttons. This is
  what FreeCAD does.
* **macOS** has no such road (only 3Dconnexion's framework): not yet.

:class:`NdofInput` picks the backend for the platform and emits
``motion(sample, dt)`` in the user's frame (see :mod:`core.ndof`).
"""
from __future__ import annotations

import os
import struct
import sys
import time

from PySide6.QtCore import QObject, Signal

from core.ndof import NdofSample, from_hid, from_spacenavd

SPNAV_SOCKETS = ("/var/run/spnav.sock", "/run/spnav.sock")
_SPNAV_PACKET = struct.Struct("=8i")


class NdofInput(QObject):
    """One 3D mouse, whichever the platform. ``motion`` carries an
    :class:`NdofSample` and the seconds since the previous one; ``button``
    the button number and whether it went down."""

    motion = Signal(object, float)
    button = Signal(int, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._backend = None
        self._last_t: float | None = None

    @property
    def backend_name(self) -> str | None:
        return getattr(self._backend, "name", None)

    def start(self) -> bool:
        """Connect to the device's driver. False when there is none — the
        normal case on a machine without a 3D mouse, and silent."""
        if self._backend is not None:
            return True
        for cls in _backends_for(sys.platform):
            try:
                b = cls(self)
                if b.open():
                    self._backend = b
                    return True
            except Exception:  # noqa: BLE001 — a driver quirk never stops the app
                continue
        return False

    def stop(self) -> None:
        if self._backend is not None:
            try:
                self._backend.close()
            finally:
                self._backend = None
        self._last_t = None

    # ---- called by the backends ------------------------------------------
    def _emit_motion(self, sample: NdofSample, dt: float | None = None) -> None:
        now = time.monotonic()
        if dt is None:
            # The device reports steadily while the cap is held; the first
            # reading after a pause gets one report's worth of time.
            dt = (now - self._last_t) if self._last_t is not None else 1 / 60
        self._last_t = None if sample.is_idle() else now
        self.motion.emit(sample, float(dt))

    def _emit_button(self, number: int, down: bool) -> None:
        self.button.emit(int(number), bool(down))


def _backends_for(platform: str) -> list:
    if platform.startswith("linux") or platform.startswith("freebsd"):
        return [SpnavBackend]
    if platform == "win32":
        return [RawInputBackend]
    return []


# ---- Linux: spacenavd --------------------------------------------------------

class SpnavBackend:
    name = "spacenavd"

    def __init__(self, owner: NdofInput) -> None:
        self.owner = owner
        self.sock = None
        self.notifier = None
        self._buf = b""

    def open(self) -> bool:
        import socket
        from PySide6.QtCore import QSocketNotifier
        path = next((p for p in SPNAV_SOCKETS if os.path.exists(p)), None)
        if path is None:
            return False
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(path)
        except OSError:
            sock.close()
            return False
        sock.setblocking(False)
        self.sock = sock
        self.notifier = QSocketNotifier(sock.fileno(),
                                        QSocketNotifier.Read, self.owner)
        self.notifier.activated.connect(self._read)
        return True

    def close(self) -> None:
        if self.notifier is not None:
            self.notifier.setEnabled(False)
            self.notifier.deleteLater()
            self.notifier = None
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def _read(self, *_args) -> None:
        try:
            chunk = self.sock.recv(4096)
        except BlockingIOError:
            return
        except OSError:
            chunk = b""
        if not chunk:                       # the daemon went away
            self.close()
            return
        self._buf += chunk
        latest = None
        size = _SPNAV_PACKET.size
        while len(self._buf) >= size:
            packet, self._buf = self._buf[:size], self._buf[size:]
            kind, *vals = _SPNAV_PACKET.unpack(packet)
            if kind == 0:
                # Coalesce: a burst read at once is one camera step with the
                # time the device says it covered (``period``, in ms).
                x, y, z, rx, ry, rz, period = vals
                latest = (from_spacenavd(x, y, z, rx, ry, rz),
                          (latest[1] if latest else 0.0) + period / 1000.0)
            elif kind in (1, 2):
                self.owner._emit_button(vals[0], kind == 1)
        if latest is not None:
            sample, dt = latest
            self.owner._emit_motion(sample, dt if dt > 0 else None)


def parse_spnav_packets(data: bytes) -> list:
    """The packets in *data* as ``(kind, values)`` — for tests and for
    anyone checking what the daemon sends."""
    size = _SPNAV_PACKET.size
    out = []
    for i in range(0, len(data) - size + 1, size):
        kind, *vals = _SPNAV_PACKET.unpack(data[i:i + size])
        out.append((kind, vals))
    return out


# ---- Windows: Raw Input ------------------------------------------------------

WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIM_TYPEHID = 2
HID_USAGE_PAGE_GENERIC = 0x01
HID_USAGE_MULTI_AXIS = 0x08


def parse_hid_report(report: bytes, state: dict) -> NdofSample | None:
    """Fold one HID report from a 3Dconnexion device into *state* (the last
    translation and rotation) and return the six axes, or None for a report
    that carries no motion. Report 1 is the translation — or, on the newer
    devices (SpaceMouse Compact/Pro Wireless, the Universal Receiver), all
    six axes in one; report 2 the rotation; report 3 the buttons."""
    if not report:
        return None
    rid, body = report[0], report[1:]
    if rid == 1 and len(body) >= 12:
        vals = struct.unpack_from("<6h", body)
        state["t"], state["r"] = vals[:3], vals[3:]
    elif rid == 1 and len(body) >= 6:
        state["t"] = struct.unpack_from("<3h", body)
    elif rid == 2 and len(body) >= 6:
        state["r"] = struct.unpack_from("<3h", body)
    elif rid == 3:
        mask = int.from_bytes(body[:4].ljust(4, b"\0"), "little")
        state["buttons"] = mask
        return None
    else:
        return None
    t = state.get("t", (0, 0, 0))
    r = state.get("r", (0, 0, 0))
    return from_hid(*t, *r)


class RawInputBackend:
    name = "rawinput"

    def __init__(self, owner: NdofInput) -> None:
        self.owner = owner
        self.filter = None
        self.state: dict = {}

    def open(self) -> bool:
        import ctypes
        from ctypes import wintypes
        from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

        class RAWINPUTDEVICE(ctypes.Structure):
            _fields_ = [("usUsagePage", wintypes.USHORT),
                        ("usUsage", wintypes.USHORT),
                        ("dwFlags", wintypes.DWORD),
                        ("hwndTarget", wintypes.HWND)]

        user32 = ctypes.windll.user32
        dev = RAWINPUTDEVICE(HID_USAGE_PAGE_GENERIC, HID_USAGE_MULTI_AXIS,
                             0, None)      # follow the keyboard focus
        if not user32.RegisterRawInputDevices(
                ctypes.byref(dev), 1, ctypes.sizeof(dev)):
            return False
        backend = self

        class _Filter(QAbstractNativeEventFilter):
            def nativeEventFilter(self, event_type, message):
                try:
                    if bytes(event_type) == b"windows_generic_MSG":
                        backend._on_msg(int(message))
                except Exception:  # noqa: BLE001 — never break the event loop
                    pass
                return False, 0

        self.filter = _Filter()
        QCoreApplication.instance().installNativeEventFilter(self.filter)
        return True

    def close(self) -> None:
        if self.filter is not None:
            from PySide6.QtCore import QCoreApplication
            app = QCoreApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self.filter)
            self.filter = None

    def _on_msg(self, msg_ptr: int) -> None:
        import ctypes
        from ctypes import wintypes

        class MSG(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                        ("wParam", wintypes.WPARAM),
                        ("lParam", wintypes.LPARAM),
                        ("time", wintypes.DWORD), ("pt", wintypes.POINT)]

        class RAWINPUTHEADER(ctypes.Structure):
            _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                        ("hDevice", wintypes.HANDLE),
                        ("wParam", wintypes.WPARAM)]

        msg = MSG.from_address(msg_ptr)
        if msg.message != WM_INPUT:
            return
        user32 = ctypes.windll.user32
        size = wintypes.UINT(0)
        hdr = ctypes.sizeof(RAWINPUTHEADER)
        user32.GetRawInputData(ctypes.c_void_p(msg.lParam), RID_INPUT, None,
                               ctypes.byref(size), hdr)
        if size.value == 0:
            return
        buf = ctypes.create_string_buffer(size.value)
        got = user32.GetRawInputData(ctypes.c_void_p(msg.lParam), RID_INPUT,
                                     buf, ctypes.byref(size), hdr)
        if got != size.value:
            return
        header = RAWINPUTHEADER.from_buffer_copy(buf.raw[:hdr])
        if header.dwType != RIM_TYPEHID:
            return
        size_hid, count = struct.unpack_from("<II", buf.raw, hdr)
        data = buf.raw[hdr + 8:hdr + 8 + size_hid * count]
        for i in range(count):
            report = data[i * size_hid:(i + 1) * size_hid]
            before = self.state.get("buttons", 0)
            sample = parse_hid_report(report, self.state)
            if sample is not None:
                self.owner._emit_motion(sample)
            after = self.state.get("buttons", 0)
            for bit in range(32):
                if (before ^ after) >> bit & 1:
                    self.owner._emit_button(bit, bool(after >> bit & 1))


# ---- Settings ----------------------------------------------------------------

_KEYS = (("enabled", True), ("sensitivity", 1.0), ("invert_pan", False),
         ("invert_zoom", False), ("invert_rotate", False),
         ("invert_pan_x", False), ("invert_pan_y", False),
         ("invert_tilt", False), ("invert_spin", False),
         ("lock_rotation", False))


def load_settings():
    """The user's 3D mouse settings (Preferences ▸ Navigation)."""
    from PySide6.QtCore import QSettings
    from core.ndof import NdofSettings
    st = QSettings()
    out = NdofSettings()
    for key, default in _KEYS:
        raw = st.value(f"ndof/{key}", None)
        if raw is None:
            continue
        if isinstance(default, bool):
            setattr(out, key, str(raw).lower() in ("1", "true"))
        else:
            try:
                setattr(out, key, max(0.25, min(4.0, float(raw))))
            except (TypeError, ValueError):
                pass
    return out


_settings_cache = None


def current_settings():
    """The settings every window moves the camera with — read once, then
    kept current by :func:`save_settings`."""
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = load_settings()
    return _settings_cache


def save_settings(settings) -> None:
    global _settings_cache
    _settings_cache = settings
    from PySide6.QtCore import QSettings
    st = QSettings()
    for key, default in _KEYS:
        val = getattr(settings, key)
        st.setValue(f"ndof/{key}",
                    ("1" if val else "0") if isinstance(default, bool)
                    else float(val))
    st.sync()


_shared: NdofInput | None = None


def shared_input() -> NdofInput:
    """The application's one 3D mouse connection — several model windows
    share it and the active one moves (a device has one driver socket)."""
    global _shared
    if _shared is None:
        from PySide6.QtCore import QCoreApplication
        _shared = NdofInput(QCoreApplication.instance())
        _shared.start()
    return _shared
