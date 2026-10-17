# TEST RESULTS — Continuous beam diagrams / v0.2.4

CG-001, 11 October 2026. Existing source and original live model backed up.

| Final suite | Passed | Failed | Not Tested / skipped |
|---|---:|---:|---:|
| Primary | 267 | 0 | 10 Qt module skips, run separately |
| Qt | 72 | 0 | 0 |
| New primary focused | 8 | 0 | 0 |
| New Qt focused | 3 | 0 | 0 |
| Live component checks | 18 | 0 | See below |

Focused tests are included in full-suite totals. New tests: 8 primary + 3 Qt.
Installed source matched 35 Python files. Solver remains PyNiteFEA 3.2.0.
No model/solver inputs changed by selecting/displaying plots.

## Passed scope

Single cumulative station axis, shared scale, joint/Member labels, signed fill,
exact projected-polynomial extrema. Unsplit vs split solver representation
checks in 2D/3D, reversed member and section rotation 37°, all components,
relative tolerance 1e-7 / absolute 1e-9. These are representation-invariance
checks, not independent new solver-theory benchmarks. Existing primary suite
retains its prior engineering benchmark coverage.

Point-load fixture preserves shear jump of 10 kN and moment continuity. No false
smoothing. Invalid overlapping chains rejected. QTest clicks select station,
member and x/L; joint left/right respects common direction and reversed members.
Six-span view scrolls horizontally; single-member mode and Stale clearing pass.

Live installed/hot-loaded components show M2+M10 at 0–8 m, joint 4 m, station
6 m reads M10 local x=2 m. Both joint sides and all seven 3D plots checked after
Qt event loop. Real screenshots inspected. Original 21-member inputs unchanged.
The real model has a moment jump at the joint: this remains visible according
to the actual solver result; it is not forced to a smooth curve.

## Development failures resolved

Initial test fixture expected a 6 m length for the existing 4 m cantilever;
expectation corrected. Horizontal scroll minimum-width propagation fixed and
rerun. One premature live screenshot/check occurred before queued Qt layout/show
events; all seven components were rechecked individually after the event loop,
with actual images. Initial evidence kept in live-before-event-loop.json.
Final failed counts above refer to the final runs/rechecks.

## Not Tested

Cold Restart/full plugin reload, physical mouse interaction, clean Windows VM,
live committed Save/Load/Undo/Redo and rebuilt Setup. Hot component import tests
do not establish full plugin cold startup. Qt QTest is simulated interaction.

## Known limitations

Connected collinear chains only; overlaps/branches cannot be presented as a
single beam. Common axes are those of the context-selected member; transformed
values in group mode are distinct from a member's raw local-axis components.
Raw values retained. Real force/moment jumps remain. Capacity / Code Compliance
Not Available. No analytical nodes are merged automatically.

## Changed files

go_structural_analysis/member_graph_ui.py; new continuous_graph.py;
tests/test_continuous_graph.py, test_qt_continuous_graph.py and report builder;
MEMBER_WORKFLOWS.md, docs/tasks/CG-001-continuous-member-graphs.md,
docs/UI_BACKLOG.md, CHANGELOG_v0.2.4.md, ROADMAP.md, UPDATE_v0.2.4.md,
this report and artifacts/continuous-graphs/ XML/JSON/PNG evidence.

Backup: backups/continuous-graphs-before-20261011/live-model-before.igz
and original source. No Program Files changes. No commit/push requested.
