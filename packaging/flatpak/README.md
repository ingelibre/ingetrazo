# IngeTrazo as a Flatpak

For the engineer who never opens a terminal: download `IngeTrazo.flatpak`,
double-click it, and GNOME Software / KDE Discover installs it — the
Freedesktop runtime comes from Flathub automatically (the bundle carries
`--runtime-repo`). Deliberately NOT on Flathub for now; this is
self-distribution, the same road IngeCAD and IngePresupuestos walk. The
bundle rides each GitHub release.

Building requires the matching Freedesktop SDK and its Rust extension:

```bash
flatpak remote-add --user --if-not-exists flathub \
  https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub org.freedesktop.Platform//25.08 \
  org.freedesktop.Sdk//25.08 org.freedesktop.Sdk.Extension.rust-stable//25.08
```

    packaging/flatpak/build-flatpak.sh            # build + install (user)
    packaging/flatpak/build-flatpak.sh --bundle   # + .staging/IngeTrazo.flatpak

The app module lets pip and Cargo reach the network for wheels (PySide6,
numpy, openskp), maturin and Rust crates, which is exactly what Flathub
forbids: if this ever goes there, those dependencies must become generated
offline sources (flatpak-pip-generator and flatpak-cargo-generator).

The Rust engine is compiled inside the SDK against the sandbox's Python,
then installed into `/app`; maturin stays in a temporary build environment
and is not shipped. After installing, the build script runs `--check` in
the normal runtime with `INGETRAZO_REQUIRE_RUST=1`, rejecting a missing or
unloadable engine before exporting a bundle. Release CI installs the Rust
SDK extension too. The engine remains off by default: enable it in
Preferences ▸ General and restart IngeTrazo.

Sandbox: wayland + fallback-x11 + dri + `--filesystem=home`, **plus
network** — unlike IngeCAD, IngeTrazo fetches base-map tiles, the terrain
DEM and geocoding results (Track G). The pure-Python openskp backend
covers every .skp era natively.
