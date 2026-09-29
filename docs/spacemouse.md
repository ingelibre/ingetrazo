# 3Dconnexion SpaceMouse

Connect your SpaceMouse before or after starting IngeTrazo. Open
**Window ▸ Preferences ▸ 3D Mouse** to check the connection, enable navigation,
adjust speed or invert individual axes. Connections are retried every two
seconds when unavailable or disconnected.

* **macOS:** install and run the 3Dconnexion driver. IngeTrazo loads its
  installed client framework and registers for motion and the first two
  buttons. It relinquishes device control when another application is active,
  when a modal dialog opens, or when navigation is disabled. Preferences
  shows **3Dconnexion macOS driver** when registration succeeds. The framework
  is not redistributed with IngeTrazo. On machines without the driver, direct
  HID access is attempted using `hidapi` (included in requirements.txt and
  packaged builds); macOS permissions or another driver may prevent this.
  Older prebuilt releases do not contain these backends.
* **Linux:** install and start `spacenavd` using your distribution's package
  manager. The application connects to `/var/run/spnav.sock` or `/run/spnav.sock`.
  Sandboxed packages also need access to that socket.
* **Windows:** use the 3Dconnexion driver. IngeTrazo reads Windows Raw Input.

The cap moves the model: push sideways to pan, lift to move it up, push away
to zoom out, tilt to orbit vertically and twist to orbit horizontally.
Movements can be combined. The horizon stays level: cap roll is intentionally
ignored. Enable **Pan and zoom only** to preserve a plan view. Buttons 1 and 2
fit the model. Disabling navigation also disables these button actions.
Only the active model window responds; a modal dialog does not navigate.

The macOS backend accepts Logitech and 3Dconnexion multi-axis HID interfaces
and handles both split and combined motion reports. Wired USB and USB receiver
connections exposing that interface are supported by the implementation;
Bluetooth and individual hardware models have not been physically validated.

Backend reference: [cython-hidapi](https://github.com/trezor/cython-hidapi).
