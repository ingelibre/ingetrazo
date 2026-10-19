import importlib,math,sys,types,unittest
from pathlib import Path
p=types.ModuleType('tb17pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
G=importlib.import_module('tb17pure.stair_placement');S=importlib.import_module('tb17pure.stairs');P=importlib.import_module('tb17pure.placement')
class StairPlacementTests(unittest.TestCase):
    def test_all_forms_hands_anchor_exactly_at_first_point(self):
        for layout in S.LAYOUTS:
            for hand in ('Left','Right'):
                p=dict(layout=layout,hand=hand);m=G.pose(p,(7,-4,99),(9,0,-80),-.4)
                for a,b in zip(P.point(m,G.entrance(p)),(7,-4,-.4)):self.assertAlmostEqual(a,b)
    def test_initial_ascent_aligns_with_second_point(self):
        for layout in S.LAYOUTS:
            for hand in ('Left','Right'):
                for dx,dy in ((1,0),(0,1),(-1,0),(0,-1),(2,3)):
                    p=dict(layout=layout,hand=hand);m=G.pose(p,(0,0,0),(dx,dy,0),0);u=G.ascent(p);a=P.point(m,(0,0,0));b=P.point(m,u)
                    self.assertAlmostEqual(b[0]-a[0],dx/math.hypot(dx,dy));self.assertAlmostEqual(b[1]-a[1],dy/math.hypot(dx,dy))
    def test_direction_distance_does_not_change_size(self):
        self.assertEqual(G.pose({},(0,0,0),(1,0,0),0),G.pose({},(0,0,0),(90,0,80),0))
    def test_duplicate_point_rejected(self):
        with self.assertRaises(ValueError):G.pose({},(0,0,0),(0,0,30),0)
    def test_direction_distance_bounds(self):
        for x in (.049,100.01):
            with self.assertRaises(ValueError):G.pose({},(0,0,0),(x,0,0),0)
    def test_nonfinite_points_rejected(self):
        with self.assertRaises(ValueError):G.pose({},(math.nan,0,0),(1,0,0),0)
    def test_wrong_point_shape_rejected(self):
        with self.assertRaises(ValueError):G.pose({},(0,0),(1,0,0),0)
    def test_entrance_is_midpoint_not_centre_of_spiral(self):
        self.assertEqual(G.entrance(dict(layout='Spiral',inner_radius=.2,width=1)),(.7,0,0));self.assertEqual(G.entrance({}),(0,.5,0))
    def test_preview_edges_unique_and_nonzero(self):
        edges=G.edges(S.spec(layout='U'));self.assertTrue(edges);self.assertEqual(len(edges),len({tuple(sorted((a,b))) for a,b in edges}));self.assertTrue(all(a!=b for a,b in edges))
    def test_placement_is_upright_rigid(self):
        m=G.pose(dict(layout='Circular'),(7,8,9),(-1,2,3),4);self.assertEqual(P.rigid_matrix(m),m);self.assertEqual(m[8:11],[0,0,1])
if __name__=='__main__':unittest.main()
