# SPDX-License-Identifier: GPL-3.0-or-later
import ctypes as C
from types import SimpleNamespace

from PySide6.QtCore import Qt

from views import connexion_macos as mac


def test_driver_state_abi():
    assert C.sizeof(mac.DeviceState) == 48
    assert mac.DeviceState.time.offset == 12
    assert mac.DeviceState.axis.offset == 30
    assert mac.DeviceState.buttons.offset == 44


def backend(monkeypatch):
    motion, buttons, controls = [], [], []
    owner = SimpleNamespace(_last_t=None,
                            _emit_motion=motion.append,
                            _emit_button=lambda *args: buttons.append(args))
    device = mac.ConnexionBackend(owner)
    device.client = 42
    device.active = True
    device._control = lambda command: (controls.append(command), 0)[1]
    app = SimpleNamespace(applicationState=lambda: Qt.ApplicationActive,
                          activeModalWidget=lambda: None)
    monkeypatch.setattr(mac, "QApplication", SimpleNamespace(instance=lambda: app))
    from views import ndof_input
    settings = SimpleNamespace(enabled=True)
    monkeypatch.setattr(ndof_input, "current_settings", lambda: settings)
    return device, motion, buttons, controls, settings, app


def send(device, client=42, command=3, buttons=0):
    state = mac.DeviceState(client=client, command=command, buttons=buttons)
    state.axis[:] = [350, 0, -350, 0, 0, 0]
    device._message(0, 0x33645352, C.addressof(state))


def test_callbacks_copy_data_and_only_deliver_our_client(monkeypatch):
    device, motion, buttons, *_ = backend(monkeypatch)
    send(device, client=99)
    device._poll()
    assert not motion
    send(device)
    assert not motion  # callback never mutates camera or Qt
    device._poll()
    assert motion[0].right == 1 and motion[0].up == 1
    device._poll()
    assert len(motion) == 1  # no replay of a held/stale deflection
    send(device, command=2, buttons=1)
    send(device, command=2, buttons=1)
    send(device, command=2, buttons=0)
    device._poll()
    assert buttons == [(0, True), (0, False)]


def test_disabled_or_background_app_releases_device(monkeypatch):
    device, motion, buttons, controls, settings, app = backend(monkeypatch)
    settings.enabled = False
    send(device)
    device._poll()
    assert controls == [0x33646463]
    assert not motion and not device.active
    settings.enabled = True
    device._poll()
    assert controls[-1] == 0x33646163 and device.active
    app.applicationState = lambda: Qt.ApplicationInactive
    send(device)
    device._poll()
    assert not motion and not device.active


def test_device_removal_clears_pending_motion(monkeypatch):
    device, motion, *_ = backend(monkeypatch)
    send(device)
    device.removed_callback(0)
    device._poll()
    assert not motion


def test_modal_dialog_releases_device(monkeypatch):
    device, motion, _, controls, _, app = backend(monkeypatch)
    app.activeModalWidget = lambda: object()
    send(device)
    device._poll()
    assert controls == [0x33646463]
    assert not motion
