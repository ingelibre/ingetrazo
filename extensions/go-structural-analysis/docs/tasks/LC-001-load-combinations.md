# LC-001 — Load Combination Matrix / Reviewed Generator

อ้างอิงคู่มือหน้า 30 และส่วนบนหน้า 31: การสร้างชุดด้วย Generator และตรวจ
ตัวคูณหลาย Combination ในตารางเดียว ตรวจทั้งภาพและข้อความแล้ว
หน้า 50/76 ใช้เป็นจุดอ้างอิงงานต่อ แต่ยังไม่ได้อ่านภาพในรอบนี้

## ขอบเขตรอบนี้

- Matrix: แถวเป็น Combination, คอลัมน์เป็น Load Case; แก้ Custom แบบตัวเลข
- เปิด/ปิด Custom, ค้นหาชุด, เลือกและทำสำเนา; แสดงสูตรและที่มา
- สูตรกฎหมาย Read-only; สำเนาแก้ได้พร้อม provenance
- Generator เลือก ASD/LRFD, D/L และ Wind alternatives ที่มีอยู่
- ตรวจสูตรจริง/Missing Input ก่อนใช้; ไม่สร้างกรณีแรงเปล่าหรือแรงจริงขึ้นเอง
- บันทึกครั้งเดียวและทำให้ผลเดิม Stale ตาม Safety เดิม; Cancel ไม่เปลี่ยน Inputs

ไม่มีตัวเลือกหลอกสำหรับ Concrete/Steel capacity design, Cracked Section,
P-Delta, earthquake action generation หรือ code compliance ที่ GO ยังไม่ได้คำนวณ
สูตร Prota ในตัวอย่างไม่ใช้แทน Thailand 2566; ใช้ Thai Code Pack เดิมเท่านั้น

## Acceptance / Tests

ตรวจหลายแถว, +/-/0, ปิดชุด, duplicate, protected clone, precision เมื่อเปิดปิด
editor โดยไม่แก้, invalid finite factors, Missing Load Case, Wind alternatives,
Generator cancel, 2D/3D superposition, live window และ original model preservation

## สถานะรอบ 11 ตุลาคม 2026

Implemented: Matrix, Duplicate, Collapsible detail editor และ Reviewed Generator
ผลทดสอบ/ข้อจำกัดฉบับล่าสุดดู [รายงาน](../../TEST_RESULTS_COMBINATION_OVERVIEW.md)
งานถัดไป: bulk paste ที่ตรวจ Header/Case IDs, quick case creation ที่อัปเดต
references อย่างปลอดภัย, live Save/Load/Undo/Redo และ Cold Restart ของชุดสุดท้าย
