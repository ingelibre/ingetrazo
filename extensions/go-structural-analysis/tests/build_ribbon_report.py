"""Aggregate executed ribbon checks and installed source hashes."""
import hashlib,json,os
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'artifacts/ribbon'
def suite(name):
    cases=ET.parse(OUT/name).findall('.//testcase')
    return dict(passed=sum(not any(c.find(t) is not None for t in ('failure','error','skipped')) for c in cases),failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases),skipped=sum(c.find('skipped') is not None for c in cases))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
installed=Path(os.environ['APPDATA'])/'ingetrazo/plugins/go_structural_analysis'
hashes={p.name:dict(source=sha(p),installed=sha(installed/p.name)) for p in (ROOT/'go_structural_analysis').glob('*.py')}
assert all(v['source']==v['installed'] for v in hashes.values())
report=dict(date='2026-10-11',version='0.2.4',scope='Compact engineering ribbon',primary=suite('primary-pytest.xml'),qt=suite('qt-pytest.xml'),installed_files=len(hashes),sha256=hashes,live_status='Not Tested',live_reason='MCP bridge connection refused',screenshots='Offscreen Qt adapter; not installed-host captures',not_tested=['Live host painting and mouse input','Cold restart','Clean Windows VM','Rebuilt Setup executable'])
(OUT/'test-results-ribbon.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
root=ET.Element('testsuites')
for name in ('primary-pytest.xml','qt-pytest.xml'):
    for node in ET.parse(OUT/name).getroot(): root.append(node)
ET.ElementTree(root).write(OUT/'pytest.xml',encoding='utf-8',xml_declaration=True)
print(json.dumps({k:report[k] for k in ('primary','qt','installed_files','live_status')}))
