# Changelog

All notable changes to IngeTrazo are documented here.
Format inspired by [Keep a Changelog](https://keepachangelog.com); versions
follow [SemVer](https://semver.org).

## [0.3.6.3] — 2026-08-27

**The release that puts .skp import back.** A change in OpenSKP upstream
turned every imported model into a field of spikes, and hunting Marco's
report through a modelling session took five more defects with it.

### Fixed
- **Imported `.skp` models came in shattered into triangles and spikes.**
  OpenSKP normalized what a coedge's flag carries — SketchUp's raw storage
  bit (0 forward, 1 reversed) became the documented +1 / −1 — and reading it
  as a boolean then took the same endpoint for every coedge, so any polygon
  holding a reversed one came out as a self-intersecting star. Measured on
  Marco's plaza: the same 115973 faces and the same bounding box, with the
  model's surface down from 43008 to 13590 m². The ring now comes from the
  loop's connectivity, which reads the same under either contract, so a
  future rename cannot break it again. v0.3.5 was built before that change
  and was never affected; every 0.3.6.x build was.
- **Drawing a rectangle on a solid opened it.** The Rectangle tool adds its
  own faces, and the flag that says so also gated propagating an edge SPLIT
  into the other faces carrying that edge — so a door drawn on a wall split
  the wall's bottom edge in three while the floor kept the original long
  one. Coincident, not shared, and the box stopped being closed. Everything
  volumetric quietly stops working on an open shell, which is where the next
  three came from. Three fuzz sequences that used to hit a known engine gap
  now pass.
- **Push/Pull into a face read the drag backwards on an open shell.** The
  tool signs the distance along the base's outward normal, which
  `orient_outward` can only establish where there is a volume to test parity
  against. On an open shell a face keeps whatever winding the draw gave it,
  so a drag INTO a wall read as positive: the base face was never hidden and
  the outer face stood there covering the pocket forming behind it, and the
  commit then swept the push the wrong way entirely.
- **Push/Pull's drag preview now reads as one clean solid.** It draws the
  sweep's own edges (they were missing), softens a curve's facet seams the
  way the commit does, carries the material and re-anchors the texture to
  each new face, and paints both sides of a preview face alike — an overlay
  has no back. A clean prism extend or shrink is previewed by moving the
  cap in the model instead, so nothing of the old shape is left standing.
- **Push/Pull extrudes the material with the shape.** Pulling a painted
  rectangle up gave a box with one painted face; the new sides come out
  painted too, each mapping the texture in its own plane.
- **Splitting or carving a painted face keeps the paint.** A line drawn
  across a textured face wiped it off both halves, and a door outlined on a
  textured wall came out bare. Both keep the mother's paint now, and keep
  its texture map, so the image runs straight across the cut instead of
  restarting on each piece.
- **Snapping no longer reaches through a group.** Occlusion only knew the
  loose mesh, so nothing inside a group hid anything and drawing on a box
  snapped to the edge on its far side. It asks the pick index now — the one
  structure that holds the whole model — so occlusion and picking can never
  disagree about what is in front.

### Known
- A rectangle drawn on a face, pushed out and pushed back flush, dissolves
  into the wall. Isolated to the per-plane rebuild: its rule may dissolve
  the operation's own seams, and a pushed face's boundary is both the user's
  line and the operation's rim. Telling them apart needs an edge to carry
  where it came from — the identity work already on the list.

## [0.3.6.2] — 2026-08-27

### Fixed
- **Base-map tile cache evicted the tile it had just written.** Eviction
  reads the filesystem's modification times, and their granularity can be
  coarser than the gap between two writes — so a busy cache had no order
  left to sort by and dropped fresh tiles while keeping stale ones. Each
  write now stamps its tile as strictly the newest.

## [0.3.6.1] — 2026-08-27

### Fixed
- **Saving `.skp` was broken in the 0.3.6 build.** The exporter passed the
  writer two arguments only our OpenSKP fork has (a texture's applied size
  and the opacity gate), so against the library the release is built with,
  every scene with a painted face failed to save. The joins now ask the
  installed writer what it accepts and pass only that; an older library
  writes the file without them rather than not at all.

## [0.3.6] — 2026-08-27

**The nested-placement release**: an imported component keeps the sharing
SketchUp gave it inside itself, which is what makes the files we write
small again — and, hunting that through a real modelling session, three
long-standing freezes fell with it.

### Added
- **Nested placements**: a group owns placements of shared prototype
  meshes, drawn, picked, saved and exported as part of it — one object
  to you, however deep the tree. An imported component no longer arrives
  flattened, so a hedge stored as 9600 faces placed 48 times stays that
  way instead of becoming 230400 real ones.
- **Eyedropper parity (Paint ▸ Alt)**: sampling a face now carries its
  material to the next click the way SketchUp does — image, applied
  size, rotation, translucency and the material identity. A face with an
  explicit world→UV map hands it on only within its own plane, where it
  keeps the pattern lined up; a face on another plane takes the material
  with its own projection at the same size (copying the map across
  planes smeared the image into stripes). The pointer becomes an
  eyedropper while Alt is down.

### Fixed
- **`.skp` files were five times too big.** Saving Marco's pool wrote
  80 MB against SketchUp's 14. Not textures (6.7 MB embedded there
  against 7.1 here) — geometry duplicated by losing a component's
  internal sharing. Now **72.4 MB → 28.7 MB**, with stored faces down
  from 1 294 258 to 75 599 and the world geometry identical (same
  bounding box, area within 0.08%). Prototypes with identical content
  are folded too: a .skp can carry the SAME material under two ids,
  which was splitting the hedge's leaves into twin prototypes.
- **Deleting inside an imported group hung the app** — 206 s to erase
  60 faces in a 3054-face barbecue, and a cliff that made it look
  random: the heal's 3000-face guard let the work through only once you
  had deleted enough. Three passes that scaled with the whole model for
  an edit that touched a part: the T-junction sweep (one pass alone
  measured 24.8 s and repeated per split — the batched version already
  written for Push/Pull now serves both call sites), the heal's
  quadratic coplanar pairing (4.2M face-normal recomputations), and the
  orphan-edge prune. **206 s → 3.07 s**, with a byte-identical result.
- **A moved group left a ghost selection box** where it used to be: the
  translation fast paths carried every cached array except that one.
- **Selecting a big component took seconds** — the box was derived by
  welding a merged copy of the whole component (23.6 s with nested
  placements, 5.1 s before) to read eight corners. Now it works from
  the points: **0.11 s**, and the box is identical.
- Drag previews, rubber-band selection, Explode and the scene queries
  (bounds, world faces, BIM quantities, model info) all reach a
  component's nested geometry; Explode used to leave it behind entirely.
- Zoom got its lightness back: the per-frame instance gather is cached
  per scene version and its frustum cull is one vectorised pass
  (2.5 ms → 0.1 ms per frame).

## [0.3.5] — 2026-08-25

**Sections, the SketchUp parity batch, AI modelling, and the performance
marathon** — a full real-world modelling session (a 280k-face pool
project) hunted down every freeze it hit.

### Added
- **Section planes** (SketchUp's Sections, complete): place the active
  cut with hover plane inference (arrow keys / Shift to lock), one
  active cut per context, GPU-clipped model with **thick cut edges**,
  **section fill**, corner symbol balloons and the Sections toolbar.
  Sections move/rotate/delete like geometry, reverse and "Align View"
  from the context menu, picks and snaps ignore the clipped side, and
  scenes + `.igz` remember the active cut. The composer's hidden-line
  pass clips too and draws the cut chords — real plans and sections on
  sheets.
- **SketchUp tool parity batch**: **Flip** (2023-style axis planes,
  Ctrl = flip a copy, classic context-menu entries), **Make Component**
  (G, shared definitions + Make Unique), **Freehand** (sampled,
  RDP-simplified, selects as one contour), **Pie** arc (closes the
  wedge with a face) and chord bulge / radius suffixes in the
  Measurements box. "Offset" is now **Equidistancia** (SketchUp's
  Spanish name).
- **AI Assistant** (Extensions menu): chat with an AI provider from
  inside IngeTrazo — provider picker with per-provider API key and
  model memory; every AI edit lands as ONE undoable command with full
  rollback on failure. Plus the **AI Bridge (MCP)**: model with Claude
  from outside the app over the Model Context Protocol.
- **Native glTF/GLB import** (PBR materials mapped to the paint
  system).
- **Starter components and textures**: CC0/CC-BY sedan, oak, bush and
  a scale figure standing at SketchUp's real offset; texture library
  additions (bark, rock, river pebbles, lawn, concrete pavers, water);
  glass paints translucent end-to-end (library → paint → face).
- Drawing axes recalibrated against SketchUp (fine-dot negative
  directions, denser dots); imported files show their name in the
  window title; the plugin path is documented for outside developers.

### Fixed
- **The paste "app not responding" hang**: `Scene.bounds()` walked the
  whole model in Python and ran twice per hover over empty space (work
  plane + status-bar coordinate) — the event loop starved for 10+
  seconds on big scenes. Now cached per scene version with a
  vectorized walk. This was most of the "zoom feels slow" report too.
- Billboards keep mipmaps with a hard alpha cut (no more dither dots
  at distance); Groq 403/404 in the AI Assistant.

### Performance
The pool-project marathon, in order of pain: box select vectorized ·
loose-edge silhouettes vectorized (the constant orbit/zoom lag) ·
erase cascade indexed (30 s curved-surface deletes → instant) ·
`heal_overlapping_faces` capped at hand-drawing scale · zoom focus
pinned to the camera pose and revalidated by projection after an orbit
(no ~25 ms re-pick per notch) · ray picks bucket only hit triangles ·
**Move, Rotate AND Paste preview through frozen scratch VBOs** (one
upload, every drag/hover frame is a translated MVP — SketchUp-grade
dragging of a 230k-face group) · Merge Groups fuses group-to-group
without the loose-mesh detour · one Newell per face on edit frames ·
group copies go through the bulk-weld pass · **pasting a huge classic
group stamps an O(1) sibling of the clipboard prototype** (SketchUp
semantics: copies share the definition until edited) — stamping the
230k-face group went from ~12 s to instant, rotating a pasted copy
from seconds to 0.1 s.

## [0.3.4] — 2026-08-25

**The dogfooding release: a real modelling session's bug hunt, plus
SketchUp-parity work.** Everything here came from drawing an actual
model and comparing, tool by tool, against SketchUp's official
documentation.

### Added
- **Display styles** (Camera → Style), SketchUp's Styles scoped to what
  serves printing: Default, Architectural (textures on white), Shaded
  (materials as their texture's average colour), Hidden line (the plan
  style), Monochrome, Wireframe and X-ray — plus Edges/Profiles toggles.
  Scenes remember their style; `.igz` persists it.
- **Composer frames pick any style** (LayOut-style viewports): each
  sheet frame can render in any of the styles above, the model's active
  style, or the exact vector hidden-line pass.
- **Copy/paste for groups and components** (Ctrl+C/X/V, context menu):
  instances paste as siblings of the same prototype; attrs (colours,
  textures, layers, BIM tags) travel; positioned textures re-anchor to
  the paste point. Paste previews the SOLID model — colours and
  textures riding under the cursor — and stamps once, returning to
  Select (SketchUp).
- **Protractor rebuilt to SketchUp parity** (official docs): plane
  inference by hover with axis-coloured disc, arrow-key plane locks,
  Shift freeze, fixed-size disc with 15° ticks, tick snapping near the
  disc / 0.1° free farther out, slope input as rise:run (`3:12`), and
  the guide stays retypeable after creation.
- **Rotate shows the same protractor**, with tick-snapped live preview,
  Ctrl = rotate a COPY (groups, instances and loose geometry), a
  click-drag from the centre to set a custom fold axis, and hot retype
  after the commit. The Measurements box accepts `3:12` here too.
- **Tool cursors**: the pointer becomes the active tool — a pencil
  (with the shape as a badge) for the drawing tools, hotspot at its
  tip; eraser/bucket/tape/protractor at their action points; orbit,
  pan and the magnifier during camera navigation.

### Fixed
- Box selection now takes groups and component instances (window =
  fully enclosed, crossing = touched), and guides (crossing only).
- Move/Rotate/Scale transform the WHOLE mixed selection — every group
  plus loose geometry — as one undo step (only the first group moved).
- Guides survive perspective (an endpoint behind the camera made the
  whole guide vanish from render, snap and eraser), and are now
  selectable/deletable with Select + Delete, right-click, or a
  crossing box. Guide points feed the snap engine.
- Esc releases the arrow-key axis lock / reference before cancelling
  the operation (it never did).
- Copying painted or textured loose geometry pasted bare; attrs now
  travel through the clipboard with textures re-anchored.
- Planar-projected textures (hand-painted, the scale figure) no longer
  swim through the paste preview as the cursor moves.
- About dialog: Arequipa, Perú.

### Changed
- openskp dependency back on upstream (`iamahsanmehmood/openskp`):
  every IngeTrazo patch is merged there, including the annotations
  writer (PR #203). CI pins upstream by SHA.

## [0.3.3] — 2026-08-21

**The complete SketchUp round trip.** IngeTrazo now writes native `.skp`
(File → Export → SketchUp) and opens Marco's entire 13-year real-project
corpus — 186 of 186 files, 2013–2026 — natively. Annotations travel BOTH
ways: dimensions and leader texts drawn in IngeTrazo appear in SketchUp,
and the ones in `.skp` files land in IngeTrazo as live, editable
annotations. The underlying reader fixes are merged into upstream
[OpenSKP](https://github.com/iamahsanmehmood/openskp) (PRs #194/#199);
the annotation writer is proposed as PR #203.

### Added
- **Native `.skp` export** (`formats/skp_out.py`, powered by
  `openskp.create`): faces with holes, groups, shared components (one
  definition + N placements), named materials with textures, layers —
  and now **dimensions and leader texts**.
- **`.skp` annotation import**: linear dimensions (all eras) and leader
  texts with their real label position and leader line; text records
  decoded byte-exact against SDK-generated ground truth ("Rosetta"
  files) and human-drawn corpus records.
- **Material registry** — materials have NAMES that survive editing:
  painting keeps identity, right-click a named swatch to edit-and-restamp
  every use, Model Info reports per-material quantities (m²), and OBJ/DAE/
  glTF/SKP exports carry the real names (`Concreto_visto`, not `mat0`).
- **Leader-text lifecycle**: select by clicking the text itself (glyphs
  outrank geometry), move with the anchor pinned (leader stretches, live
  preview), edit on double-click (SketchUp's gesture), delete with
  Supr/context menu, box-select — every step one undoable command.
- **Solid Inspector** (bundled plugin): explains WHY a solid is not
  watertight.

### Fixed
- Legacy (2013–2020) `.skp` reader: 16 decoded format variants merged
  upstream — burned MapObject indices with piecewise reference
  translation, v20 layer-list separators, self-calibrating guide-line
  tails, CImage entities, escaped/forward entity refs, Length/Point3d
  attributes, per-object layers on 2014-era files, and more. Every fix
  validated against fingerprint-identical corpus parses.
- Texture drape detection now only runs on legacy files (the projected
  flag is authoritative there); modern VFF files trust their own flags.
- Deleting a selected leader text with Supr raised a silent NameError
  (missing import since the Text tool's original commit); the context
  menu's Delete ignored leader texts entirely.
- `.skp` export kept same-recipe named materials separate (a repaint in a
  different name no longer merges them), and unpainted faces keep
  SketchUp's default material instead of turning white.
- Python Console: a failing script no longer drags an internal
  SyntaxError into the error report.

## [0.3.2] — 2026-08-18

**IngeTrazo has extensions.** The plugin system `docs/plugins.md` had been
promising is implemented: an **Extensions** menu discovers Python plugins at
startup from `<app>/plugins/` and the per-user directory
(`~/.local/share/ingetrazo/plugins/` on Linux, `%APPDATA%\ingetrazo\plugins\`
on Windows). Based on contributions by Ahsan Mehmood
([OpenSKP](https://github.com/iamahsanmehmood/openskp)) — thank you! —
consolidated and reworked in #4.

### Added
- **Extensions menu + plugin engine** (`core/extensions.py`): plugins load
  by file path (works in the packaged builds), a broken plugin shows as a
  disabled "⚠ (load error)" entry instead of preventing startup, only tools
  *defined* in a plugin register, and a plugin cannot steal a built-in
  shortcut.
- **Model Info** (bundled plugin): geometry counts, bounding box in the
  document's units, materials in use with painted area per material, layers,
  and BIM objects with quantities — the same numbers the BIM tray and the
  IFC export report.
- **Python Console** (bundled plugin, `Ctrl+Shift+P`): a live REPL over the
  open document. Every run is ONE undoable step through the command layer
  (Ctrl+Z, dirty flag, immediate repaint); a failing script rolls back
  whole; a demo script builds a BIM-tagged pavilion
  (`scripts/create_architectural_showcase.py`).
- **CI on pull requests**: the fast test suite runs on every PR (previously
  only on release tags).
- `docs/plugins.md` rewritten: the implemented contract, plus the
  `SnapshotImport` recipe for plugins that modify the model.

## [0.3.1] — 2026-08-12

Linux gets first-class installers: every release now ships an **AppImage**
(make executable and run; needs FUSE) and a **plain tarball**
(`IngeTrazo-<version>-linux-x86_64.tar.gz` — extract and run `./ingetrazo`,
no FUSE, unpacks anywhere), both built and smoke-tested by CI on
ubuntu-22.04 so they start on 22.04 and later. The Windows installer is
unchanged.

### Added
- `packaging/build-appimage.sh` (PyInstaller onedir → AppImage + tarball,
  adapted from IngeCAD's) and the `release-linux` workflow.
- `main.py --check`: self-diagnosis that reports whether the install can
  find its shaders, translations, textures, components and icons, plus
  whether the optional Wine/skp2dae converter is present. CI gates the
  bundle, the AppImage and the extracted tarball on it.
- `core/paths.py` (`app_root()`): the six runtime resource lookups that
  derived paths from `__file__` now go through it, so a frozen build fails
  loudly at `--check` instead of at first shader load if the bundle layout
  ever drifts.

### Changed
- Composer: big models no longer freeze the sheet tools.
- Repository references updated from `tuxiasumari/ingetrazo` to
  `ingelibre/ingetrazo` (About dialog, tile-fetcher user agents, and the
  skp2dae download URL, which only worked through GitHub's rename
  redirect).

## [0.3.0] — 2026-08-08

The sheet-composer release: model to printed plan without leaving IngeTrazo.

### Added
- **Sheet composer** (Archivo ▸ Compositor de láminas): QGIS-style page
  layout with model-view frames at EXACT scale (1:100 on a 200 mm frame is
  20 m of model), N sheets per document persisted in the `.igz`, its own
  undo history, and vector PDF export (single sheet or the whole atlas in
  one file).
  - Frames render shaded, technical (white + dark edges via exact
    hidden-line removal) or lines-only; automatic frame titles, graphic
    scale bar, north arrow, layer legend, images, text and an editable
    title block; DXF (R12) export of a frame's vector view for IngeCAD.
  - **Sheet dimensions anchored to the model**: snap both points to frame
    geometry (green dot) and the cota remembers the 3D points — edit the
    model, move or rescale the frame, and the dimension follows with its
    label re-measured (the exact 3D distance). LayOut-style placement:
    two clicks for the points, a third pulls the line away with extension
    lines; separation stays draggable afterwards.
  - Dimension styles: text height, decimals, oblique ticks / arrows /
    none, line width, colour.
  - Shapes: line, arrow, rectangle (with corner radius), ellipse and
    regular polygon (3–24 sides), each with line colour, fill and fill
    colour.
  - Title block: editable rows (add/remove/rename fields), 1–4 column
    groups, outer border and inner line widths, exact width/height; long
    values wrap to more lines and only then shrink.
  - QGIS habits: stacking order (bring to front / raise / lower / send to
    back) and per-item lock via right-click; items panel lists the stack
    top-first; zoom combo with fit-width / fit-page / presets where 100%
    is TRUE paper size.
- **Photogrammetric survey import (WebODM/ODM)**: the textured drone mesh
  loads as display-only reference geometry with its real UTM placement and
  altitudes, texture atlases capped to the GPU budget, saved inside the
  `.igz`, and a plan-grid `height_at` query that feeds the live profile.
- **UTM WGS84 in the georef UI**: the base-map panel and the project
  locator accept zone/hemisphere/E/N (what the drone or total station
  reports) or lat/lon — one frame at a time, chosen with a remembered
  selector. The locator's centre pin is explicitly the model's origin
  (0,0), and moving an existing origin asks first.
- New app icon (V11D): line-drawn cube with amber nodes on the IngeCAD
  family tile, now a single SVG source of truth.

### Fixed
- **Opening a `.skp` by double-click could freeze before the window
  appeared** (a progress callback ran on the worker thread and
  deadlocked); imports also no longer fall back to the external converter
  silently.
- **Single instance**: a second launch opens the file in the running
  window instead of dying to a zombie; an unresponsive instance no longer
  swallows launches.
- Drawing tools: the first unsnapped point stays in the plane you are
  looking at; bigger snap markers; frontal measurement in standard views.
- Georef: omitting altitude means "on the reference plane", not sea level.

## [0.2.4] — 2026-07-26

Self-contained `.igz` documents: textures travel INSIDE the file (ZIP
container, 5× smaller than the previous flat JSON), no absolute paths
left; `.skp` import stops creating folders next to the user's file. See
the GitHub release notes for the details.

## [0.2.3] — 2026-07-22

Native pure-Python `.skp` import for ALL SketchUp eras (our OpenSKP fork:
VFF walker + legacy MFC parser), validated for exact parity on real
models; skp2dae becomes an emergency fallback only. See the GitHub
release notes for the details.

## [0.2.2] — 2026-07-20

A polish release focused on the toolbar icons, plus two new zoom tools and
branded file-type icons.

### Added
- **Zoom** and **Zoom Window** camera tools on the View toolbar (and Camera
  menu). Zoom (`Z`) drags up/down to zoom in/out; Zoom Window drags a
  rectangle and frames that region. Icons: a magnifier, and a magnifier
  inside a rectangle.
- **Branded document icons** for the file types IngeTrazo works with —
  `.igz` (native), `.dae` (COLLADA) and `.skp` (SketchUp). On Linux a
  freedesktop MIME package paints the icons in the file manager (installed
  by `scripts/install_desktop.sh`); on Windows the installer associates the
  `.igz` icon and adds IngeTrazo to the "Open with" list for `.dae`/`.skp`.
  Double-clicking a `.dae`/`.skp` now imports it.
- **3D Text** now has a button on the Annotate toolbar (it was menu-only).

### Changed
- **Redesigned the tool icons** so each is the plainest picture of what it
  does, on its own visual identity: Paint is now Inkscape's tilted-bucket
  "fill" mark, Rotate is a pair of circular arrows, Orbit is an arrow
  circling a sphere, Pan is a cleaner open hand, and the Standard Views are
  little houses drawn from each viewpoint (front with a door, back with a
  window, mirrored sides, roof-from-above, an isometric house) — 3D Text is
  a solid extruded "A".

### Fixed
- Toolbar icons are re-drawn when the OS theme flips light ↔ dark while the
  app is open — they were baked at startup and previously stayed in the old
  theme's ink until a restart.

## [0.2.1] — 2026-07-16

Open SketchUp files directly: File ▸ Import ▸ SketchUp (.skp)…

### Added
- **Direct `.skp` import** through the external `skp2dae` converter — run as
  a separate process (the proprietary Trimble DLL never enters the GPL
  tree). The `.dae` and its texture folder land next to the `.skp`, then the
  existing COLLADA importer takes over (groups, components, textures,
  face-me sprites). On Linux the converter runs via Wine.
- **One-click converter install**: if `skp2dae` is missing, the import
  dialog offers to install it automatically — the converter executable is
  downloaded from the IngeTrazo release and the SketchUp runtime DLLs from
  the Blender "SketchUp Importer" add-on's public release, into
  `~/.local/share/skp2dae/`. No terminal required.

### Fixed
- `.skp` files stored under accented paths (`Imágenes`, `ñ`…) failed with a
  UTF-8 decode error — Wine re-encodes command-line arguments to the
  Windows ANSI codepage. The conversion now routes through an ASCII
  temporary path and tolerates any output encoding.

## [0.2.0] — 2026-07-15

The BIM release: the IFC bridge to IngePresupuestos is validated end to end,
SketchUp models migrate with textures and components, the terrain workflow
takes real field data — and the UI grew into its SketchUp skin.

### BIM → IFC (the thesis, closed)
- **Per-class base quantities** (`Qto_*BaseQuantities`): walls report net
  side area + height/length/width, slabs area + thickness + perimeter,
  columns/beams volume + length + cross-section, doors/windows real leaf
  dimensions (also as `OverallHeight/Width` attributes), piles/members/
  railings by the metre via `IfcQuantityLength`.
- **IFC4 export validated against a real consumer**: ifcopenshell parses it
  with zero schema/EXPRESS issues, tessellates every body, reads the
  quantity sets — permanent in the test suite.
- **The bridge works**: a tagged model imported by IngePresupuestos' IFC
  importer lands every takeoff EXACT (walls in m², columns in m³, piles by
  the metre, doors by the unit) — also a permanent cross-repo test.
- **Tag as you draw** (active class): arm a class in the BIM panel and every
  trace assumes it — one BIM object per trace, honest per-object takeoffs.
  Push/pull extends a tagged base to the solid it raises.
- The BIM panel now shows the **budget measure per object** (10.40 m²,
  0.31 m³, 1 und) instead of the misleading shell area.

### Bring your SketchUp models
- **COLLADA (.dae) import with real textures**: per-face UV maps from the
  file's TEXCOORDs, texture-tolerant coplanar fusion (no dirty
  triangulations), representative colours when the image folder is missing.
- **SketchUp's group structure survives**: one Group per assembly (a plaza
  imports as 291 groups, not one blob) — click selects the lamppost, not
  the world; edit by entering the small group.
- **Components import as shared instances**: one prototype mesh, N
  transforms (16 instances/6 prototypes saved 59k faces on a real nursery
  project; import went 24.7 → 10.8 s).
- **Face-me sprites recovered**: the cutout people/trees SketchUp exports
  without the flag turn toward the camera again, with SketchUp-style
  selection outlines and snap anchors (feet, head).
- **Big-model interaction**: vectorised pick index (2138 → 22 ms), per-group
  render/pick chunks, one-draw-call faces — a 394k-triangle plaza orbits
  at 60 fps and a 17k-triangle building imports in 0.8 s.

### Terrain, from field data
- **Survey-point CSV import** (P,N,E,Z,desc in UTM — GPS/total station):
  points become snappable reference markers; the pencil lands bit-exact on
  the surveyed coordinate. Anchors the scene datum at the first point.
- **Named XYZ sources, saved forever** (QGIS-style): add a tile source once
  with a name and it is always in the menu, each with its own tile cache;
  the last-used source restores on startup.
- The Georef tab is now **Terreno** — the trade's word.

### New tools
- **Text (X)**: leader-text annotations — the prompt prefills with the
  clicked edge's length, face's area, or point coordinates (SketchUp-style);
  occluded leaders, selectable, saved in `.igz`.
- **3D Text**: real extruded geometry from any system font — one watertight
  solid per letter (counters preserved), smooth thickness, glued to the
  face under the cursor (a relief sign on a wall, text lying on a slab).
- **Hi-res image export** (File ▸ Export ▸ Image): the current view at any
  pixel width through the exact render pipeline, presentation overlays
  included — 4K sheets straight from the program.
- **Component placement with the cursor**: inserts follow the mouse and
  settle on the ground plane (or any face you point at); Esc discards.

### UI, SketchUp-shaped
- Menu bar reorganized to mirror SketchUp: **Archivo · Edición · Cámara ·
  Dibujo · Herramientas · Ventana · Ayuda** (Draw groups Arcs/Shapes,
  Camera owns views/projection/orbit, Window owns panels + language).
- **Components tray panel** with static image thumbnails (no 3D rendering
  to show them), replacing the File-menu submenu.
- File menu unified into **Import** and **Export** submenus (survey CSV
  included); duplicate dock titles above the tray tabs removed.

### Fixes
- Graze intersections snap to the vertex they graze (tangent circles).
- Lines drawn on a populated plane run the scoped rebuild (no stacked
  inverted faces).
- A slit edge deletes the line and keeps the face.
- Face attrs (textures, colours, layers, IFC tags) travel through Make
  Group / Explode.
- MSAA moved into the scene FBO — first real antialiasing.
- Orbiting with dimensions visible: occlusion test cached + vectorised
  (280 → 6 ms/frame).

## [0.1.0] — 2026-07-11

The first release. A usable, free, Linux-first SketchUp-style 3D modeler for
civil engineering and architecture — draw → model → tag → take off → export.

### Modeling engine
- Shared-vertex non-manifold topology engine (SketchUp's model): sticky
  geometry, automatic welding, face detection, planar-arrangement rebuilds.
- Push/Pull with the full solid pipeline: recess, steps, through-holes,
  clamps, distance inference, Ctrl = copy, double-click repeats — and the
  **BIM-grade watertightness guard**: the engine never commits a broken
  solid (ambiguous operations are refused safely, and told to the user).
- Robust curve entities: circles, polygons, 4 arc types; curves select as
  whole contours, split at intersections, survive copy/paste/offset/groups.
- Deterministic intersections: circle×line, circle×circle, rect×rect split
  into proper regions — on flat drawings, next to solids, and on solid faces.
- Transactional command history: any internal failure rolls back to the
  exact previous state, tells the user, and logs to `ingetrazo-errors.log`.
- Fuzz-tested: 1000 seeded operation sequences with structural invariants
  (watertightness, orientation, undo fidelity) — 996 clean, 4 known-hard
  frozen as expected failures.

### Tools
- Draw: Line, Rectangle, Rotated Rectangle, Circle, Polygon, Arc (2-point,
  3-point, centre+angle), Offset, Follow Me (profile swept along a path,
  mitred corners, closed paths weld into lathes).
- Transform: Move, Rotate (protractor), Scale (anchor + factor, negative
  mirrors) — live previews, exact snapshots undo, autofold.
- Select: click (curves/surfaces as wholes), double-click (face + edges),
  triple-click (whole connected solid), window/crossing box, Select All.
- Annotate: Tape Measure with construction guides, Protractor (angled
  guides), Dimensions with styles, terrain profile for geo paths.
- Eraser (click + stroke), Paint with materials, escalating Esc.

### Materials, layers, groups
- Categorised texture library (22 procedural, seamlessly tileable,
  licence-clean textures across 9 civil categories) painted at real-world
  tile size; edit width/height/rotation of any texture, undoably.
- Layers/tags with visibility and locking — top view + parallel projection
  + layers = the plan drawing, no separate 2D module.
- Groups: isolated geometry, edit-inside context (double-click in),
  cross-context undo correctness, face-me billboards.

### BIM (the thesis)
- Tag any faces or group as an IFC object (15 curated classes) — metadata
  over freeform geometry, never rigid primitives.
- Live quantities per object: area always, volume only when watertight.
- Takeoff CSV export — the bridge to IngePresupuestos today.
- **IFC4 export**, hand-written STEP (zero dependencies): spatial skeleton,
  real IFC classes, faceted BRep geometry, BaseQuantities in the file.

### Georeferencing (Track G)
- Local datum + UTM conversion; satellite base maps (Esri/Sentinel-2/custom
  XYZ) with area-limited capture; 3D draped terrain from free global DEM;
  geo paths with longitudinal profiles (stations, slopes, CSV/PNG export);
  KML/GeoJSON import.

### Interchange
- Native `.igz` documents (JSON, versioned).
- Import: COLLADA `.dae` (SketchUp exports, components, Y-up/inches
  conversion), OBJ (+MTL colours), KML/GeoJSON.
- Export: IFC4, STL (3D printing), OBJ (+MTL, textures with UVs).

### Experience
- Bilingual UI (English source, full Spanish), SketchUp-style movable
  icon toolbars, QGIS-style panels (Properties | BIM | Georef tabs),
  sky/ground horizon, paper-white maquette shading with face culling,
  infinite dashed axes.
- Scale figure: the author himself (1.65 m) as a face-me billboard cutout,
  plus generic 2D/3D people, tree, bush, car components — and "insert your
  own transparent PNG at real height".
- Desktop launcher + icon installer (`scripts/install_desktop.sh`);
  the icon is the author's mark: his tri-blade wrapped around the cube.

[0.1.0]: https://github.com/tuxiasumari/ingetrazo/releases/tag/v0.1.0
