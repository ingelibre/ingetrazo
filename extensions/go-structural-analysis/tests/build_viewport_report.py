"""Summarize executed tests/profiles; do not invent successful QA evidence."""
import hashlib,json
from pathlib import Path
from datetime import datetime,timezone
import xml.etree.ElementTree as ET

ROOT=Path(__file__).parents[1]; OUT=ROOT/'artifacts/viewport-performance'
def counts(path):
    cases=list(ET.parse(path).iter('testcase'))
    return {kind:sum(predicate(t) for t in cases) for kind,predicate in {
        'passed':lambda t:all(t.find(k) is None for k in ('failure','error','skipped')),
        'failed':lambda t:t.find('failure') is not None or t.find('error') is not None,
        'skipped':lambda t:t.find('skipped') is not None}.items()}
def main():
    installed=Path.home()/'AppData/Roaming/ingetrazo/plugins/go_structural_analysis'
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    sources=[dict(file=p.name,sha256=sha(p),installed_matches=(installed/p.name).is_file() and sha(p)==sha(installed/p.name)) for p in sorted((ROOT/'go_structural_analysis').glob('*.py'))]
    before=json.loads((OUT/'before.json').read_text()); after=json.loads((OUT/'after-final.json').read_text()); live=json.loads((OUT/'live-results.json').read_text())
    comparisons=[dict(mode='Loads' if a['tab']==1 else a['diagram'],before_ms=b['mean_ms'],after_ms=a['mean_ms'],reduction_percent=100*(1-a['mean_ms']/b['mean_ms']),before_projection_calls=b['projection_calls'],after_projection_calls=a['projection_calls']) for b,a in zip(before,after)]
    report=dict(created_utc=datetime.now(timezone.utc).isoformat(),version='0.2.4',solver='PyNiteFEA 3.2.0',primary=counts(OUT/'primary-pytest.xml'),qt=counts(OUT/'qt-pytest.xml'),live=live,performance=comparisons,installed_sources=sources,
        performance_method='Live installed host world_to_pixels API plus QPainter on a viewport-sized QImage; 255-member house, DL, labels OFF, changing yaw; warm frames. Before 4 frames, final after 16. CPU overlay repaint time, not monitor FPS or complete GUI event latency.',
        limitations=['All-member moment diagrams still require about 75 ms per measured frame; no 60 FPS guarantee. Dense labels add work; switch Labels off / Sparse when navigating large models.','Geometry/restraint precheck does not prove internal stability. Solver performs active stiffness checks. Buckling, capacity and full code compliance are not available.','Crossings may be intentional; do not merge automatically. Tolerance is editable in metres.','Installed MCP high-resolution FBO screenshot omits the child overlay; reviewed live window.grab captures instead.'],
        not_tested=['Physical mouse / manual orbit hardware','Clean Windows VM','Installer rebuild / installer payload with this patch'],
        resolved=['Native-callback detection hid the compatibility canvas; corrected to a single canvas renderer and repeated cold launch/window visual inspection.','An intermediate label-grid profile contained inconsistent diagram point counts; excluded from comparisons. Final profiles assert requested diagram and Current state.'])
    assert report['primary']['failed']==report['qt']['failed']==0
    assert all(row['status']=='Passed' for row in live.values()) and all(row['installed_matches'] for row in sources)
    (OUT/'test-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    rows='\n'.join(f"| {r['mode']} | {r['before_ms']:.1f} | {r['after_ms']:.1f} | {r['reduction_percent']:.1f}% |" for r in comparisons)
    md=f'''# Viewport performance and model diagnostics — v0.2.4 patch

10 October 2026. Existing source and installed user plugin were backed up in `backups/viewport-diagnostics-before-20261010`. No IngeTrazo core / Program Files changes.

## Executed results

- Primary automated: **{report['primary']['passed']} Passed, {report['primary']['failed']} Failed**. {report['primary']['skipped']} Qt modules skipped in solver environment; Qt runs separately.
- Qt automated: **{report['qt']['passed']} Passed, {report['qt']['failed']} Failed**.
- Installed Windows MCP: **{len(live)} Passed, 0 Failed**. Cold plugin load, visible canvas, house geometry, near-duplicate nodes/overlapping members, issue selection, precheck gate, unstable solver rejection, stable analysis via dialog, equilibrium, Save/Load, Undo/Redo and 2D overlay.
- House timing uses a restored previously analyzed QA IGZ. Fresh solver execution in this QA used cantilever/unstable examples; full house engineering/reference comparisons ran in primary tests.
- Source/installed SHA-256 comparison: {len(sources)} Python files match.

## Actual measured repaint time

| View | Before [ms] | After [ms] | Reduction |
|---|---:|---:|---:|
{rows}

{report['performance_method']}

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
'''
    (ROOT/'TEST_RESULTS_VIEWPORT.md').write_text(md,encoding='utf-8')
    print(json.dumps(dict(primary=report['primary'],qt=report['qt'],live=len(live),sources=len(sources),performance=comparisons),indent=2))
if __name__=='__main__': main()
