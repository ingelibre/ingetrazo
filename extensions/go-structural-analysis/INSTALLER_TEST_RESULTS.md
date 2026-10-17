# GO Structural Analysis v0.1.3 — Windows installer tests

ทดสอบวันที่ 9 ตุลาคม 2026 บนเครื่อง Windows 11 ปัจจุบัน
ทดสอบ executable จริงแบบ silent โดยติดตั้งลงโฟลเดอร์ทดสอบแยก
ไม่ได้เปลี่ยนปลั๊กอินที่ใช้งานอยู่หรือปิด IngeTrazo ที่มี workspace ของผู้ใช้

| กลุ่ม | Passed | Failed | Not Tested |
|---|---:|---:|---:|
| Install / reinstall / uninstall checks | 14 | 0 | 0 |
| ตัวอย่างด้วย runtime ที่มากับ Setup | 21 | 0 | 0 |
| App automated tests รวม regression เดิม | 90 | 0 | 0 |
| สภาพแวดล้อมเพิ่มเติมด้านล่าง | 0 | 0 | 4 |

Installer checks รันติดตั้งจริง 2 รอบ: exit code, runtime, worker_config ชี้ไปที่
Python ที่ติดตั้งใหม่, healthcheck ผ่าน JSON worker, ทั้ง 21 ตัวอย่าง,
สำรองปลั๊กอินก่อนติดตั้งซ้ำ, ปฏิเสธการติดตั้งขณะ host เปิดอยู่,
ถอนติดตั้งสำเร็จ, ลบ plugin/runtime ของตัวติดตั้ง,
รักษาไฟล์อื่น/โมเดลตัวอย่าง และ hash ของปลั๊กอินเดิมไม่เปลี่ยน
14 checks รวม setup exit ของสองรอบ จึงไม่ใช่ 14 เครื่อง/สภาพแวดล้อม

Bundled Python 3.12.14 จาก python-build-standalone และ PyNiteFEA 3.2.0
ทดสอบตัวอย่างผ่าน client subprocess และ JSON protocol จริงใน runtime ที่ย้ายตำแหน่งแล้ว
ทั้ง 21 ตัวอย่าง: 19 วิเคราะห์สำเร็จ และ 2 mechanism ต้องถูกปฏิเสธตามคาด
ทดสอบ path ที่มีช่องว่างและตัวอักษร non-ASCII
ตรวจ Program Files/Windows preflight guard เพิ่มแล้ว: ปฏิเสธก่อนเขียน package

หลักฐาน: `artifacts/installer/test-results.json`, setup/blocked logs และ
`examples.json` ในโฟลเดอร์รอบทดสอบ พร้อม `dist/installer-build-manifest.json`
แสดง SHA256 ของ payload และเวอร์ชัน dependencies
SHA256 ของ Setup.exe อยู่ในไฟล์ `.exe.sha256` คู่กับ executable

## Not Tested / ข้อจำกัดที่ทราบ

- Clean Windows VM ที่ไม่มี Python หรือ development tools
- การคลิก Wizard ทีละหน้าด้วย GUI; ทดสอบ executable และ lifecycle แบบ silent จริง
- Cold IngeTrazo restart หลังลงด้วย Setup; ทดสอบปลั๊กอินใน host จริงผ่าน MCP ก่อนหน้านี้
- Windows code-signing/SmartScreen reputation: ตรวจ signature แล้วไฟล์เป็น **NotSigned**

ไม่อ้างว่าสี่รายการนี้ผ่าน จึงจัดชุดนี้เป็นตัวติดตั้งสำหรับทดลองใช้งาน
ต้องติดตั้ง IngeTrazo ที่รองรับ Plugin API v2 อยู่ก่อน ตัว Setup ไม่รวม host
Setup ใช้ `PrivilegesRequired=lowest`, ไม่ติดตั้ง Python ลง PATH และไม่เขียน Program Files
ไม่รวมลายเซ็นดิจิทัลหรือใบรับรองความถูกต้องทางวิศวกรรม

## Build / Run

`packaging/build_installer.py` สร้าง payload จาก runtime และ solver environment ที่ทดสอบแล้ว
ใช้ Inno Setup 6 สำหรับ Windows x64 พร้อมภาษาไทย/อังกฤษ
`packaging/test_installer.ps1` ทดสอบใน directory ใหม่และคืนสภาพหลังถอนติดตั้ง
ดู `packaging/README.md` สำหรับคำสั่งและรูปแบบไฟล์
