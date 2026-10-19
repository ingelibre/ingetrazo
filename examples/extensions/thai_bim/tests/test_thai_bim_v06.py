import importlib,sys,types,unittest,math
from pathlib import Path
package=types.ModuleType('tb06pure');package.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules['tb06pure']=package
E=importlib.import_module('tb06pure.engine');P=importlib.import_module('tb06pure.placement');D=importlib.import_module('tb06pure.detailing')

def volume(faces):return sum(E.dot(f[0],E.cross(f[i],f[i+1]))/6 for f in faces for i in range(1,len(f)-1))

class PlacementTests(unittest.TestCase):
    def test_anchor_and_rotation(self):
        for kind in ('Column','Footing','Beam','Slab'):
            s=P.member_spec(kind,2,1,.4);m=P.matrix((3,4,3.65),90);world=P.world_specs([s],m)[0]
            self.assertAlmostEqual(volume(world['faces']),.8,places=8)
            points=[p for f in world['faces'] for p in f]
            self.assertAlmostEqual(min(p[2] for p in points),3.65)
            if kind in ('Column','Footing'):
                self.assertAlmostEqual(min(p[0] for p in points),2.5);self.assertAlmostEqual(max(p[1] for p in points),5)
            else:self.assertAlmostEqual(min(p[0] for p in points),2);self.assertAlmostEqual(max(p[1] for p in points),6)
    def test_pose_validation(self):
        self.assertTrue(P.same_pose(None,P.IDENTITY))
        for index in (0,5,10,12,15):
            m=list(P.IDENTITY);m[index]=2
            with self.assertRaises(ValueError):P.rigid_matrix(m)
        mirror=list(P.IDENTITY);mirror[0]=-1
        with self.assertRaises(ValueError):P.rigid_matrix(mirror)
        with self.assertRaises(ValueError):P.rigid_matrix([float('nan')]*16)
        self.assertFalse(P.same_pose(P.matrix((0,0,0)),P.matrix((0,0,.001))))
    def test_rotated_bent_bar_length(self):
        s=D.bent_bar('U',[(0,0,.2),(0,0,0),(1,0,0),(1,0,.2)],.012,.024,'U-90')
        original=list(s['bar_path']);world=P.world_specs([s],P.matrix((-3,7,3.75),-32))[0]
        self.assertEqual(s['bar_path'],original);self.assertEqual(s['bbs'],world['bbs'])
        self.assertAlmostEqual(volume(s['faces']),volume(world['faces']),places=8)
        for a,b,x,y in zip(s['bar_path'],s['bar_path'][1:],world['bar_path'],world['bar_path'][1:]):self.assertAlmostEqual(E.norm(E.sub(b,a)),E.norm(E.sub(y,x)),places=9)
    def test_grid_priority_and_pixels(self):
        points=P.grid_points([0,3],[0,4],3.65);pixels=[(10,10),(100,10),(10,100),(100,100)]
        self.assertEqual(P.nearest_grid(points,pixels,[True]*4,(103,104)),points[3])
        self.assertIsNone(P.nearest_grid(points,pixels,[True]*4,(110,110)))
        self.assertIsNone(P.nearest_grid(points,pixels,[False]*4,(10,10)))
        for kind in P.NAMED_SNAPS:self.assertIsNone(P.nearest_grid(points,pixels,[True]*4,(10,10),kind))
    def test_grid_validation(self):
        with self.assertRaises(ValueError):P.grid_points(list(range(21)),list(range(20)),0)
        with self.assertRaises(ValueError):P.grid_points([],[],0)
        with self.assertRaises(ValueError):P.grid_points([0],[0],float('inf'))
        self.assertEqual(len(P.grid_points(list(range(20)),list(range(20)),0)),400)

if __name__=='__main__':unittest.main()
