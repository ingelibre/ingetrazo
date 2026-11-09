# IngeTrazo roadmap

*Last updated: 12 October 2026, after 0.5.8. This is a direction, not a promise: priorities change with what users report, and a release waits when it needs more testing. It is reviewed after every release. Questions and proposals are welcome in [discussion #553](https://github.com/ingelibre/ingetrazo/discussions/553).*

*Thanks to Félix for proposing this roadmap ([#364](https://github.com/ingelibre/ingetrazo/issues/364)).*

**In one line:** IngeTrazo wants to be the free, offline 3D modeller where you **draw like by hand, tag what you drew, and get quantities out** — model → BIM tags → IFC → quantity take-off → budget.

## How to help

- **Pick an issue:** issues labelled `good first issue` are small and well described; `help wanted` ones are bigger. Leave a comment before you start, so two people don't do the same work.
- **Pull requests** go to this repository. Every PR needs the test suite green, and changes to the geometry engine or to the `.igz` file format are reviewed by Marco before merging.
- **Niche tools become extensions, not core features.** If something would be used by few people, it belongs in the [extension catalog](https://ingetrazo.com/extensiones) — and it can still be listed and installed from inside the app with the Extension Manager.
- **Good extension projects people have asked for:** CNC toolpaths ([#107](https://github.com/ingelibre/ingetrazo/issues/107)), cut lists for furniture ([#309](https://github.com/ingelibre/ingetrazo/issues/309)), acoustics export ([#102](https://github.com/ingelibre/ingetrazo/issues/102)), daylight and bioclimatic analysis ([#117](https://github.com/ingelibre/ingetrazo/issues/117)), stairs ([#506](https://github.com/ingelibre/ingetrazo/issues/506)), national coordinate systems ([#192](https://github.com/ingelibre/ingetrazo/issues/192)), VR ([#514](https://github.com/ingelibre/ingetrazo/issues/514)). Extensions can soon ship their own translations ([#507](https://github.com/ingelibre/ingetrazo/issues/507)), and a crashing extension will be skipped on the next start ([#306](https://github.com/ingelibre/ingetrazo/issues/306)).
- **Bugs:** a short `.igz` file that reproduces the problem is worth more than a long description.
- **Support the project:** [ingetrazo.com/apoyar](https://ingetrazo.com/apoyar).

---

## Now — 0.5.8 (released on 12 October)

Out now: [release notes and downloads](https://github.com/ingelibre/ingetrazo/releases/tag/v0.5.8). The main changes:

- **Extension Manager** inside the app: browse the catalog, install, update, disable and uninstall.
- **Units** for the whole document (metric and imperial), chosen at startup and in a units panel.
- **Model Browser** (outliner): nest groups by dragging, lock and isolate them, manage section planes ([#490](https://github.com/ingelibre/ingetrazo/issues/490), [#549](https://github.com/ingelibre/ingetrazo/issues/549)). *Views and sheets* in the sheet composer; Solid Inspector that repairs problems one by one.
- **Performance:** drawing inside big groups, push/pull and terrain work several times faster.
- **Push/Pull** shows the real result while you drag, also when pushing inwards.
- Many inference and tool fixes, French, German, Chinese, Polish, Indonesian and more translations.
- **Large models** are saved in a new format that opens 3× faster and is a third of the size; older versions can't open it, so share big models with people who have updated.

## Next — frequent releases, and the performance work

**Frequent, small releases** with fixes that are already tested (0.5.9, 0.5.10, …). The issues below are what they will work through; the next one is tracked in the [0.5.9 milestone](https://github.com/ingelibre/ingetrazo/milestone/1). Every open issue is labelled by area (`area: tools`, `area: inference`, `area: files`…), so you can filter the ones you care about.

**Performance, in its own branch.** Looking at a model is already fast — orbiting a 1 000-group town square model takes about 8 ms per frame. What is still slow is **editing**, and **very large models**:

| What you do | Today (0.5.8) | Target |
|---|---|---|
| Draw or edit inside a large group | ~0.7 s per edit | under 0.15 s |
| A normal push/pull | 0.6–1.3 s | under 0.3 s |
| Push/pull on terrain | 16–24 s | 1–3 s |
| Push/pull of one very large face (hundreds of m²) | minutes | seconds |
| Open a model with millions of faces | tens of seconds and several GB of memory | a fraction of that |

Why, and what will change:

- **Every edit still looks at too much.** After a change, parts of the engine re-check geometry far from what you touched. The fix is a **persistent spatial index**, so an edit only looks at its neighbourhood.
- **Redrawing after an edit rebuilds too much.** The fix is **truly incremental drawing**: only the faces that changed are sent to the graphics card again.
- **Deciding which side of a face is "outside"** is done for the whole solid. The fix is **local orientation**: only around the edit.
- **Each face is a Python object** (about 3 KB). Fine for buildings, too heavy for imported plants with millions of faces. The fix is **light components**: geometry kept as compact arrays until you enter a component to edit it.

It lands when it is measured against the previous version on real models — not before, because the geometry engine is where a rushed change hurts the most.

**How to help with performance:** share a real model that is slow for you in [ingetrazo-benchmark-models](https://github.com/ingelibre/ingetrazo-benchmark-models) (a link and a checksum, not the file), and say what is slow in it. Performance PRs are welcome when they come with numbers before and after on those models.

**Geometry engine (coplanar faces):** faces on the same plane that should merge sometimes end up stacked or rebuilt wrongly — [#356](https://github.com/ingelibre/ingetrazo/issues/356), [#519](https://github.com/ingelibre/ingetrazo/issues/519), [#537](https://github.com/ingelibre/ingetrazo/issues/537), [#538](https://github.com/ingelibre/ingetrazo/issues/538).

**Drawing and inference fixes:**
[#539](https://github.com/ingelibre/ingetrazo/issues/539) (snaps to geometry removed by Undo/New) · [#540](https://github.com/ingelibre/ingetrazo/issues/540) (arrow lock after a typed length) · [#543](https://github.com/ingelibre/ingetrazo/issues/543) and [#545](https://github.com/ingelibre/ingetrazo/issues/545) (rectangle plane) · [#544](https://github.com/ingelibre/ingetrazo/issues/544) (a rule beats *On edge*) · [#546](https://github.com/ingelibre/ingetrazo/issues/546) (*On axis* inference) · [#389](https://github.com/ingelibre/ingetrazo/issues/389) (long thin rectangles) · [#407](https://github.com/ingelibre/ingetrazo/issues/407) (push/pull and the origin) · [#384](https://github.com/ingelibre/ingetrazo/issues/384) (section marker snaps)

**Tools:** [#541](https://github.com/ingelibre/ingetrazo/issues/541) (Intersect Faces with everything selected) · [#542](https://github.com/ingelibre/ingetrazo/issues/542) (`x5` multiplier) · [#305](https://github.com/ingelibre/ingetrazo/issues/305) (`Ns` rebuilds the last circle) · [#254](https://github.com/ingelibre/ingetrazo/issues/254) (dimension consistency) · [#408](https://github.com/ingelibre/ingetrazo/issues/408) (paint bucket / materials tab) · [#426](https://github.com/ingelibre/ingetrazo/issues/426) / [#429](https://github.com/ingelibre/ingetrazo/issues/429) (imported images on faces) · [#420](https://github.com/ingelibre/ingetrazo/issues/420) (very small pieces) · merge coplanar faces ([#488](https://github.com/ingelibre/ingetrazo/issues/488)) · move a single vertex ([#311](https://github.com/ingelibre/ingetrazo/issues/311), [#531](https://github.com/ingelibre/ingetrazo/issues/531)) · join line segments ([#372](https://github.com/ingelibre/ingetrazo/issues/372)) · smooth shading across soft edges ([#131](https://github.com/ingelibre/ingetrazo/issues/131), [#347](https://github.com/ingelibre/ingetrazo/issues/347)) · totals for a multiple selection in Entity Info ([#274](https://github.com/ingelibre/ingetrazo/issues/274), PR [#524](https://github.com/ingelibre/ingetrazo/issues/524)) · texture position and size on faces ([#318](https://github.com/ingelibre/ingetrazo/issues/318), [#460](https://github.com/ingelibre/ingetrazo/issues/460), [#447](https://github.com/ingelibre/ingetrazo/issues/447))

**Navigation:** choose which mouse button orbits and which pans ([#231](https://github.com/ingelibre/ingetrazo/issues/231), [#373](https://github.com/ingelibre/ingetrazo/issues/373), [#422](https://github.com/ingelibre/ingetrazo/issues/422); PRs [#467](https://github.com/ingelibre/ingetrazo/issues/467), [#525](https://github.com/ingelibre/ingetrazo/issues/525)), field of view ([#526](https://github.com/ingelibre/ingetrazo/issues/526)), orbit around the selection ([#381](https://github.com/ingelibre/ingetrazo/issues/381)), previous / next view ([#282](https://github.com/ingelibre/ingetrazo/issues/282)), trackpad pinch-to-zoom on macOS ([#248](https://github.com/ingelibre/ingetrazo/issues/248), [#453](https://github.com/ingelibre/ingetrazo/issues/453)).

**File exchange:** STL exported at the wrong scale ([#513](https://github.com/ingelibre/ingetrazo/issues/513)), DWG import that freezes ([#401](https://github.com/ingelibre/ingetrazo/issues/401), [#491](https://github.com/ingelibre/ingetrazo/issues/491)), DXF export ([#428](https://github.com/ingelibre/ingetrazo/issues/428)), sheets and elevations to DWG/DXF ([#88](https://github.com/ingelibre/ingetrazo/issues/88), [#118](https://github.com/ingelibre/ingetrazo/issues/118)).

**Sheets:** [#260](https://github.com/ingelibre/ingetrazo/issues/260) (lines and ground line) · units of sheet dimensions ([#403](https://github.com/ingelibre/ingetrazo/issues/403), PR [#405](https://github.com/ingelibre/ingetrazo/issues/405)) · section line weights ([#195](https://github.com/ingelibre/ingetrazo/issues/195)) · sections with a limited depth, in the viewport and on sheets ([#451](https://github.com/ingelibre/ingetrazo/issues/451)) · composer navigation like the model view ([#83](https://github.com/ingelibre/ingetrazo/issues/83)).

**Layers:** colour by layer ([#120](https://github.com/ingelibre/ingetrazo/issues/120), PR [#442](https://github.com/ingelibre/ingetrazo/issues/442)), multi-select and sorting in the Layers panel ([#281](https://github.com/ingelibre/ingetrazo/issues/281)), an optional active layer ([#302](https://github.com/ingelibre/ingetrazo/issues/302)) — reviewed together with the interface contest.

**AI assistant:** provider fixes ([#517](https://github.com/ingelibre/ingetrazo/issues/517)), more settings ([#339](https://github.com/ingelibre/ingetrazo/issues/339)) and a way to turn it off completely for people who don't use it ([#456](https://github.com/ingelibre/ingetrazo/issues/456)).

## After that — BIM by discipline (the next big block)

The core stays a free-form modeller for everyone; BIM is an **optional layer of tags** on top of what you draw, and it feeds IFC and quantity take-off. The order matters:

1. **One common BIM API for extensions** — how a wall, a slab or a window is tagged, which properties it carries and how its quantities are computed. Any extension that tags this way gets correct IFC and take-off for free, so tools from different authors fit together instead of each inventing its own. The resource-library work in PR [#412](https://github.com/ingelibre/ingetrazo/issues/412) is a starting point.
2. **A small project from end to end** — a real little house (walls, a slab, a door, a window) going all the way from IngeTrazo to IFC to a correct budget in IngePresupuestos. It proves the idea and shows what the API is missing.
3. **Structures** ([#204](https://github.com/ingelibre/ingetrazo/issues/204)): grids, columns, beams, slabs, concrete and steel quantities, and reinforcement as IfcReinforcingBar ([#495](https://github.com/ingelibre/ingetrazo/issues/495)).
4. **Architecture** (walls, openings, slabs, roofs, stairs) and **doors and windows** as discipline tools built on that API — community extensions are very welcome here, and some are already exploring it (PR [#430](https://github.com/ingelibre/ingetrazo/issues/430), to be published in the catalog). MEP systems ([#307](https://github.com/ingelibre/ingetrazo/issues/307)) and levels / floor plans ([#310](https://github.com/ingelibre/ingetrazo/issues/310)) fit best as extensions on the same API.
5. **Common building blocks** extensions keep asking for: section hatches by material or layer, plan views tied to levels, an API for curves and soft edges.

## Rendering

IngeTrazo does not build its own photorealistic engine: **Blender is the engine**, and IngeTrazo prepares the scene for it. What already works: the **Render tab** renders the current view with your own Blender (Cycles for quality, EEVEE for speed), by day with the sun of the Shadows panel, overcast, or at night with point lights and spots placed on the model; finishes per material (glass, water, metal, gloss…); and a live draft that follows the camera. In the viewport, real **sun shadows** for any place, date and hour.

Next, in this order:

- **Render materials** ([#194](https://github.com/ingelibre/ingetrazo/issues/194)): reflection, metalness, transparency, relief and own light (emission) per material, starting from today's finishes.
- **Render lights as model objects** ([#205](https://github.com/ingelibre/ingetrazo/issues/205)): selecting and deleting them already works; moving them with Move (M) is next.
- **Where images go** ([#244](https://github.com/ingelibre/ingetrazo/issues/244)): choose the output folder before rendering and open it from the app.
- **Image export with a transparent background**, keeping the shadows ([#100](https://github.com/ingelibre/ingetrazo/issues/100)) — for presentation boards.

Good candidates for **extensions** ([#225](https://github.com/ingelibre/ingetrazo/issues/225), [#331](https://github.com/ingelibre/ingetrazo/issues/331)): batch renders from the scenes, walkthrough videos, 360° panoramas, other render engines.

## Interface

The **interface contest** ([#299](https://github.com/ingelibre/ingetrazo/issues/299)) takes proposals until **15 November**; voting runs **16–30 November**, and the winning ideas are implemented after that. Until then the known interface is kept stable — changes to menus, toolbars and panels go through discussion first.

## Platforms

- **Windows:** code signing in progress, so the installer and the installed program stop being flagged by antivirus software ([#162](https://github.com/ingelibre/ingetrazo/issues/162)).
- **macOS:** builds for Apple Silicon and Intel; signing needs an Apple developer account, until then a guide for the first launch (Gatekeeper) on the website ([#317](https://github.com/ingelibre/ingetrazo/issues/317)).
- **Linux:** Flatpak (updates itself), AppImage, tarball and Snap.
- **Updates:** a notice inside the app when a new version is out, for Windows, macOS and AppImage ([#250](https://github.com/ingelibre/ingetrazo/issues/250)).
- **Known problems we are working on:** Flatpak not starting on some systems because of fonts ([#279](https://github.com/ingelibre/ingetrazo/issues/279), [#499](https://github.com/ingelibre/ingetrazo/issues/499)) · a broken display on some NVIDIA laptop GPUs ([#406](https://github.com/ingelibre/ingetrazo/issues/406)) · tooltips on HiDPI screens ([#444](https://github.com/ingelibre/ingetrazo/issues/444)) · Linux ARM64 builds ([#127](https://github.com/ingelibre/ingetrazo/issues/127)).

## Ideas without a date

Point clouds ([#421](https://github.com/ingelibre/ingetrazo/issues/421)) · SubD tools — a community extension is on its way ([#388](https://github.com/ingelibre/ingetrazo/issues/388)) · steel profiles and steel framing ([#397](https://github.com/ingelibre/ingetrazo/issues/397)) · contour lines · easier blue-axis inference in every camera position · composer: grid bubbles, numbered tags with a legend table, room labels, vertical title block · booleans · STEP export, as an extension ([#532](https://github.com/ingelibre/ingetrazo/issues/532)) · IFC import ([#129](https://github.com/ingelibre/ingetrazo/issues/129)) · a headless command-line mode to convert and export ([#303](https://github.com/ingelibre/ingetrazo/issues/303)) · Windows Explorer thumbnails for .igz ([#522](https://github.com/ingelibre/ingetrazo/issues/522)) · a start window with recent files · a 3D/AR viewer from GLB ([#396](https://github.com/ingelibre/ingetrazo/issues/396)).

## Not planned for now

- **Mobile / iPad app:** IngeTrazo needs desktop OpenGL and mouse-and-keyboard. A community web version ([#390](https://github.com/ingelibre/ingetrazo/issues/390)) is being explored independently.
- **Rewriting the core in another language:** the speed work above comes first, measured on real models.
- **Running plugins written for other modellers:** not planned. The most-requested tools from those plugin lists (bounding box, bend, unfold, components from groups) become built-in tools or extensions instead.
