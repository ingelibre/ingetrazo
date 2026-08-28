# Colour sources

- `ral.json` — the **RAL Classic** collection: 213 colours, each with its
  code, its name in English and Spanish, and its sRGB value.

  The point of shipping it is not that it has more colours than the handful
  the tray had: it is that a colour picked from it paints as a **named**
  material — `RAL 7035 Gris claro` — so what the drawing carries is a
  reference a painter can buy, not an RGB triple nobody can match. It is the
  standard architectural and industrial finishes are specified in.

  The codes, names and hex values were taken from
  **[pixelbrackets/ral-color-chart](https://github.com/pixelbrackets/ral-color-chart)**
  (`src/RalColorChart.php`), published under **GPL-2.0-or-later** and so
  usable here. Three entries were normalised against the standard's own
  naming: RAL 6003 and RAL 6019 arrived lower-cased, and RAL 7013 carried an
  alias list (`Brown-grey also NATO-olive also Stone-grey-olive`) where the
  official English name is `Brown grey`. The Spanish names are our own
  translation of the standard's names.

  RAL® is a registered trademark of RAL gGmbH. Nothing here is affiliated
  with or endorsed by them: the file is a list of public colour references
  with approximate sRGB values, which is all a screen can offer. **For a real
  finish, match against a physical RAL fan deck** — no monitor is a
  colourimeter.

  The names live in this file rather than in `i18n/`, because they are the
  standard's own words in the standard's own languages; putting "Beige" or
  "Cream" into the UI translations would collide with strings that mean
  something else entirely.
