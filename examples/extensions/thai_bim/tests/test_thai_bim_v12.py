import copy,importlib,sys,types,unittest,json
from pathlib import Path
p=types.ModuleType('tb12pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
A=importlib.import_module('tb12pure.analytical');P=importlib.import_module('tb12pure.placement')
def source(uid,kind='Column',x=0,y=0,z=0,width=.2,depth=.2,height=3,pose=None):
    return dict(id=uid,native_uid=uid,name=uid,kind=kind,params=dict(x=x,y=y,z=z,width=width,depth=depth,height=height),pose=pose,geometry_hash='fixture')
class AnalyticalTests(unittest.TestCase):
    def test_centroid_axes_and_rigid_rotation(self):
        s=source('b','Beam',width=4,depth=.2,height=.4,pose=P.matrix((1,2,3),90));m=A.member(s)
        self.assertAlmostEqual(m['axis'][0][0],.9);self.assertEqual(m['axis'][1],[.9,6.,3.2]);self.assertAlmostEqual(m['section']['area_m2'],.08)
        self.assertAlmostEqual(m['section']['iy_m4'],.2*.4**3/12)
    def test_endpoint_internal_split_and_stable_ids(self):
        rows=[source('c',x=-.1,y=-.1),source('b','Beam',x=0,y=-.1,z=1.3,width=4,depth=.2,height=.4)]
        m=A.build(rows);self.assertEqual(len(m['elements']),3);self.assertEqual(len(m['nodes']),4);self.assertEqual(len(m['components']),1)
        n=A.build(list(reversed(rows)),previous=m);self.assertEqual(n['revision'],2);self.assertEqual(n['id'],m['id']);self.assertEqual(n['nodes'],m['nodes']);self.assertEqual(n['elements'],m['elements'])
    def test_near_joints_remain_separate(self):
        m=A.build([source('a'),source('b',z=3.005)])
        self.assertEqual(len(m['components']),2);self.assertTrue(any(r['code']=='near_joint' for r in m['issues']))
    def test_interior_crossing_is_diagnostic_only(self):
        rows=[source('a','Beam',x=-2,y=-.1,width=4),source('b','Beam',x=-2,y=-.1,width=4,pose=P.matrix((0,0,0),90))]
        m=A.build(rows);self.assertEqual(len(m['components']),2);self.assertTrue(any(r['code']=='interior_crossing' for r in m['issues']))
    def test_coincident_duplicate_and_unspecified_support(self):
        m=A.build([source('a'),source('b')]);self.assertTrue(any(i['code']=='duplicate_axis' for i in m['issues']));self.assertFalse(m['solver_ready']);self.assertEqual(m['supports'],[])
    def test_json_roundtrip_and_tampered_snapshot_rejected(self):
        m=A.build([source('a')]);self.assertEqual(A.validate(json.loads(json.dumps(m))),m)
        for key in ('nodes','source_digest','solver_ready'):
            bad=copy.deepcopy(m);bad[key]=[] if key=='nodes' else 'forged'
            with self.assertRaises(ValueError):A.validate(bad)
    def test_sources_immutable_and_source_stamp_changes(self):
        rows=[source('a')];before=copy.deepcopy(rows);m=A.build(rows);self.assertEqual(rows,before)
        rows[0]['pose']=P.matrix((1,0,0));self.assertNotEqual(A.build(rows)['source_digest'],m['source_digest'])
    def test_rejected_geometry_and_duplicate_identity(self):
        for rows in ([],[source('a'),source('a')],[source('a',kind='Slab')],[source('a',height=0)],[source('a',pose=[2,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])]):
            with self.assertRaises(ValueError):A.build(rows)
        with self.assertRaises(ValueError):A.build([source('a')],tolerance=1)
