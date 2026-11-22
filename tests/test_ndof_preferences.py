"""Live connection labels must disconnect automatically when Qt deletes them."""
from types import SimpleNamespace

from PySide6.QtCore import SIGNAL
import shiboken6

from views.ndof_input import NdofInput
from views.preferences_dialog import _NdofStatusLabel


def test_connection_label_tracks_connect_and_disconnect():
    device = NdofInput()
    label = _NdofStatusLabel(device)
    disconnected = label.text()
    device._backend = SimpleNamespace(name='Example SpaceMouse')
    device.status_changed.emit()
    assert 'Example SpaceMouse' in label.text()
    device._backend = None
    device.status_changed.emit()
    assert label.text() == disconnected
    shiboken6.delete(label)


def test_deleted_label_disconnects_its_qt_slot():
    device = NdofInput()
    label = _NdofStatusLabel(device)
    signal = SIGNAL('status_changed()')
    assert device.receivers(signal) == 1
    shiboken6.delete(label)
    assert device.receivers(signal) == 0
    device.status_changed.emit()
