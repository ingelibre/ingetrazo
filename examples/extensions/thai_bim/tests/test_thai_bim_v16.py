import copy,importlib,json,sys,tempfile,types,unittest
from pathlib import Path
p=types.ModuleType('tb16pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
C=importlib.import_module('tb16pure.stair_catalogue');S=importlib.import_module('tb16pure.stairs')
class StairLibraryTests(unittest.TestCase):
    def setUp(self):self.data=C.defaults();self.row=copy.deepcopy(self.data['types'][1])
    def test_defaults_six_valid_layouts(self):
        self.assertEqual({r['params']['layout'] for r in C.validate(self.data)['types']},set(S.LAYOUTS))
    def test_deterministic_default_identity(self):self.assertEqual(self.data,C.defaults())
    def test_snapshot_detached(self):
        row=C.snapshot(self.row);row['params']['width']=2;self.assertNotEqual(row['params'],self.row['params'])
    def test_revision_upsert_preserves_others(self):
        self.row['revision']+=1;self.row['name']='บันได L';result=C.upsert(self.data,self.row)
        self.assertEqual(result['types'][-1],self.row);self.assertEqual(len(result['types']),6);self.assertNotEqual(result,self.data)
    def test_revision_conflict(self):
        with self.assertRaises(ValueError):C.upsert(self.data,self.row)
    def test_new_type_requires_revision_one(self):
        row=C.stair_type('ST-X','New',self.row['params'],self.row['rebar'],revision=2)
        with self.assertRaises(ValueError):C.upsert(self.data,row)
    def test_duplicate_code_casefold(self):
        row=C.stair_type(self.row['code'].lower(),'copy',self.row['params'],self.row['rebar'])
        with self.assertRaises(ValueError):C.upsert(self.data,row)
    def test_duplicate_id(self):
        with self.assertRaises(ValueError):C.validate(dict(schema=1,types=[self.row,self.row]))
    def test_unicode_atomic_roundtrip(self):
        self.row['name']='บันไดครอบครัว';self.row['rebar']['extra_connections']=[dict(name='เหล็กต่อ',x=0,y=0,z=0,angle=0,length=.3,leg=.1,count=2,spacing=.15)]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'คลัง.json';C.write(path,dict(schema=1,types=[self.row]));self.assertEqual(C.read(path)['types'][0],C.snapshot(self.row));self.assertEqual(len(list(Path(d).iterdir())),1)
    def test_invalid_write_preserves_file(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'data.json';C.write(path,self.data);old=path.read_bytes()
            with self.assertRaises(ValueError):C.write(path,{'schema':1,'types':[{}]})
            self.assertEqual(path.read_bytes(),old)
    def test_legacy_schema_rejected(self):
        row=copy.deepcopy(self.row);row['kind']='Stair'
        with self.assertRaises(ValueError):C.snapshot(row)
    def test_unknown_fields_rejected(self):
        self.row['params']['x']=10
        with self.assertRaises(ValueError):C.snapshot(self.row)
    def test_bad_rebar_fit_rejected(self):
        self.row['rebar']['cover']=.1
        with self.assertRaises(ValueError):C.snapshot(self.row)
    def test_nonfinite_rejected(self):
        self.row['rebar']['spacing']=float('nan')
        with self.assertRaises(ValueError):C.snapshot(self.row)
    def test_numeric_boolean_rejected(self):
        self.row['params']['risers']=True
        with self.assertRaises(ValueError):C.snapshot(self.row)
    def test_landing_boolean_strict(self):
        self.row['params']['top_landing']='false'
        with self.assertRaises(ValueError):C.snapshot(self.row)
    def test_bounded_connection_schema(self):
        self.row['rebar']['extra_connections']=[dict(name='bar',x=0)]
        with self.assertRaises(ValueError):C.snapshot(self.row)
    def test_full_representation_kept(self):
        self.row['rebar']['representation']='Full';self.assertEqual(C.snapshot(self.row)['rebar']['representation'],'Full')
    def test_bad_identity(self):
        self.row['id']='bad'
        with self.assertRaises(ValueError):C.snapshot(self.row)
    def test_file_size_guard(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'big.json';path.write_bytes(b' '*4_000_001)
            with self.assertRaises(ValueError):C.read(path)
    def test_empty_library_preserved(self):self.assertEqual(C.validate(dict(schema=1,types=[])),dict(schema=1,types=[]))
if __name__=='__main__':unittest.main()
