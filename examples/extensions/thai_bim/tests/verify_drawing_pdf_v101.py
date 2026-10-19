"""Verify physical scale and vector output independently of the modeling API."""
import json,hashlib
from pathlib import Path
import pdfplumber
root=Path(__file__).resolve().parents[1]
folder=root/'verification-local'
path=folder/'Thai-BIM-drawings-1-50.pdf'
report=[]
with pdfplumber.open(path) as pdf:
    assert len(pdf.pages)==5
    for page,code in zip(pdf.pages,('A101','A102','A201','A202','A301')):
        width,height=page.width*25.4/72,page.height*25.4/72
        assert abs(width-420)<.2 and abs(height-297)<.2
        text=page.extract_text()
        assert code in text and '1:50 @ A3' in text and 'FOR COORDINATION' in text
        assert '3000 mm' in text if code in ('A101','A102','A201') else '4000 mm' in text
        if code in ('A201','A202','A301'):assert '+3.750' in text and '+3.650' in text
        assert len(page.lines)>100 and not page.images
        bars=[r for r in page.rects if r['x0']<300 and r['top']>780 and 6<r['height']<8]
        assert len(bars)==4
        widths=[r['width']*25.4/72 for r in bars]
        assert all(abs(w-20)<.001 for w in widths),widths
        # Check model projection, separately from the decorative scale bar.
        span=60 if code in ('A101','A102','A201') else 80
        dims=[l for l in page.lines if abs(l['y0']-l['y1'])<.001 and abs(l['width']*25.4/72-span)<.001]
        assert dims,code
        report.append(dict(sheet=code,paper_mm=[width,height],vector_lines=len(page.lines),
                           raster_images=len(page.images),metre_scale_segments_mm=widths,
                           measured_grid_dimension_paper_mm=span))
out=dict(version='0.10.1',pages=report,pdf_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
         visual_review='All five Poppler-rendered pages inspected; explicit levels separated with leaders; synthetic coordination fixture, not construction design')
(folder/'pdf-qa.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print('PASS: 5 A3 vector pages; model grid projection and 1 m scale segments physically verified at 1:50')
