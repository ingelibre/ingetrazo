"""Create a portable source/install/evidence bundle from this existing project."""
import hashlib
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).parents[1]

def main():
    files=[*sorted((ROOT/'go_structural_analysis').glob('*.py')),*sorted((ROOT/'tests').glob('*.py'))]
    files += [ROOT/name for name in ['README.md','TEST_RESULTS.md','TEST_RESULTS_v0.1.3.md','ROADMAP.md','CHANGED_FILES.md','install.ps1','requirements.txt','.gitignore']]
    files += [p for p in sorted((ROOT/'artifacts'/'v0.1.3').rglob('*')) if p.is_file()]
    files += [p for p in sorted((ROOT/'artifacts'/'audit-20261009').rglob('*')) if p.is_file()]
    files += [p for p in sorted((ROOT/'artifacts'/'examples-v0.1.3').rglob('*')) if p.is_file()]
    files.append(ROOT/'EXAMPLES.md')
    files += [p for p in sorted((ROOT/'artifacts'/'visual-update').rglob('*')) if p.is_file()]
    files += [p for p in sorted((ROOT/'artifacts'/'materials').rglob('*')) if p.is_file()]
    files.append(ROOT/'artifacts'/'regression-before-v0.1.3.xml')
    output=ROOT/'dist'/'GO-Structural-Analysis-v0.1.3.zip'; output.parent.mkdir(exist_ok=True)
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file,'GO-Structural-Analysis-v0.1.3/'+file.relative_to(ROOT).as_posix())
    with ZipFile(output) as archive:
        bad=archive.testzip()
        if bad: raise RuntimeError('Corrupt archive entry: '+bad)
    checksum=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(checksum+'  '+output.name+'\n',encoding='utf-8')
    print(f'{output}\n{len(files)} files; {output.stat().st_size} bytes; SHA256 {checksum}')

if __name__=='__main__': main()
