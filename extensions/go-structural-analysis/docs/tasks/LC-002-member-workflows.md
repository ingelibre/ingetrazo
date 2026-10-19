# LC-002 — Mixed combinations, member load extent and member graph review

User-requested bundle continuing LC-001, 11 October 2026. Uses the existing
combination matrix workflow reviewed on Prota pages 30–31. No new guide chapter
or engineering design module is claimed.

## Implemented

- Select **ASD + LRFD** to see all 18 original Thai presets together. Changing the
  preset selector retains enabled presets from the previous method.
- Generator replaces selections for its selected method and retains the other
  method and Custom entries. Shared action bindings remain visible and reviewed;
  changing them affects both methods and requires a fresh analysis.
- `combination_manager.methods` declares participating statutory methods.
  Legacy configs without it retain the single-method validation behavior.
  Combination metadata/envelopes remain ASD, LRFD and Custom separately.
- Distributed-load row shows length computed from edited analytical coordinates.
  **Full member** explicitly fills x1=0, x2=L. Geometry edits update the length
  display but never silently overwrite an existing partial-load interval.
- Right-click Member → **Member Graphs** opens a modeless window with case,
  component, x/L and left/right inspection. It can show the selected member or
  connected collinear members, joined by analytical node IDs (not merely nearby
  or parallel). Each member retains its own local i→j axes and signed plot.
- Positive/negative areas, solver extrema/positions, lengths and units are shown.
  Displacement display uses mm; stored data is untouched. Graph line tessellation
  is for display only; extrema and x/L values use existing solver results.
- Current results required. An open graph clears plots and shows OUT OF DATE
  after input changes. No solver values/model data are modified by the dialog.

## Validation / remaining scope

See `TEST_RESULTS_MEMBER_WORKFLOWS.md` and `artifacts/member-workflows/`.
Primary/Qt regression, mixed 2D/3D superposition and separate envelopes,
IGZ round trip, stale protection, real-host dialog rendering and menu routing.
Live tests use reloaded installed components, not cold restart evidence.
Physical mouse, live committed Save/Load/Undo/Redo, clean VM and rebuilt Setup
remain Not Tested. Groups display separate member plots, not a merged global
force diagram. Capacity / Code Compliance remains Not Available.
