from pathlib import Path
for name in ['go_structural_analysis/__init__.py','install.ps1','packaging/build_installer.py','packaging/setup.iss','packaging/install-helper.ps1','packaging/test_installer.ps1','packaging/START-HERE.txt','packaging/README.md']:
 p=Path(name); p.write_text(p.read_text(encoding='utf-8').replace('0.2.3','0.2.4'),encoding='utf-8')
