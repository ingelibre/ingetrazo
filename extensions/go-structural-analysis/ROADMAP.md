# v0.2.4 — implemented scope and evidence

LC-001 matrix/generator increment: [Prota-reference backlog](docs/UI_BACKLOG.md)
and task [LC-001](docs/tasks/LC-001-load-combinations.md). Matrix edits/Custom clone,
reviewed Thai preset generator and guide continuation records are implemented;
Cold Restart and live persistence remain pending in TEST_RESULTS_COMBINATION_OVERVIEW.md.

Command UI increment (11 October 2026): central routing/enabling rules, Ctrl+K
search, Model Tree filter and analytical context menus with delete-impact preview.
Evidence: `TEST_RESULTS_COMMAND_UI.md`. Configurable quick access, property-form
previews, Project workflows and storey/grid/view management remain future work.

Compact ribbon increment (11 October 2026): five task tabs delegating to the
existing panel workflows, collapsible commands, status, safe exports and overlay
spacing. Future command search, context menus, storeys/grids and named views are
tracked in `RIBBON_UI.md`; installed-host validation is pending.

Load forms patch (11 October 2026): named-case manager, numeric Custom factors,
live preview and checkbox action bindings. Primary 252 and Qt 34 passed.
Installed-host QA is incomplete; see `TEST_RESULTS_LOAD_FORMS.md`.

Viewport/model diagnostics patch (10 October 2026): batched projection and picking,
world-geometry caches, signed-region merging, single visible canvas, idle repaint
suppression, blue self-weight members and read-only geometry/restraint checks.
Evidence: `TEST_RESULTS_VIEWPORT.md` (252 primary, 25 Qt, 23 installed-host checks).
Internal stiffness remains a solver check; topology repair/buckling are future work.

| Phase | Implementation | Verification |
|---|---|---|
| 1 | Gazette-cited ASD/LRFD pack, directional binding, Custom clone/edit/disable, separate groups | Independent 18-formula factor golden tests + 2D/3D closed-form solver goldens; live manager |
| 2 | Input fingerprints, five states, stale/archived display/export, finite/equilibrium/failure guards | Safety tests, current report, live watermark/export/undo/save checks |
| 3 | Selected axes, signed fills, plane/highlight, collision placement/density, mm/tolerance/defaults | Qt placement/immutability tests; perspective/camera/member-pick live captures |
| 4 | Model tree, collapsible sections, width bounds, viewport controls, reviewed action/custom tables | Qt + installed-host UI screenshots/themes/hide/restart |
| 5 | Preserved baseline and added golden/safety/UI/installer validation | TEST_RESULTS_v0.2.4.md; manual hardware and clean VM remain Not Tested |

# GO Structural Analysis — v0.2.3 development

| Phase | Scope | Verification evidence |
|---|---|---|
| 1 | Schema 2 XYZ, 6 DOF supports/springs/releases, rotation, migration, geometry review | `phase1-v02.xml`, model/editor and migration tests |
| 2 | PyNite 3.2 six-DOF adapter, proper rotation, stiffness/equilibrium guards | `phase2-v02.xml`, cantilever/torsion/axial/spring/protocol tests |
| 3 | Cases, user combinations, self-weight once, exact envelopes and CSV | `phase3-v02.xml`, local/global load and superposition tests |
| 4 | XYZ diagrams, local axes, deformed shape, camera-independent selection | Qt and live viewport evidence in `artifacts/v0.2` |
| 5 | 12 benchmark groups with an independent frame/truss reference | `phase5-v02.xml`, `artifacts/v0.2/engineering-checks.json` |
| 6 | 2D/3D UI, themes, background worker, save/load/history/cold restart | `artifacts/v0.2/live/live-results.json` and screenshot evidence |

See `TEST_RESULTS_v0.2.md` for the final actual counts and remaining checks.
Next v0.3 candidates: nonlinear/P-delta, design-code capacity checks, constrained
joint/intersection tools, section libraries, and an envelope viewport with collision-aware labels.

## Preserved v0.1.3 history

This release extends the existing v0.1 project and user plugin. Original evidence
and source/plugin backups are retained; the host core and Program Files are unchanged.

| Milestone | Implementation | Executed verification |
|---|---|---|
| v0.1.1 Engineering visualization | Support/release/load symbols, N/V/M/D, deformation, scales, labels, legend, world projection | Live viewport captures, camera transform and picking checks |
| v0.1.2 Result inspector | Member selection, exact x/L with left/right values, four tables, five CSV files, stale results | Automated evaluation/CSV tests and live viewport/editor/save/load/history checks |
| v0.1.3 Solver verification | Segment polynomial extrema, reference benchmarks, sparse LU stability and equilibrium guards, cases/self-weight, material presets | 90 pytest cases, original 19 regression cases included, actual reference comparisons in JSON |

See `TEST_RESULTS_v0.1.3.md` for Passed / Failed / Not Tested and remaining
environment checks. Cold process restart, physical mouse input and an actual
Windows theme change were not executed. Preserve those qualifications when
sharing the release; do not label these checks Passed.

The solver adapter is intentionally pinned to PyNiteFEA 3.2.0. Updating that pin
requires repeating the continuous-segment, transformation, release and load-jump
benchmarks. Nonlinear analysis, combinations and design-code checks are outside
this release's scope.


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
