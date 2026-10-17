# Installer QA — v0.2.4

วันที่ 2026-10-10T09:56:05.5229765+07:00; Setup SHA-256 `D954C9C48AF870052DCB5C15D2AE851EFC827D501A2D274CB042BF30B9870952`

Lifecycle: 14 Passed, 0 Failed.

ทดสอบ Silent Install ในโฟลเดอร์แยกที่มีชื่อภาษาไทย, Runtime Relocation, Solver Healthcheck, ติดตั้งซ้ำ/สำรอง Plugin, ปิดกั้นการติดตั้งทับ Plugin ที่ Host กำลังใช้, Uninstall และรักษาไฟล์ผู้ใช้/โมเดล/Plugin จริง

ผล Solver ที่บรรจุใน Setup อยู่ใน `artifacts/v0.2.4/installer-examples.json` รวม 33 ตัวอย่างเดิม และ 4 Thai ASD/LRFD แบบ 2D/3D ตรวจ Version/Fingerprint/Envelope

**Not Tested:** Clean Windows VM, Interactive Wizard, Cold Host Restart หลังติดตั้งผ่าน Setup, Code Signing/SmartScreen Reputation. Source Installation Cold Restart ตรวจแล้วแยกจาก Setup
