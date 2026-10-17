# Ribbon UI patch — 11 October 2026

## Passed

- Primary regression: **252 passed**, 6 Qt modules skipped in the solver-only env.
- Qt adapter regression: **39 passed**, including 5 new ribbon workflow tests.
- New tests verify actual button delegation, tab/panel synchronization, preservation
  of model/results during display changes, collapse/resize, hidden-panel access,
  Current/Stale export gating, background analysis and Light/Dark/System palettes.
- Offscreen Qt images for Model, Loads, Analysis, Results, Display and Collapsed
  were generated. Model layout was visually inspected at 980 px width; Thai font
  fallback was registered for offscreen rendering. These are adapter screenshots,
  not installed-host captures.

The initial new-test run had one assertion mismatch: it expected bare `Stale`
while the status contained the full capacity notice. The ribbon now shows short
status with the full message in its tooltip. Review also corrected update ordering
so export buttons follow the inspector's refreshed safety state. Final test counts
are recorded in `artifacts/ribbon/primary-pytest.xml` and `qt-pytest.xml`.

## Not Tested / limits

- Installed-host Ribbon load, painting, mouse interaction and cold restart:
  MCP connection to 127.0.0.1:4763 returned connection refused.
- Final live Save/Load/Undo/Redo of the preceding load-form patch is still pending;
  its failed preview assertion remains documented in TEST_RESULTS_LOAD_FORMS.md.
- Clean Windows VM and a rebuilt Setup installer.
- Full ribbon customization, command search, context menus, storeys/grids and
  multiple docked views are planned; not implemented here.

No final installed-host Passed claims are made for this patch. Reconnect AI →
Start bridge and perform each live operation in a short separate MCP call.

## Changes / preservation

Added `ribbon_ui.py` and `tests/test_qt_ribbon.py`; changed `ui.py`, `theme.py`,
`visualization.py`, `visualization3d.py` for integration, style and header spacing.
Model/solver schemas and units are unchanged. Source backup:
`backups/ribbon-before-20261011/go_structural_analysis`. Existing model backups are
retained; this patch does not edit live model data. No Program Files changes.
