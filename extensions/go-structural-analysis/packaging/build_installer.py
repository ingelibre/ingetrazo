"""Offline payload from the tested CPython distribution and pinned solver env."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime

ROOT=Path(__file__).parents[1]
RELEASE='0.2.4'
PRODUCTION=['contourpy','cycler','fonttools','kiwisolver','matplotlib','numpy','packaging','pillow','prettytable','pynitefea','pyparsing','python-dateutil','scipy','six','wcwidth']
MODULES=['contourpy','cycler','fontTools','kiwisolver','matplotlib','mpl_toolkits','numpy','numpy.libs','packaging','PIL','prettytable','Pynite','pyparsing','dateutil','scipy','scipy.libs','six.py','pylab.py','wcwidth']

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--site-packages',type=Path,required=True)
    parser.add_argument('--iscc',type=Path,default=Path('C:/Program Files (x86)/Inno Setup 6/ISCC.exe'))
    args=parser.parse_args()
    out=ROOT/'dist'; out.mkdir(exist_ok=True)
    stage=out/('installer-stage-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    stage.mkdir()
    ignore=shutil.ignore_patterns('__pycache__','*.pyc')
    shutil.copytree(args.runtime,stage/'runtime',ignore=ignore)
    site=stage/'runtime/Lib/site-packages'; site.mkdir(exist_ok=True)
    versions={}
    for module in MODULES:
        src=args.site_packages/module
        if src.is_dir(): shutil.copytree(src,site/module,ignore=ignore)
        else: shutil.copy2(src,site/module)
    for name in PRODUCTION:
        matches=list(args.site_packages.glob(name.replace('-','_')+'-*.dist-info'))
        if len(matches)!=1: raise RuntimeError('Missing or ambiguous dependency: '+name)
        shutil.copytree(matches[0],site/matches[0].name)
        versions[name]=matches[0].name.split('-',1)[1].removesuffix('.dist-info')
    (stage/'runtime/python312._pth').write_text('.\nLib\nDLLs\nLib/site-packages\nimport site\n',encoding='utf-8')
    shutil.copytree(ROOT/'go_structural_analysis',stage/'plugin',ignore=shutil.ignore_patterns('__pycache__','*.pyc','worker_config.json'))
    docs=stage/'docs'; docs.mkdir()
    for name in ['README.md','TEST_RESULTS_v0.1.3.md','TEST_RESULTS_v0.2.md','TEST_RESULTS_v0.2.4.md','THAI_CODE_PACK_v0.2.4.md','UPDATE_v0.2.4.md','CHANGELOG_v0.2.4.md','INSTALLER_TEST_RESULTS.md','EXAMPLES.md','EXAMPLES_v0.2.md']:
        shutil.copy2(ROOT/name,docs/name)
    for folder in ['v0.1.3','audit-20261009','examples-v0.1.3','visual-update','materials','v0.2','v0.2.4']:
        shutil.copytree(ROOT/'artifacts'/folder,docs/'artifacts'/folder,ignore=shutil.ignore_patterns('original-before.igz','Before-UI.png'))
    shutil.copytree(ROOT/'examples/v0.2',docs/'examples/v0.2')
    shutil.copytree(ROOT/'code_packs',docs/'code_packs')
    for file in (ROOT/'artifacts').glob('*'):
        if file.is_file(): shutil.copy2(file,docs/'artifacts'/file.name)
    guide=docs/'START-HERE.txt'; guide.write_text((ROOT/'packaging/START-HERE.txt').read_text(encoding='utf-8'),encoding='utf-8-sig')
    for name in ['install-helper.ps1','healthcheck.py']:
        shutil.copy2(ROOT/'packaging'/name,stage/name)
    # Windows PowerShell 5.1 needs a BOM for non-ASCII text.
    helper=stage/'install-helper.ps1'; helper.write_text(helper.read_text(encoding='utf-8'),encoding='utf-8-sig')
    licence=ROOT/'LICENSE'
    if not licence.is_file(): licence=ROOT.parents[1]/'LICENSE'
    shutil.copy2(licence,stage/'LICENSE.txt')
    with zipfile.ZipFile(stage/('source-v'+RELEASE+'.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        files=[*ROOT.glob('*.md'),ROOT/'install.ps1',ROOT/'requirements.txt',licence]
        for folder in ['go_structural_analysis','tests','packaging']:
            files += [p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ['.py','.ps1','.iss','.txt']]
        for file in files:
            archive.write(file,'LICENSE' if file.name=='LICENSE' else file.relative_to(ROOT).as_posix())
    manifest={'version':RELEASE,'runtime_origin':'astral-sh/python-build-standalone','runtime_build':(args.runtime/'BUILD').read_text().strip(),'python':'3.12.14','solver_dependencies':versions,
              'files':{p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(stage.rglob('*')) if p.is_file()}}
    (stage/'build-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    subprocess.run([str(stage/'runtime/python.exe'),'-I','-V'],check=True)
    subprocess.run([str(args.iscc),'/Q','/DStageDir='+str(stage),'/DOutputDir='+str(out),str(ROOT/'packaging/setup.iss')],check=True)
    exe=out/('GO-Structural-Analysis-v'+RELEASE+'-Windows-x64-Setup.exe')
    exe.with_suffix('.exe.sha256').write_text(hashlib.sha256(exe.read_bytes()).hexdigest()+'  '+exe.name+'\n',encoding='utf-8')
    shutil.copy2(stage/'build-manifest.json',out/'installer-build-manifest.json')
    print(f'Installer: {exe} ({exe.stat().st_size/1024/1024:.1f} MiB)')

if __name__=='__main__': main()
