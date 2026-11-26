# Working with IngeTrazo – Instructions for AI Assistants

Copy this file into the instructions of your AI tool (system prompt, project
instructions, `CLAUDE.md`, a skill …). It describes a best-practice workflow
for building and documenting a building model in IngeTrazo, for example
through the AI bridge (MCP, see [`docs/ai-bridge.md`](../../docs/ai-bridge.md)).
The demo model in this folder (`workflow-demo.igz`, built by
`create-demo/workflow-demo.py`) follows every rule below;
[`README.md`](README.md) shows it step by step with screenshots.

## 1. Core idea
The model geometry is the single source of truth. Everything else – layers,
saved views, sheets, sheet sets, BIM data and exports – refers to it. Never
copy coordinates or quantities into documents; query the model instead.

```
Model tree ──► Layers ──► Saved views ──► Sheets ──► Sheet sets ──► PDF per trade
     └────────► BIM information (IFC class, quantities) ─────────► lists / IFC
```

## 2. Model tree (Outliner)
- Structure every model as **Storey → Trade → Status → Element**
  - Storey: `GF`, `FF`, `Roof` …
  - Trade: `Walls`, `Tiles`, `Kitchen`, `Windows_Doors` …
  - Status: `<Trade>_Existing`, `<Trade>_Demolition`, `<Trade>_New`
- **Containers** (storey, trade, status) carry the layers. **Elements carry
  no layer** – they inherit it. Also clear face-level layers on imported
  geometry (`face.attrs["layer"]`).
- Do not create empty status containers.
- Each element has exactly one status. An unchanged element exists once
  (Existing). A changed element is split: the removed part goes to
  Demolition, the added part to New, the rest stays Existing.
- Group names are not unique. Find elements by walking the tree and checking
  bounding boxes, not by name alone.

## 3. Layers
- Three kinds, filed in layer folders: storey layers (`GF`), trade layers
  (`Walls`, `Tiles`, `Kitchen`) and status layers (`S_Existing` grey,
  `S_Demolition` yellow, `S_New` red).
- Optional `Archive` layer: hidden in every view, for geometry kept only for
  reference (move it there instead of deleting it).
- A hidden container layer hides everything below it, so storey, trade and
  status filter independently.
- *Colour by layer* uses the nearest assigned layer (face → group → parent).
  Therefore the status must be the lowest assigned layer.

## 4. BIM information
- Tag every element with an IFC class as soon as it is created:
  `g.ifc = {"class": "IfcWall", "name": "Wall_A"}` – always a dict, never a
  plain string.
- Model rooms as `IfcSpace` with number and name.
- Keep quantities (area, length, volume, count) derivable from geometry and
  use them for room lists, bills of quantities and the IFC export.

## 5. Saved views (scenes)
- A saved view stores camera, hidden layers, display style and the active
  section plane.
- Standard status set: `_old` (hide `S_New`), `_new` (hide `S_Demolition`),
  `_delta` (everything visible, style with *colour by layer*). Always hide
  `Archive`.
- Trade views show only what one trade needs (e.g. `V_Tiles`: hide
  `Kitchen`; `V_Kitchen`: hide `Tiles` and `S_Demolition`).
- For floor plans activate a horizontal section plane; the plane removes the
  side its normal points to.
- File views in scene folders (`Status`, `Trades`, `Sections` …).

## 6. Sheets
- A sheet holds frames. Each frame points to one saved view
  (`view_key = "scene:<name>"`) and has a standard scale (1:20, 1:50, 1:100,
  1:200).
- Dimensions anchored to model points follow model changes.
- Use the title block (project, author, scale, sheet number) and its
  placeholders instead of loose text.
- Before rendering or exporting a sheet, apply its view in the model once so
  that frames follow the view's layer visibility.

## 7. Sheet sets (optional, planned feature)
- Sheets can always be exported directly. Optionally, a sheet set is an
  ordered selection of sheets for one recipient – one trade
  or tender (e.g. *Tiler*, *Kitchen fitter*, *Structural engineer*) – with its
  own cover and contents page, exported as one PDF.
- Until the feature exists, use **one sheet folder per trade**
  (`Set_Tiler`, `Set_Kitchen_fitter`) and export the sheets of that folder.

## 8. Safe working
- Before risky edits record the original geometry (bounding boxes); undo over
  the API is not always reliable – check with a short query instead of
  retrying blindly.
- Instanced components share one mesh – make an instance unique before
  editing it alone.
- Do not edit Demolition or Archive elements unless explicitly asked.
- The user saves the document; do not assume changes are saved.
- Prefer a few large, checked operations over many small blind ones. Verify
  with one screenshot or a rendered sheet.

## 9. Minimal example (this folder)

One room corner: the old splashback on Wall_A is removed, a sink cabinet
with new tiles goes on Wall_B.

| Element | Model tree | Layers (inherited) | BIM |
|---|---|---|---|
| Floor, Wall_A, Wall_B | GF › Walls › Walls_Existing | GF / Walls / S_Existing | IfcSlab, IfcWall |
| Splashback_old | GF › Tiles › Tiles_Demolition | GF / Tiles / S_Demolition | IfcCovering, 1.2 m² |
| Tiles_new | GF › Tiles › Tiles_New | GF / Tiles / S_New | IfcCovering, 2.4 m² |
| Sink_base_cabinet | GF › Kitchen › Kitchen_New | GF / Kitchen / S_New | IfcFurniture, 1 pc |

- Finishes such as tiles are single faces, so the takeoff is exactly their
  area.
- Views: `V_Tiles` (delta), `V_Kitchen` (new) in folder *Trades*;
  `Corner_old`, `Corner_new`, `Corner_delta` in folder *Status*. All in
  parallel projection so that sheets print to scale.
- Sheets: `Sheet_Tiles` (V_Tiles, 1:25), `Sheet_Kitchen` (V_Kitchen, 1:25).
- Sheet sets (folders): `Set_Tiler` = Sheet_Tiles,
  `Set_Kitchen_fitter` = Sheet_Kitchen → one PDF each.
