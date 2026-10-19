"""Package actual recorded evidence; never turn an unexecuted check into Passed."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).parents[1]
OUT=ROOT/'artifacts'/'v0.1.3'
BACKUP=ROOT/'backups'/'before-v0.1.3-20261008-191932'

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    xml=ET.parse(OUT/'pytest.xml'); suite=xml.getroot().find('testsuite')
    tests=[]
    for t in xml.iter('testcase'):
        status='Failed' if t.find('failure') is not None or t.find('error') is not None else 'Not Tested' if t.find('skipped') is not None else 'Passed'
        tests.append({'id':t.get('classname')+'::'+t.get('name'),'status':status,'seconds':float(t.get('time','0'))})
    engineering=json.loads((OUT/'engineering-checks.json').read_text(encoding='utf-8'))
    live=json.loads((OUT/'live-tests.json').read_text(encoding='utf-8'))
    not_tested=[
        {'id':'cold_process_restart','status':'Not Tested','reason':'Preserved the original unsaved workspace; exercised the real discovery loader and live setup instead.'},
        {'id':'physical_mouse_device','status':'Not Tested','reason':'Clicked through a synthetic QMouseEvent delivered to the actual live viewport event path; no physical input device test.'},
        {'id':'os_theme_change_notification','status':'Not Tested','reason':'Applied Light/Dark/System through the host theme API; did not change the Windows OS theme.'},
    ]
    installation=[]
    installed=Path.home()/'AppData'/'Roaming'/'ingetrazo'/'plugins'/'go_structural_analysis'
    for source in sorted((ROOT/'go_structural_analysis').glob('*.py')):
        dest=installed/source.name
        installation.append({'file':source.name,'source_sha256':digest(source),'installed_sha256':digest(dest) if dest.is_file() else None,'status':'Passed' if dest.is_file() and digest(source)==digest(dest) else 'Failed'})
    report={'extension':'GO Structural Analysis','version':'0.1.3','pytest':{'timestamp':suite.get('timestamp'),'seconds':float(suite.get('time')),'counts':{s:sum(t['status']==s for t in tests) for s in ['Passed','Failed','Not Tested']},'tests':tests},'regression_original':{'count':19,'passed':sum(t['status']=='Passed' and 'tests.test_solver::' in t['id'] for t in tests)},'engineering':{'counts':{s:sum(t['status']==s for t in engineering) for s in ['Passed','Failed','Not Tested']},'comparisons':engineering},'live':live,'installation':installation,'not_tested':not_tested}
    audit_path=ROOT/'artifacts'/'audit-20261009'/'live-tests.json'
    if audit_path.is_file():
        audit=json.loads(audit_path.read_text(encoding='utf-8'))
        report['live_audit_20261009']={'evidence':str(audit_path.relative_to(ROOT)),
            'counts':{s:sum(v.get('status')==s for v in audit.values()) for s in ['Passed','Failed','Not Tested']},'checks':audit}
    example_path=ROOT/'artifacts'/'examples-v0.1.3'/'live-results.json'
    if example_path.is_file():
        examples=json.loads(example_path.read_text(encoding='utf-8'))
        report['live_examples']={'evidence':str(example_path.relative_to(ROOT)),
            'counts':{s:sum(v.get('status')==s for v in examples) for s in ['Passed','Failed','Not Tested']},'checks':examples}
    visual_path=ROOT/'artifacts'/'visual-update'/'live-results.json'
    if visual_path.is_file():
        visuals=json.loads(visual_path.read_text(encoding='utf-8'))
        report['visual_update']={'evidence':str(visual_path.relative_to(ROOT)),
            'counts':{s:sum(v.get('status')==s for v in visuals) for s in ['Passed','Failed','Not Tested']},'checks':visuals}
    material_path=ROOT/'artifacts'/'materials'/'live-results.json'
    if material_path.is_file():
        materials=json.loads(material_path.read_text(encoding='utf-8'))
        report['materials']={'counts':{s:sum(v.get('status')==s for v in materials) for s in ['Passed','Failed','Not Tested']},'checks':materials}
    (OUT/'test-results.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    paths=[*sorted((ROOT/'go_structural_analysis').glob('*.py')),*sorted((ROOT/'tests').glob('*.py')),ROOT/'install.ps1',ROOT/'README.md',ROOT/'TEST_RESULTS_v0.1.3.md',ROOT/'ROADMAP.md']
    paths.append(ROOT/'EXAMPLES.md')
    changes=[]
    for path in paths:
        old=BACKUP/path.relative_to(ROOT)
        if path.is_file() and (not old.is_file() or digest(old)!=digest(path)):
            changes.append({'file':path.relative_to(ROOT).as_posix(),'change':'Modified' if old.is_file() else 'Added','sha256':digest(path)})
    (OUT/'changed-files.json').write_text(json.dumps(changes,indent=2),encoding='utf-8')
    (ROOT/'CHANGED_FILES.md').write_text('# v0.1 → v0.1.3: changed files\n\n'+ '\n'.join(f"- {c['change']}: `{c['file']}`" for c in changes)+'\n\nGenerated evidence: `artifacts/v0.1.3/` (pytest XML, JSON, CSV, IGZ and PNG).\nOriginal `tests/test_solver.py`, `requirements.txt`, icons, theme and `TEST_RESULTS.md` were retained.\n',encoding='utf-8')
    print(json.dumps({'pytest':report['pytest']['counts'],'regression':report['regression_original'],'engineering':report['engineering']['counts'],'live_passed':sum(isinstance(v,dict) and v.get('status')=='Passed' for v in live.values()),'installation_files':len(installation),'installation_failed':sum(c['status']=='Failed' for c in installation),'changed_files':len(changes)},indent=2))

if __name__=='__main__': main()
