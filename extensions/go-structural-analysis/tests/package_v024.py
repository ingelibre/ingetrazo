"""Package tested source/evidence without private models or local environments."""
import hashlib
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).parents[1]

def main():
    files = [*ROOT.glob('*.md'), ROOT/'LICENSE', ROOT/'install.ps1',
             ROOT/'requirements.txt', ROOT/'test-results-v0.2.4.json', ROOT/'pytest.xml']
    for folder in ('go_structural_analysis', 'tests', 'packaging', 'code_packs',
                   'examples/v0.2', 'artifacts/v0.2.4'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix != '.pyc'
                     and p.name not in ('worker_config.json', 'original-before.igz',
                                        'Before-UI.png', 'SHOULD-NOT-EXPORT-RUNNING.json'))
    target = ROOT/'dist/GO-Structural-Analysis-v0.2.4.zip'
    with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
        for p in sorted(set(files)):
            archive.write(p, 'GO-Structural-Analysis-v0.2.4/'+p.relative_to(ROOT).as_posix())
    with ZipFile(target) as archive:
        if archive.testzip():
            raise RuntimeError('Archive validation failed')
    target.with_suffix('.zip.sha256').write_text(
        hashlib.sha256(target.read_bytes()).hexdigest()+'  '+target.name+'\n', encoding='utf-8')
    print(str(target)+'; '+str(len(set(files)))+' files')

if __name__ == '__main__':
    main()
