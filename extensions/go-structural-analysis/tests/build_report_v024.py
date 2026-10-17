"""Aggregate executed evidence; baseline subsets are not counted twice."""
import hashlib,json,shutil
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).parents[1]; OUT=ROOT/'artifacts/v0.2.4'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def suite(path):
    rows=[]
    for t in ET.parse(path).iter('testcase'):
        status='Failed' if t.find('failure') is not None or t.find('error') is not None else 'Not Tested' if t.find('skipped') is not None else 'Passed'
        rows.append(dict(id=t.get('classname','')+'::'+t.get('name',''),status=status,seconds=float(t.get('time',0))))
    return dict(evidence=str(path.relative_to(ROOT)),counts={s:sum(r['status']==s for r in rows) for s in ('Passed','Failed','Not Tested')},tests=rows)
def main():
    primary=suite(OUT/'pytest.xml'); qt=suite(OUT/'qt-pytest.xml'); base=suite(OUT/'baseline-primary.xml'); baseqt=suite(OUT/'baseline-qt.xml')
    ids={r['id'] for r in primary['tests'] if r['status']=='Passed'}; qids={r['id'] for r in qt['tests'] if r['status']=='Passed'}
    old=json.loads((ROOT/'test-results-v0.2.json').read_text()); regression=old['regression_v013']['tests']
    engineering=json.loads((OUT/'engineering-checks.json').read_text()); baseline=old['engineering']['comparisons']
    same=len(engineering)==len(baseline)==3105 and all(a['name']==b['name'] and a['reference']==b['reference'] and abs(a['actual']-b['actual'])<=max(a['tolerance'],b['tolerance']) and a['status']=='Passed' for a,b in zip(engineering,baseline))
    live=json.loads((OUT/'live-results.json').read_text()); installed=Path.home()/'AppData/Roaming/ingetrazo/plugins/go_structural_analysis'
    install=[dict(file=p.name,status='Passed' if (installed/p.name).is_file() and digest(p)==digest(installed/p.name) else 'Failed',sha256=digest(p)) for p in sorted((ROOT/'go_structural_analysis').glob('*.py'))]
    backup=sorted((ROOT/'backups').glob('v024-before-*'))[-1]; files=[*ROOT.glob('*.md'),ROOT/'install.ps1']
    for folder in ('go_structural_analysis','tests','packaging','code_packs'):
        files += [p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.ps1','.iss','.md','.txt','.json') and p.name!='worker_config.json' and '__pycache__' not in p.parts]
    changed=[dict(file=p.relative_to(ROOT).as_posix(),change='Modified' if (backup/p.relative_to(ROOT)).exists() else 'Added',sha256=digest(p)) for p in sorted(set(files)) if not (backup/p.relative_to(ROOT)).exists() or digest(p)!=digest(backup/p.relative_to(ROOT))]
    installer_file=OUT/'installer-test-results.json'; installer=json.loads(installer_file.read_text(encoding='utf-8-sig')) if installer_file.is_file() else dict(status='Not Tested',reason='Awaiting final Setup build lifecycle test')
    if (OUT/'installer-examples.json').is_file():
        installer['solver_examples']=json.loads((OUT/'installer-examples.json').read_text(encoding='utf-8-sig'))
    report=dict(version='0.2.4',created=datetime.now().astimezone().isoformat(),solver='PyNiteFEA 3.2.0',primary=primary,qt=qt,
        preserved_baseline=dict(primary_passed=sum(r['id'] in ids for r in base['tests'] if r['status']=='Passed'),primary_total=146,qt_passed=sum(r['id'] in qids for r in baseqt['tests'] if r['status']=='Passed'),qt_total=9,regression_passed=sum(r['id'] in ids for r in regression),regression_total=90,engineering=dict(status='Passed' if same else 'Failed',comparisons=3105)),
        engineering=engineering,live=dict(counts={s:sum(r['status']==s for r in live.values()) for s in ('Passed','Failed','Not Tested')},checks=live),installed_sources=install,installer=installer,
        source_backup=str(backup.relative_to(ROOT)),model_backups=['backups/v024-open-model-before.igz','backups/v024-cold-model-before.igz'],changed_files=changed,
        not_tested=['Physical/manual mouse hardware interaction (live Qt events were tested instead)','Clean Windows VM without Python/development tools','Windows OS theme-change notification','Interactive installer wizard clicks','Cold restart after installing through Setup (source install cold restarts tested)'],
        known_limitations=['Linear elastic Euler-Bernoulli analysis only; no nonlinear/P-delta/buckling/section capacity checks.','Capacity, full code compliance and complete serviceability checks are Not Available.','No automatic seismic/pressure/temperature/creep/settlement action generator; reviewed equivalent-force input is required.','Direction alternatives are derived combinations, not statutory simultaneous-direction rules.','Envelope extrema and governing locations are in inspector/tables; viewport renders a selected case or combination.','Greedy label placement may suppress labels at high density; all raw values remain in result tables.','Legacy unmodified 2D self-weight convention is retained; Code Pack uses a single reviewed D case.'])
    (ROOT/'CHANGED_FILES_v0.2.4.md').write_text('# Files changed for v0.2.4\n\n'+'\n'.join('- '+r['change']+': `'+r['file']+'`' for r in changed)+'\n',encoding='utf-8')
    for row in changed:
        if row['file']=='CHANGED_FILES_v0.2.4.md':
            row['sha256']=digest(ROOT/row['file'])
    (ROOT/'test-results-v0.2.4.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); shutil.copy2(ROOT/'test-results-v0.2.4.json',OUT/'test-results-v0.2.4.json')
    print(json.dumps(dict(primary=primary['counts'],qt=qt['counts'],baseline=report['preserved_baseline'],live=report['live']['counts'],installed_files=len(install)),indent=2))
    return report
if __name__=='__main__': main()
