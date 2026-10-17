# Prota → GO: ดัชนีและ Backlog ทั้งเล่ม

รายการนี้ครอบคลุมหมวดในสารบัญ 95 หน้า ไม่ใช่ประกาศว่าฟีเจอร์ทุกหน้าเสร็จแล้ว
สถานะ UI เป็นบางส่วนของ GO; งานวิศวกรรมที่ไม่มี Solver/Design รองรับยังเป็น Planned

| ID | หน้า | เรื่องอ้างอิง / งาน GO | สถานะ GO |
|---|---|---|---|
| REF-000 | 1–5, 95 | เอกสารต้นฉบับ สารบัญ บริบทและขอบเขต | เก็บ PDF/Metadata และดัชนีแล้ว |
| UI-001 | 6–9 | Ribbon, Quick Access, Search, Display, Layers | Ribbon/Search บางส่วนทำแล้ว; Layers/Views ยังมีงาน |
| PROJECT-001 | 10–14 | Start Page, Project, Settings, Backups, Templates | มี Workspace/Save; Project Center ยัง Planned |
| GRID-001 | 15–21 | Selection, Navigation, Axes/Grid, Reference Drawing | มี Orbit/Pan/Zoom; Grid/Reference workflow ยัง Planned |
| MODEL-001 | 22–29 | Column, Wall, Beam, Snap, ปรับตำแหน่ง | มี Node/Member Beam/Column; Property forms/Snap ยังมีงาน; Wall ไม่รองรับ |
| LC-001 | 30–31, 50, 76 | Load Cases/Combinations, Generator และตารางตัวคูณ | กำลังเพิ่ม Matrix/Reviewed Generator; หน้า 50/76 ยังไม่ตรวจภาพ |
| LC-002 | 30–31 | ASD/LRFD ร่วมโมเดล + ความยาวโหลด + กราฟสมาชิก/แนวเดียวกัน ตามคำขอ | Implemented; ดู docs/tasks/LC-002-member-workflows.md และ QA รอบนี้ |
| CG-001 | คำขอเพิ่มเติม | กราฟคานต่อเนื่องบนแกนระยะเดียว รวมสมาชิกกลับทิศ/หมุนหน้าตัด | Implemented; ดู docs/tasks/CG-001-continuous-member-graphs.md |
| SLAB-001 | 31–34, 46 | Slab/Cantilever/Opening/Polyline | Planned; ต้องแยก Slab load distribution กับ Shell solver |
| VIEW-001 | 35 | Named Views, Plan/3D และจัดหน้าต่าง | Planned; มี Viewport ปัจจุบัน |
| STOREY-001 | 36–37 | Storey และ Building Parameters | Planned |
| LOAD-002 | 38–45 | Wall Library, Member/Storey/Slab Load Editors | Member load ทำแล้วบางส่วน; ฟอร์ม/พื้นที่รับแรงยัง Planned |
| MODEL-002 | 47 | Member Relabelling | Planned; ต้องรักษา Load/Result references |
| ANALYSIS-001 | 48–52 | Analysis, Materials, Combinations, Wind, Model Options | มี PyNite/วัสดุ/Load Cases; Auto wind/Model options ยังมีงาน |
| REVIEW-001 | 53–58 | Load Comparison, Analytical Model, Review | มี Equilibrium/Diagnostics/Inspector; รายงาน Review ยังมีงาน |
| DESIGN-RC-001 | 59–66 | Column/Wall/Beam design, Reinforcement | Not Available; ต้องมี Design Module และหลักฐานอิสระก่อน |
| DESIGN-SLAB-001 | 67–71 | Slab Analysis/Design/Status | Not Available |
| REPORT-001 | 72–73 | Quantity, Preferences, Report Manager | มี CSV/Engineering JSON; Quantity/Report Manager ยัง Planned |
| STEEL-001 | 74–79 | Steel model, Axes/Storeys, Materials, Column/Beam | มี 3D Frame/วัสดุ; Steel building workflow ยังมีงาน |
| STEEL-002 | 80–82 | Truss/Purlin Creation | มี Truss; Roof generation workflow ยังมีงาน |
| STEEL-003 | 83–89 | Cladding/Loads, Braces, Girts, Splices, Analysis | มีตัวอย่างหลังคา/Frame; tools/library ยัง Planned |
| DESIGN-STEEL-001 | 90–94 | Steel Design/Utilization | Not Available |

## สถานะงานที่เปิด

| งาน | ขอบเขตที่ทำรอบนี้ | เอกสาร/หลักฐาน |
|---|---|---|
| LC-001 | ตารางตัวคูณหลายชุด, ทำสำเนา Custom, Generator ที่ใช้ Thai Code Pack เดิม | [Task](tasks/LC-001-load-combinations.md), TEST_RESULTS_COMBINATION_OVERVIEW.md |

คำว่า Implemented ใช้เฉพาะสิ่งที่แก้โค้ดแล้ว; Passed ใช้เฉพาะรายการที่รันทดสอบจริง
แต่ละหัวข้อให้เปิด Task ใหม่หรือสรุปรอบย่อยในไฟล์เดิม ห้ามย้ายสถานะทั้งหมดเป็น Done
โดยอาศัยเพียง Screenshot หรือการทดสอบ Component ที่ยังไม่ได้ Cold Restart
