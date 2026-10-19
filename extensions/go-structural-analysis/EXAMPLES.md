# ตัวอย่าง GO Structural Analysis v0.1.3

เปิด Extensions → GO Structural Analysis → Model เลื่อนลงถึง Engineering Examples / Benchmarks
เลือกตัวอย่าง → Load selected example → Run Analysis → Results เลือก Load Case และ Diagram
หาก workspace เดิมมีข้อมูลที่ยังไม่บันทึก ระบบถามก่อนแทนที่; Save เก็บตัวอย่างเดิมได้

ตัวอย่าง Stability สองรายการต้อง Analysis failed เพราะเป็น mechanism ไม่ใช่โครงสร้างที่เสถียร
Passed ในหลักฐานหมายถึง solver ปฏิเสธได้ถูกต้อง

[เปิดแกลเลอรีครบชุด](artifacts/examples-v0.1.3/index.html)

| ตัวอย่าง | Live test | ภาพหน้าจอจริง |
|---|---|---|
| Simply Supported Beam — UDL | Passed | [model](artifacts/examples-v0.1.3/simple_udl-model.png) · [loads](artifacts/examples-v0.1.3/simple_udl-loads.png) · [results](artifacts/examples-v0.1.3/simple_udl-results.png) · [deformed](artifacts/examples-v0.1.3/simple_udl-deformed.png) |
| Simply Supported Beam — Point Load | Passed | [model](artifacts/examples-v0.1.3/simple_point-model.png) · [loads](artifacts/examples-v0.1.3/simple_point-loads.png) · [results](artifacts/examples-v0.1.3/simple_point-results.png) · [deformed](artifacts/examples-v0.1.3/simple_point-deformed.png) |
| Cantilever — Point Load | Passed | [model](artifacts/examples-v0.1.3/cantilever_point-model.png) · [loads](artifacts/examples-v0.1.3/cantilever_point-loads.png) · [results](artifacts/examples-v0.1.3/cantilever_point-results.png) · [deformed](artifacts/examples-v0.1.3/cantilever_point-deformed.png) |
| Cantilever — UDL | Passed | [model](artifacts/examples-v0.1.3/cantilever_udl-model.png) · [loads](artifacts/examples-v0.1.3/cantilever_udl-loads.png) · [results](artifacts/examples-v0.1.3/cantilever_udl-results.png) · [deformed](artifacts/examples-v0.1.3/cantilever_udl-deformed.png) |
| Continuous Beam — 2 spans | Passed | [model](artifacts/examples-v0.1.3/continuous_2-model.png) · [loads](artifacts/examples-v0.1.3/continuous_2-loads.png) · [results](artifacts/examples-v0.1.3/continuous_2-results.png) · [deformed](artifacts/examples-v0.1.3/continuous_2-deformed.png) |
| Continuous Beam — 3 spans | Passed | [model](artifacts/examples-v0.1.3/continuous_3-model.png) · [loads](artifacts/examples-v0.1.3/continuous_3-loads.png) · [results](artifacts/examples-v0.1.3/continuous_3-results.png) · [deformed](artifacts/examples-v0.1.3/continuous_3-deformed.png) |
| Portal Frame — Vertical load | Passed | [model](artifacts/examples-v0.1.3/portal_vertical-model.png) · [loads](artifacts/examples-v0.1.3/portal_vertical-loads.png) · [results](artifacts/examples-v0.1.3/portal_vertical-results.png) · [deformed](artifacts/examples-v0.1.3/portal_vertical-deformed.png) |
| Portal Frame — Horizontal load | Passed | [model](artifacts/examples-v0.1.3/portal_horizontal-model.png) · [loads](artifacts/examples-v0.1.3/portal_horizontal-loads.png) · [results](artifacts/examples-v0.1.3/portal_horizontal-results.png) · [deformed](artifacts/examples-v0.1.3/portal_horizontal-deformed.png) |
| Inclined Frame — Transformation | Passed | [model](artifacts/examples-v0.1.3/inclined-model.png) · [loads](artifacts/examples-v0.1.3/inclined-loads.png) · [results](artifacts/examples-v0.1.3/inclined-results.png) · [deformed](artifacts/examples-v0.1.3/inclined-deformed.png) |
| 2D Truss — Joint load | Passed | [model](artifacts/examples-v0.1.3/truss-model.png) · [loads](artifacts/examples-v0.1.3/truss-loads.png) · [results](artifacts/examples-v0.1.3/truss-results.png) · [deformed](artifacts/examples-v0.1.3/truss-deformed.png) |
| Member Release — j end | Passed | [model](artifacts/examples-v0.1.3/release_j-model.png) · [loads](artifacts/examples-v0.1.3/release_j-loads.png) · [results](artifacts/examples-v0.1.3/release_j-results.png) · [deformed](artifacts/examples-v0.1.3/release_j-deformed.png) |
| Member Releases — both ends | Passed | [model](artifacts/examples-v0.1.3/release_both-model.png) · [loads](artifacts/examples-v0.1.3/release_both-loads.png) · [results](artifacts/examples-v0.1.3/release_both-results.png) · [deformed](artifacts/examples-v0.1.3/release_both-deformed.png) |
| Stability — released mechanism (loaded) | Passed | [model](artifacts/examples-v0.1.3/unstable_loaded-model.png) · [loads](artifacts/examples-v0.1.3/unstable_loaded-loads.png) · [results](artifacts/examples-v0.1.3/unstable_loaded-results.png) |
| Stability — released mechanism (unloaded) | Passed | [model](artifacts/examples-v0.1.3/unstable_unloaded-model.png) · [loads](artifacts/examples-v0.1.3/unstable_unloaded-loads.png) · [results](artifacts/examples-v0.1.3/unstable_unloaded-results.png) |
| Multiple Load Cases — self-weight OFF | Passed | [model](artifacts/examples-v0.1.3/cases_off-model.png) · [loads](artifacts/examples-v0.1.3/cases_off-loads.png) · [results](artifacts/examples-v0.1.3/cases_off-results.png) · [deformed](artifacts/examples-v0.1.3/cases_off-deformed.png) |
| Multiple Load Cases — self-weight ON | Passed | [model](artifacts/examples-v0.1.3/cases_on-model.png) · [loads](artifacts/examples-v0.1.3/cases_on-loads.png) · [results](artifacts/examples-v0.1.3/cases_on-results.png) · [deformed](artifacts/examples-v0.1.3/cases_on-deformed.png) |
| 2D Truss — self-weight ON | Passed | [model](artifacts/examples-v0.1.3/truss_weight-model.png) · [loads](artifacts/examples-v0.1.3/truss_weight-loads.png) · [results](artifacts/examples-v0.1.3/truss_weight-results.png) · [deformed](artifacts/examples-v0.1.3/truss_weight-deformed.png) |
| Exact Extrema — off-grid point load | Passed | [model](artifacts/examples-v0.1.3/off_grid-model.png) · [loads](artifacts/examples-v0.1.3/off_grid-loads.png) · [results](artifacts/examples-v0.1.3/off_grid-results.png) · [deformed](artifacts/examples-v0.1.3/off_grid-deformed.png) |
| Exact Extrema — triangular UDL | Passed | [model](artifacts/examples-v0.1.3/triangular-model.png) · [loads](artifacts/examples-v0.1.3/triangular-loads.png) · [results](artifacts/examples-v0.1.3/triangular-results.png) · [deformed](artifacts/examples-v0.1.3/triangular-deformed.png) |
| Axial — distributed load | Passed | [model](artifacts/examples-v0.1.3/axial-model.png) · [loads](artifacts/examples-v0.1.3/axial-loads.png) · [results](artifacts/examples-v0.1.3/axial-results.png) · [deformed](artifacts/examples-v0.1.3/axial-deformed.png) |
| Moment — concentrated member moment | Passed | [model](artifacts/examples-v0.1.3/moment_jump-model.png) · [loads](artifacts/examples-v0.1.3/moment_jump-loads.png) · [results](artifacts/examples-v0.1.3/moment_jump-results.png) · [deformed](artifacts/examples-v0.1.3/moment_jump-deformed.png) |
