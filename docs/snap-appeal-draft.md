# Borrador de apelación — Snap Store (ingetrazo marcado como malicioso)

**Para:** help@snapcraft.io
**Asunto:** False positive review on snap "ingetrazo" (rev 1) — fully open-source, built in public CI

---

Hello Snap Store team,

I received your notice that my snap "ingetrazo" (revision 1, version
0.3.8) was flagged as potentially malicious and made private. I believe
this is a false positive and I would like to ask for a re-review. Every
claim below is publicly verifiable:

1. **IngeTrazo is free software (GPL-3.0-or-later).** Full source code:
   https://github.com/ingelibre/ingetrazo — a 3D modeling application
   (Qt/PySide6) for architecture and civil engineering. Website:
   https://ingetrazo.com

2. **The exact snap you reviewed was built in public GitHub Actions CI**,
   not on a private machine. Build run:
   https://github.com/ingelibre/ingetrazo/actions/runs/33466823574
   (job "Snap (x86_64)"). The recipe is in the repository:
   `packaging/snap/snapcraft.yaml.in` and the `snap` job in
   `.github/workflows/release.yml`. The same commit ships as AppImage,
   tarball, Flatpak and a Windows installer on the GitHub release
   (v0.3.8), all built by the same public pipeline.

3. **What likely tripped the scanner:**
   - The application is frozen with **PyInstaller**; its bootloader is a
     well-known antivirus false-positive family.
   - The snap bundles `vendor/libredwg/bin/dwg2dxf`, the DWG→DXF
     converter from **GNU LibreDWG** (GPL, https://www.gnu.org/software/libredwg/),
     used for opening AutoCAD DWG drawings. Its provenance and rebuild
     instructions are documented in the repo
     (`vendor/libredwg/SOURCES.md`).

4. The snap requests only standard auto-connecting interfaces (opengl,
   x11, wayland, desktop, home, network, removable-media) under strict
   confinement, and contains no telemetry, no cryptocurrency code, no
   obfuscation.

I am happy to rebuild the snap any way you prefer (for example from
source with the python plugin), to provide checksums matching the CI
artifacts, or anything else that helps the review. Could you please
re-review revision 1 and restore the snap?

Thank you for your time,

Marco Sumari
ing.marco.sumari@gmail.com
https://github.com/ingelibre — IngeTrazo, IngeCAD, IngePresupuestos

---

**Además del correo:** publica el mismo texto en
https://forum.snapcraft.io/ (categoría *store-requests*) — el foro suele
responder más rápido que el correo, y las apelaciones de falsos positivos
se resuelven ahí normalmente en días.

**Mientras tanto, NO:** re-subir revisiones, cambiar la visibilidad, ni
publicar los snaps hermanos (ingecad, ingepresupuestos) — un segundo
flag en la misma cuenta escalaría feo. Primero que respondan.
