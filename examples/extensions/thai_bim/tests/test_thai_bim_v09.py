import importlib,sys,types,unittest,math
from pathlib import Path
p=types.ModuleType('tb09pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
L=importlib.import_module('tb09pure.drawing_layout')
class V09Tests(unittest.TestCase):
    def cfg(self,**kw):
        p=dict(bounds=([0,0,0],[6,4,4.8]),grid_x=[0,3,6],grid_y=[0,4],levels=[dict(name='Ground',z=0),dict(name='Upper FFL',z=3.75),dict(name='Upper structure',z=3.65)])
        return L.config(**{**p,**kw})
    def test_exact_scale_projection_all_views(self):
        cfg=self.cfg()
        for s in cfg['sheets']:
            a=list(s['target']);b=list(a);b[s['axes'][0]]+=1
            self.assertAlmostEqual(math.dist(L.project(s,a),L.project(s,b)),20)
            b=list(a);b[s['axes'][1]]+=1
            self.assertAlmostEqual(L.project(s,b)[1]-L.project(s,a)[1],-20)
    def test_no_silent_rescale_and_large_paper(self):
        with self.assertRaisesRegex(ValueError,'clip'):self.cfg(bounds=([0,0,0],[9,14,8]))
        self.assertEqual(self.cfg(bounds=([0,0,0],[9,14,8]),paper='A1')['scale'],50)
        with self.assertRaises(ValueError):self.cfg(bounds=([0,0,0],[100,100,100]),paper='A0')
    def test_world_origin_and_negative_levels(self):
        cfg=self.cfg(bounds=([-6,-4,-2],[0,0,3]),grid_x=[-6,-3,0],grid_y=[-4,0],levels=[dict(name='Base',z=-2)],cut_z=0,section_x=-3,datum=-2)
        for s in cfg['sheets']:
            x,y,w,h=s['frame'];self.assertEqual(L.project(s,s['target']),(x+w/2,y+h/2))
        self.assertEqual(cfg['datum'],-2)
    def test_reject_invalid_and_duplicate_inputs(self):
        for opts in [dict(grid_x=[]),dict(grid_y=[0]),dict(cut_z=99),dict(section_x=99),dict(views=[]),dict(views=['plan','plan']),dict(levels=[dict(name='a',z=0),dict(name='a',z=1)]),dict(grid_x=[0,float('nan')]),dict(paper='A4')]:
            with self.assertRaises(ValueError):self.cfg(**opts)
    def test_close_levels_separate_without_changing_model_z(self):
        cfg=self.cfg();s=next(s for s in cfg['sheets'] if s['key']=='front');ls=L.level_positions(s,cfg['levels'])
        self.assertTrue(all(b[2]-a[2]>=7 for a,b in zip(ls,ls[1:])))
        self.assertEqual([v[0]['z'] for v in ls],[3.75,3.65,0])
        for level,py,_ in ls:
            p=list(s['target']);p[2]=level['z'];self.assertEqual(py,L.project(s,p)[1])
    def test_grid_labels_beyond_z(self):
        self.assertEqual([L.grid_label(i) for i in (0,25,26,27,51,52)],['A','Z','AA','AB','AZ','BA'])
if __name__=='__main__':unittest.main()
