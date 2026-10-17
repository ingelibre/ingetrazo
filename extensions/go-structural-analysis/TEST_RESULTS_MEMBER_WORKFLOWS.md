# TEST RESULTS — Member workflows v0.2.4 / 2026-10-11

Actual evidence for LC-002. Source/model backed up; no Program Files changes.

| Suite | Passed | Failed | Not Tested / skipped |
|---|---:|---:|---:|
| Primary | 259 | 0 | 9 Qt module skips (run separately) |
| Qt | 69 | 0 | 0 |
| Final graph/UI focused rerun after repaint fix | 8 | 0 | 0 |
| Live MCP component checks | 17 | 0 | See limitations below |

New tests: 7 primary + 8 Qt. Focused checks are included in the full-suite totals,
not additional unique tests. Mixed-method factors are independently checked,
legacy single-method validation preserved, 2D/3D displacement and reactions
verified against linear superposition (rel 1e-8 / abs 1e-9), method envelopes
separate, IGZ round trip retains method settings. Geometry tests cover diagonal,
reversed, parallel, disconnected and coincident distinct nodes.

Qt checks cover length from edited coordinates, explicit full-member load,
preserved partial interval, missing member, modal status, graph components,
Current/Stale guards and no input mutations. Existing regression includes the
prior solver/engineering benchmarks and UI/theme checks.

Live checks: installed components imported/reloaded, 18 presets shown, method
switch retains choices, generator appends LRFD, length/full-member form,
modeless graph and x/L, actual context action, connected group of 2 members,
all 3D components, immediate repaint cleanup and original 21-member model
preservation. Screenshots were inspected; the old/new plot overlap found in
the first immediate capture was fixed before final captures.

Installed source hashes matched for 34 Python files. Installer was not
rebuilt. Live checks do not establish cold plugin loading. No draft was committed
into the user's original model. Failed assertions during development were fixed
and rerun; final Failed counts above refer to final evidence.

## Not Tested

Cold Restart, physical mouse interaction, live committed Save/Load/Undo/Redo,
clean Windows VM, rebuilt Setup. The live registry/dialog checks use reloaded
installed components; existing panel construction was not restarted.

## Known Limitations

Each connected member retains its own local i→j sign convention and plot;
no combined global diagram. Only shared analytical node IDs establish joints.
ASD/LRFD/Custom retain separate metadata/envelope groups. Shared action bindings
affect both methods and must be reviewed if edited. Capacity / Code Compliance
remains Not Available. Graph tessellation is display only; inspector/extrema
come from existing result polynomials and solver extrema, raw precision kept.

## Changed files

go_structural_analysis/thai_code.py, combination_ui.py, combination_tools.py,
ui.py, command_ui.py; new member_geometry.py and member_graph_ui.py.
New test_member_workflows.py, test_qt_member_workflows.py and report builder.
MEMBER_WORKFLOWS.md, docs/tasks/LC-002-member-workflows.md, docs/UI_BACKLOG.md,
CHANGELOG_v0.2.4.md, ROADMAP.md, UPDATE_v0.2.4.md, this report and evidence.

Evidence: artifacts/member-workflows/pytest.xml,
test-results-member-workflows.json, live-results.json and live PNG captures.
Backup: backups/member-workflows-before-20261011/ including live-model-before.igz.
