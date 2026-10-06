"""Fallback selection, focus gating and reconnect without USB hardware."""
import struct
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from core.ndof import NdofSettings
from views import ndof_input, ndof_hid


class Device:
    def __init__(self):
        self.reports = []
        self.closed = False

    def read(self, _size):
        if self.reports and isinstance(self.reports[0], Exception):
            raise self.reports.pop(0)
        return self.reports.pop(0) if self.reports else []

    def close(self):
        self.closed = True

    def open_path(self, path):
        self.path = path

    def set_nonblocking(self, value):
        self.nonblocking = value


@pytest.fixture
def fallback(monkeypatch):
    owner = ndof_input.NdofInput()
    backend = ndof_hid.HidBackend(owner)
    backend.device = Device()
    owner._backend = backend
    state = SimpleNamespace(focus=Qt.ApplicationActive, modal=None)
    app = SimpleNamespace(applicationState=lambda: state.focus,
                          activeModalWidget=lambda: state.modal)
    monkeypatch.setattr(ndof_hid, "QApplication", SimpleNamespace(instance=lambda: app))
    monkeypatch.setattr(ndof_input, "_settings_cache", NdofSettings())
    yield owner, backend, state
    owner.stop()


def test_split_reports_coalesce_without_replaying_motion(fallback):
    owner, backend, _state = fallback
    motion, buttons = [], []
    owner.motion.connect(lambda sample, _dt: motion.append(sample))
    owner.button.connect(lambda *args: buttons.append(args))
    backend.device.reports = [struct.pack('<B3h', 1, 350, 0, 0),
                              struct.pack('<B3h', 2, 0, 350, 0),
                              bytes([3, 1, 0, 0, 0]), bytes([3, 0, 0, 0, 0])]
    backend._read()
    assert len(motion) == 1 and motion[0].right == 1
    assert buttons == [(0, True), (0, False)]
    backend._read()
    assert len(motion) == 1


@pytest.mark.parametrize('blocked', ['focus', 'modal', 'disabled'])
def test_focus_modal_and_disabled_release_buttons(fallback, blocked):
    owner, backend, state = fallback
    buttons, motions = [], []
    owner.button.connect(lambda *args: buttons.append(args))
    owner.motion.connect(lambda *args: motions.append(args))
    backend.device.reports = [bytes([3, 1, 0, 0, 0])]
    backend._read()
    if blocked == 'focus':
        state.focus = Qt.ApplicationInactive
    elif blocked == 'modal':
        state.modal = object()
    else:
        ndof_input.current_settings().enabled = False
    backend.device.reports = [struct.pack('<B3h', 1, 350, 0, 0)]
    backend._read()
    assert buttons == [(0, True), (0, False)] and not motions
    assert owner._last_t is None
    assert not backend.state


def test_disconnect_closes_device_and_schedules_retry(fallback):
    owner, backend, _state = fallback
    device = backend.device
    device.reports = [OSError('unplugged')]
    backend._read()
    assert device.closed and owner._backend is None
    assert owner._retry.isActive()


def test_open_is_nonexclusive_and_ignores_ordinary_logitech_mouse(fallback, monkeypatch):
    owner, backend, _state = fallback
    calls = []
    def exclusive(value):
        calls.append(value)
    library = SimpleNamespace(hid_darwin_set_open_exclusive=exclusive)
    monkeypatch.setattr('ctypes.CDLL', lambda _path: library)
    device = Device()
    monkeypatch.setitem(sys.modules, 'hid', SimpleNamespace(
        __file__='fake-hid', device=lambda: device,
        enumerate=lambda: [dict(vendor_id=0x046D, usage_page=1, usage=2, path=b'mouse'),
                           dict(vendor_id=0x256F, usage_page=1, usage=8, path=b'cap')]))
    assert backend.open()
    assert calls == [0] and device.path == b'cap' and device.nonblocking
    assert backend.timer.isActive()


def test_driver_failure_selects_hid_fallback(fallback, monkeypatch):
    owner, backend, _state = fallback
    owner.stop()
    class MissingDriver:
        def __init__(self, owner):
            pass
        def open(self):
            raise OSError('no driver')
        def close(self):
            pass
    monkeypatch.setattr(ndof_input, '_backends_for', lambda _platform: [MissingDriver, lambda _owner: backend])
    monkeypatch.setattr(backend, 'open', lambda: True)
    assert owner.start() and owner.backend_name == 'HIDAPI (3Dconnexion)'
    assert not owner._retry.isActive()
