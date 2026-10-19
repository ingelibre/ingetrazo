import importlib,sys,types,unittest,math
from pathlib import Path
p=types.ModuleType('tb07pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
C=importlib.import_module('tb07pure.steel');D=importlib.import_module('tb07pure.detailing');E=importlib.import_module('tb07pure.engine')
class V07Tests(unittest.TestCase):
    def test_catalogue_exceptions_and_units(self):
        self.assertEqual([x['size'] for x in C.entries(C.ASTM_SI)],['#3','#4','#5','#6','#7','#8','#9','#10','#11','#14','#18'])
        for size,inch,mm in [('#9',1.128,28.7),('#14',1.693,43),('#18',2.257,57.3)]:
            a=C.selection(C.ASTM_SI,size,'Grade 60 [420]');b=C.selection(C.ASTM_IN,size,'Grade 60 [420]')
            self.assertEqual(a['diameter_mm'],mm);self.assertAlmostEqual(b['diameter_mm'],inch*25.4)
        with self.assertRaises(ValueError):C.selection(C.ASTM_SI,'#12','Grade 60 [420]')
        with self.assertRaises(ValueError):C.selection(C.ASTM_SI,'#18','Grade 40 [280]')
    def test_tis_surface_and_mismatched_size(self):
        rb=C.selection(C.TIS_RB,'RB9','SR24');db=C.selection(C.TIS_DB,'DB12','SD40')
        self.assertEqual(rb['surface'],'Plain');self.assertEqual(db['surface'],'Deformed')
        with self.assertRaises(ValueError):C.validate(db,10)
        with self.assertRaises(ValueError):C.selection(C.TIS_RB,'RB16','SR24')
    def test_quality_changes_preserve_analytic_bbs(self):
        host=E.box_spec('Column',0,0,0,.3,.3,3)['params']
        variants=[D.reinforcement('Column',host,representation=q) for q in ('Full','Lightweight','Centreline')]
        for a,b,c in zip(*variants):
            self.assertEqual(a['bbs'],b['bbs']);self.assertEqual(a['bbs'],c['bbs']);self.assertFalse(c['faces'])
        faces=[sum(len(b['faces']) for b in v) for v in variants]
        self.assertLess(faces[1],faces[0]*.3);self.assertEqual(faces[2],0)
    def test_rb_db_grade_separation_and_bbs_columns(self):
        pts=[(0,0,0),(1,0,0)];a=D.bent_bar('a',pts,.012)
        b=D.bent_bar('b',pts,.012)
        C.tag(a,C.selection(C.TIS_DB,'DB12','SD40'));C.tag(b,C.selection(C.TIS_RB,'RB12','SR24'))
        self.assertNotEqual(a['bbs']['mark'],b['bbs']['mark']);self.assertEqual(a['quantity'],b['quantity'])
        records=[dict(id='a',host_uid='host',bbs=a['bbs']),dict(id='b',host_uid='host',bbs=b['bbs'])]
        table=D.tables(records)[0][1];self.assertEqual(len(table),3)
        self.assertTrue(all(len(row)==len(table[0]) for row in table))
    def test_large_us_size(self):
        record=C.selection(C.ASTM_SI,'#18','Grade 60 [420]')
        host=E.box_spec('Footing',0,0,0,2,2,.6)['params']
        bars=D.reinforcement('Footing',host,diameter=.0573,inside_radius=.06,representation='Centreline',main_steel=record)
        self.assertTrue(bars);self.assertTrue(all(b['steel']['size']=='#18' for b in bars))
        self.assertAlmostEqual(bars[0]['bbs']['unit_mass_kg_m'],math.pi*.0573**2/4*7850)
if __name__=='__main__':unittest.main()
