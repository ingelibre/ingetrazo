# ผลทดสอบตัวอย่างบ้านเพชรนารายณ์

วันที่ 10 ตุลาคม 2026; เพิ่มตัวอย่างใน Source/Plugin v0.2.4 เดิม, PyNiteFEA 3.2.0

- Primary: **234 Passed, 0 Failed**; รวม Tests บ้านใหม่ 3 รายการ. Qt modules 2 modules ถูก Skip ใน Solver environment และรันแยก
- Qt: **18 Passed, 0 Failed**; รวม Test รายการบ้านและการเปิด/ปิด Loads ใน Model View
- Live MCP: **18 Passed, 0 Failed** รวมภาพ, Cold Catalog/Load Button, Background Analysis, 10 Case/Combination Results, Save/Load, Stale/Undo และการคืน Document เดิม
- Source ที่ติดตั้งตรงกับ Source ที่ทดสอบ **25 ไฟล์** ตรวจ SHA-256
- ตรวจกราฟเชื่อมต่อทั้ง 146 Nodes/255 Members; Fixed Bases 12 จุด
- ตรวจน้ำหนักตัวเองคำนวณอิสระ ΣρAL + DL เพิ่ม เทียบ ΣReaction โดย Tolerance rel=1e-7, abs=1e-7
- เทียบ Node Displacement/Rotation/Reaction ทั้ง 1,752 Components กับ Direct Stiffness ที่ไม่ใช้ PyNite/โค้ด Solver หลัก: rel=1e-6, abs=1e-7 ในหน่วย Solver
- ตรวจ Linear Superposition และสมดุลแรง/โมเมนต์ทุก Case/Combination

หลักฐาน: `artifacts/house/regression-pytest.xml`, `qt-pytest.xml`, `live-results.json`, `test-results-house.json` และภาพ House-Model-Clean/Loads/Mz/N/Deformed/Reaction

โมเดลพกพา `examples/house/Phetnaray-RC-Steel-Roof.igz` ขนาด 165,815 bytes เก็บ Inputs เท่านั้น ให้ Run Analysis หลังเปิด. ตัวอย่างถูกเปิดทิ้งไว้ใน Workspace ที่แยกจาก Document เดิมเพื่อให้ทดลองต่อได้

ไม่มี Failed ค้างในชุดสุดท้าย. ระหว่างพัฒนาพบ Test Discovery ไปเก็บ Backups, QA Helper ส่ง keyword ซ้ำ และฟังก์ชันเก่าค้างในหน่วยความจำ; แก้และรันทดสอบซ้ำแล้ว. ตรวจทานแกนดัดของคานสี่เหลี่ยมและแก้ Model-mode Load Toggle พร้อม Qt Render Test

**Not Tested:** เมาส์ฮาร์ดแวร์จริง, Clean Windows VM, ตัวอย่างบ้านภายใน Setup v0.2.4 เดิม (ไม่ได้สร้าง Setup ใหม่), การตรวจออกแบบ/ข้อต่อ/ฐานรากจริง

หลังคา/หน้าตัดเหล็ก/โหลดเป็นสมมติฐานเพื่อการสอน; ไม่ใช่โมเดลบ้านจริงที่รับรองความปลอดภัย. ดูรายการสมมติฐานและวิธีเปิดใน `HOUSE_EXAMPLE.md`

ไฟล์เปลี่ยน: `house_example.py`, `house_reference.py`, `examples3d.py`, `ui.py`, `visualization3d.py`, `README.md`; เพิ่ม Tests/Live QA/Report Script, `HOUSE_EXAMPLE.md`, รายงานนี้, JSON/IGZ และภาพหลักฐาน. HTML ต้นฉบับและ IngeTrazo Core ไม่ถูกแก้
