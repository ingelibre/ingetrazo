# Ejemplos

Cuatro documentos reales, dibujados con IngeTrazo para la remodelación de la
plaza de Yanque, distrito de Chichas (Arequipa, 2026) por Marco Sumari Tellez. Ábrelos
con **Archivo ▸ Abrir** (o doble clic si tienes IngeTrazo instalado); tres
de ellos traen su lámina A3 lista en **Archivo ▸ Compositor de láminas** y,
al lado, el PDF que sale de ahí para que compares.

| Archivo | Qué es | Qué enseña |
|---|---|---|
| `pileta-fuente-yanque.igz` (+ `.pdf`) | La pileta central de la plaza: pedestal octogonal, fuste estriado, dos platos de borde ondulado, vereda con nariz boleada | Componentes repetidos (22 instancias), sombras con sol real, plano de sección, lámina con planta, cortes y detalle |
| `banca-pergola-yanque.igz` (+ `.pdf`) | Banca de concreto con pérgola de madera | Componentes, cinco escenas guardadas, lámina con 23 cotas y 12 etiquetas con guía |
| `luminaria-solar-yanque.igz` (+ `.pdf`) | Poste de alumbrado solar de 4,5 m: dado tronco-cónico, cimiento enterrado y su acero de 3/8", dos reflectores con panel | Modelado por recetas con el Asistente IA (puente MCP), detalle de acero, lámina con cuatro vistas |
| `arco-yanque.igz` | Arco de bienvenida «YANQUE» según la lámina estructural E02: concreto, **todo el acero** (zapatas, columnas, arco segmental, viga, tímpano), capiteles de sillar, cuatro farolas ornamentales, letras y escultura | Rayos X para ver el acero, planos de sección, imágenes face-me, texturas |

Están guardados con la versión 0.3.12 o posterior; una versión anterior no
los abre. Los cuatro pesan 6,3 MB en total.

## Capas

`capas-prueba.igz` — un documento de ejemplo, sintético, con todas las
funciones de capas: carpetas anidadas, capa activa, los diez tipos de línea,
grosores, transparencia, una capa bloqueada, otra que no se imprime, capas
vacías para purgar, escenas y una lámina con la leyenda. Es el que siguen el
manual [`docs/layers.md`](../docs/layers.md) y sus capturas. Lo genera
`capas-prueba.py` (`python examples/capas-prueba.py` desde la carpeta de
IngeTrazo), que lo deja como nuevo si lo has modificado al probar.

## Extensiones

`extensions/niveles.py` — **Niveles**: niveles del edificio (PB, PA…) guardados en el documento, guías a trazos en alzados y cortes en proyección paralela, y el cursor que se engancha a esas alturas. Idea y primera versión de José Castro Basso (FADU–UDELAR). Viene con IngeTrazo pero sin activar: se instala desde **Extensiones ▸ Gestionar extensiones…** (o copiándola en la carpeta de complementos) y se reinicia IngeTrazo: aparece la pestaña «Niveles» en la bandeja lateral.

## Licencia

Los documentos de esta carpeta (modelos, láminas y PDF) son de
Marco Sumari Tellez y se publican bajo
[Creative Commons Atribución 4.0](https://creativecommons.org/licenses/by/4.0/deed.es):
úsalos, modifícalos y compártelos citando la fuente. El código de IngeTrazo
sigue bajo la GPL-3.0-or-later del repositorio.
