# GO Structural Analysis v0.2.4

New [Combination overview / Loading Generator](COMBINATION_OVERVIEW.md): edit
multiple Custom rows, clone originals and review Thai presets before applying.
[Guide/task records](docs/PROTA_REFERENCE.md) make future Prota-referenced work
repeatable. [LC-001 actual QA](TEST_RESULTS_COMBINATION_OVERVIEW.md).

New [command search and context menus](COMMAND_UI.md): Ctrl+K, searchable Model
Tree, Node/Member actions and shared Ribbon safety rules. [Actual command QA](TEST_RESULTS_COMMAND_UI.md)
includes installed-host component checks; cold restart remains pending.

New compact [workspace Ribbon](RIBBON_UI.md): Model / Loads / Analysis / Results /
Display, collapsible groups and quick Save/Run. [Ribbon QA](TEST_RESULTS_RIBBON.md)
records automated checks and pending installed-host verification.

New [Load Case / Combination forms](LOAD_FORMS.md): named cases, numeric factors,
live formula preview and checkbox action bindings. [Actual patch QA](TEST_RESULTS_LOAD_FORMS.md)
separates automated success from incomplete installed-host verification.

New editable [Phetnaray house example](HOUSE_EXAMPLE.md): concrete beams/columns,
steel hip roof, independent analysis checks and a portable `.igz` model.

Current release adds a [Thailand 2566 Code Pack](THAI_CODE_PACK_v0.2.4.md),
reviewed Combination Manager, engineering result safety and professional display
controls. Read [v0.2.4 update instructions](UPDATE_v0.2.4.md),
[actual QA](TEST_RESULTS_v0.2.4.md) and [changelog](CHANGELOG_v0.2.4.md).
Capacity, full code compliance and complete serviceability checks are Not Available.

The existing 2D/3D feature set described below is preserved. This release extends the existing v0.1.3 source with **3D beam/column/frame/truss**
analysis, six DOFs, section rotation, DOF supports/springs/releases, load combinations,
exact result envelopes, XYZ overlays and a 3D inspector. The complete 2D workflow
remains supported. Global Z is up; PyNiteFEA stays pinned to 3.2.0 in a separate worker.

Start with [update instructions](UPDATE_v0.2.md), [12 editable 3D examples](EXAMPLES_v0.2.md)
[v0.2 QA evidence](TEST_RESULTS_v0.2.md), and [installer QA](INSTALLER_TEST_RESULTS_v0.2.md). Legacy documentation below describes
the retained 2D workflow and its earlier verification.

Python extension for IngeTrazo Plugin API v2. Source lives outside Program Files.

## Install and run

For trial users, run the matching **GO-Structural-Analysis-v0.2.4-Windows-x64-Setup.exe**.
It includes the offline Python/PyNite solver; save your work and close IngeTrazo
before Setup. Then open Extensions → GO Structural Analysis and choose an example.
Start menu provides Quick Start, Example Gallery, Check Solver and Uninstall.
IngeTrazo Plugin API v2 is required separately. See
[installer tests](INSTALLER_TEST_RESULTS.md) for executed checks and known limitations.
The PowerShell installer below remains available for development installs.

Run `powershell -ExecutionPolicy Bypass -File .\install.ps1`. The installer creates
an isolated Python 3.12 solver under `%LOCALAPPDATA%\GO Structural Analysis\solver-v0.1`
and copies the plugin package to `%APPDATA%\ingetrazo\plugins\go_structural_analysis`.
It never writes to Program Files. With uv unavailable, a working `python -m venv`
and pip are required. Internet access is required for first-time dependency installation.
Restart IngeTrazo; choose Extensions → GO Structural Analysis v0.1.3.

## Engineering example library

Model → **Engineering Examples / Benchmarks** → select an example →
**Load selected example** → **Run Analysis**. Scroll the Model tab to reach the
selector. The 21 editable examples cover simple/cantilever/continuous beams,
portal/inclined frames, trusses, releases, stability, multiple cases,
self-weight and exact extrema. Results → Load Case selects LC1/LC2.
Unsaved structural data requires confirmation before replacement; the original
model stays parked. The two Stability examples are expected to fail analysis.
See [EXAMPLES.md](EXAMPLES.md) for the full list and real window captures.

The side panel follows the supplied UI reference: Model / Loads / Results
tabs, circular Beam/Frame/Truss selectors, icon cards, and a Run Analysis footer.
Model cards open the corresponding editor tab; Supports opens node support data.
The Loads tab controls point/distributed loads, cases and self-weight. Results
contains case/diagram/label/legend controls, deformation scale, a member inspector
and modeless result tables. Click a member in the Results tab, move x/L, and choose
left/right at a concentrated load discontinuity. CSV export writes five tables
with load-case IDs and units. The extension
has its own truss icon in the header, Extensions menu and dock; icons are drawn
with Qt and need no external fonts or image packages. Styling is scoped to the
extension and its editor. Colors follow IngeTrazo **Window → Preferences → Theme**
(Light / Dark / System), including live changes, secondary text, selectors and
icons. The plugin uses the host `views.theme.style` registry and Qt palette;
it does not set an application palette or save any theme preference.

1. Enter 2D workspace; the original scene/history/camera are parked by the host API.
2. Edit nodes, members, materials, sections and loads in the table editor. Add/delete rows.
3. Specify case names, supports and self-weight. Analyze runs in a QThread using a
   separate JSON worker process; it never touches the scene off the main thread.
4. Choose case and Model/N/V/M/Deflection/Reaction/Deformed in the panel.
5. Save structural .igz. Return to model restores the original model.
   **Store in current document** explicitly copies analysis data to that model;
   use File → Save to persist it. This is never done automatically.

To open a saved structural `.igz`, use normal IngeTrazo File → Open (it becomes
the current model document), then enter the structural workspace. The plugin
also displays its data in a current `.igz` without a workspace.

## Analysis conventions

Materials editor → choose **Steel / Concrete / Aluminium / Wood** → **Add preset**.
Members → material now has an editable selector using the current material IDs.
Adding an existing preset selects its row and preserves edited properties.
Presets are editable starting values, not design strengths or capacity checks.

| Preset | E [kN/m²] | G [kN/m²] | nu | rho [kN/m³] |
|---|---:|---:|---:|---:|
| Concrete | 33,000,000 | 13,750,000 | 0.20 | 25 |
| Aluminium | 70,000,000 | 26,923,076.923 | 0.30 | 26.477955 |
| Wood | 11,000,000 | 690,000 | 0.42 | 4.118793 |

Concrete starts with uncracked C30/37-like stiffness; adjust E for the project,
grade and cracking. Aluminium is a generic elastic preset, not an alloy strength.
Wood uses C24-like longitudinal stiffness along each member; G is supplied
independently, and this scalar material interface does not model full orthotropy.
For aluminium/wood, mass density is converted by rho_weight = rho_mass × 9.80665/1000.
Reference values: [concrete research, Ecm table](https://kth.diva-portal.org/smash/get/diva2%3A1972893/FULLTEXT01.pdf),
[aluminium elastic parameters](https://upcommons.upc.edu/bitstreams/cf2ed9c5-c107-450d-8956-0257ee941b42/download),
[timber research, C24 E/G/nu/density](https://pure.au.dk/portal/files/279530292/1_s2.0_S0003682X21001109_main.pdf).
Concrete rho=25 and nu=0.20 are chosen starting assumptions for this preset.

- Coordinates X/Z in metres, forces kN, moments kN·m, E/G kN/m², A m²,
  Iy/Iz/J m⁴, rho weight density kN/m³. Positive FZ upwards.
- Host X/Z maps to solver X/Y. Local member x goes i→j; local y is the in-plane
  perpendicular chosen by PyNite's transformation matrix (not an assumed rotation).
  The exact two basis rows are stored as `members[id].basis` in each case.
  For a left-to-right horizontal member local y is +global Z; members facing
  negative X can have a different perpendicular sign. **Iz governs in-plane bending**. Iy/J/G are passed to the solver
  but out-of-plane degrees of freedom are restrained in this 2D extension.
- N/V/M are PyNite local section force signs (N positive compression).
  For the left-to-right benchmark, downward UDL produces negative M (−45).
  Deflection D is local transverse displacement (diagram/CSV metres, inspector mm);
  Deformed uses global X/Z displacement. Between load discontinuities:
  `N' = p_local`, `V' = w_local`, `M' = -V`, `D'' = -M/(E Iz)` and
  `u_local' = -N/(E A)`. These equations define section signs unambiguously.
  `MY` is the extension's in-plane moment: positive counterclockwise in the X-right,
  Z-up view, mapped to solver +MZ. It is about host **minus Y**, not a right-handed
  global +Y moment. Node rotation/reaction tables use that same plane convention.
  Member end-force tables are local nodal actions at i/j, not section-cut signs.
- Pin: X/Z fixed, rotation free. Roller: Z fixed. RollerX: X fixed.
  Fixed: X/Z and in-plane rotation fixed. All nodes constrain out-of-plane DOFs.
- Beam and Frame use the same 2D Euler–Bernoulli frame element, supporting axial
  and bending action. Truss releases in-plane end moments; rotations at truss-only
  nodes are restrained to remove unused DOFs. Loads on trusses must be nodal.
  Optional `release_i` / `release_j` booleans release the in-plane end moment.
  A nonzero nodal moment at an unsupported fully released rotation is rejected.
- Load cases are solved independently at factor 1. Self-weight, if checked,
  applies to **every case**. Beam/frame self-weight is global downward UDL;
  truss self-weight is lumped equally into its two joints to retain axial-only action.
  No combinations, nonlinear/P-delta, buckling, shear deformation, design-code
  checks or capacity checks in v0.1.3.
- Extrema come from all real roots of each continuous load segment's polynomial
  derivative, plus both sides of segment boundaries. Deflection uses up to a
  fifth-degree polynomial for linearly varying loads. Curves include exact extrema
  and both sides of jumps; the old 61 samples remain only for data compatibility.
  Force/deflection diagrams auto-scale to 18% of longest member length and apply
  the user multiplier. Deformation scale is a displacement multiplier. Neither
  visual scale changes the solver values. Geometry is reprojected on each paint,
  so supports, loads, curves and picking remain anchored during zoom/pan.
  Force arrow tips end on the loaded member/node; reaction tips end on the node.
  Reactions show separate global Rx and Rz arrows with independent labels, never
  a resultant. Nonzero in-plane moments use a curved arrow about the node/load
  location: positive counterclockwise, negative clockwise in X-right/Z-up.
  N/V/M/D areas use transparent blue for positive values and orange for negative
  values, split at zero crossings; the legend displays both signs. Deformed shape
  remains an unfilled displacement curve.
- Model/load edits retain the previous result but mark it OUT OF DATE; diagrams,
  live inspector values and CSV export require a matching SHA256 model fingerprint.
  Old v0.1 results must be rerun once; schema-1 models remain readable. Results
  arriving after a document/model change are discarded.

## Architecture and compatibility

`model.py`: JSON schema/validation. `worker.py`: PyNiteFEA 3.2.0.
`client.py`: bounded subprocess/JSON protocol with error propagation.
`ui.py`: API v2 panel/workspace/document persistence and background analysis.
`solver_results.py`: pinned PyNite continuous-segment adapter and equilibrium checks.
`results.py`: Qt-free exact inspector evaluation, fingerprint, hit test and CSV.
`visualization.py`: engineering glyphs, diagrams and viewport projection.
`inspector.py`: compact member readout and modeless result tables.
Worker JSON protocol stays 1; result schema is 2 with extension version 0.1.3.
The worker rejects near-zero sparse LU stiffness pivots (roundoff threshold
`machine_epsilon * active_DOF_count * max_abs_active_stiffness`) and any failed
global equilibrium check. This catches released mechanisms even with zero load.
Extremely ill-conditioned models can require better scaling or restraints;
they are rejected instead of returning unreliable results.

The installed IngeTrazo is frozen Python 3.12.10 with no pip/PyNite. Solver venv
uses Python 3.12.14. Reference API reviewed at GitHub commit
`6be29fe437a7cd992d4e079f71720821b25216b9`:
https://github.com/ingelibre/ingetrazo/blob/6be29fe437a7cd992d4e079f71720821b25216b9/docs/plugins.md

The native `add_overlay` API is registered, plus a transparent, mouse-pass-through
Qt child canvas provides drawing on the tested installed build. No host code or
methods are patched. The host MCP `screenshot` uses `render_image` and omits
extension overlays; Qt widget captures include the compatibility canvas.
API v2 is provisional upstream; other versions fail setup clearly.

## Validate

`uv venv .venv --python 3.12`
`uv pip install --python .venv\Scripts\python.exe -r requirements.txt pytest`
`.venv\Scripts\python.exe -m pytest tests -q`

See [TEST_RESULTS_v0.1.3.md](TEST_RESULTS_v0.1.3.md) and `artifacts/v0.1.3/`
for current pytest XML, JSON checks, real screenshots, CSV and the benchmark `.igz`.
`TEST_RESULTS.md` preserves the original v0.1 evidence. Before-upgrade source and
installed-plugin backups are under `backups/before-v0.1.3-20261008-191932/`.

## Viewport performance and model checks

The v0.2.4 viewport patch batches 2D/3D projection, avoids idle overlay repainting,
and displays self-weight as blue members. Open **Model → Check Model / Stability…**
to review duplicate/near nodes, overlapping members, connectivity and rigid-body
restraints; **Run Analysis + stiffness check** performs the solver check.
See [VIEWPORT_DIAGNOSTICS.md](VIEWPORT_DIAGNOSTICS.md) for update/use instructions
and [TEST_RESULTS_VIEWPORT.md](TEST_RESULTS_VIEWPORT.md) for measured performance,
executed tests and remaining limitations.

## Uninstall

Close IngeTrazo and remove only `%APPDATA%\ingetrazo\plugins\go_structural_analysis`.
The solver venv may also be removed separately. Saved `.igz` plugin data is retained.
