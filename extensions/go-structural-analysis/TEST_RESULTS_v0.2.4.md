# GO Structural Analysis v0.2.4 — ผลทดสอบ

วันที่ 10 ตุลาคม 2026; Solver PyNiteFEA 3.2.0; Extension API v2; หน่วย kN–m และผลดิบ Full Precision

## Passed

- Primary Automated Tests: **231 Passed, 0 Failed** (`artifacts/v0.2.4/pytest.xml`)
- Qt Tests ใน environment แยก: **17 Passed, 0 Failed** (`artifacts/v0.2.4/qt-pytest.xml`)
- รักษา Baseline เดิม: Primary 146/146, Qt 9/9, 2D Regression 90/90 ทั้งหมดเป็นส่วนหนึ่งของชุดข้างต้น ไม่ได้นับซ้ำ
- Engineering Comparisons **3,105/3,105** ผ่าน และเทียบ Reference/ค่าที่คำนวณกับ Baseline ภายใน Tolerance เดิม
- Golden Tests ของ ASD 7 สูตรและ LRFD 11 สูตร ใช้ตารางอ้างอิงที่เขียนแยกจากตัวสร้างสูตร; Solver Tests 36 กรณี 2D/3D และอีก 2 กรณี Self-weight เปรียบเทียบสมการคานยื่นและสมดุลแรง
- ตรวจ Load Direction, Missing Input, Preset Protection, Custom Clone, Method Separation, Self-weight ซ้ำ และ Migration 2D → 3D ของ Combination
- ตรวจ Fingerprint, Current/Stale/Running/Failed/Not Analyzed, Non-finite/Equilibrium Guards, ปิด Export Current ระหว่าง Running/Failed/Stale และส่งออก Archived/Stale พร้อมข้อมูลต้นฉบับ
- Live QA บน IngeTrazo ที่ติดตั้งจริงผ่าน MCP: **70 Passed, 0 Failed** รวมรายการยืนยันภาพ; Plugin Load/Cold Restart, Background Analysis, Manager, Inspector/Tables/Envelope, Save/Load, Undo/Redo, 2D Compatibility, Unstable Detection, Theme, Panel Hide, Camera Perspective/Pan/Zoom, Orbit Drag และการเลือกสมาชิกผ่าน Qt Mouse Event
- ตรวจภาพ Model/Loads/Results/Inspector และ N/Vy/Vz/My/Mz/T/D/Deformed/Reaction รวมถึง Watermark เมื่อปิด Legend; ภาพและรายการตรวจจริงอยู่ใน `artifacts/v0.2.4/live-results.json`
- Source ที่ติดตั้งตรงกับ Source ที่ทดสอบ 23 ไฟล์ ตรวจ SHA-256 ใน JSON Report

Qt modules 2 modules ถูก Skip ใน Solver environment ซึ่งไม่มี Qt; ได้รันแยกใน Qt environment แล้ว 17 รายการ ไม่ใช่ฟีเจอร์ที่ยังไม่ได้ทดสอบ

Tolerance ทางวิศวกรรมอยู่ในแต่ละ Test/Comparison; สูตรมาตรฐานตรวจ Factor โดยตรง ส่วน Solver Golden ใช้ `pytest.approx` Relative Tolerance เริ่มต้น 1e-6 ร่วมกับ Absolute Tolerance 1e-8 สำหรับแรง/โมเมนต์ และ 1e-10 สำหรับการเคลื่อนตัว หน่วยตาม Solver. Residual/Benchmark อื่นระบุ Tolerance ของตนเองในหลักฐาน JSON/Tests โดยเก็บค่าเต็ม ไม่ใช้ค่าปัดบนหน้าจอในการยืนยันผล

## Code Pack และข้อจำกัด

ต้นฉบับ: [ราชกิจจานุเบกษา 6 กันยายน 2566 เล่ม 140 ตอน 54 ก](https://ratchakitcha.soc.go.th/documents/140A054N0000000000400.pdf), ข้อ 6–7 หน้าเอกสาร 7–8. เก็บ URL, Clause, Method, Version และ SHA-256 ของ PDF ใน Code Pack และไฟล์ PDF สำเนา

Derived Directional Combinations แยกจากสูตรกฎหมาย ไม่สมมติทิศทางพร้อมกัน; E/H/F/T ต้องมีข้อมูลที่ตรวจสอบแล้วจึงเปิดใช้ Preset ที่เกี่ยวข้องได้ โปรแกรมไม่ได้สร้างแรงแผ่นดินไหวตามกฎหมายครบถ้วน และ Capacity/Code Compliance/Serviceability แบบครบเกณฑ์แสดง **Not Available**

เป็น Linear Elastic Analysis; ไม่มี Nonlinear/P-delta/Buckling/Section Design. Envelope แสดง Governing Combination และตำแหน่งใน Inspector/Tables ส่วน Viewport แสดง Case/Combination ที่เลือก. Auto Label Placement อาจซ่อน Label เมื่อแน่น แต่ข้อมูลดิบยังอยู่ในตาราง

## Failed / Not Tested

ไม่มี Test Failure ค้างในชุดสุดท้าย. Import Qt แบบ eager ที่พบระหว่างพัฒนาถูกแก้เป็น Lazy Import และทดสอบซ้ำแล้ว; ช่อง Export ระหว่าง Running และ Migration ของ Code-managed Combination ถูกแก้พร้อมเพิ่ม Tests

**Not Tested:** Clean Windows VM, เมาส์ฮาร์ดแวร์/การโต้ตอบด้วยมือจริง, OS Theme-change Notification, การกด Wizard ตัวติดตั้งด้วยมือ และ Cold Restart หลังติดตั้งผ่าน Setup. การทดสอบ Mouse ข้างต้นใช้ Qt Event บน Viewport จริง ส่วน Cold Restart ใช้การติดตั้ง Source

Installer v0.2.4 ที่สร้างใหม่: **Lifecycle 14 Passed, 0 Failed** และ **Bundled Solver Examples 37 Passed, 0 Failed**. ตรวจ Silent Install/Reinstall/Backup/Running-host Protection/Uninstall และไม่ทำให้ Plugin หรือโมเดลผู้ใช้เดิมเสียหาย. หลักฐานและ SHA-256 อยู่ใน `INSTALLER_TEST_RESULTS_v0.2.4.md` และ `artifacts/v0.2.4/installer-*.json`. ไม่ใช้ผล v0.2.3 แทน; เอกสารที่ฝังใน Setup เป็นหลักฐาน ณ เวลาสร้าง ส่วนรายงานภายนอกและ Source ZIP รวมผล Lifecycle หลังสร้างแล้ว

## หลักฐาน

`test-results-v0.2.4.json`, `pytest.xml`, `artifacts/v0.2.4/qt-pytest.xml`, `engineering-checks.json`, `engineering-baseline-comparison.json`, `live-results.json`, ภาพ Before/After และ `CHANGED_FILES_v0.2.4.md`

สำรอง Source/Plugin และโมเดลก่อนแก้ไข; Live QA ใช้ Workspace/Model สำเนาแล้วคืน Document เดิม ไม่มีการแก้ IngeTrazo Core ภายใน Program Files
