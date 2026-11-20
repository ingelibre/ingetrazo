# SpaceMouse setup

Use Preferences → 3D Mouse to enable navigation and adjust speed, axis
inversion and rotation locking. The active model window receives the input.

- Linux: install and start `spacenavd`.
- Windows: install the 3Dconnexion driver.
- macOS: install and start 3DxWare. IngeTrazo uses the installed
  `3DconnexionClient.framework`; the proprietary driver is not bundled.
  If the framework is unavailable, IngeTrazo tries the `hidapi` Python
  package included in the macOS requirements. This fallback opens only
  SpaceMouse multi-axis devices from 3Dconnexion or Logitech, in
  nonexclusive mode.

An unavailable connection is retried every two seconds. Preferences updates
its driver status when a connection succeeds or is lost. Unplugging a HID
device schedules reconnection; the framework backend remains registered
with 3DxWare across device removal and releases held buttons and motion.
macOS input pauses when the app loses focus, navigation is disabled, or
a modal dialog is open. Closing a dialog resumes navigation automatically.

The fallback has automated tests using simulated devices. Real hardware
still needs verification with and without 3DxWare, including unplug/replug
and switching between CAD applications.

The HIDAPI fallback and reconnect behavior were adapted from
[Brian Russell's PR #190](https://github.com/ingelibre/ingetrazo/pull/190).
The existing framework backend is retained.
