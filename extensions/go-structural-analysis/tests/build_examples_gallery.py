"""Build an inspectable gallery from actual live captures, without invented images."""
import html
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'go_structural_analysis'))
from examples import CATALOG

ROOT=Path(__file__).parents[1]
OUT=ROOT/'artifacts/examples-v0.1.3'

def main():
    checks=json.loads((OUT/'live-results.json').read_text(encoding='utf-8'))
    statuses={row.get('key'):row for row in checks}
    cards=[]
    rows=[]
    for key,title,description in CATALOG:
        status=statuses.get(key,{}).get('status','Not Tested')
        images=[]
        links=[]
        for mode in ['model','loads','results','deformed']:
            name=f'{key}-{mode}.png'
            if (OUT/name).is_file():
                images.append(f'<a href="{name}"><img loading="lazy" src="{name}" alt="{html.escape(title)} {mode}"><span>{mode}</span></a>')
                links.append(f'[{mode}](artifacts/examples-v0.1.3/{name})')
        cards.append(f'<article><h2>{html.escape(title)}</h2><p>{html.escape(description)}</p><strong>{status}</strong><div class="images">'+''.join(images)+'</div></article>')
        rows.append(f'| {title} | {status} | '+ ' · '.join(links)+' |')
    (OUT/'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>GO Structural v0.1.3 — 21 Examples</title><style>body{font:16px system-ui;margin:32px;background:#edf1f5;color:#182d43}h1{font-size:32px}article{background:white;padding:24px;margin:24px 0;border-radius:12px}.images{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}img{width:100%;border:1px solid #d4dce5}a{color:#234b79}span{display:block;padding:8px}strong{color:#286640}@media(max-width:850px){.images{grid-template-columns:1fr}}</style><h1>GO Structural Analysis v0.1.3 — 21 Examples</h1><p>Actual IngeTrazo window captures. Stability examples must fail analysis; Passed means the rejection worked.</p>'+''.join(cards)+'</html>',encoding='utf-8')
    (ROOT/'EXAMPLES.md').write_text('# ตัวอย่าง GO Structural Analysis v0.1.3\n\nเปิด Extensions → GO Structural Analysis → Model เลื่อนลงถึง Engineering Examples / Benchmarks\nเลือกตัวอย่าง → Load selected example → Run Analysis → Results เลือก Load Case และ Diagram\nหาก workspace เดิมมีข้อมูลที่ยังไม่บันทึก ระบบถามก่อนแทนที่; Save เก็บตัวอย่างเดิมได้\n\nตัวอย่าง Stability สองรายการต้อง Analysis failed เพราะเป็น mechanism ไม่ใช่โครงสร้างที่เสถียร\nPassed ในหลักฐานหมายถึง solver ปฏิเสธได้ถูกต้อง\n\n[เปิดแกลเลอรีครบชุด](artifacts/examples-v0.1.3/index.html)\n\n| ตัวอย่าง | Live test | ภาพหน้าจอจริง |\n|---|---|---|\n'+'\n'.join(rows)+'\n',encoding='utf-8')
    print(f'Gallery: {OUT / "index.html"}')

if __name__=='__main__': main()
