from pathlib import Path
import json
r=Path(__file__).resolve().parents[1]
t=(r/'tests/verify_member_pdf_v20.py').read_text(encoding='utf-8-sig').split('for kind,width in')[0].replace('verification-v20','verification-v21')
exec(compile(t,'independent-pdf-check','exec'))
for mode in ('One-way','Two-way','Precast'):
 inspect(folder/(mode+'-opening-A3-50.pdf'),bbs=folder/(mode+'-opening-BBS.xlsx'),width=4)
 with pdfplumber.open(folder/(mode+'-opening-A3-50.pdf')) as pdf:
  # Closed 1m square hole is a separate vector outline in the real plan.
  # Slice-axis vertices split each outline edge into two 500 mm segments.
  expected=500/50*72/25.4
  assert sum(abs(q['width']-expected)<.02 and q['height']<.02 for q in pdf.pages[0].lines)>=4
  assert sum(abs(q['height']-expected)<.02 and q['width']<.02 for q in pdf.pages[0].lines)>=4
(folder/'pdf-qa.json').write_text(json.dumps(dict(version='0.21.0',verified=report,total_pages=sum(v['pages'] for v in report)),indent=2),encoding='utf8')
print('PASS',sum(v['pages'] for v in report),'vector pages; true hole outline; exact scale; actual BBS marks/counts/lengths')
