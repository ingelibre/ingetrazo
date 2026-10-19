import importlib.util
import math
from pathlib import Path
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
import openpyxl

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('tb_engine',ROOT/'engine.py')
E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)


def signed_volume(faces):
    result=0
    for f in faces:
        for i in range(1,len(f)-1): result+=E.dot(f[0],E.cross(f[i],f[i+1]))/6
    return result


class EngineTests(unittest.TestCase):
    def test_box_solid_winding_and_volume(self):
        s=E.box_spec('Column',100,-80,3.65,.2,.3,2.6)
        self.assertAlmostEqual(signed_volume(s['faces']),.156,places=8)
        edges={}
        for f in s['faces']:
            for a,b in zip(f,f[1:]+f[:1]):
                key=tuple(sorted((a,b)));edges.setdefault(key,[]).append((a,b))
        self.assertTrue(all(len(v)==2 and v[0]==v[1][::-1] for v in edges.values()))

    def test_roof_sections_envelope_and_positive_solids(self):
        p=E.batten_profile()
        self.assertAlmostEqual(max(x for x,y in p)-min(x for x,y in p),.061,places=10)
        self.assertAlmostEqual(max(y for x,y in p)-min(y for x,y in p),.027,places=10)
        specs=E.roof_specs(width=6,depth=4,pitch=30)
        self.assertEqual(len([s for s in specs if s['kind']=='Rafter']),12)
        self.assertEqual(len({s['slot'] for s in specs}),len(specs))
        for s in specs:
            self.assertGreater(signed_volume(s['faces']),0,s['slot'])
            if 'section_area_m2' in s:
                self.assertAlmostEqual(signed_volume(s['faces']),s['section_area_m2']*s['quantity'],places=9)
        covers=[s for s in specs if s['unit']=='m2']
        self.assertAlmostEqual(sum(s['quantity'] for s in covers),2*(3.4/math.cos(math.pi/6))*4.8)

    def test_invalid_inputs_and_spacing_limits(self):
        for kw in ({'width':0},{'pitch':0},{'pitch':float('nan')},{'batten_spacing':0},{'depth':1000}):
            with self.assertRaises(ValueError): E.roof_specs(**kw)
        with self.assertRaises(ValueError): E.box_spec('Beam',0,0,0,-1,1,1)
        with self.assertRaises(ValueError): E.coordinates('0,0,3')
        with self.assertRaises(ValueError): E.levels('GF=0\nGF=3')
        for length in [1.1,2,3.7,8]:
            s=E.stations(length,.3,.05)
            self.assertAlmostEqual(s[-1],length-.05)
            self.assertLessEqual(max(b-a for a,b in zip(s,s[1:])),.300001)

    def test_xlsx_round_trip_thai_units_and_formula_safety(self):
        rows=[dict(id='a',name='เสาชั้นบน',discipline='Structure',item='RC Column',unit='m3',quantity=.156,basis='Measured',source='แบบ +3.65',note=''),
              dict(id='b',name='=1+2',discipline='Structure',item='RC Column',unit='m3',quantity=None,basis='Unverified',source='PDF',note='Edited'),
              dict(id='c',name='แป',discipline='Structure',item='Batten',unit='m',quantity=4.8,basis='Net',source='User',note='No laps')]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'ไทย.xlsx';E.write_xlsx(path,rows,['ตรวจระยะแป'])
            with zipfile.ZipFile(path) as z:
                self.assertIsNone(z.testzip())
                for n in z.namelist(): ET.fromstring(z.read(n))
            wb=openpyxl.load_workbook(path,data_only=False)
            self.assertEqual(wb.sheetnames,['Summary','Elements','Issues'])
            self.assertEqual(wb['Elements']['B2'].value,'เสาชั้นบน')
            self.assertEqual(wb['Elements']['B3'].value,'=1+2')
            self.assertEqual(wb['Elements']['B3'].data_type,'s')
            self.assertEqual(wb['Elements']['F2'].value,.156)
            self.assertIsNone(wb['Elements']['F3'].value)
            self.assertEqual(wb['Issues']['A2'].value,'ตรวจระยะแป')
            wb.close()
            csvpath=Path(d)/'ไทย.csv';E.write_csv(csvpath,rows)
            self.assertTrue(csvpath.read_bytes().startswith(b'\xef\xbb\xbf'))
            self.assertIn("'=1+2",csvpath.read_text(encoding='utf-8-sig'))


if __name__=='__main__': unittest.main()
