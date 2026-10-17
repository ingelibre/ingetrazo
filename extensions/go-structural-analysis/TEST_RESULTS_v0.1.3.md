# GO Structural Analysis v0.1.3 — Test Results

ทดสอบวันที่ 8 ตุลาคม 2026 บน Windows กับ IngeTrazo ที่ติดตั้งจริง ผ่าน MCP และ Qt ของโปรแกรม
พัฒนาต่อใน `C:\Users\g_np2\Projects\go-structural-analysis` ไม่สร้างโปรเจกต์ทดแทน

## ตรวจซ้ำวันที่ 9 ตุลาคม 2026

พบโค้ด v0.1.3 และการติดตั้งเดิมอยู่แล้ว จึงตรวจและทดสอบต่อในโปรเจกต์เดิม
สำรอง Source, tests, เอกสาร และ installed plugin ก่อนดำเนินการที่
`backups/audit-20261009-081906/` ไม่เขียนไฟล์ใน Program Files

- Regression เดิม: **19 Passed / 0 Failed / 0 Not Tested**, 4.11 วินาที
- Automated tests ทั้งหมด: **52 Passed / 0 Failed / 0 Not Tested**, 4.61 วินาที
- Engineering comparisons: **198 Passed / 0 Failed** พร้อม reference/error/tolerance ใน JSON
- ติดตั้งซ้ำด้วย `install.ps1 -SkipDependencies`; source/installed Python 11 ไฟล์ hash ตรงกัน
- ตรวจใน host จริงผ่าน MCP: API v2, setup ซ้ำ, QThread analysis พร้อม GUI timer,
  overlay Model/N/V/M/D/Reaction/Deformed, event เลือก Member, slider x/L,
  result tables, CSV 5 ไฟล์, IGZ Save/Load, stale results, Undo/Redo, Zoom/Pan picking
  และการคืน scene/history/plugin data/camera ของโมเดลต้นฉบับ
- ภาพหน้าจอรอบนี้: [Model](artifacts/audit-20261009/model.png),
  [Loads](artifacts/audit-20261009/loads.png), [Results](artifacts/audit-20261009/results.png),
  [Result Inspector](artifacts/audit-20261009/result-inspector.png)
- หลักฐานรอบนี้แยกจากวันที่ 8: [live-tests.json](artifacts/audit-20261009/live-tests.json),
  [regression.xml](artifacts/audit-20261009/regression.xml),
  [pytest.xml](artifacts/v0.1.3/pytest.xml); JSON รวมมี `live_audit_20261009`

เพิ่ม `tests/live_audit_v013.py` เพื่อทำการตรวจซ้ำอย่างเป็นขั้นตอนใน workspace แยก
พบ ImportError ในสคริปต์ตรวจครั้งแรกจากการเรียก `load_scene` ซึ่ง host ไม่มี
แก้เป็น `load_into(Scene(), path)` แล้วตรวจ Save/Load ผ่านจริง
เพิ่ม assertion ว่า event เรียก selection handler จริง ไม่อาศัยค่าเริ่มต้นของ combobox
ภาพตารางใช้ `dialog.grab()` เพราะเป็นหน้าต่างแยกจาก main window

Not Tested ยังคงมี 3 รายการ: cold process restart, physical mouse device,
และ Windows OS theme notification จริง ส่วน Light/Dark/System API มีหลักฐานวันที่ 8
รอบนี้ไม่ได้เปลี่ยน Windows theme หรือปิด host เพื่อรักษางานผู้ใช้
ผลสำเร็จของการบันทึก PNG เป็นการตรวจ capture; การตรวจภาพจริงทำแยกจากตัวนับนั้น

## ผลสุดท้าย

### Material presets — 9 ตุลาคม 2026

เพิ่ม Concrete / Aluminium / Wood ผ่าน Add preset ใน Materials และเลือกวัสดุใน Members
ค่าเริ่มต้นแก้ไขได้ ไม่ใช่ค่า strength/design check; rho เป็นน้ำหนัก kN/m³
Wood ใช้ stiffness ตามแนวเสี้ยน ไม่ใช่ orthotropic model เต็มรูปแบบ
pytest ล่าสุด **90 Passed / 0 Failed / 0 Not Tested**, 6.63 วินาที
ทดสอบ deflection แปรตาม 1/E และ self-weight ของทั้งสามวัสดุเทียบสมการ
Live editor **8 Passed / 0 Failed**: เพิ่มวัสดุ, ไม่เพิ่มซ้ำหรือเขียนทับค่าที่แก้,
Member dropdown, validation, legacy round-trip, รักษา document เดิม
[ภาพ Materials](artifacts/materials/materials-editor.png),
[live-results.json](artifacts/materials/live-results.json)
ตารางสรุปด้านล่างอัปเดตเป็น 90 รายการ; เวลารอบก่อนเก็บไว้ตามลำดับการตรวจ

ผลปัจจุบันหลังเพิ่มตัวอย่างและปรับ Reaction/Moment ตรวจซ้ำจาก source ที่เพิ่มเข้า
Git repository `extensions/go-structural-analysis` วันที่ 9 ตุลาคม 2026:
**86 Passed / 0 Failed / 0 Not Tested**, pytest console 6.42 วินาที
timestamp และเวลาจาก JUnit อยู่ใน XML และ JSON ปัจจุบัน

### Reaction แยกแกนและสัญลักษณ์ Moment — 9 ตุลาคม 2026

- Rx และ Rz เป็นลูกศรอิสระตามแกน global X/Z โดยหัวอยู่ที่ Node และแสดงค่า/หน่วยแยก
- ไม่วาดลูกศรแรงลัพธ์ และซ่อน component ที่เป็นศูนย์ (threshold 1e-10)
- Moment ปฏิกิริยาและโหลด MY ใช้ลูกศรโค้งพร้อมหัวลูกศรและค่า kN·m
  บวกทวนเข็ม ลบตามเข็ม ในมุมมอง X-right/Z-up ตาม convention เดิม
- แยกตำแหน่ง label Rx/Rz/M เพื่ออ่านได้ชัดเจน
- pytest **86 Passed / 0 Failed / 0 Not Tested**, 5.62 วินาที
- ตรวจภาพจริง Portal Frame (Rx/Rz และ M บวก), Inclined Frame (M ลบ),
  Cantilever และ Concentrated Moment ผ่าน MCP พร้อมคืน workspace/model เดิม
- [Reaction แยกแกนและ Moment](artifacts/visual-update/portal_horizontal-Reaction.png)
  / [Moment ลบ](artifacts/visual-update/inclined-Reaction.png)
  / [Moment Load](artifacts/visual-update/moment_jump-Model.png)
- Backup: `backups/reactions-20261009-090105/`

### ปรับลูกศรและพื้นที่กราฟ — 9 ตุลาคม 2026

- หัวลูกศร Point/Distributed/Self-weight จบที่จุดลงแรงบน Member หรือ Node
- หัวลูกศร Reaction จบที่ Node; หางอยู่ด้านตรงข้ามทิศแรง
- เติมพื้นที่ระหว่าง Member กับ N/V/M/D: บวกสีฟ้า ลบสีส้ม โปร่งใสพร้อม Legend
- แบ่งพื้นที่ที่จุดตัดศูนย์และไม่เชื่อมพื้นที่ข้าม discontinuity ที่ x ซ้ำ
- ชุด pytest ล่าสุด **82 Passed / 0 Failed / 0 Not Tested**, 8.67 วินาที
- ตรวจภาพจริง Loads/Reaction/V และ continuous M ที่มีทั้งบวกและลบ;
  เก็บภาพเพิ่มสำหรับ point load, portal และ truss ที่ `artifacts/visual-update/`
- ตรวจผ่าน MCP ด้วยข้อมูลผล solver จริงและคืน panel/camera หลัง preview;
  scene/history/workspace identity และ plugin data ของผู้ใช้คงเดิม
- Backup: `backups/visualization-20261009-085124/`
- [โหลดบน Member](artifacts/visual-update/simple_udl-Model.png),
  [Reaction บน Node](artifacts/visual-update/simple_udl-Reaction.png),
  [กราฟ V สองสี](artifacts/visual-update/simple_udl-V.png),
  [กราฟ M คานต่อเนื่อง](artifacts/visual-update/continuous_3-M.png)

### เพิ่มตัวเลือกตัวอย่างในปลั๊กอิน — 9 ตุลาคม 2026

รายการเดิมใน UI มีเฉพาะ UDL แม้ตัวอย่างอื่นอยู่ใน pytest
เพิ่ม `examples.py` และ Engineering Examples / Benchmarks ใน Model tab
เลือกได้ 21 ตัวอย่างและมีคำอธิบายโหลด/ค่าคาดหวัง แทนที่ workspace ที่ยังไม่บันทึกต้องยืนยัน
โครงสร้างไม่เสถียร 2 ตัวอย่างเป็น expected failure; ห้ามนำผลไปใช้งาน
ชุด pytest ล่าสุด **74 Passed / 0 Failed / 0 Not Tested**, 4.96 วินาที
(52 เดิม + 22 catalogue tests; regression เดิม 19 อยู่ใน 74)
ตรวจ live ผ่านปุ่ม Load selected example และ Run Analysis ทุกตัวอย่าง
หลักฐานรายตัวอยู่ใน `artifacts/examples-v0.1.3/live-results.json`
และ [แกลเลอรีครบชุด](artifacts/examples-v0.1.3/index.html)
สำรองก่อนเพิ่มตัวอย่างที่ `backups/examples-20261009-082539/`

ตารางสรุปปัจจุบัน (กลุ่มย่อยบางรายการรวมอยู่ใน pytest และไม่ให้นับซ้ำ):

| กลุ่ม | Passed | Failed | Not Tested |
|---|---:|---:|---:|
| pytest ทั้งหมด | 90 | 0 | 0 |
| Regression เดิม (รวมอยู่ใน 90) | 19 | 0 | 0 |
| เปรียบเทียบค่าทางวิศวกรรมจริงใน JSON | 198 | 0 | 0 |
| Live integration checks | 20 | 0 | 0 |
| Live audit รอบ 9 ต.ค. (รวม capture checks) | 28 | 0 | 0 |
| ตัวอย่างผ่านปุ่ม UI (รวมคืน original model 1 check) | 22 | 0 | 0 |
| Visual capture checks (รวมคืน workspace 1 check) | 34 | 0 | 0 |
| Materials live editor checks | 8 | 0 | 0 |
| Source/installed Python file hash verification | 14 | 0 | 0 |
| การตรวจสภาพแวดล้อมเพิ่มเติมด้านล่าง | 0 | 0 | 3 |

การเปรียบเทียบ 198 ค่าเป็น Assertions ภายใน Tests ไม่ใช่ 198 Test Cases เพิ่มเติม
หลักฐานเครื่องอ่านได้: [pytest.xml](artifacts/v0.1.3/pytest.xml),
[test-results.json](artifacts/v0.1.3/test-results.json),
[engineering-checks.json](artifacts/v0.1.3/engineering-checks.json),
[live-tests.json](artifacts/v0.1.3/live-tests.json)

Live checks รอบใหม่: [audit](artifacts/audit-20261009/live-tests.json),
[examples](artifacts/examples-v0.1.3/live-results.json),
[Reaction/Moment/diagram captures](artifacts/visual-update/live-results.json)
Capture Passed หมายถึงบันทึกภาพได้; การตรวจภาพจริงรายงานในแต่ละหัวข้อข้างบน
ตัวอย่าง Stability สองรายการ Passed เมื่อ solver ปฏิเสธโครงสร้างไม่เสถียรตามคาด

คำสั่งที่รันจริง:

```powershell
.venv\Scripts\python.exe -m pytest tests -q --junitxml=artifacts\v0.1.3\pytest.xml
# ผลล่าสุดจาก repository: 86 passed in 6.42s
.\install.ps1 -SkipDependencies
.venv\Scripts\python.exe tests\build_report_v013.py
```

ก่อนแก้ไข Regression เดิมผ่าน 19 รายการ เก็บ XML ไว้ที่
`artifacts/regression-before-v0.1.3.xml` และไม่แก้ `tests/test_solver.py`

## Runtime / API / Installation

- Host เป็น frozen CPython 3.12.10, Plugin API v2; ไม่ติดตั้ง dependencies ลง host
- Solver Worker Python 3.12.14 / PyNiteFEA 3.2.0 ที่
  `%LOCALAPPDATA%\GO Structural Analysis\solver-v0.1\Scripts\python.exe`
  ใช้ runtime เดิมต่อ แม้ชื่อ directory จะยังเป็น `solver-v0.1`
- Plugin ติดตั้งที่ `%APPDATA%\ingetrazo\plugins\go_structural_analysis`
  Python ทั้ง 13 ไฟล์ตรงกับ Source ด้วย SHA256 ในการตรวจหลังติดตั้งล่าสุด
- ตรวจ `core.extensions.discover_plugins` ใน host จริง: พบ GO plugin ไม่มี PluginError;
  เรียก setup กับ ExtensionApp v2 จริงได้ และการเรียกซ้ำไม่สร้าง Panel ซ้ำ
- API v1 ถูกปฏิเสธด้วยข้อความชัดเจน
- ตรวจ GitHub Plugin API v2 จาก
  [ingelibre/ingetrazo docs/plugins.md](https://github.com/ingelibre/ingetrazo/blob/6be29fe437a7cd992d4e079f71720821b25216b9/docs/plugins.md)
  และ source reference commit `6be29fe437a7cd992d4e079f71720821b25216b9`
- Host โหลด plugin โดย file path ใน namespace `ingetrazo_plugin_go_structural_analysis`;
  ordinary `import go_structural_analysis` ใน host ไม่ใช่เส้นทางโหลดที่ถูกต้อง
- JSON Protocol ยังเป็น 1, result schema เป็น 2, extension version เป็น 0.1.3;
  subprocess ใช้ isolated mode และ worker ไม่ import Qt/host
- ไม่แก้ IngeTrazo core หรือไฟล์ภายใน Program Files

## Engineering benchmarks และ Reference

Units: m, kN, kN·m, E/G kN/m², A m², Iy/Iz/J m⁴, rho kN/m³
General tolerance: `max(1e-8, 1e-7 * abs(reference))` ต่อค่าที่ตรวจ
Regression เดิมรักษา tolerance ของเดิม เช่น deflection relative 1e-8
สมดุลแต่ละแกนใช้ `1e-7 * max(1, abs(applied), abs(reaction))`
ค่า Actual / Reference / Absolute Error / Tolerance ของทุก comparison อยู่ใน JSON

| Benchmark ที่รันจริง | Reference Solution | ผล |
|---|---|---|
| Simply supported UDL | R=wL/2, moment magnitude max=wL²/8, Dmax=5wL⁴/(384EI) | Passed |
| Simply supported midpoint point load | R=P/2, moment magnitude max=PL/4, Dmax=PL³/(48EI); ทดสอบแรงลงเดิมและแรงขึ้นชุดใหม่ | Passed |
| Cantilever point load | R=P, moment=PL, Dtip=PL³/(3EI) | Passed |
| Cantilever UDL | R=wL, moment=wL²/2, Dtip=wL⁴/(8EI) | Passed |
| Continuous beam 2 spans, 6 m/span | R=[22.5,75,22.5] kN, interior hogging magnitude 45 kN·m | Passed |
| Continuous beam 3 spans, 6 m/span | R=[24,66,66,24] kN, interior hogging magnitude 36 kN·m | Passed |
| Portal frame: vertical UDL / horizontal point load | Independent 2D frame stiffness solution; compare node translations, rotations and reactions | Passed |
| Inclined frame facing negative X | Independent coordinate transformation / frame stiffness; compare node results and transformed member-end displacement | Passed |
| Triangle truss / joint load | Joint equilibrium: bottom N=-5, diagonal compression N=10/√2 kN | Passed |
| Member release j / both ends | Released end moment zero; propped beam R=37.5/22.5 kN; both releases R=30/30, simple-beam D | Passed |
| Released mechanism, loaded / unloaded | Singular stiffness must reject; assert RuntimeError from solver itself | Passed |
| Multiple load cases, self-weight OFF/ON | External loads plus rho·A·L; cases solved independently at factor 1 | Passed |
| Truss self-weight | Half each member weight at each joint; reactions and diagonal N by joint equilibrium; zero member M | Passed |
| Off-grid point at x=1.37 m | M extrema at point, analytical D stationary position and value; left/right shear jump | Passed |
| Triangular UDL | R=10/20 kN, stationary M at L/√3, magnitude wL²/(9√3) | Passed |
| Axial UDL on cantilever | N(x)=-q(L-x), u(L)=qL²/(2EA), reaction=-qL | Passed |
| Interior concentrated moment | R=±C/L; M jump=C; exact maximum and position at load | Passed |
| Whole-structure force/moment balance | Applied global loads + support reactions, moments about global origin | Passed |

Reference frame code: `tests/reference_frame.py` ใช้ textbook axial +
Euler–Bernoulli 6×6 stiffness / global transformation / consistent UDL vectors
โดยไม่ import PyNite; continuous-beam displacement เพิ่ม particular UDL solution
เข้ากับ Hermite interpolation ของ nodal results

### คานอ้างอิง 6 เมตร UDL 10 kN/m, Self-weight OFF

E=200,000,000 kN/m², Iz=8e-5 m⁴, Pin / Roller

| Quantity | Theory | Actual | ผล |
|---|---:|---:|---|
| Left reaction | 30 kN | 30 kN | Passed |
| Right reaction | 30 kN | 30 kN | Passed |
| Maximum moment magnitude @ 3 m | 45 kN·m | 45 kN·m | Passed |
| Downward midspan displacement | 10.546875 mm | 10.546875 mm | Passed |

PyNite section M=-45 kN·m และ global UZ=-0.010546875 m
บันทึกเอกสารแยกไว้ที่ [benchmark-v0.1.3.igz](artifacts/v0.1.3/benchmark-v0.1.3.igz)

## Exact extrema / signs

อ่าน continuous segments ของ PyNite 3.2.0 แยกตามจุดแรง/ช่วง distributed load
แล้วสร้าง polynomial ของ N/V/M/local D/u; ค้นรากจริงของ derivative พร้อม
ตรวจปลายทุก segment ทั้งด้านซ้าย/ขวา ไม่ใช้ 61 sampling points เป็นตัวค้น extrema
61 samples เดิมเก็บเพื่อความเข้ากันได้เท่านั้น
Inspector ประเมิน polynomial ที่ x จริง; vertices ของ Diagram รวม extrema และ load jumps

Global X ขวา / Z ขึ้น; local x จาก i ไป j; local y ใช้แถวของ PyNite transformation
ที่ serialized ใน `basis` จริง จึงรองรับสมาชิกที่ชี้ไป negative X
N positive compression; M'=-V, D''=-M/(EIz); D positive local y
MY เป็น in-plane counterclockwise ใน XZ (about host minus Y), map ไป solver +MZ
Member end-force table เป็น local nodal actions ไม่ใช่ section-cut sign
รายละเอียดทั้งหมดอยู่ใน README

## Live MCP / UX / Persistence

- วิเคราะห์จริงผ่าน QThread + installed worker และ UI Timer 10 ms ทำงาน 280 ครั้ง
  ระหว่าง thread ยังรันอยู่; ไม่ block GUI ด้วย synchronous solve
- ส่ง Qt MouseButtonPress ไป viewport จริง เลือก B1 ผ่าน event filter/picking
  และ slider x/L=0.25 อ่าน N=0, V=15, M=-33.75 kN·m, D=-7.51465 mm
- Four tables: Node Displacements 2 rows, Reactions 2, End Forces 2, Extrema 8
- ส่งออก CSV จริง 5 ไฟล์ มี Header / case / units ใน [csv](artifacts/v0.1.3/csv)
- `.igz` Save/Load ผ่าน `formats.igz` ของ host: model/results ตรงกันทุกค่า
- Undo analysis -> result ว่าง; Redo -> result เดิมกลับมาตรงกัน
- แก้โหลด -> เก็บผลเก่าแต่แจ้ง OUT OF DATE, หยุดใช้ diagram/inspector และ disable CSV;
  Undo -> model fingerprint ตรงและผลกลับมาใช้ได้
- Switch LC1 / LC2: viewport/readout เลือกค่าของ case จริงที่ solver คำนวณ
- วาด Fixed/Pin/Roller/RollerX/releases, Point/Distributed/Self-weight loads;
  N/V/M/D, Reaction, Deformed, Max/Min labels บน Qt child canvas จริง
- Pan/Zoom camera: projected member points เปลี่ยนตาม geometry และ picking ยังเลือก ID ถูก
- Label / Legend OFF และ Diagram scale=1.8 render ได้; Deformed scale=100 render ได้
- Light / Dark / System ผ่าน host `apply_theme`; palette และ live restyle เปลี่ยนตาม host
- Editor schema-1 roundtrip และ negative E rejection ผ่าน
- Unstable model และ released mechanisms ใน installed worker แสดง Analysis failed,
  thread จบและ Run button กลับมาใช้งานได้
- คืน original scene/history identities, plugin data, camera และ active unsaved workspace
  เหมือนเดิม ไม่ commit test model ลง document เดิม

Host MCP `screenshot` render เฉพาะ host geometry และไม่รวม extension overlays ใน build นี้
จึงตรวจ overlays ด้วย `viewport.grab()` / `window.grab()` ของ Qt host จริง
พร้อมเรียก MCP query_model และ screenshot เพื่อตรวจการเชื่อมต่อ

## ภาพหน้าจอ

- [Model](artifacts/v0.1.3/model-window.png)
- [Loads](artifacts/v0.1.3/loads-window.png)
- [Results](artifacts/v0.1.3/results-window.png)
- [Result Inspector](artifacts/v0.1.3/result-inspector-window.png)
- [Inspector tables](artifacts/v0.1.3/result-inspector-tables.png)
- [Dark](artifacts/v0.1.3/results-dark.png) / [System](artifacts/v0.1.3/results-system.png)
- [Zoom/Pan](artifacts/v0.1.3/overlay-pan-zoom.png)
- [Fixed / RollerX / release / self-weight](artifacts/v0.1.3/supports-rollerX-release-selfweight.png)
- `overlay-N/V/M/D/Reaction/Deformed.png`, `point-load-case-LC2.png`
  และ `table-*.png` อยู่ในโฟลเดอร์เดียวกัน

## ข้อผิดพลาดที่พบและแก้จริง

1. Reference test helper เดิมส่ง dict ทั้งก้อนแทนค่า component — แก้แล้ว rerun
2. Audit ของ engineering JSON พบ moment residual -180 kN·m ใน released mechanism
   ซึ่ง PyNite residual-only stability check ไม่ปฏิเสธ และ broad `raises(Exception)`
   ใน Test เคยจับ assertion ผิดเป็น expected error — แก้ Test ให้ตรวจ RuntimeError
   จาก `solve` โดยตรงทั้ง loaded/unloaded เพิ่ม sparse LU pivot guard และบังคับ
   reject solution เมื่อ equilibrium ไม่ผ่าน ผลสุดท้าย 198 comparisons ผ่านทั้งหมด
   เก็บหลักฐานก่อนแก้ไว้ใน `engineering-checks-before-stability-fix.json`
   และ `pytest-before-stability-fix.xml` เพื่อไม่ลบประวัติข้อผิดพลาด
3. ผลลัพธ์เก่า schema 1 ไม่มี polynomial/basis/fingerprint — แจ้ง stale และต้อง Run ใหม่
4. เพิ่ม malformed JSON/protocol/result/nonzero-exit tests และข้อความ error ที่อ่านได้

## Not Tested

- Cold process restart: ไม่ปิดโปรแกรมที่มี unsaved workspace ของผู้ใช้;
  ทดสอบ live discovery/import/setup แล้ว แต่ไม่ได้ทดสอบการเปิด executable รอบใหม่
- Physical mouse input: ใช้ synthetic Qt mouse event บน live viewport จริง;
  ไม่ได้กด mouse hardware หรือใช้ QtTest (frozen host ไม่มี QtTest)
- เปลี่ยน Windows Theme เพื่อรับ OS notification จริง: ทดสอบ host Light/Dark/System
  API แล้ว แต่ไม่เปลี่ยนการตั้งค่า Windows

ไม่อ้างสามรายการนี้ว่าผ่าน และไม่ใช้ผลย้อนหลัง v0.1 แทนการทดสอบ v0.1.3

## Backup / Changed files

สำรอง Source + installed plugin ก่อนแก้ไว้ที่
`backups/before-v0.1.3-20261008-191932/`
รายการไฟล์ที่เพิ่ม/แก้: [CHANGED_FILES.md](CHANGED_FILES.md)
และ `artifacts/v0.1.3/changed-files.json`
Source ถูกติดตั้งลง user Plugins แล้ว; เอกสาร v0.1 อ่านได้ แต่ results เดิมต้อง Run Analysis
ใหม่เพื่อสร้าง result schema 2 ไม่มีการ Run หรือเขียนผลทับโมเดลเดิมอัตโนมัติ
