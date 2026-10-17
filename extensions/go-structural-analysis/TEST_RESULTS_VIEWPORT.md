# Viewport performance and model diagnostics — v0.2.4 patch

10 October 2026. Existing source and installed user plugin were backed up in `backups/viewport-diagnostics-before-20261010`. No IngeTrazo core / Program Files changes.

## Executed results

- Primary automated: **252 Passed, 0 Failed**. 4 Qt modules skipped in solver environment; Qt runs separately.
- Qt automated: **25 Passed, 0 Failed**.
- Installed Windows MCP: **23 Passed, 0 Failed**. Cold plugin load, visible canvas, house geometry, near-duplicate nodes/overlapping members, issue selection, precheck gate, unstable solver rejection, stable analysis via dialog, equilibrium, Save/Load, Undo/Redo and 2D overlay.
- House timing uses a restored previously analyzed QA IGZ. Fresh solver execution in this QA used cantilever/unstable examples; full house engineering/reference comparisons ran in primary tests.
- Source/installed SHA-256 comparison: 28 Python files match.

## Actual measured repaint time

| View | Before [ms] | After [ms] | Reduction |
|---|---:|---:|---:|
| Model | 52.2 | 17.5 | 66.5% |
| Loads | 338.1 | 22.9 | 93.2% |
| Mz | 878.3 | 74.5 | 91.5% |
| Deformed | 107.6 | 49.1 | 54.4% |

Live installed host world_to_pixels API plus QPainter on a viewport-sized QImage; 255-member house, DL, labels OFF, changing yaw; warm frames. Before 4 frames, final after 16. CPU overlay repaint time, not monitor FPS or complete GUI event latency.

Mz projection calls reduced from 8,256 to one per warm frame. Cached world geometry still projects again for each camera, so perspective/orbit/pan/zoom cannot reuse obsolete screen coordinates. Signed polygons preserve the existing plotted area and zero/load-jump boundaries. Full solver results, inspector values and extrema remain unchanged.

## User workflow

**Model → Check Model / Stability…**. Set geometry tolerance in metres (0.001 m = 1 mm), then Check again. The table identifies duplicate IDs, coincident/near nodes, duplicate/reversed members, zero length, missing references, collinear overlap, unsplit nodes/crossings, orphan nodes, unrestrained rigid-body modes and invalid axial/torsion releases. Click a row to select its first Node/Member; review every ID listed. It never merges/deletes inputs automatically.

**Run Analysis + stiffness check** starts the existing background worker after precheck errors are resolved. Rigid-body screening does not detect every internal mechanism. The solver rejects singular active stiffness; this is linear stability screening, not a buckling or section-capacity check.

On **Loads**, automatic self-weight appears as blue members only when its case/combination factor is active. Explicit migrated self-weight loads use the same convention. Ordinary user loads retain arrows. This display change does not change density, case factors, units or solver loading.

## Reviewed live images

- `artifacts/viewport-performance/Self-weight-blue.png`
- `artifacts/viewport-performance/Model-check.png`
- `artifacts/viewport-performance/Model-check-errors.png`
- `artifacts/viewport-performance/Mz-camera-0.png`, `Mz-camera-1.png`, `Mz-camera-2.png` (orthographic/perspective)
- `artifacts/viewport-performance/2D-model.png`

Actual window captures include the child canvas. The installed host's high-resolution FBO MCP screenshot omits it; that blank FBO capture is not used as viewport evidence.

## Files changed

Source: `projection_cache.py`, `diagnostics.py`, `diagnostics_ui.py`, `visualization.py`, `visualization3d.py`, `diagram_geometry.py`, `display.py`, `ui.py`, `workspace_ui.py`.
Tests: `test_diagnostics.py`, `test_qt_performance.py`, `profile_viewport.py`, `build_viewport_report.py`. Documentation: this report, `VIEWPORT_DIAGNOSTICS.md`, `README.md`, `ROADMAP.md`, `CHANGELOG_v0.2.4.md`; executed evidence is under `artifacts/viewport-performance`.

## Failed / Not Tested / Known limitations

- Final executed failures: **0**. The earlier disappearing-canvas regression was corrected and the cold/visible-window checks repeated.
- Not Tested: physical mouse input, clean Windows VM, rebuilt installer payload. The local installed plugin is updated; the existing Setup executable has not been rebuilt for this patch.
- Large all-member graphs and dense labels still cost more than a model-only view; no 60 FPS claim. Labels off / Sparse helps navigation. No automatic topology repair, nonlinear/P-delta/buckling analysis or capacity/code-compliance verdict.

## Reproduce

` .venv/Scripts/python.exe -m pytest tests -q --junitxml=artifacts/viewport-performance/primary-pytest.xml `

` .qa-venv/Scripts/python.exe -m pytest tests/test_qt_v02.py tests/test_qt_v024.py tests/test_qt_house.py tests/test_qt_performance.py -q --junitxml=artifacts/viewport-performance/qt-pytest.xml `

In the installed MCP session, execute `tests/profile_viewport.py`, then `profile(panel, 'after-final', 16)` on a Current house model with DL selected. Run `tests/build_viewport_report.py` after recording live checks; it rejects failed tests, failed checks or installed-source hash differences.
