# Toolbar icon refinement

This change retains the 101 existing core toolbar keys and tool metaphors,
refines spacing and stroke weights, and gives each selected accent a tone
suited to the current light or dark toolbar background. The runtime renderer
uses the current Qt ink and the existing `views.theme.accent_color()` value,
including custom system accents. No additional preference is introduced.

The original QPainter drawings in `views/icons.py` remain the cursor geometry
and the fallback for new tool keys or unavailable resources. Toolbar rendering
is separate, so cursor hotspots and tool interaction are preserved.

`resources/icons/toolbar.json` contains one shared SVG template per tool with
neutral-ink and accent placeholders. `views/toolbar_icons.py` resolves those
colors at runtime and supplies 20/24/32/40 px and HiDPI rasters. The resource
is included in the PyInstaller specification.

## Matching runtime toolbar comparisons

These images use the real `MainWindow` action lists rendered in isolated Qt
toolbars at the same 24 px size, palette, and button states. The before side
uses `views/icons.py` from upstream commit
`d79ab4419db814ee1b7f04af7abbebc1d93a8022`; the after side uses this change.
They are toolbar renderings, rather than screenshots of the OpenGL viewport.

![Light toolbar before and after](05-toolbars-before-after-light.png)

![Dark toolbar before and after](05-toolbars-before-after-dark.png)

## Saved design comparisons

All previously prepared review images are preserved below. They document the
artwork proposal; the runtime renderer derives its exact colors from the live
Qt palette. The system example uses IngeTrazo's fallback blue rather than a
captured OS setting. Actual system accents are resolved dynamically.

![Original icon sheet](00-original-icons.png)

![Selected icons before and after](01-before-after.png)

![Accent tone overview](02-theme-color-overview.png)

![Light refinement sheet](03-original-refinement-light.png)

![Dark refinement sheet](04-original-refinement-dark.png)

### Every icon in each preset

![Orange icons](theme-orange-all-icons.png)

![Blue icons](theme-blue-all-icons.png)

![Green icons](theme-green-all-icons.png)

![Red icons](theme-red-all-icons.png)

![Purple icons](theme-purple-all-icons.png)

![Yellow icons](theme-yellow-all-icons.png)

![System accent example](theme-system-all-icons.png)

## Validation

Focused tests cover all keys in every preset and appearance, live system
accent and palette changes, frozen resource lookup, small and HiDPI sizes,
resource fallback, and cursor bitmap/hotspot preservation. Existing icon,
theme, accent refresh and toolbar-size tests are included in the same run.

Artwork is derived from IngeTrazo's own icons, under GPL-3.0-or-later.
Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
No SketchUp artwork is included.
