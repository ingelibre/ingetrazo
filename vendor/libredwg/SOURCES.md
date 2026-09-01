# vendor/libredwg — el satélite DWG

`bin/dwg2dxf` es el conversor de [GNU LibreDWG](https://www.gnu.org/software/libredwg/)
(GPL-3.0-or-later, como IngeTrazo), compilado como ejecutable de línea de
comandos para x86_64 Linux, enlazado solo contra libc/libm — corre en
cualquier distro razonable. Portado del build de IngeCAD (2026-08-31), que
lleva los dos remiendos documentados en `formats/dwg_bridge.py` (handles 0 y
duplicados — LibreDWG issue #1356).

El código fuente está en el upstream de LibreDWG (https://github.com/LibreDWG/libredwg).
Para reconstruirlo: `./configure --disable-shared --disable-bindings && make`
y tomar `programs/dwg2dxf`.

`dxf2dwg` (export a DWG) no se incluye: la app aún no lo usa.
