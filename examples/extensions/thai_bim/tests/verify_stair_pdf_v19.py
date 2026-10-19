"""Independent PDF physical-scale, vector, Bar Mark and XLSX verification."""
import json,re,math
from pathlib import Path
import pdfplumber,openpyxl
root=Path(__file__).resolve().parents[1];folder=root/'verification-local';report=[]
for layout in ('Straight','L','U','Spiral','Circular','Floating'):
 path=folder/f'stair-{layout}-A3-50.pdf';work=openpyxl.load_workbook(folder/f'stair-{layout}-BBS.xlsx',data_only=True)
 summary=work.worksheets[0];rows=list(summary.values);marks={str(r[1]):int(r[4]) for r in rows[1:] if r[1]}
 texts=[];pages=[]
 with pdfplumber.open(path) as pdf:
  for page in pdf.pages:
   text=page.extract_text() or '';texts.append(text)
   assert abs(page.width*25.4/72-420)<.3 and abs(page.height*25.4/72-297)<.3
   assert not page.images and 'MODEL DETAIL / REVIEW' in text
   assert page.lines and not any('□' in word['text'] for word in page.extract_words())
   for word in page.extract_words():assert word['x0']>=9 and word['x1']<=page.width-9 and word['top']>=9 and word['bottom']<=page.height-9,(path.name,page.page_number,word)
   if 'BBS SCHEDULE' in text:
    assert 'NTS' in text
   else:
    assert '1:50' in text
    rects=[r for r in page.rects if r['x0']<100 and r['top']>page.height-100 and r['height']<10]
    assert any(abs(r['width']*25.4/72-20)<.02 for r in rects),(layout,page.page_number)
   pages.append(dict(number=page.page_number,lines=len(page.lines),images=len(page.images)))
  alltext='\n'.join(texts);pdfmarks=set(re.findall(r'B-[A-F0-9]{12}',alltext));assert pdfmarks==set(marks),(layout,pdfmarks,set(marks))
  # Rotated dimension text is not reliably ordered by PDF text extraction.
  # Verify projected 1m geometry in the drawing body, separately from footer scale bars.
  model_lines=[l for l in pdf.pages[0].lines if 45<l['top']*25.4/72<217 and 38<l['x0']*25.4/72<312 and (abs(l['height']*25.4/72-20)<.02 or abs(l['width']*25.4/72-20)<.02)]
  assert model_lines,layout
  if layout=='Straight':assert '+3.750' in texts[1] and '+6.750' in texts[1]
  report.append(dict(file=path.name,pages=len(pdf.pages),marks=len(marks),bar_count=sum(marks.values()),vector=True,paper_mm=[420,297],scale=50,checks=pages))
for n,paper,size in [(20,'A1',(841,594)),(25,'A2',(594,420))]:
 path=folder/f'stair-scale-{n}-{paper}.pdf'
 with pdfplumber.open(path) as pdf:
  p=pdf.pages[0];assert abs(p.width*25.4/72-size[0])<.3 and abs(p.height*25.4/72-size[1])<.3
  rects=[r for r in p.rects if r['x0']<300 and r['top']>p.height-100 and r['height']<10];assert any(abs(r['width']*25.4/72-500/n)<.02 for r in rects)
  # Check an actual projected model width, independently of the scale bar.
  lines=[l for l in p.lines if abs(l['x0']-l['x1'])<.02 and abs(l['height']*25.4/72-1000/n)<.02];assert lines
  report.append(dict(file=path.name,pages=len(pdf.pages),paper_mm=list(size),scale=n,model_width_mm=1000/n))
(folder/'stair-pdf-qa.json').write_text(json.dumps(dict(version='0.19.0',verified=report,total_pages=sum(r['pages'] for r in report)),indent=2),encoding='utf8')
print('PASS independent PDF: '+str(sum(r['pages'] for r in report))+' vector pages; all scales and all six Bar Mark sets match XLSX')
