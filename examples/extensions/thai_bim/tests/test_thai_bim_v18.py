import importlib,math,sys,types,unittest
from pathlib import Path
p=types.ModuleType('tb18pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
C=importlib.import_module('tb18pure.stair_connections');E=importlib.import_module('tb18pure.engine');P=importlib.import_module('tb18pure.placement')
def cube(x=0):
    faces=E.box_spec('Beam',x,0,0,1,1,1)['faces'];return [[f[0],f[i],f[i+1]] for f in faces for i in range(1,len(f)-1)]
def report(points,required=.2,tri=None):return C.inspect([dict(slot='a',path=points)],tri or cube(),required)['rows'][0]
class StairConnectionTests(unittest.TestCase):
    def test_crossing_clips_exact_inside_length(self):
        r=report([(-1,.5,.5),(2,.5,.5)]);self.assertAlmostEqual(r['inside_length_m'],1);self.assertEqual(r['state'],'geometry_length_met')
    def test_entirely_inside(self):self.assertAlmostEqual(report([(.1,.5,.5),(.9,.5,.5)])['inside_length_m'],.8)
    def test_outside(self):self.assertEqual(report([(-1,2,.5),(2,2,.5)])['state'],'no_entry')
    def test_surface_contact_excluded(self):
        r=report([(-1,0,.5),(2,0,.5)]);self.assertEqual(r['state'],'surface_contact_only');self.assertEqual(r['inside_length_m'],0);self.assertAlmostEqual(r['boundary_length_m'],1)
    def test_endpoint_touch_only(self):self.assertEqual(report([(-1,.5,.5),(0,.5,.5)])['state'],'surface_contact_only')
    def test_missing_required_input(self):self.assertEqual(report([(.1,.5,.5),(.9,.5,.5)],None)['state'],'requirement_missing')
    def test_short_interval(self):self.assertEqual(report([(.9,.5,.5),(2,.5,.5)],.2)['state'],'geometry_length_short')
    def test_disjoint_solids_use_longest_not_total(self):
        r=report([(-1,.5,.5),(4,.5,.5)],1.5,cube()+cube(2));self.assertAlmostEqual(r['inside_length_m'],2);self.assertAlmostEqual(r['longest_inside_m'],1);self.assertEqual(r['state'],'geometry_length_short');self.assertEqual(len(r['inside_intervals_m']),2)
    def test_crank_continuity_across_segments(self):
        r=report([(.1,.5,.5),(.5,.5,.5),(.5,.5,.9)],.7);self.assertAlmostEqual(r['longest_inside_m'],.8);self.assertEqual(len(r['inside_intervals_m']),1)
    def test_diagonal(self):self.assertAlmostEqual(report([(-1,-1,-1),(2,2,2)])['inside_length_m'],math.sqrt(3))
    def test_triangulation_edge_hit_deduplicated(self):self.assertEqual(C.classify((.5,.5,.5),cube()),'inside')
    def test_reversed_winding_same(self):self.assertAlmostEqual(report([(-1,.5,.5),(2,.5,.5)],tri=[list(reversed(t)) for t in cube()])['inside_length_m'],1)
    def test_world_rotation_preserves_lengths(self):
        m=P.matrix((4,3,2),37);tri=[[P.point(m,v) for v in t] for t in cube()];pts=[P.point(m,v) for v in [(-1,.5,.5),(2,.5,.5)]];self.assertAlmostEqual(report(pts,tri=tri)['inside_length_m'],1)
    def test_open_mesh_rejected(self):
        with self.assertRaises(ValueError):C.prepare(cube()[:-1])
    def test_degenerate_triangle(self):
        with self.assertRaises(ValueError):C.prepare(cube()+[[(0,0,0)]*3])
    def test_empty_paths(self):
        with self.assertRaises(ValueError):C.inspect([],cube())
    def test_nonfinite_path(self):
        with self.assertRaises(ValueError):report([(math.nan,0,0),(1,0,0)])
    def test_bad_required(self):
        with self.assertRaises(ValueError):report([(0,0,0),(1,0,0)],0)
    def test_not_design_verified(self):self.assertFalse(C.inspect([dict(slot='a',path=[(.1,.5,.5),(.9,.5,.5)])],cube())['design_verified'])
    def test_zero_length_segment_does_not_break_inside_continuity(self):self.assertAlmostEqual(report([(.1,.5,.5),(.1,.5,.5),(.9,.5,.5)])['longest_inside_m'],.8)
if __name__=='__main__':unittest.main()
