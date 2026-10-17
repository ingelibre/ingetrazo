# Load forms patch — v0.2.4, 11 October 2026

## Passed

| Executed suite | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Primary pytest (`.venv`, `tests`) | 252 | 0 | 5 Qt modules |
| Qt adapter suite (`.qa-venv`, five Qt modules) | 34 | 0 | 0 |
| Focused forms suite (subset, not additional count) | 9 | 0 | 0 |

The nine form tests cover reference-safe rename and protected metadata,
self-weight mapping, duplicate-name errors, unused-case deletion, numeric positive
and negative factors, hidden JSON storage, checkbox mapping, statutory clone
protection, rename/delete/cancel, preserving existing full-precision factors,
background solver superposition, names containing commas, result invalidation and
a shown house dialog that adds a combination without changing existing formulas.
Existing 2D/3D engineering tests are included in the primary run.

Installed-host MCP completed five checks on the house workspace: cold plugin
load, actual Load Cases card save/rename, load-reference rename, Stale result
invalidation, and undo restoring the original model with Current results.
Dialog screenshots were captured from actual Qt windows before the interrupted
live run. Their appearance is evidence of rendering, not proof of all workflows.

The development installer copied the final package to the user plugin directory.
SHA-256 comparison of all 29 Python files is recorded in the JSON report.
The worker/runtime configuration is retained. Program Files was not changed.

## Failed / incomplete live verification

The installed-host `numeric_formula_preview` assertion failed. Its callback did
not record the actual formula text or which assertion predicate failed. The
pending modal call subsequently timed out on the UI thread. The same shown house
dialog scenario passes the added Qt test; this does **not** resolve the live
failure. A subsequent MCP call returned connection refused. The Windows
computer-use runtime also reported that its native pipe was unavailable.

Do not label the complete installed-host combination workflow Passed. Reconnect
AI → Start bridge, repeat with individual short calls and log the formula text,
selected combination and numeric factors before asserting. Save/Load and full
combination Undo/Redo still require completion in the installed host.

## Not Tested

- Cold restart of the final copied source after final label/unused-case changes.
- Completed live combination Save/Load and Undo/Redo round trip.
- Physical mouse/keyboard interaction and clean Windows VM.
- Rebuilding or distributing a new Setup executable for this patch.

Backups: `backups/load-forms-before-20261010/go_structural_analysis`,
`model-before.igz` (analyzed house) and `original-before-cold.igz` (parked document).
No source model is overwritten by these form changes. Since MCP is disconnected,
the final live workspace state cannot be rechecked.

## Evidence and reproducibility

Evidence lives in `artifacts/load-forms`: primary/Qt/focused pytest XML,
combined `pytest.xml`, `test-results-load-forms.json`, raw `live-results.json`,
`Load-cases.png` and `Load-combinations.png`.

Run `.venv/Scripts/python.exe -m pytest tests -q` for primary checks. Run the
five `test_qt_v02.py`, `test_qt_v024.py`, `test_qt_house.py`,
`test_qt_performance.py`, `test_qt_load_forms.py` modules under `.qa-venv` for Qt.
`tests/build_load_forms_report.py` aggregates recorded evidence without replacing
historical v0.2.4 or viewport reports. Full release acceptance remains incomplete.
