"""Collect recorded command UI evidence and user-plugin source hashes."""
import hashlib,json,os
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'artifacts/command-ui'
def suite(name):
    cases=ET.parse(OUT/name).findall('.//testcase')
    return dict(passed=sum(not any(c.find(t) is not None for t in ('failure','error','skipped')) for c in cases),failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases),skipped=sum(c.find('skipped') is not None for c in cases))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
installed=Path(os.environ['APPDATA'])/'ingetrazo/plugins/go_structural_analysis'
hashes={p.name:dict(source=sha(p),installed=sha(installed/p.name)) for p in (ROOT/'go_structural_analysis').glob('*.py')}
assert all(v['source']==v['installed'] for v in hashes.values())
report=dict(date='2026-10-11',version='0.2.4',scope='Command search / context menus',primary=suite('primary-pytest.xml'),qt=suite('qt-pytest.xml'),focused=suite('commands-pytest.xml'),live=json.loads((OUT/'live-results.json').read_text(encoding='utf-8')),live_scope='Temporary new components inside old loaded Panel; not cold plugin load',installed_files=len(hashes),sha256=hashes,not_tested=['Cold restart / full Panel load','Physical mouse/keyboard','New deletion Save/Load/Undo/Redo live','Exact preceding house preview assertion','Clean Windows VM','Rebuilt Setup executable'])
(OUT/'test-results-command-ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
root=ET.Element('testsuites')
for name in ('primary-pytest.xml','qt-pytest.xml'):
    for node in ET.parse(OUT/name).getroot(): root.append(node)
ET.ElementTree(root).write(OUT/'pytest.xml',encoding='utf-8',xml_declaration=True)
print(json.dumps({k:report[k] for k in ('primary','qt','focused','installed_files')}))
