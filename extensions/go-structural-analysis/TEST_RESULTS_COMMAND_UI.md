# Command UI patch — 11 October 2026

## Passed

| Actual executed suite | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Primary regression, solver `.venv` | 252 | 0 | 7 Qt modules |
| Seven Qt adapter modules, `.qa-venv` | 48 | 0 | 0 |
| Focused command module (subset) | 9 | 0 | 0 |
| Installed-host MCP component checks | 12 | 0 | 0 |

Command tests cover keyword/no-match search, Enter routing, busy-state recheck,
Current/Stale exports, selection enable states, member/node context actions,
retaining the original context target, rejecting removed targets, delete cancel/
confirmed cascade, tree-filter preservation and a synthetic viewport context event.
The first focused run had two incorrect fixture assumptions (member M1 instead of
fixture B1; `fz` instead of the 3D load schema). Corrected tests now use actual IDs
and edit geometry for invalidation. No engineering changes were needed.

MCP checked actual new components inside the running host: module import, search
keywords, member Inspector routing, node action availability, Current export
gating, collapse, unchanged inputs, tree filter, numeric combination form and
cancel, a Qt viewport context event, and restoring the original view/model.
Actual window captures are in `artifacts/command-ui`.

**Scope of live evidence:** the host still had its previous Panel loaded. New
registry/Ribbon components were temporarily attached for these checks and removed
afterward. This is live component verification, not a cold-load/full-plugin claim.
The final copied source adds automatic command-state refresh after the live checks;
the final Qt regression covers that change. No live model inputs were committed.
The 8-member model was backed up to
`backups/command-ui-before-20261011/live-model-before.igz`.

The numeric form now passes on the current 8-member model. It is not a rerun of
the earlier house-model failed assertion; retain that historical qualification in
TEST_RESULTS_LOAD_FORMS.md. One preliminary MCP request containing literal Thai
failed with UnicodeEncodeError and was rolled back; ASCII-code retries succeeded.

## Not Tested

- Cold restart and complete final Panel/plugin loading.
- Physical Ctrl+K, mouse right-click/orbit/pan and shortcut conflicts.
- New context-menu deletion history in the installed host, full Save/Load/Undo/Redo
  of the preceding load-form patch and its exact house preview assertion.
- Clean Windows VM or a rebuilt Setup executable.

These remain pending and are not labelled Passed. The development installer copied
the final source to the user plugin; SHA-256 values are in the JSON evidence.
No Program Files changes, solver/schema changes or original-model overwrite.

## Changed files / evidence

New `go_structural_analysis/command_ui.py`, `tests/test_qt_commands.py`,
`tests/build_command_ui_report.py`. Updated `ui.py` and `ribbon_ui.py`, plus user
instructions/roadmap/changelog. Source backup:
`backups/command-ui-before-20261011/go_structural_analysis`.

Evidence: `artifacts/command-ui/primary-pytest.xml`, `qt-pytest.xml`,
`commands-pytest.xml`, combined `pytest.xml`, `live-results.json`,
`test-results-command-ui.json` and actual window PNGs. Counts from the focused
module are already included in the 48 Qt tests.
