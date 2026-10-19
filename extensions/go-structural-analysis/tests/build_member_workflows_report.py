"""Aggregate actual stored QA evidence; this script does not run tests."""
import json,hashlib,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'artifacts/member-workflows'
def suite(name):
    root=ET.parse(OUT/name).getroot(); s=root.find('testsuite')
    tests=int(s.get('tests')); failed=int(s.get('failures'))+int(s.get('errors')); skipped=int(s.get('skipped'))
    return dict(passed=tests-failed-skipped,failed=failed,not_tested=skipped,source=name)
installed=Path.home()/'AppData/Roaming/ingetrazo/plugins/go_structural_analysis'
hashes={}
for file in (ROOT/'go_structural_analysis').glob('*.py'):
    assert (installed/file.name).read_bytes()==file.read_bytes(),file.name
    hashes[file.name]=hashlib.sha256(file.read_bytes()).hexdigest()
live=json.loads((OUT/'live-results.json').read_text(encoding='utf-8'))
report=dict(date='2026-10-11',version='0.2.4',task='LC-002',primary=suite('primary-pytest.xml'),qt=suite('qt-pytest.xml'),final_focused=suite('final-focused-pytest.xml'),new_tests=dict(primary=7,qt=8),live=live,live_scope='Reloaded installed components and context registry, original 21-member document preserved; not cold plugin-load evidence',installed_sha256=hashes,not_tested=['Cold Restart / final full plugin load','Physical mouse interaction','Live committed Save/Load/Undo/Redo','Clean Windows VM','Rebuilt Setup'],known_limitations=['Connected members shown as separate local-sign plots; no merged global diagram','Geometry connectivity uses analytical node IDs; coincident distinct nodes are not automatically joined','Capacity / Code Compliance Not Available'],resolved_failures=['Initial generator append test failed: other-method selection not retained; fixed and rerun','Live immediate repaint showed pending old plot widgets; hide before deleteLater fixed and rechecked'],backup='backups/member-workflows-before-20261011')
(OUT/'test-results-member-workflows.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
combined=ET.Element('testsuites')
for name in ('primary-pytest.xml','qt-pytest.xml'):
    for suite_node in ET.parse(OUT/name).getroot(): combined.append(suite_node)
ET.ElementTree(combined).write(OUT/'pytest.xml',encoding='utf-8',xml_declaration=True)
passed=sum(r['status']=='Passed' for r in live); failed=sum(r['status']=='Failed' for r in live)
text=f'''# TEST RESULTS — Member workflows v0.2.4 / 2026-10-11

Actual evidence for LC-002. Source/model backed up; no Program Files changes.

| Suite | Passed | Failed | Not Tested / skipped |
|---|---:|---:|---:|
| Primary | {report['primary']['passed']} | {report['primary']['failed']} | {report['primary']['not_tested']} Qt module skips (run separately) |
| Qt | {report['qt']['passed']} | {report['qt']['failed']} | {report['qt']['not_tested']} |
| Final graph/UI focused rerun after repaint fix | {report['final_focused']['passed']} | {report['final_focused']['failed']} | {report['final_focused']['not_tested']} |
| Live MCP component checks | {passed} | {failed} | See limitations below |

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

Installed source hashes matched for {len(hashes)} Python files. Installer was not
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
'''
(ROOT/'TEST_RESULTS_MEMBER_WORKFLOWS.md').write_text(text,encoding='utf-8')
print(json.dumps(dict(primary=report['primary'],qt=report['qt'],live_passed=passed,live_failed=failed,installed=len(hashes))))
