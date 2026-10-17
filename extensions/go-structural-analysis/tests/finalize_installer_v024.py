"""Record executed Setup lifecycle evidence without inferring unexecuted checks."""
import json, shutil
from pathlib import Path

ROOT = Path(__file__).parents[1]
OUT = ROOT/'artifacts/v0.2.4'

def main():
    summary = json.loads((ROOT/'artifacts/installer/test-results.json').read_text(encoding='utf-8-sig'))
    assert 'v0.2.4-' in summary['setup_file'] and summary['failed'] == 0
    testroot = Path(summary['test_root'])
    examples = json.loads((testroot/'examples.json').read_text(encoding='utf-8-sig'))
    for p, name in ((ROOT/'artifacts/installer/test-results.json','installer-test-results.json'),
                    (testroot/'examples.json','installer-examples.json'),
                    (testroot/'checks.json','installer-checks.json'),
                    (testroot/'setup.log','installer-setup.log'),
                    (testroot/'blocked.log','installer-blocked.log')):
        if p.is_file():
            shutil.copy2(p, OUT/name)
    text = '# Installer QA — v0.2.4\n\n'
    text += f"วันที่ {summary['date']}; Setup SHA-256 `{summary['setup_sha256']}`\n\n"
    text += f"Lifecycle: {summary['passed']} Passed, {summary['failed']} Failed.\n\n"
    text += 'ทดสอบ Silent Install ในโฟลเดอร์แยกที่มีชื่อภาษาไทย, Runtime Relocation, Solver Healthcheck, ติดตั้งซ้ำ/สำรอง Plugin, ปิดกั้นการติดตั้งทับ Plugin ที่ Host กำลังใช้, Uninstall และรักษาไฟล์ผู้ใช้/โมเดล/Plugin จริง\n\n'
    text += 'ผล Solver ที่บรรจุใน Setup อยู่ใน `artifacts/v0.2.4/installer-examples.json` รวม 33 ตัวอย่างเดิม และ 4 Thai ASD/LRFD แบบ 2D/3D ตรวจ Version/Fingerprint/Envelope\n\n'
    text += '**Not Tested:** Clean Windows VM, Interactive Wizard, Cold Host Restart หลังติดตั้งผ่าน Setup, Code Signing/SmartScreen Reputation. Source Installation Cold Restart ตรวจแล้วแยกจาก Setup\n'
    (ROOT/'INSTALLER_TEST_RESULTS_v0.2.4.md').write_text(text, encoding='utf-8')
    print(json.dumps({'lifecycle_passed':summary['passed'],'examples':examples}, ensure_ascii=False)[:3000])

if __name__ == '__main__':
    main()
