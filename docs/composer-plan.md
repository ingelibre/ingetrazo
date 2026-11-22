# Sheet composer — plan C1→C4

*English · [Español](composer-plan.es.md)*

> Print the 3D model as a drawing, at exact scale. The UX reference is the
> **QGIS print composer** (Marco's choice), not a separate sheet program
> with its own format (the scope trap); QGIS is a
> window of the same program whose canvas is a `QGraphicsScene` — exactly
> the framework we already have underneath. Defined on 2026-08-08.

## The idea in one paragraph

A **Composition** is one or more paper pages (A4…A0) with **items**
on top. The central item is the **ModelView**: a frame that references a
saved **Scene** (camera + hidden layers — these already exist, Scenes panel) plus
a **1:N scale**, and it is filled by rendering the model with an orthographic camera
through the viewer's real pipeline (`render_image`, which already exists). The other
items (text, title block, image) are pure 2D. Everything is exported to PDF with exact
physical metrics (`QPdfWriter`) or to the printer. Compositions live
INSIDE the `.igz`, the way QGIS stores its layouts in the project.

## The QGIS → IngeTrazo mapping

| QGIS | IngeTrazo | where it comes from |
|---|---|---|
| Layout | `Composicion` (core/composition.py) | new |
| `QgsLayoutItemMap` | `MarcoVista` — scene + projection + 1:N scale | new |
| Map theme | `SavedView` (core/saved_views.py) | ✅ exists |
| Frame render | `viewport.render_image(w, h, overlays=False)` | ✅ exists (an explicit height gets added) |
| Page/export | `QPdfWriter` + `QPrinter` | Qt |
| Editor canvas | `QGraphicsScene` in **millimetres** | Qt |
| Layout manager | dock with a list of compositions | C2 |

## The sacred maths (the only part that is non-negotiable)

Model units: **metres**. Composer canvas units: **millimetres
of paper**. For a frame of height `H_mm` at scale `1:N`:

    model_height_m  = H_mm × N / 1000
    cam.perspective = False
    cam.distance    = (model_height_m / 2) / tan(rad(cam.fov_deg) / 2)
    # because OrbitCamera's parallel projection derives its half-height from
    # distance·tan(fov/2)  (core/camera.py:56)
    px = mm / 25.4 × DPI      # frame raster, DPI = 300

and the camera aspect is set to `W_px/H_px` during the render (and restored
afterwards — the composer render **never** leaves a trace in the viewer
state: camera, aspect and layer visibility are captured and restored in a
`try/finally`).

**Scale DoD, machine-verifiable:** a 1 m cube at 1:100 must measure
**10.00 mm** on paper. The test rasterises the exported PDF at 300 dpi and
counts the inked pixels of the edge: 10 mm × 300/25.4 = **118 px ± 1**. (The
house has already learned that you measure the final result, not the intermediate step.)

## Decision: raster first, HLR later

The frame is filled **as a raster at 300 dpi** through the viewer pipeline (a whole A3
is ~3500×4900 px — sharp when printed; QGIS rasterises the same way when it
has to). **Vector** hidden-line removal (the pure line-drawing
look) is the only hard problem in the project and it is C4: edge projection
+ occlusion test against the mesh. It blocks nothing: the complete
municipal workflow works with raster.

## Phases

### C1 — The core *(this session)*
**Sheet composer** window (File menu), `QGraphicsScene` canvas in mm with one
page (A4/A3/A2/A1, portrait/landscape, shadow and margin), **one** movable
`MarcoVista` bound to: the current view, a saved scene or a standard view
(plan/front/…); scale from a list (1:50/100/200/500/1000 + custom); frame size
via spinboxes; *Export PDF* button. No persistence or undo yet.
- **DoD:** the cube test above passes (118 px ± 1 in the PDF); the window
  opens from the menu and the frame shows the real model; the viewer state
  is left untouched after every render (same camera/layer fingerprint).

### C2 — Items and persistence
Multiple `MarcoVista` per page (plan + elevations + iso on one sheet),
**text**, **image** and **title block** items (label: project/author/date/
scale/sheet — for the trade it is THE item), resize handles, guides with
snapping, composition manager (N per document), **persistence in
the .igz** and undo via Command (house invariant: every mutation goes through a
Command).
- **DoD:** closing and reopening the .igz keeps the complete sheet; an
  A1 sheet with 4 views + title block can be put together without touching code.

### C3 — The drawing style
A "technical" render mode for the frame: white background, edges only (+ an option for
white faces), honouring section planes if there are any. Graphic scale bar as an
item. Automatic frame title ("Plan — 1:100").
- **DoD:** a printable sheet that a colleague cannot tell apart from a CAD drawing at
  first glance.

### C4 — The luxury ✅ (2026-08-08)
EXACT vector HLR (core/hlr.py: per edge, the shadow of each triangle is
the intersection of 4 linear inequalities in t — no sampling at all; the
self-occlusion against its own faces is resolved by the epsilon because e(t)≈0 along
the whole edge), a "vector" frame style (real lines in the PDF: 0
embedded images), **DXF R12 export of the views in model units
(formats/dxf_out.py) → a direct bridge to IngeCAD** — verified by opening the DXF
with IngeCAD's ezdxf: extent 9.144 m, the same number the PDF ink
measured in the C1 DoD —, sheet renumbering and atlas (all sheets
in one multi-page PDF, each with its own paper size). The top/bottom views go to TRUE
90° with up=+Y (the interactive preset stops at 89° because of the lookAt
singularity; that 1° was drawing double lines 0.5 mm apart on a 3 m plan).

## Known gotchas that apply here

- `QWidget.grab()` does not capture QPainter overlays; the composer uses
  `render_image`, which does paint them — but **with an explicit height the overlays are
  skipped** (`overlays=False`): they are calibrated to the widget's aspect and
  would come out shifted. Dimensions on the sheet are a C3 matter.
- The interactive "plan" view uses the `top` preset (pitch 89°); the
  composer brings it to exactly 90° with up=+Y (see C4) — at 89° the floor
  peeks out below the front and double lines appear on paper.
- Wayland: the frame render goes through the viewer's own FBO with its
  depth workaround — do not add another GL path.
