import importlib,sys,types,unittest,tempfile,copy,math
from pathlib import Path
p=types.ModuleType('tb10pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
C=importlib.import_module('tb10pure.catalogue');G=importlib.import_module('tb10pure.path_geometry');P=importlib.import_module('tb10pure.placement')
class V10Tests(unittest.TestCase):
    def test_types_validate_unique_and_snapshots(self):
        d=C.defaults();self.assertEqual(len(d['types']),5)
        row=d['types'][2];snap=C.snapshot(row);row['params']['depth']=.3
        self.assertEqual(snap['params']['depth'],.2)
        duplicate=copy.deepcopy(row);duplicate['id']=d['types'][0]['id'];d['types'].append(duplicate)
        with self.assertRaises(ValueError):C.validate(d)
    def test_unicode_library_atomic_roundtrip(self):
        d=C.defaults();d['types'][0]['name']='ฐานรากบ้านไทย'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ชนิด.json';C.write(path,d);self.assertEqual(C.read(path),C.validate(d))
            with self.assertRaises(ValueError):C.write(path,dict(schema=99,types=[]))
            self.assertEqual(C.read(path),C.validate(d))
    def test_type_edit_retains_identity_and_enforces_kind(self):
        d=C.defaults();r=copy.deepcopy(d['types'][0]);r['revision']+=1;r['params']['width']=2
        result=C.upsert(d,r);self.assertEqual(len(result['types']),5);self.assertEqual(d['types'][0]['params']['width'],1.2)
        r['kind']='Column'
        with self.assertRaises(ValueError):C.upsert(d,r)
        with self.assertRaises(ValueError):C.member_type('Stair','ST','stairs',dict(C.DEFAULTS['Stair'],risers=2.5))
    def test_beam_two_points_axis_and_volume(self):
        sp,m=G.beam((1,2),(4,6),3,dict(depth=.2,height=.4));self.assertAlmostEqual(sp['quantity'],.4)
        self.assertEqual(P.point(m,(0,0,0)),(1,2,3));b=P.point(m,(5,0,0))
        self.assertAlmostEqual(b[0],4);self.assertAlmostEqual(b[1],6)
        with self.assertRaises(ValueError):G.beam((0,0),(0,0),0,dict(depth=.2,height=.4))
    def test_rectangle_reverse_corners(self):
        sp,m=G.rectangle((6,4),(0,0),2,dict(height=.15))
        self.assertAlmostEqual(sp['quantity'],3.6);self.assertEqual(P.point(m,(0,0,0)),(0,0,2))
    def test_concave_slab_and_bad_polygons(self):
        shape=[(0,0),(4,0),(4,2),(2,2),(2,4),(0,4)]
        for pts in (shape,list(reversed(shape))):
            sp,m=G.polygon(pts,3,dict(height=.15));self.assertAlmostEqual(sp['quantity'],1.8)
            self.assertEqual(sp['params']['shape'],'polygon')
        for pts in ([(0,0),(2,2),(0,2),(2,0)],[(0,0),(2,0),(1,0),(1,1)],[(0,0),(0,0),(1,1)]):
            with self.assertRaises(ValueError):G.polygon(pts,0,dict(height=.15))
    def test_stair_direction_does_not_stretch_steps(self):
        p=dict(C.DEFAULTS['Stair'],kind='Stair');sp,m=G.stair((2,3),(2,10),.15,p)
        self.assertAlmostEqual(P.point(m,(4.76,0,0))[1],7.76);self.assertEqual(sp['stair_params']['going'],.28)
        with self.assertRaises(ValueError):G.stair((0,0),(0,0),0,p)
