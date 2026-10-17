# คู่มือ Prota เป็นต้นแบบ Workflow ของ GO

เก็บคู่มือทั้งเล่มเพื่ออ้างอิงทีละเรื่อง โดยแยก “สิ่งที่คู่มือแสดง” ออกจาก
“สิ่งที่ GO ทำแล้วและทดสอบจริง” ไม่ใช้เอกสารนี้แทนมาตรฐานหรือสมการออกแบบไทย

- คู่มือ: ProtaStructure 2022 Basic Training Guide, 95 หน้า
- [แหล่งต้นฉบับ](https://d2dpssj7o46s6b.cloudfront.net/documents/protastructure-2022-basic-training-guide.pdf)
- สำเนาในเครื่อง: `reference/prota2022/protastructure-2022-basic-training-guide.pdf`
- ลิงก์ รุ่น จำนวนหน้า วันดาวน์โหลด และ SHA-256: `reference/prota2022/source.json`
- แผนงาน: [UI_BACKLOG.md](UI_BACKLOG.md)
- คำสั่ง AI ประจำโครงการ: [AGENTS.md](../AGENTS.md)
- งานปัจจุบัน: [LC-001](tasks/LC-001-load-combinations.md)

PDF อยู่ในเครื่องและไม่ได้ใส่ใน Git/Installer โดยอัตโนมัติ ไฟล์ดัชนี Metadata
และแผนงานเป็นเอกสารของ GO และเก็บตาม Source ได้ หากย้ายเครื่องให้ดาวน์โหลดจาก
URL ใน Metadata แล้วตรวจ SHA-256 ก่อนอ่าน ไม่คัดลอกภาพ/โลโก้ของ Prota ไปเป็น Asset
ของหน้าต่างโปรแกรม

## สถานะการอ่าน

อ่านสารบัญหน้า 3–5 เพื่อจัดหมวดทั้งเล่ม และตรวจทั้งภาพ/ข้อความหน้า 6–9, 30–31
แล้ว บทอื่นใน Backlog เป็นดัชนีจากสารบัญ ต้องอ่านหน้าจริงก่อนพัฒนาในเรื่องนั้น
หน้า 31 ส่วนบนเป็นตาราง Combination ส่วนที่เหลือเริ่มหัวข้อ Slab Creation

## วิธีสั่งพัฒนาต่อ

ส่งคำสั่งลักษณะนี้ได้เลย:

> ทำงาน LC-001 ต่อใน C:\Users\g_np2\Projects\go-structural-analysis
> อ่าน AGENTS.md, docs/PROTA_REFERENCE.md และ docs/tasks/LC-001-load-combinations.md
> ดูคู่มือ Prota หน้า 30–31 และผล QA ล่าสุดก่อนแก้
> ทำเฉพาะฟอร์ม Combination รอบนี้ รักษาสูตร Thailand 2566 และ Result Safety
> ติดตั้ง ทดสอบ Regression/MCP แล้วอัปเดตสถานะกับไฟล์ที่แก้ ห้ามอ้าง Passed หากไม่ได้ทดสอบ

สำหรับเรื่องใหม่ เปลี่ยน ID และหน้าคู่มือ เช่น `GRID-001 หน้า 15–21` หรือ
`LOAD-002 หน้า 38–45` ให้ AI สร้างไฟล์งานตาม [Template](tasks/TEMPLATE.md)
ก่อนแก้โค้ด ระบุพฤติกรรมที่ต้องการให้ชัด เช่น “เลือกสมาชิกใน Viewport แล้วเปิด
ฟอร์ม Load พร้อมหน่วยและ Preview” แทนการสั่งทำทั้งคู่มือในครั้งเดียว

## เกณฑ์แปลงคู่มือเป็นงาน

แต่ละงานระบุหน้าอ้างอิง, หน้าต่าง/คำสั่งเดิมของ GO, ขอบเขตครั้งนี้,
Acceptance Criteria, กรณีทดสอบ, ข้อจำกัด และหลักฐาน UI ก่อน/หลัง
ฟีเจอร์ที่ GO ยังไม่มี เช่น slab shell, cracked stiffness, P-Delta หรือ capacity
design ต้องเป็นงาน Model/Solver/Design แยกต่างหาก ไม่เพิ่ม Checkbox ที่ทำให้
ผู้ใช้เข้าใจว่าได้คำนวณแล้ว
