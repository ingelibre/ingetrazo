"""Collect LC-001 test evidence, installed hashes and local source metadata."""
import hashlib,json,os
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'artifacts/combination-overview'
def suite(name):
    cases=ET.parse(OUT/name).findall('.//testcase')
    return dict(passed=sum(not any(c.find(t) is not None for t in ('failure','error','skipped')) for c in cases),failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases),skipped=sum(c.find('skipped') is not None for c in cases))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
installed=Path(os.environ['APPDATA'])/'ingetrazo/plugins/go_structural_analysis'
hashes={p.name:dict(source=sha(p),installed=sha(installed/p.name)) for p in (ROOT/'go_structural_analysis').glob('*.py')}
assert all(v['source']==v['installed'] for v in hashes.values())
metadata=json.loads((ROOT/'docs/reference/prota2022/source.json').read_text(encoding='utf-8'))
assert sha(ROOT/'docs/reference/prota2022'/metadata['local_file'])==metadata['sha256']
qt=ET.parse(OUT/'qt-pytest.xml'); new_cases=[c for c in qt.findall('.//testcase') if c.get('classname','').endswith('test_qt_combination_overview')]
report=dict(date='2026-10-11',task='LC-001',version='0.2.4',primary=suite('primary-pytest.xml'),qt=suite('qt-pytest.xml'),new_qt_tests=len(new_cases),live=json.loads((OUT/'live-results.json').read_text(encoding='utf-8')),live_scope='Reloaded installed dialog components; no live draft committed, not cold plugin-load evidence',installed_files=len(hashes),sha256=hashes,reference=metadata,reference_hash_verified=True,not_tested=['Cold Restart / final plugin load','Physical interaction','Live draft commit Save/Load/Undo/Redo','Clean Windows VM','Rebuilt Setup'])
(OUT/'test-results-combination-overview.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
root=ET.Element('testsuites')
for name in ('primary-pytest.xml','qt-pytest.xml'):
    for node in ET.parse(OUT/name).getroot(): root.append(node)
ET.ElementTree(root).write(OUT/'pytest.xml',encoding='utf-8',xml_declaration=True)
print(json.dumps({k:report[k] for k in ('primary','qt','new_qt_tests','installed_files','reference_hash_verified')}))
