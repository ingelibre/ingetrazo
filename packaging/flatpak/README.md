# IngeTrazo as a Flatpak

For the engineer who never opens a terminal: download `IngeTrazo.flatpak`,
double-click it, and GNOME Software / KDE Discover installs it — the
Freedesktop runtime comes from Flathub automatically (the bundle carries
`--runtime-repo`). Deliberately NOT on Flathub for now; this is
self-distribution, the same road IngeCAD and IngePresupuestos walk. The
bundle rides each GitHub release.

    packaging/flatpak/build-flatpak.sh            # build + install (user)
    packaging/flatpak/build-flatpak.sh --bundle   # + .staging/IngeTrazo.flatpak

The app module lets pip reach the network for wheels (PySide6, numpy,
openskp), which is exactly what Flathub forbids: if this ever goes there,
that module becomes generated offline sources (flatpak-pip-generator) and
this file is the reminder.

Sandbox: wayland + fallback-x11 + dri + `--filesystem=home`, **plus
network** — unlike IngeCAD, IngeTrazo fetches base-map tiles, the terrain
DEM and geocoding results (Track G). No skp2dae fallback inside the
sandbox (it is a Wine satellite); the pure-Python openskp backend covers
every .skp era natively.
