import importlib,sys,types,unittest,copy,tempfile
from pathlib import Path
p=types.ModuleType('tb11pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
R=importlib.import_module('tb11pure.rebar_recipe');C=importlib.import_module('tb11pure.catalogue');S=importlib.import_module('tb11pure.steel');D=importlib.import_module('tb11pure.detailing')
class RecipeTests(unittest.TestCase):
    def row(self,kind='Beam'):
        r=next(r for r in C.defaults()['types'] if r['kind']==kind);r['rebar']=R.defaults();return C.snapshot(r)
    def test_all_five_kinds_and_old_library(self):
        self.assertTrue(all(r['rebar'] is None for r in C.defaults()['types']))
        for kind in C.KINDS:self.assertEqual(self.row(kind)['rebar'],R.defaults())
    def test_snapshot_nested_isolation_and_revision(self):
        row=self.row();snap=C.snapshot(row);row['rebar']['main_steel']['grade']='SD50';row['revision']+=1
        self.assertEqual(snap['rebar']['main_steel']['grade'],'SD40');self.assertEqual(snap['revision'],1)
    def test_portable_unicode_and_atomic_invalid_write(self):
        row=self.row();row['name']='คานบ้านไทย';data=C.upsert(C.defaults(),row)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ชนิดเหล็ก.json';C.write(path,data);self.assertEqual(C.read(path),data)
            bad=copy.deepcopy(data);bad['types'][-1]['rebar']['cover']=-40
            with self.assertRaises(ValueError):C.write(path,bad)
            self.assertEqual(C.read(path),data)
    def test_invalid_fields_and_counts(self):
        for key,value in [('count_x',2.5),('layers',True),('spacing',float('nan')),('cover',0),('representation','Mesh')]:
            p=R.defaults();p[key]=value
            with self.assertRaises(ValueError):R.validate('Beam',p)
        for p in ({},dict(R.defaults(),unknown=1)):
            with self.assertRaises(ValueError):R.validate('Beam',p)
    def test_steel_nominal_diameter_and_astm_units(self):
        p=R.defaults();p['main_steel']=S.selection(S.ASTM_IN,'#9','Grade 60 [420]');p['diameter']=p['main_steel']['diameter_mm']
        self.assertAlmostEqual(R.validate('Beam',p)['diameter'],28.6512)
        p['diameter']=28.7
        with self.assertRaises(ValueError):R.validate('Beam',p)
        p=R.defaults();p['tie_steel']=None;p['tie_diameter']=7;self.assertIsNone(R.validate('Beam',p)['tie_steel'])
    def test_kind_specific_impossible_details(self):
        for kind,key,value in [('Footing','lap_length',100),('Slab','extension_end',100),('Column','hook_length',50),('Beam','hook_length',50),('Stair','layers',2),('Stair','lap_length',200)]:
            p=R.defaults();p[key]=value
            with self.assertRaises(ValueError):R.validate(kind,p)
        p=R.defaults();p.update(hook_length=20,extension_start=50)
        with self.assertRaises(ValueError):R.validate('Stair',p)
    def test_provenance_hash_override_and_forgery(self):
        row=self.row();source=R.source(row);p=copy.deepcopy(row['rebar'])
        self.assertFalse(R.provenance('Beam',source,p)['overridden']);p['spacing']=200
        self.assertTrue(R.provenance('Beam',source,p)['overridden'])
        source['recipe']['cover']=50
        with self.assertRaises(ValueError):R.provenance('Beam',source,p)
    def test_recipe_does_not_claim_actual_fit(self):
        p=R.validate('Beam',R.defaults())
        for key in ('cover','diameter','tie_diameter','spacing','inside_radius','tie_inside_radius','hook_length','tie_hook_length','lap_length','extension_start','extension_end'):p[key]/=1000
        with self.assertRaises(ValueError):D.reinforcement('Beam',dict(x=0,y=0,z=0,width=1,depth=.06,height=.06),**p)
