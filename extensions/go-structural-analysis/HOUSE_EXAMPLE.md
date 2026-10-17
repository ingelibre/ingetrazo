# ตัวอย่างบ้านเพชรนารายณ์ — คาน/เสาคอนกรีตและโครงหลังคาเหล็ก

ตัวอย่าง 3D สำหรับทดลอง GO Structural Analysis v0.2.4 ใช้พิกัดแนวคานและตำแหน่งเสาที่เลือกจาก `อาจารย์กวี_PhetnarayBMA.html` โดยไม่แก้ไฟล์ HTML ต้นฉบับ ไม่ใช่โมเดลออกแบบหรือรับรองบ้านจริง

## วิธีเปิด

1. เปิด IngeTrazo → Extensions → GO Structural Analysis
2. Model → Engineering Examples / Benchmarks
3. เลือก **House Phetnaray / บ้านเพชรนารายณ์ — RC + steel roof**
4. กด **Load selected example** → **Run Analysis**
5. Results → เลือก DL, LL, RL, WX+/WX−, WY+/WY− หรือ DEMO Gravity แล้วเลือก N / Vy / Vz / My / Mz / T / D / Deformed / Reaction

หรือ File → Open → `examples/house/Phetnaray-RC-Steel-Roof.igz` ซึ่งเก็บโมเดลตัวอย่างขนาดเล็ก ให้กด Run Analysis หลังเปิด. เปิดใน v0.2.4 ได้โดยไม่ต้องพึ่งไฟล์ HTML. JSON ต้นแบบอยู่ใน `examples/house/phetnaray-rc-steel-roof.json`

หากใช้ Source รุ่นก่อนเพิ่มบ้าน ให้ติดตั้ง Source เพิ่มเติมด้วย `powershell -ExecutionPolicy Bypass -File .\install.ps1 -SkipDependencies` เมื่อมี Runtime PyNiteFEA 3.2.0 เดิม แล้วเปิด IngeTrazo ใหม่. ตัวติดตั้ง v0.2.4 ที่สร้างก่อนเพิ่มบ้านยังไม่มีรายการบ้านนี้ แต่สามารถเปิดไฟล์ `.igz` ตัวอย่างได้

## โมเดล

- 146 Nodes / 255 Members / Fixed Bases 12 จุด
- ตำแหน่งเสา 12 จุดและแนวคาน 101 รายการจาก HTML; แบ่ง Member ที่จุดตัดและลบช่วงซ้อนเพื่อไม่ให้นับหน้าตัด/น้ำหนักซ้ำ
- เสาคอนกรีต C200 และ C250; หน้าตัดคาน B1/B2/B4/B4A/B12/RB2/BST/B16/B16A/B19/B50 ตามค่าขนาดใน HTML
- ระดับฐาน −1.00, แนวโครงสร้างชั้นล่าง +0.55, ชั้นบน +3.75, ชายคา +6.80, ยอดหลังคา +8.70 เมตร; FFL ต้นแบบ +0.60/+3.80 ลบ Finish 0.05 เมตร
- หลังคาปั้นหยาแบบย่อ: ตะเฆ่สัน จันทัน แปสองแนว คานชายคา เสารับยอด และคานถ่ายแรงไปโครงคอนกรีต
- Global Z ขึ้น; Local y เป็นแนวดิ่งสำหรับคานแนวนอน; ความลึกคานอยู่ตาม Local y จึงใช้ Iz เป็นแกนดัดรับแรงแนวดิ่ง
- ใช้หน่วย kN–m, ผลดิบเต็มความละเอียด และแสดงการเคลื่อนตัวเป็น mm ตาม Display Settings

## สมมติฐานที่ต้องทราบ

หลังคา HTML เดิมมี C-section และรายละเอียดระแนงมากกว่าตัวอย่างนี้ ตัวอย่างใช้ **RHS100×100×3 และ RHS75×75×3 mm** เพื่อทดลอง โดยไม่อ้างว่าเป็นหน้าตัดจริงตามแบบ. หน้าตัด RHS คำนวณไม่รวมมุมโค้ง; J ใช้สูตร Thin-wall Closed Section

คอนกรีตใช้ Gross Uncracked Section, E=25 GPa, ν=0.2 และน้ำหนัก 24 kN/m³ ซึ่งเป็นค่าทดลอง ไม่ได้อนุมาน E จากกำลังคอนกรีต 180 ksc ใน HTML. เหล็ก E=200 GPa, ν=0.3, น้ำหนัก 76.98 kN/m³

ฐาน Fixed; จุดต่อทั้งหมดรวมจุดตัดหลังคาถือเป็น Rigid. ไม่จำลองความยืดหยุ่นเสาเข็ม/ดิน, Slab Diaphragm, Cracked Stiffness, รายละเอียดข้อต่อ, ผนัง หรือบันได

โหลดใช้ Equivalent Nodal Loads แบบย่อ: พื้นที่พื้น 9.3×8.3 m ต่อชั้น, DL เพิ่ม 1.5 kPa และ LL 2.0 kPa กระจายเท่ากันไปจุดเสา. หลังคา DL 0.6 kPa / RL 0.25 kPa อ้างพื้นที่ฉายราบ กระจายไป Roof Nodes. แรงลม ±10 kN ต่อระดับบนต่อแกน เป็นแรงตัวอย่าง ไม่ใช่ผลคำนวณลมตามกฎหมาย

Self-weight ของ Member เปิดเฉพาะ DL หนึ่งครั้ง. DEMO Gravity = DL+LL+RL และ DEMO Wind X± = DL+WX± เป็น **Custom Combinations สำหรับสอน** ไม่ใช่ Preset ตามกฎหมาย. หากใช้ Thai Manager ให้ผู้ใช้จัดหมวดและตรวจโหลดเองก่อนเลือก ASD/LRFD

Capacity / Code Compliance / การตรวจ Serviceability ครบเกณฑ์ยังเป็น **Not Available**

## หลักฐาน QA

`artifacts/house/house-pytest.xml`, `regression-pytest.xml`, `qt-pytest.xml`, `live-results.json` และภาพ House-Model/Loads/Mz/N/Deformed/Reaction. รายงานผลเพิ่มบ้านอยู่ใน `TEST_RESULTS_HOUSE.md` โดยแยกจากหลักฐาน Release v0.2.4 ที่สร้างก่อนเพิ่มตัวอย่างนี้
