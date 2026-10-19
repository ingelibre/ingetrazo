"""Record current house-demo evidence and package the editable example/source."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).parents[1]; OUT=ROOT/'artifacts/house'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def counts(path):
    tests=list(ET.parse(path).iter('testcase'))
    return dict(passed=sum(t.find('failure') is None and t.find('error') is None and t.find('skipped') is None for t in tests),
                failed=sum(t.find('failure') is not None or t.find('error') is not None for t in tests),
                skipped=sum(t.find('skipped') is not None for t in tests))
def main():
    live=json.loads((OUT/'live-results.json').read_text())
    installed=Path.home()/'AppData/Roaming/ingetrazo/plugins/go_structural_analysis'
    sources=[dict(file=p.name,sha256=sha(p),status='Passed' if (installed/p.name).exists() and sha(p)==sha(installed/p.name) else 'Failed') for p in sorted((ROOT/'go_structural_analysis').glob('*.py'))]
    report=dict(example='House Phetnaray / บ้านเพชรนารายณ์',extension_version='0.2.4',solver='PyNiteFEA 3.2.0',
        primary=counts(OUT/'regression-pytest.xml'),qt=counts(OUT/'qt-pytest.xml'),
        live=dict(passed=sum(c['status']=='Passed' for c in live.values()),failed=sum(c['status']=='Failed' for c in live.values()),checks=live),
        installed_sources=sources,model=dict(nodes=146,members=255,base_supports=12,cases=7,combinations=3,file='examples/house/Phetnaray-RC-Steel-Roof.igz',bytes=(ROOT/'examples/house/Phetnaray-RC-Steel-Roof.igz').stat().st_size),
        verified=['Connected topology','Fresh editable catalog example','Single-case self-weight reaction balance','All case/combination equilibrium','Linear superposition','Independent space-frame nodal solution (1752 components)','Installed selector button/cold catalog','Background worker','IGZ roundtrip','Stale on material edit','Undo restores Current','Original document restored before preview workspace'],
        tolerances=dict(reference_relative=1e-6,reference_absolute=1e-7,selfweight_relative=1e-7,selfweight_absolute=1e-7),
        not_tested=['Physical/manual mouse hardware','House example in the pre-existing v0.2.4 Setup payload (not rebuilt)','Clean Windows VM','Actual design/connection/soil/diaphragm verification'],
        resolved_issues=['Initial pytest root discovery included backups; corrected to pytest tests.','Live QA helper duplicate status keyword corrected; rerun finished.','Live in-memory catalog function required refresh before cold-load verification.','Review corrected rectangular strong-axis Iz; full primary tests rerun.','Model-mode load toggle previously forced visible; corrected and Qt render verified.'],
        limitations=['Teaching-only centerline adaptation; roof layout/sections and loads are assumed.','No section capacity or full legal code compliance.','Equivalent nodal floor/roof loading; no floor diaphragm, wall/stair stiffness or foundation flexibility.','Portable IGZ contains inputs only; run analysis after opening.'])
    assert report['primary']['failed']==report['qt']['failed']==report['live']['failed']==0
    assert all(s['status']=='Passed' for s in sources)
    (OUT/'test-results-house.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    md=f'''# ผลทดสอบตัวอย่างบ้านเพชรนารายณ์

วันที่ 10 ตุลาคม 2026; เพิ่มตัวอย่างใน Source/Plugin v0.2.4 เดิม, PyNiteFEA 3.2.0

- Primary: **{report['primary']['passed']} Passed, 0 Failed**; รวม Tests บ้านใหม่ 3 รายการ. Qt modules 2 modules ถูก Skip ใน Solver environment และรันแยก
- Qt: **{report['qt']['passed']} Passed, 0 Failed**; รวม Test รายการบ้านและการเปิด/ปิด Loads ใน Model View
- Live MCP: **{report['live']['passed']} Passed, 0 Failed** รวมภาพ, Cold Catalog/Load Button, Background Analysis, 10 Case/Combination Results, Save/Load, Stale/Undo และการคืน Document เดิม
- Source ที่ติดตั้งตรงกับ Source ที่ทดสอบ **{len(sources)} ไฟล์** ตรวจ SHA-256
- ตรวจกราฟเชื่อมต่อทั้ง 146 Nodes/255 Members; Fixed Bases 12 จุด
- ตรวจน้ำหนักตัวเองคำนวณอิสระ ΣρAL + DL เพิ่ม เทียบ ΣReaction โดย Tolerance rel=1e-7, abs=1e-7
- เทียบ Node Displacement/Rotation/Reaction ทั้ง 1,752 Components กับ Direct Stiffness ที่ไม่ใช้ PyNite/โค้ด Solver หลัก: rel=1e-6, abs=1e-7 ในหน่วย Solver
- ตรวจ Linear Superposition และสมดุลแรง/โมเมนต์ทุก Case/Combination

หลักฐาน: `artifacts/house/regression-pytest.xml`, `qt-pytest.xml`, `live-results.json`, `test-results-house.json` และภาพ House-Model-Clean/Loads/Mz/N/Deformed/Reaction

โมเดลพกพา `{report['model']['file']}` ขนาด {report['model']['bytes']:,} bytes เก็บ Inputs เท่านั้น ให้ Run Analysis หลังเปิด. ตัวอย่างถูกเปิดทิ้งไว้ใน Workspace ที่แยกจาก Document เดิมเพื่อให้ทดลองต่อได้

ไม่มี Failed ค้างในชุดสุดท้าย. ระหว่างพัฒนาพบ Test Discovery ไปเก็บ Backups, QA Helper ส่ง keyword ซ้ำ และฟังก์ชันเก่าค้างในหน่วยความจำ; แก้และรันทดสอบซ้ำแล้ว. ตรวจทานแกนดัดของคานสี่เหลี่ยมและแก้ Model-mode Load Toggle พร้อม Qt Render Test

**Not Tested:** เมาส์ฮาร์ดแวร์จริง, Clean Windows VM, ตัวอย่างบ้านภายใน Setup v0.2.4 เดิม (ไม่ได้สร้าง Setup ใหม่), การตรวจออกแบบ/ข้อต่อ/ฐานรากจริง

หลังคา/หน้าตัดเหล็ก/โหลดเป็นสมมติฐานเพื่อการสอน; ไม่ใช่โมเดลบ้านจริงที่รับรองความปลอดภัย. ดูรายการสมมติฐานและวิธีเปิดใน `HOUSE_EXAMPLE.md`

ไฟล์เปลี่ยน: `house_example.py`, `house_reference.py`, `examples3d.py`, `ui.py`, `visualization3d.py`, `README.md`; เพิ่ม Tests/Live QA/Report Script, `HOUSE_EXAMPLE.md`, รายงานนี้, JSON/IGZ และภาพหลักฐาน. HTML ต้นฉบับและ IngeTrazo Core ไม่ถูกแก้
'''
    (ROOT/'TEST_RESULTS_HOUSE.md').write_text(md,encoding='utf-8')
    target=ROOT/'dist/GO-Structural-Analysis-House-Phetnaray-Example.zip'
    files=[ROOT/'HOUSE_EXAMPLE.md',ROOT/'TEST_RESULTS_HOUSE.md',ROOT/'install.ps1',ROOT/'requirements.txt',ROOT/'LICENSE']
    for folder in ('go_structural_analysis','tests','examples/house','artifacts/house'):
        files += [p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc' and p.name!='worker_config.json']
    with ZipFile(target,'w',ZIP_DEFLATED) as z:
        for p in sorted(set(files)): z.write(p,'GO-Structural-Analysis-House-Phetnaray/'+p.relative_to(ROOT).as_posix())
    with ZipFile(target) as z: assert z.testzip() is None
    target.with_suffix('.zip.sha256').write_text(sha(target)+'  '+target.name+'\n',encoding='utf-8')
    print(json.dumps(dict(primary=report['primary'],qt=report['qt'],live=report['live']['passed'],installed=len(sources),package_bytes=target.stat().st_size)))
if __name__=='__main__': main()
