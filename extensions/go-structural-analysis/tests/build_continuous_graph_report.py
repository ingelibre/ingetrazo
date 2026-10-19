"""Aggregate recorded QA evidence, without rerunning tests."""
import json,hashlib,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'artifacts/continuous-graphs'
def suite(name):
    s=ET.parse(OUT/name).getroot().find('testsuite')
    failed=int(s.get('failures'))+int(s.get('errors')); skipped=int(s.get('skipped'))
    return dict(passed=int(s.get('tests'))-failed-skipped,failed=failed,not_tested=skipped,source=name)
installed=Path.home()/'AppData/Roaming/ingetrazo/plugins/go_structural_analysis'; hashes={}
for f in (ROOT/'go_structural_analysis').glob('*.py'):
    assert f.read_bytes()==(installed/f.name).read_bytes(),f.name
    hashes[f.name]=hashlib.sha256(f.read_bytes()).hexdigest()
live=json.loads((OUT/'live-results.json').read_text(encoding='utf-8'))
report=dict(task='CG-001',date='2026-10-11',version='0.2.4',primary=suite('primary-pytest.xml'),qt=suite('qt-pytest.xml'),focused=suite('focused-pytest.xml'),qt_focused=suite('qt-focused-pytest.xml'),new_tests=dict(primary=8,qt=3),live=live,installed_sha256=hashes,live_scope='Reloaded installed graph components; original 21-member model unchanged, M2+M10 continuous plot',not_tested=['Cold Restart / full plugin reload','Physical mouse interaction (Qt QTest is simulated)','Clean Windows VM','Live committed Save/Load/Undo/Redo','Rebuilt Setup'],known_limitations=['Only connected collinear nonoverlapping chains; geometry branches/overlaps require Check Model','Common frame of context-selected member; 3D components are displayed in that reviewed frame','Physical jumps at joints/point actions remain visible, no artificial smoothing','Capacity / Code Compliance Not Available'],development_notes=['Initial Qt fixture expected 6 m for a 4 m cantilever; corrected fixture expectation','Scroll minimum width propagation fixed and rerun','Premature live capture before Qt event loop reported missing graph; all seven components rechecked/captured after event loop; original evidence retained as live-before-event-loop.json'])
(OUT/'test-results-continuous-graphs.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
combined=ET.Element('testsuites')
for name in ('primary-pytest.xml','qt-pytest.xml'):
    for node in ET.parse(OUT/name).getroot(): combined.append(node)
ET.ElementTree(combined).write(OUT/'pytest.xml',encoding='utf-8',xml_declaration=True)
passed=sum(r['status']=='Passed' for r in live); failed=sum(r['status']=='Failed' for r in live)
text=f'''# TEST RESULTS — Continuous beam diagrams / v0.2.4

CG-001, 11 October 2026. Existing source and original live model backed up.

| Final suite | Passed | Failed | Not Tested / skipped |
|---|---:|---:|---:|
| Primary | {report['primary']['passed']} | {report['primary']['failed']} | {report['primary']['not_tested']} Qt module skips, run separately |
| Qt | {report['qt']['passed']} | {report['qt']['failed']} | {report['qt']['not_tested']} |
| New primary focused | {report['focused']['passed']} | {report['focused']['failed']} | {report['focused']['not_tested']} |
| New Qt focused | {report['qt_focused']['passed']} | {report['qt_focused']['failed']} | {report['qt_focused']['not_tested']} |
| Live component checks | {passed} | {failed} | See below |

Focused tests are included in full-suite totals. New tests: 8 primary + 3 Qt.
Installed source matched {len(hashes)} Python files. Solver remains PyNiteFEA 3.2.0.
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
'''
(ROOT/'TEST_RESULTS_CONTINUOUS_GRAPHS.md').write_text(text,encoding='utf-8')
print(json.dumps(dict(primary=report['primary'],qt=report['qt'],live_passed=passed,live_failed=failed,installed_files=len(hashes))))
