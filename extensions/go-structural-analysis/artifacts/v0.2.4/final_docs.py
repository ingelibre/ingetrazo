from pathlib import Path
import json,shutil
root=Path('.')
shutil.copy2(root/'artifacts/v0.2/engineering-checks.json',root/'artifacts/v0.2.4/engineering-checks.json')
checks=json.loads((root/'artifacts/v0.2.4/engineering-checks.json').read_text())
baseline=json.loads((root/'test-results-v0.2.json').read_text())['engineering']['comparisons']
assert len(checks)==len(baseline)==3105
assert all(a['name']==b['name'] and abs(a['actual']-b['actual'])<=max(a['tolerance'],b['tolerance']) and a['reference']==b['reference'] and a['status']=='Passed' for a,b in zip(checks,baseline))
(root/'artifacts/v0.2.4/engineering-baseline-comparison.json').write_text(json.dumps(dict(status='Passed',comparisons=3105,baseline='test-results-v0.2.json',check='names/reference identical; actual difference within original tolerance'),indent=2),encoding='utf-8')
p=root/'README.md'; text=p.read_text(encoding='utf-8'); text=text.replace('# GO Structural Analysis v0.2.3','# GO Structural Analysis v0.2.4',1)
text=text.replace('This release extends the existing v0.1.3 source', '''Current release adds a [Thailand 2566 Code Pack](THAI_CODE_PACK_v0.2.4.md),
reviewed Combination Manager, engineering result safety and professional display
controls. Read [v0.2.4 update instructions](UPDATE_v0.2.4.md),
[actual QA](TEST_RESULTS_v0.2.4.md) and [changelog](CHANGELOG_v0.2.4.md).
Capacity, full code compliance and complete serviceability checks are Not Available.

The existing 2D/3D feature set described below is preserved. This release extends the existing v0.1.3 source''',1)
text=text.replace('matching **GO-Structural-Analysis-v0.2.3-Windows-x64-Setup.exe**','matching **GO-Structural-Analysis-v0.2.4-Windows-x64-Setup.exe**')
p.write_text(text,encoding='utf-8')
p=root/'ROADMAP.md'; old=p.read_text(encoding='utf-8'); p.write_text('''# v0.2.4 — implemented scope and evidence

| Phase | Implementation | Verification |
|---|---|---|
| 1 | Gazette-cited ASD/LRFD pack, directional binding, Custom clone/edit/disable, separate groups | Independent 18-formula factor golden tests + 2D/3D closed-form solver goldens; live manager |
| 2 | Input fingerprints, five states, stale/archived display/export, finite/equilibrium/failure guards | Safety tests, current report, live watermark/export/undo/save checks |
| 3 | Selected axes, signed fills, plane/highlight, collision placement/density, mm/tolerance/defaults | Qt placement/immutability tests; perspective/camera/member-pick live captures |
| 4 | Model tree, collapsible sections, width bounds, viewport controls, reviewed action/custom tables | Qt + installed-host UI screenshots/themes/hide/restart |
| 5 | Preserved baseline and added golden/safety/UI/installer validation | TEST_RESULTS_v0.2.4.md; manual hardware and clean VM remain Not Tested |

'''+old,encoding='utf-8')
print('3105 original engineering comparisons preserved; docs updated')
