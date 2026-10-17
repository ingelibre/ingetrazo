"""Independent native PDF geometry/physical scale and XLSX BBS correspondence."""
import json,re
from pathlib import Path
import pdfplumber,openpyxl
root=Path(__file__).resolve().parents[1];folder=root/'verification-local';report=[]
def inspect(path,scale=50,bbs=None,width=1.4):
 texts=[];count=0
 with pdfplumber.open(path) as pdf:
  for page in pdf.pages:
   assert abs(page.width*25.4/72-420)<.3 and abs(page.height*25.4/72-297)<.3
   text=page.extract_text() or '';texts.append(text);count+=1
   assert page.lines and not page.images and 'MODEL DETAIL / REVIEW' in text
   for word in page.extract_words():assert word['x0']>=9 and word['x1']<=page.width-9 and word['top']>=9 and word['bottom']<=page.height-9,(path.name,page.page_number,word)
   if 'BBS SCHEDULE' in text:assert 'NTS' in text
   else:
    assert '1:'+str(scale) in text
    rectangles=[r for r in page.rects if r['x0']<100 and r['top']>page.height-100 and r['height']<10]
    expected=(1000 if scale==50 else 500)/scale
    assert any(abs(r['width']*25.4/72-expected)<.02 for r in rectangles),(path.name,page.page_number)
  # An actual projected concrete edge, separate from the footer scale bar.
  assert any(abs(line['height'])<.02 and abs(line['width']*25.4/72-width*1000/scale)<.02 and 45<line['top']*25.4/72<217 for line in pdf.pages[0].lines),path.name
 if bbs:
  work=openpyxl.load_workbook(bbs,data_only=True);rows=list(work.worksheets[0].values)
  expected={str(r[1]):int(r[4]) for r in rows[1:] if r[1]};marks=set(re.findall(r'B-[A-F0-9]{12}','\n'.join(texts)))
  assert marks==set(expected),(path.name,marks,set(expected))
  # BBS vector table preserves quantity and cut length on the same extracted line.
  for mark,qty in expected.items():
   row=next(r for r in rows[1:] if str(r[1])==mark)
   matches=[line for text in texts for line in text.splitlines() if line.startswith(mark)]
   assert any(re.search(r'\b'+str(qty)+r'\b',line) and f'{row[5]:.3f}' in line for line in matches),(mark,matches)
  if path.name.startswith('Footing'):assert '+3.600' in texts[1] and '+4.100' in texts[1]
 report.append(dict(file=path.name,pages=count,scale=scale,vector=True,marks=len(expected) if bbs else None,model_width_mm=width*1000/scale))
for kind,width in [('Footing',1.4),('Column',.4),('Beam',4),('Slab',3),('Slab-Two-way',3),('Slab-Precast',3),('Slab-Polygon',3)]:inspect(folder/(kind+'-A3-50.pdf'),bbs=folder/(kind+'-BBS.xlsx'),width=width)
for scale in (20,25):inspect(folder/('Footing-scale-'+str(scale)+'-A3.pdf'),scale=scale)
data=dict(version='0.20.0',verified=report,total_pages=sum(r['pages'] for r in report));(folder/'member-pdf-qa.json').write_text(json.dumps(data,indent=2),encoding='utf8')
print('PASS independent member PDF:',data['total_pages'],'pages; physical scales / projected geometry / Bar Marks / counts / cut lengths / world levels')
