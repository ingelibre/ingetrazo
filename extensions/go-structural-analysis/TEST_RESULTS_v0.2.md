# GO Structural Analysis v0.2.3 — ผลทดสอบจริง

พัฒนาต่อใน `C:\Users\g_np2\Projects\go-structural-analysis` จาก v0.1.3
บน Windows วันที่ 9 ตุลาคม 2026 ใช้ PyNiteFEA **3.2.0** และ IngeTrazo API **v2**
สำรอง source, tests, packaging และ installed plugin ใน `backups/v02-before-*`
สำรองโมเดลที่เปิดอยู่ใน `backups/v02-open-model-before.igz` และ `v02-cold-before.igz`
ก่อนติดตั้ง/restart ไม่แก้ไฟล์ใน Program Files และไม่เขียนทับไฟล์โมเดลเดิมของผู้ใช้

## ผลล่าสุด

| กลุ่ม | Passed | Failed | Not Tested / Skipped |
|---|---:|---:|---:|
| Solver/schema/regression pytest | 146 | 0 | 1 module skip |
| Qt QA ใน environment แยก | 9 | 0 | 0 |
| Regression v0.1.3 ทั้งหมด (รวม 86 เดิม + material 4) | 90 | 0 | 0 |
| 3D engineering comparisons พร้อม reference/error/tolerance | 3105 | 0 | 0 |
| Live IngeTrazo MCP (รวม capture checks) | 92 | 0 | 0 |
| Source/installed Python SHA256 | 18 | 0 | 0 |

146 + 9 คือ **155 automated tests ที่ได้รันผ่านจริง** ส่วน module skip ใน solver
environment เกิดจากไม่มี Qt โดยเจตนา ไม่ใช่ Qt 9 tests ไม่ผ่าน: ได้รัน Qt tests
ใน `.qa-venv` แยกและเก็บ XML ของตัวเอง ไม่ย้าย Qt เข้า solver environment
Regression 90 เป็น subset ของ 146 ไม่ให้นับซ้ำเป็นจำนวน tests เพิ่ม
Live checks รวม screenshot capture checks ไม่ใช่จำนวน benchmarks อิสระ

ไฟล์อ้างอิงผล:

- [pytest.xml](artifacts/v0.2/pytest.xml)
- [Qt pytest XML](artifacts/v0.2/qt-pytest.xml)
- [test-results-v0.2.json](test-results-v0.2.json)
- [3D comparisons](artifacts/v0.2/engineering-checks.json)
- [Live checks](artifacts/v0.2/live/live-results.json)
- [รายการไฟล์ที่เปลี่ยน](CHANGED_FILES_v0.2.md)

## Phase 1–6

1. **Model Builder:** schema 2 XYZ, Beam/Column/Frame/Truss, E/G/nu/rho,
   A/Iy/Iz/J, section rotation, support DOFs/springs/releases, duplicate/orphan
   detection และ connectivity validation ผ่าน automated tests; editor และ
   node selection/edit/member delete/undo ผ่าน live host ด้วย
2. **3D Solver:** 6 DOF; proper coordinate rotation `(X,Z,−Y)` ไป PyNite;
   local basis เทียบ actual T matrix; six force components, displacement/rotation
   และ force/moment reactions; singular mechanism ปฏิเสธทั้งมีและไม่มี load
3. **Loads:** base cases/user combinations, local/global directions, partial
   varying load, linear superposition, self-weight ลง case เดียว, mass→weight
   conversion, six CSV tables, exact envelope พร้อม governing case และ x/side
4. **Visualization:** world-space XYZ overlay, local axes, support/load/release
   glyphs, N/Vy/Vz/My/Mz/T/D, 3D deformed shape, scales/labels, inspector,
   orbit/pan/zoom/picking; ภาพ live host และ offscreen Qt แยกโฟลเดอร์กันชัดเจน
5. **Verification:** cantilever สองแกน, pure torsion TL/GJ, axial PL/EA,
   3D portal, space truss, multi-bay frame, local rotation, end release,
   self-weight ON/OFF, combinations, global equilibrium 6 components,
   unstable structure ครบ 12 กลุ่ม มี 11 กลุ่ม solve สำเร็จ และ 1 กลุ่มต้องปฏิเสธ
6. **UX/live QA:** Model/Loads/Results เดิม, 2D/3D workspace, Light/Dark/System,
   background QThread + subprocess worker, Save/Load `.igz`, Undo/Redo, stale
   results, 2D live compatibility, cold restart และเปิด Extension ใหม่

Independent reference ใน `tests/reference3d.py` ไม่ import PyNite หรือ production
model code; สร้าง 12-DOF Euler–Bernoulli stiffness หรือ axial bar stiffness เอง
เทียบ node displacement/reaction และ member end forces ของ frame ทุก case
Cantilever, torsion, axial, self-weight และ section rotation เทียบสมการปิด
Tolerance ปกติ `max(1e-9, 1e-7 × |reference|)` และ equilibrium ใช้ 1e-7 คูณ
ผลรวม absolute wrench components (ขั้นต่ำ 1); ค่าจริงทั้งหมดเก็บใน JSON

Diagram extrema ใช้ derivative roots ของ polynomial แต่ละช่วง Solver รวมจุด
load jump/boundary ไม่ใช้ sampling 61 จุดตัดสิน max/min ส่วน magnitude D ใช้
roots ของ derivative ของ u²+dy²+dz²; sampling ใช้เฉพาะวาดเส้นระหว่างจุดสำคัญ

## Live QA และภาพจริง

ทดสอบ installed executable ผ่าน MCP ใน workspace แยก แล้วคืน scene/history/
plugin data/camera ของเอกสารต้นฉบับ ไม่ใช้ผล offscreen แทน live host
ทดสอบกดเลือกด้วย synthetic QMouseEvent ที่ส่งเข้า viewport จริง ไม่ใช่ฮาร์ดแวร์เมาส์
ยืนยัน cold process PID เปลี่ยนและ auto-discovery โหลด v0.2.3 ได้หลังเริ่มใหม่
temporary bridge bootstrap สำหรับ cold QA ถูกลบหลังใช้ ไม่รวมใน plugin package

- [Model](artifacts/v0.2/live/Model.png), [Loads](artifacts/v0.2/live/Loads.png), [Results](artifacts/v0.2/live/Results.png)
- [N](artifacts/v0.2/live/N.png), [Vy](artifacts/v0.2/live/Vy.png), [Vz](artifacts/v0.2/live/Vz.png)
- [My](artifacts/v0.2/live/My.png), [Mz](artifacts/v0.2/live/Mz.png), [T nonzero](artifacts/v0.2/live/T-nonzero.png)
- [Deformed](artifacts/v0.2/live/Deformed.png), [Inspector](artifacts/v0.2/live/Inspector.png), [Result Tables](artifacts/v0.2/live/Result-Tables.png)
- [ตัวอย่าง `.igz` และ JSON](examples/v0.2), [คู่มือ 3D](EXAMPLES_v0.2.md), [ติดตั้ง/อัปเดต](UPDATE_v0.2.md)

## Failed ที่พบระหว่างพัฒนาและแก้แล้ว

- Model-tab node press ไม่ส่ง selection ใน installed build และ host process
  หายไปหลังเส้นทาง native selection นี้ แก้โดยรับ analytical node/member press
  ใน OverlayCanvas ของ extension ก่อนส่งเข้าตัวเลือก native ทดสอบหลังเปิด host
  ใหม่แล้ว Node selection/edit, member delete/undo และ QA ต่อเนื่องผ่าน
  ไม่อ้างว่าพิสูจน์ root cause ภายใน IngeTrazo Core หรือแก้ Core แล้ว
- Reference truss normalization ใช้ integer array ในครั้งแรก แก้ float dtype
  แล้ว benchmark ทั้งหมดผ่าน
- Qt QA ครั้งแรกขาด host import path/font ใน offscreen environment แก้ test
  environment และตรวจภาพอีกครั้ง แล้ว Qt 9 tests ผ่าน

รายละเอียดสถานะแรกและผลหลังแก้: [resolved-issues.json](artifacts/v0.2/resolved-issues.json)

## ตัวติดตั้ง

ตัวติดตั้ง v0.2.3 ผ่าน lifecycle 14 checks และ bundled worker examples 33 cases
บนเครื่องนี้ รวมเส้นทางภาษาไทย ดู [ผลจริงและ SHA256](INSTALLER_TEST_RESULTS_v0.2.md)
ไม่ใช้ผลตัวติดตั้ง v0.1.3 มาอ้างแทน

## Not Tested

- Physical mouse hardware; ตรวจเส้นทาง UI ด้วย Qt events จริงแล้ว
- Windows OS theme notification จริง; ไม่เปลี่ยนการตั้งค่าระบบ
- ติดตั้งบน clean Windows VM ที่ไม่มี Python/development tools
- Interactive Setup wizard และ cold restart หลังติดตั้งด้วย Setup; cold restart หลังติดตั้ง source ผ่านแล้ว

## Known Limitations / v0.3

- Linear elastic Euler–Bernoulli เท่านั้น: ไม่มี P-delta/nonlinear/buckling,
  shear deformation หรือ design-code/capacity checks
- Viewport แสดง case/combination ทีละอัน; envelope อยู่ใน table และ inspector
  ยังไม่มี envelope graph รวมทุก combination บน viewport
- Geometry conversion รับ straight selected edges ต้อง review ก่อนยืนยัน;
  ยังไม่หา centerline จาก solid/group/face หรือ split intersection อัตโนมัติ
- Truss-only rotations ที่ไม่มี stiffness ถูกปิดเป็น auxiliary DOFs;
  nodal moment ต้องมี restraint/spring จริง ไม่ส่งโมเมนต์ผ่าน truss แบบเงียบ ๆ
- Material presets เป็นค่าเริ่มต้น: คอนกรีตไม่คิด cracking และไม้ไม่ใช่ full orthotropy
- v0.3 ควรเพิ่ม constrained joints/intersection tools, section libraries,
  label collision handling, envelope viewport และ verification ก่อนเพิ่ม nonlinear/design checks
