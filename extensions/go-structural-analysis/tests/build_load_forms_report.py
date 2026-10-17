"""Collect actual load-form evidence without changing historical release reports."""
import hashlib,json,os
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/load-forms'
def suite(name):
    tree=ET.parse(OUT/name)
    cases=tree.findall('.//testcase')
    return dict(tests=len(cases),passed=sum(not any(c.find(tag) is not None for tag in ('failure','error','skipped')) for c in cases),failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases),skipped=sum(c.find('skipped') is not None for c in cases))
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
source=ROOT/'go_structural_analysis'
installed=Path(os.environ['APPDATA'])/'ingetrazo/plugins/go_structural_analysis'
hashes={p.name:dict(source=digest(p),installed=digest(installed/p.name) if (installed/p.name).is_file() else None) for p in source.glob('*.py')}
live=json.loads((OUT/'live-results.json').read_text(encoding='utf-8'))
data=dict(date='2026-10-11',version='0.2.4',scope='Load Case / Combination forms',automated={'primary':suite('primary-pytest.xml'),'qt':suite('qt-pytest.xml'),'focused':suite('focused-pytest.xml')},live=live,installation={'python_files':len(hashes),'all_match':all(v['source']==v['installed'] for v in hashes.values()),'sha256':hashes},known_issues=['Installed-host numeric_formula_preview assertion failed; subsequent modal operation timed out. The same shown house dialog scenario passes offscreen Qt, but the live failure remains unresolved.','MCP then returned connection refused; physical computer-use native pipe also unavailable.'],not_tested=['Final installed-source cold restart after small final edits','Completed live combination Save/Load and Undo/Redo round trip','Physical mouse/keyboard input','Clean Windows VM','Rebuilt/distributed Setup executable'])
(OUT/'test-results-load-forms.json').write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
combined=ET.Element('testsuites')
for name in ('primary-pytest.xml','qt-pytest.xml'):
    for item in ET.parse(OUT/name).getroot(): combined.append(item)
ET.ElementTree(combined).write(OUT/'pytest.xml',encoding='utf-8',xml_declaration=True)
assert data['installation']['all_match'], 'Installed files differ'
print(json.dumps({k:data[k] for k in ('automated','installation')},ensure_ascii=False)[:300])
