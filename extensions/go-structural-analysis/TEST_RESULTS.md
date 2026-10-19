# GO Structural Analysis v0.1 — Test Results

Tested 2026-10-08 on Windows 11 with the installed `C:\Program Files\IngeTrazo\ingetrazo.exe` through its MCP bridge.

## Runtime / API compatibility

- Live host: CPython 3.12.10, 64-bit, frozen; prefix `C:\Program Files\IngeTrazo\_internal`.
- pip and PyNite absent in host. Used isolated worker Python 3.12.14, PyNiteFEA 3.2.0.
- API_VERSION = 2. Required ExtensionApp methods present.
- Plugin discovery by the real host: package found, no import errors.
- Live setup: side panel, menu action, document-change callback and native overlay registered.
- Transparent Qt child canvas verified visually on the live viewport; native MCP
  `screenshot` excludes extension overlays in this host. `window-moment.png` and
  `window-deformed.png` are real Qt window captures, including the extension canvas.
- Editor model round-trip passed; negative E rejected without accepting edits.
- JSON worker executed from frozen host and returned expected results.
- QThread background analysis completed through the queued GUI slot.
- `.igz` save/load preserved model and results exactly.
- Native document-data Undo/Redo restored analysis results.
- Model, N, V, M, Deflection, Reaction and Deformed canvas render/capture passed.
- Workspace enter/leave preserved original scene and history identities, original
  plugin data, camera, and geometry: 1 Engineer group, 0 loose faces/edges.
- A camera restoration defect was caught during testing: integer pitch caused the
  host to cast its restored angle to int. Extension now retains float pitch;
  a repeated live workspace cycle confirmed exact camera restoration.
- No Program Files writes or changes to IngeTrazo core source. No structural data
  was committed into the original model. The benchmark is a separate `.igz` artifact.

Machine-readable evidence: `artifacts/live-tests.json`, `artifacts/pytest.xml`.

## Benchmark

Simply supported horizontal beam, L = 6 m, uniform downward w = 10 kN/m,
self-weight OFF. E = 200,000,000 kN/m² (200 GPa), G = 76,923,076.923 kN/m²,
A = 0.01 m², Iy = Iz = 8e-5 m⁴, J = 1e-5 m⁴. N1 Pin; N2 Roller.

| Quantity | Theory | Solver | Result |
|---|---:|---:|---|
| Left reaction | 30 kN | 30 kN | PASS |
| Right reaction | 30 kN | 30 kN | PASS |
| Peak moment magnitude | 45 kN·m | 45 kN·m | PASS |
| Midspan downward deflection | 10.546875 mm | 10.546875 mm | PASS |
| Sum vertical reactions | 60 kN | 60 kN | PASS |

Theory: R = wL/2; |M|max = wL²/8;
δmax = 5wL⁴/(384EIz). PyNite local moment at midspan is −45 kN·m and
vertical displacement is −0.010546875 m. Relative deflection tolerance 1e-8;
reaction/moment absolute tolerance 1e-8. The benchmark passes at these tolerances.

## Automated solver/protocol tests

**19 passed**, latest full run 4.59 seconds. Tests include:

- UDL benchmark, cantilever point load, member midpoint point load.
- Inclined frame global equilibrium and transformed endpoint displacement.
- Multiple load cases and self-weight; triangular truss and zero truss moments.
- Duplicate IDs, negative section property, NaN, missing reference, invalid load
  extent, unsupported schema and invalid truss loading.
- Unstable structure, invalid worker protocol, missing runtime, worker timeout.
- Real JSON subprocess solve and model JSON round-trip.

## UI update matching the supplied reference

Dark native Qt UI installed and loaded live without restarting the application.
Model / Loads / Results tabs and extension/menu/dock icons verified. All seven
card routes target the correct editor section. Model-type and self-weight controls
were exercised against an in-memory document; invalid truss member loading was
rejected. Editor round-trip passed, and the live document data remained unchanged
during the UI update. Evidence: `artifacts/ui-tests.json`, `ui-model-dark.png`,
`ui-loads-dark.png`, `ui-results-dark.png`, `ui-window-dark.png`, `extension-icon.png`.

## Theme preference update

The extension no longer forces a dark theme. Live tests exercised the installed
host's `apply_theme` with Light, Dark and System without saving a preference.
Panel and Editor backgrounds matched the application's palette in each mode:
Light `#efefef`, Dark `#2d2d30`, and the OS-resolved System palette. The same panel
instance updated live; its card icons switched to the new palette's ink.
Original saved theme (Light) and document data were unchanged, and Light was
restored after the checks. Native viewport colors remain controlled by the
document display style. Evidence: `artifacts/theme-tests.json`, `ui-theme-light.png`,
`ui-theme-dark.png`, `editor-theme-light.png`, `editor-theme-dark.png`.

## Limits

v0.1 is linear elastic 2D Euler–Bernoulli analysis; it does not provide structural
design-code/capacity checks, load combinations, P-delta, buckling or shear
deformation. Diagram extrema are sampled at 61 positions per member. Tests
validate the listed benchmark and representative cases; they are not certification
of every structural topology or future IngeTrazo release. See README for signs,
units, support conventions and the installed-build overlay compatibility layer.
