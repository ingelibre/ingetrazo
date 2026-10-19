# LC-001 — Combination overview / Generator QA, 11 October 2026

## Passed

| Executed suite | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Primary regression (`.venv`, tests) | 252 | 0 | 8 Qt modules |
| Qt regression (`.qa-venv`, eight modules) | 61 | 0 | 0 |
| New overview tests, included in Qt total | 13 | 0 | 0 |
| Installed-host MCP dialog checks | 15 | 0 | 0 |

New tests cover multi-row +/-/0 edits, disabled Custom combinations, finite/empty
validation, filtering, duplicate/protected-clone provenance, first-Custom selection,
protected-row operation gating, unchanged-editor precision, details/matrix sync,
independently specified golden LRFD factors, missing inputs, directional alternatives,
cancel/case preservation, 2D/3D solver superposition and Current → Stale export gates.

MCP used the actual installed new dialog modules with the user's current 8-member
model. Checks covered import, correct new-row selection, numeric matrix edits,
duplicate factors, protected rows, unchanged inputs, the actual Generator button
with a QTimer-driven modal, retained Custom rows, unavailable inputs unchecked,
draft Save validation, Save without committing the draft to the live model, Cancel
with Current results, synthetic numeric-editor Enter commit and final input preservation. Actual dialog Before/After and
Generator captures are in `artifacts/combination-overview`.

Live backup: `backups/combinations-overview-before-20261011/live-model-before.igz`.
Source backup: the adjacent `go_structural_analysis` directory. All 32 installed
Python source hashes are compared with the final source in the JSON report.
No original model inputs or Program Files files were changed.

## Initial failures and corrections

- One new test expected a nonexistent 2D `dz` node key. It now uses a nonzero
  support reaction for 2D superposition and a tip displacement for 3D.
- Live duplication exposed a real selection defect: the first Custom added to
  protected presets left the overview focused on the original row. Corrected
  selection and added a regression; live duplication then passed.
- A subsequent MCP harness call omitted its Qt import, causing NameError and
  rollback. Repeated the pending checks after importing Qt; they passed.
- The installed host does not bundle PySide6.QtTest. Used direct Qt key events
  for the live editor instead. Its first assertion ran before the queued commit;
  the next event-loop turn showed the correct 2.4 factor. Preserved that initial
  Failed snapshot in `live-before-event-loop.json` and rechecked successfully.

These are initial-run failures, not hidden final Passed claims. The final Qt/XML
counts reflect reruns after corrections. Final small provenance/invalid-display
changes are included in final Qt regression. The last numeric-editor check used
the final dialog source, while earlier live checks preceded those small changes.
The exact final package was copied and hash-checked afterward.

## Not Tested / known limits

- Cold restart and full final Panel/plugin load.
- Physical mouse/keyboard interaction, bulk paste, Clean Windows VM.
- Live committing the new draft, Save/Load/Undo/Redo: deliberately left the user's
  model untouched. The panel safety workflow is verified in the Qt adapter.
- Rebuilt Setup executable. This remains a source/development-install patch.
- Creating physical actions/empty cases, cracked stiffness, P-Delta and capacity
  design are outside LC-001. Missing action references are not replaced by zeros.

Source guide is stored locally, excluded from Git/installer. Its metadata and
backlog are versioned project documents. The chapter index comes from the full
table of contents; only pages 3–9 and 30–31 have been reviewed in this work.
Other chapters require page-level review before implementation.

## Changed files and reproducibility

Added `combination_tools.py`, `tests/test_qt_combination_overview.py`, report builder,
`AGENTS.md`, guide metadata, `docs/PROTA_REFERENCE.md`, `docs/UI_BACKLOG.md`, task
template and `LC-001` task. Changed `combination_ui.py`, `.gitignore` and release
documentation. Preserved schemas, worker, units and existing Thai equations.

Evidence: primary/Qt XML, combined `pytest.xml`, `live-results.json`,
`live-previous-attempt.json`, `test-results-combination-overview.json`, and actual
PNG captures in `artifacts/combination-overview`.

Run primary tests with `.venv/Scripts/python.exe -m pytest tests -q`. Qt uses the
eight `test_qt_*.py` files explicitly under `.qa-venv`; the new module is
`tests/test_qt_combination_overview.py`. The report builder aggregates recorded
results and validates the local reference PDF hash; it does not replace older
release reports.
