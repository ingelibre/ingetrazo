"""Aggregate only executed evidence, with explicit skipped and pending checks."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).parents[1]; OUT=ROOT/'artifacts/v0.2'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def suite(path):
    tests=[]
    for t in ET.parse(path).iter('testcase'):
        status='Failed' if t.find('failure') is not None or t.find('error') is not None else 'Not Tested' if t.find('skipped') is not None else 'Passed'
        tests.append(dict(id=t.get('classname','')+'::'+t.get('name',''),status=status,seconds=float(t.get('time',0))))
    return dict(evidence=str(path.relative_to(ROOT)),counts={s:sum(t['status']==s for t in tests) for s in ('Passed','Failed','Not Tested')},tests=tests)

def main():
    primary=suite(OUT/'pytest.xml'); qt=suite(OUT/'qt-pytest.xml'); before=suite(ROOT/'artifacts/regression-before-v02.xml')
    passed_ids={t['id'] for t in primary['tests'] if t['status']=='Passed'}
    regression=[dict(t,status='Passed' if t['id'] in passed_ids else 'Failed') for t in before['tests']]
    engineering=json.loads((OUT/'engineering-checks.json').read_text(encoding='utf-8'))
    live=json.loads((OUT/'live/live-results.json').read_text(encoding='utf-8'))
    installer_path=ROOT/'artifacts/installer/test-results.json'
    installer=json.loads(installer_path.read_text(encoding='utf-8-sig')) if installer_path.is_file() else {'status':'Not Tested'}
    if installer.get('test_root'):
        worker=Path(installer['test_root'])/'examples.json'
        if worker.is_file(): installer['worker_examples']=json.loads(worker.read_text(encoding='utf-8-sig'))
    (OUT/'installer-test-results.json').write_text(json.dumps(installer,indent=2),encoding='utf-8')
    installed=Path.home()/'AppData/Roaming/ingetrazo/plugins/go_structural_analysis'; installation=[]
    for p in sorted((ROOT/'go_structural_analysis').glob('*.py')):
        q=installed/p.name; installation.append(dict(file=p.name,source_sha256=digest(p),installed_sha256=digest(q) if q.is_file() else None,status='Passed' if q.is_file() and digest(p)==digest(q) else 'Failed'))
    backup=sorted((ROOT/'backups').glob('v02-before-*'))[-1]; changed=[]
    files=list(ROOT.glob('*.md'))+[ROOT/'install.ps1',ROOT/'requirements.txt',ROOT/'.gitignore',ROOT/'LICENSE']
    for folder in ('go_structural_analysis','tests','packaging'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.ps1','.iss','.md','.txt') and '__pycache__' not in p.parts)
    for p in sorted(set(files)):
        rel=p.relative_to(ROOT); old=backup/rel
        if p.is_file() and (not old.is_file() or digest(p)!=digest(old)): changed.append(dict(file=rel.as_posix(),change='Modified' if old.is_file() else 'Added',sha256=digest(p)))
    report=dict(extension='GO Structural Analysis',version='0.2.3',created=datetime.now().astimezone().isoformat(),solver='PyNiteFEA 3.2.0',primary_pytest=primary,offscreen_qt=qt,
        regression_v013=dict(passed=sum(t['status']=='Passed' for t in regression),total=len(regression),tests=regression),
        engineering=dict(counts={s:sum(t['status']==s for t in engineering) for s in ('Passed','Failed','Not Tested')},comparisons=engineering),
        live=dict(evidence='artifacts/v0.2/live/live-results.json',counts={s:sum(t.get('status')==s for t in live.values()) for s in ('Passed','Failed','Not Tested')},checks=live),installation=installation,installer=installer,
        backup=str(backup.relative_to(ROOT)),model_backups=['backups/v02-open-model-before.igz','backups/v02-cold-before.igz'],changed_files=changed,
        resolved_issues=json.loads((OUT/'resolved-issues.json').read_text(encoding='utf-8')),
        not_tested=[dict(id='physical_input_device',status='Not Tested',reason='Qt mouse events sent to actual live viewport; no physical mouse hardware.'),dict(id='windows_system_theme_notification',status='Not Tested',reason='Extension Light/Dark/System tested; Windows OS settings untouched.'),dict(id='clean_machine_install',status='Not Tested',reason='No clean Windows VM available.')],
        known_limitations=['Linear Euler-Bernoulli only; no P-delta/nonlinear/buckling/code capacity checks.','Viewport renders one case/combination; envelopes are in tables and point inspector.','Straight selected edges only; no automatic member centerline/intersection extraction.','Inactive truss-only rotations are constrained internally; nodal moments require real restraints or rotational springs.','Material presets are editable starting values; wood is not a full orthotropic model.'])
    (OUT/'test-results-v0.2.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (ROOT/'test-results-v0.2.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (OUT/'changed-files.json').write_text(json.dumps(changed,indent=2),encoding='utf-8')
    (ROOT/'CHANGED_FILES_v0.2.md').write_text('# Files changed for v0.2.3\n\n'+ '\n'.join('- '+p['change']+': `'+p['file']+'`' for p in changed)+'\n',encoding='utf-8')
    print(json.dumps(dict(primary=primary['counts'],qt=qt['counts'],regression=report['regression_v013']['passed'],engineering=report['engineering']['counts'],live=report['live']['counts'],installation_files=len(installation)),indent=2))

if __name__=='__main__': main()
