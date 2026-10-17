import copy,importlib,math,sys,types,unittest
from pathlib import Path
p=types.ModuleType('tb14pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
R=importlib.import_module('tb14pure.slab_rebar');E=importlib.import_module('tb14pure.engine');P=importlib.import_module('tb14pure.path_geometry');C=importlib.import_module('tb14pure.steel');D=importlib.import_module('tb14pure.detailing')
class SlabDetailTests(unittest.TestCase):
    def host(self):return E.box_spec('Slab',2,3,4,3,2,.18)['params']
    def test_one_way_roles_and_direction(self):
        s=R.generate(self.host(),{});self.assertEqual({r['bbs']['slab_role'] for r in s},{'Main Bottom','Distribution Bottom'})
        for r in s:
            a,b=r['bar_path'];self.assertEqual(a[1] if r['bbs']['slab_role']=='Main Bottom' else a[0],b[1] if r['bbs']['slab_role']=='Main Bottom' else b[0])
    def test_axis_y_switches_main(self):
        s=R.generate(self.host(),dict(axis='Y'));r=next(r for r in s if r['bbs']['slab_role']=='Main Bottom');self.assertEqual(r['bar_path'][0][0],r['bar_path'][-1][0])
    def test_two_way_top_and_bottom(self):
        s=R.generate(self.host(),dict(mode='Two-way',mats=2));self.assertEqual(len({r['bbs']['slab_role'] for r in s}),4)
    def test_crossing_mats_touch_without_overlap(self):
        s=R.generate(self.host(),{});a=next(r for r in s if r['bbs']['slab_role']=='Main Bottom');b=next(r for r in s if r['bbs']['slab_role']=='Distribution Bottom')
        self.assertAlmostEqual(b['bar_path'][0][2]-a['bar_path'][0][2],(a['bar_diameter']+b['bar_diameter'])/2)
    def test_rectangle_cover_at_both_ends(self):
        s=R.generate(self.host(),{})
        for r in s:
            c=.025+r['bar_diameter']/2
            for x,y,z in r['bar_path']:self.assertTrue(2+c-1e-8<=x<=5-c+1e-8 and 3+c-1e-8<=y<=5-c+1e-8)
    def test_concave_intervals_split(self):
        poly=[(0,0),(3,0),(3,3),(2,3),(2,1),(1,1),(1,3),(0,3)]
        self.assertEqual(len(R.clipped(poly,(1,0),2,.05)),2)
    def test_reentrant_corner_exact_radius(self):
        poly=[(0,0),(3,0),(3,3),(2,3),(2,1),(1,1),(1,3),(0,3)]
        ints=R.clipped(poly,(1,0),.98,.05);self.assertEqual(len(ints),2)
        self.assertAlmostEqual(ints[0][1],1-math.sqrt(.05**2-.02**2),places=7)
    def test_polygon_negative_local_and_source_unchanged(self):
        sp,_=P.polygon([(5,5),(2,5),(2,2),(4,2),(4,4),(5,4)],3,dict(height=.18));h=sp['params'];before=copy.deepcopy(h);s=R.generate(h,{})
        self.assertEqual(h,before);self.assertTrue(any(p[0]<0 for r in s for p in r['bar_path']))
        for r in s:
            a,b=r['bar_path']
            for i in range(21):self.assertTrue(R.inside((a[0]+(b[0]-a[0])*i/20,a[1]+(b[1]-a[1])*i/20),R.boundary(h)))
    def test_rotated_polygon_clearance(self):
        poly=[(0,0),(3,1),(2,3),(-1,2)];sp,_=P.polygon(poly,0,dict(height=.18));s=R.generate(sp['params'],dict(axis='Y'))
        for r in s:
            for pt in r['bar_path']:self.assertTrue(R.inside(pt[:2],R.boundary(sp['params'])))
    def test_mesh_small_diameter_and_qto(self):
        s=R.generate(self.host(),dict(mode='Precast',wire_a=.002,wire_b=.003));self.assertTrue(all(r['bbs']['wire'] for r in s));self.assertEqual({r['bar_diameter'] for r in s},{.002,.003})
        for r in s:self.assertAlmostEqual(r['bbs']['mass_kg'],r['quantity']*math.pi*r['bar_diameter']**2/4*7850)
    def test_small_rebar_still_rejected(self):
        with self.assertRaises(ValueError):D.bent_bar('x',[(0,0,0),(1,0,0)],.003)
    def test_precast_dowel_both_ends(self):
        s=R.generate(self.host(),dict(mode='Precast',dowels=True));self.assertEqual({r['bbs']['slab_role'] for r in s},{'Wire mesh A','Wire mesh B','End dowel Start','End dowel End'})
        d=next(r for r in s if r['bbs']['slab_role']=='End dowel Start');self.assertAlmostEqual(d['quantity'],.5);self.assertAlmostEqual(d['bar_path'][0][0],1.8)
    def test_precast_end_axis_y(self):
        s=R.generate(self.host(),dict(mode='Precast',dowels=True,axis='Y',dowel_ends='End'));d=next(r for r in s if 'dowel' in r['bbs']['slab_role']);self.assertAlmostEqual(d['bar_path'][0][1],5.2)
    def test_l_dowel_analytic_bend(self):
        s=R.generate(self.host(),dict(mode='Precast',dowels=True,dowel_shape='L',topping=.12,dowel_leg=.06));d=next(r for r in s if 'dowel' in r['bbs']['slab_role']);self.assertEqual(d['bbs']['bend_degrees'],[90]);self.assertLess(d['quantity'],.56)
    def test_representations_same_length_mass(self):
        s=[R.generate(self.host(),dict(mode='Precast',dowels=True,representation=rep)) for rep in ('Full','Lightweight','Centreline')]
        self.assertEqual([r['bbs'] for r in s[0]],[r['bbs'] for r in s[1]]);self.assertEqual([r['bbs'] for r in s[0]],[r['bbs'] for r in s[2]]);self.assertFalse(any(r['faces'] for r in s[2]))
    def test_catalogue_tag_preserved(self):
        steel=C.selection(C.TIS_DB,'DB12','SD40');s=R.generate(self.host(),dict(steel_a=steel));self.assertEqual(next(r for r in s if 'Main' in r['item'])['steel'],steel)
    def test_invalid_config_rejected(self):
        for p in (dict(mode='bad'),dict(axis='Z'),dict(mats=3),dict(cover=.2),dict(spacing_a=0),dict(wire_a=.001),dict(diameter_a=float('nan')),dict(unexpected=1)):
            with self.subTest(p=p),self.assertRaises(ValueError):R.generate(self.host(),p)
    def test_thin_cover_and_mats_rejected(self):
        h=self.host();h['height']=.08
        with self.assertRaises(ValueError):R.generate(h,dict(mats=2))
    def test_mesh_topping_collision_rejected(self):
        with self.assertRaises(ValueError):R.generate(self.host(),dict(mode='Precast',topping=.03))
    def test_dowel_overlap_with_mesh_rejected(self):
        with self.assertRaises(ValueError):R.generate(self.host(),dict(mode='Precast',dowels=True,topping=.05))
    def test_opposing_dowels_overlap_rejected(self):
        with self.assertRaises(ValueError):R.generate(self.host(),dict(mode='Precast',dowels=True,dowel_embed=2))
    def test_polygon_mesh_supported_dowels_explicitly_blocked(self):
        sp,_=P.polygon([(0,0),(3,0),(3,1),(1,1),(1,3),(0,3)],0,dict(height=.18));self.assertTrue(R.generate(sp['params'],dict(mode='Precast')))
        with self.assertRaises(ValueError):R.generate(sp['params'],dict(mode='Precast',dowels=True))
    def test_spacing_does_not_exceed_requested(self):
        rows=R.rows(.03,2.93,.2);self.assertLessEqual(max(b-a for a,b in zip(rows,rows[1:])),.2+1e-9)
    def test_openings_rejected(self):
        h=self.host();h['holes']=[[(0,0),(1,0),(0,1)]]
        with self.assertRaises(ValueError):R.generate(h,{})
