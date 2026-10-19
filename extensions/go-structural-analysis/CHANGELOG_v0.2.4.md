# v0.2.4

LC-001 patch, 11 October 2026:
- Editable Custom combination matrix, filtering/duplicate and collapsible details.
- Protected statutory rows with clone provenance and selected-row operation gates.
- Reviewed Thailand 2566 Loading Generator for existing cases and wind alternatives.
- Preserve full precision and existing Custom rows; Missing Input remains explicit.
- Guide PDF metadata, full chapter backlog, AGENTS instructions and topic task files.
- Evidence: `TEST_RESULTS_COMBINATION_OVERVIEW.md` (252 primary, 61 Qt, 15 live dialogs).

Command UI patch, 11 October 2026:
- Shared command registry for Ribbon, Ctrl+K search and analytical context menus.
- English/Thai keyword search, availability explanations and live state refresh.
- Model Tree filter retained during refresh; Node/Member properties and inspector.
- Context target preservation, deletion-impact confirmation and busy/current gates.
- Evidence: `TEST_RESULTS_COMMAND_UI.md` (252 primary, 48 Qt, 12 live components).

Compact Ribbon patch, 11 October 2026:
- Five task tabs, existing-form command groups, quick Save/Run and textual status.
- Collapsible command row, narrow-view scrolling and side-panel synchronization.
- Current/Stale exports delegated to the existing safety layer.
- Legends below the ribbon, reserved label bounds and controls above canvas.
- Actual QA and pending host checks: `TEST_RESULTS_RIBBON.md`.

Load forms patch, 11 October 2026:
- Dedicated Load Cases table with reference-safe rename, usage counts and presets.
- Custom combinations use numeric factors, live formulas, rename/delete and enable.
- Action binding uses checkbox case menus; visible JSON entry removed.
- Full editor opens both managers; point/distributed loads select named cases.
- Preserve protected statutory formulas, full-precision stored factors and Stale safety.
- Evidence and remaining live QA: `TEST_RESULTS_LOAD_FORMS.md`.

Viewport / Model Check patch, 10 October 2026:
- Batch 2D/3D projection and picking; cache world curves, merge signed fills,
  reuse pixel objects, avoid duplicate/idle painting and unchanged summary work.
- Self-weight blue-member visualization without changing solver loads.
- Model Check dialog: duplicate/near nodes, duplicate/overlapping members,
  connectivity/joint warnings, rigid-body screening and solver stiffness action.
- Actual performance and QA evidence: `TEST_RESULTS_VIEWPORT.md`.

- Thailand 2566 versioned/cited pack: 7 ASD + 11 LRFD formulas, reviewed action
  bindings, directional derivatives, missing inputs, self-weight once in D.
- Read-only statutory factors; editable/disableable Custom factor tables, Clone
  provenance and separate method envelope groups.
- 2D combinations and envelopes added without changing legacy 2D case behavior.
- Current/Stale/Running/Failed/Not Analyzed safety state; full input fingerprints,
  snapshots, finite/equilibrium guards, scene-geometry checks and failure invalidation.
- Stale watermark independent of Legend. Optional archived snapshot visualization;
  gated current CSV/JSON report and explicitly labelled archived CSV exports.
- Selected-member axes by default, All/Selected/None, label collision placement and
  density, consistent signed fills, visible diagram planes, display tolerance and mm.
- Analytical model tree, collapsible sections, width bounds, viewport quick controls,
  themes, status text and background progress.
- Added independent golden factor/closed-form solver tests, safety tests and Qt/live QA.

Limits: linear elastic analysis; no automatic seismic/pressure/thermal action
construction, no section capacity or complete serviceability/design checks.


## Member workflows - 2026-10-11

ASD/LRFD presets can coexist with Custom combinations, with separate method
metadata/envelope groups. Distributed-load rows show analytical length and an
explicit full-member action. Member context menus open modeless single/connected
collinear result plots, preserving local signs and stale-result protection.
See MEMBER_WORKFLOWS.md and TEST_RESULTS_MEMBER_WORKFLOWS.md for usage, actual
validation and remaining restart/installer/physical-interaction limitations.


## CG-001 - Continuous beam diagrams / 2026-10-11

Connected collinear beam graphs now share one cumulative station axis and scale,
with node/member labels and horizontal scroll. Reversed/rotated member forces
project to the context-selected common frame; exact polynomial extrema and
real jumps retained. Click a station to inspect member/x/L. See
MEMBER_WORKFLOWS.md and TEST_RESULTS_CONTINUOUS_GRAPHS.md for actual QA evidence.
