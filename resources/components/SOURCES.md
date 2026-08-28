# Component sources

- `person_billboard.png` (flat-colour arch-viz cutout) and
  `person_silhouette.png`/`.svg` — derived from "Silhouette of man standing and facing forward.svg"
  (Wikimedia Commons), dedicated to the public domain under **CC0 1.0**
  (no attribution required; noted here for provenance). Recoloured to the
  IngeTrazo slate tone and tight-cropped for the face-me billboard.
- `sumari.png` — the author himself (1.68 m): self-made cutout from his own photo, original artwork by Marco Sumari Tellez. The IngeTrazo scale figure, in the SketchUp tradition of real people.

- The `*.igz` starter components are Sweet Home 3D furniture-library models,
  kept offline so the tray works with no network. Each file is one group with
  its images packed inside; the online catalogue they came from is described
  in `core/library.py`. Licence and author, as those licences require:
  - `banco.igz` (Bench) — **CC BY 4.0**, Kator Legaz
  - `fuente.igz` (Fountain) — **CC BY 4.0**, Pndrdm & Emmanuel Puybaret
  - `chica.igz` (Woman) — **CC BY 4.0**, Reallusion
  - `pickup.igz`, `suv.igz` — **CC BY 4.0**, Scopia
  - `abedul.igz` (Birch), `arbol.igz` (Tree) — **Free Art License 1.3**,
    Ola-Kristian Hoff. Copyleft: a derived work inherits the licence.
  - `sofa.igz` (Sofa) — **CC0 1.0**, Blend Swap (public domain)

- The face-me people in `people.json` — `ingeniero.png`, `stallman.png`,
  `torvalds.png`, `musk.png`, `hawking.png` — are cutout illustrations
  supplied by Marco Sumari Tellez, cropped to the figure and sized to the
  real height each one stands (the manifest carries it: a scale figure whose
  height is wrong is worse than none). Hawking's is his seated height in the
  chair, because that is what the drawing shows.

No `.glb` component ships any more: the Sketchfab CC-BY starter set was
retired when the offline `.igz` set replaced it, and the bed went with it at
the author's request. `formats/glb.py` still imports the format — it is what
a user's own download arrives as.
