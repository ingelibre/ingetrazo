import importlib,math,sys,types,unittest,copy
from pathlib import Path
p=types.ModuleType('tb19pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
G=importlib.import_module('tb19pure.stair_drawing_geometry');E=importlib.import_module('tb19pure.engine');S=importlib.import_module('tb19pure.stairs')
def box():
 f=E.box_spec('Beam',0,0,0,1,1,1)['faces'];return f,[[a[0],a[i],a[i+1]] for a in f for i in range(1,len(a)-1)]
def sample_bar():return dict(uid='bar',path=[(0,0,0),(1,0,0)],bbs=dict(mark='B-A',shape='Straight',length_m=1.,mass_kg=1.,diameter_mm=12,stair_role='Main'))
class StairDrawingTests(unittest.TestCase):
 def test_section_slices_cube_exact_plane(self):
  _,t=box();lines=G.slice_triangles(t,G.frame((0,.5,0),(1,0,0),(0,0,1)));pts=[p for a in lines for p in a];self.assertEqual(min(p[0] for p in pts),0);self.assertEqual(max(p[0] for p in pts),1);self.assertEqual(max(p[1] for p in pts),1)
 def test_empty_cut_outside_cube(self):self.assertEqual(G.slice_triangles(box()[1],G.frame((0,2,0),(1,0,0),(0,0,1))),[])
 def test_coplanar_triangle_diagonal_removed(self):self.assertEqual(len(G.edges([[(0,0,0),(1,0,0),(1,1,0)],[(0,0,0),(1,1,0),(0,1,0)]])),4)
 def test_cube_edges_preserved(self):self.assertEqual(len(G.edges(box()[0])),12)
 def test_section_count_layouts(self):
  for layout in S.LAYOUTS:
   for hand in ('Left','Right'):
    with self.subTest(layout=layout,hand=hand):self.assertEqual(len(G.section_frames(dict(layout=layout,hand=hand))),2 if layout in ('L','U') else 1)
 def test_right_section_plane_reflects_left(self):
  a=G.section_frames(dict(layout='L',hand='Left'));b=G.section_frames(dict(layout='L',hand='Right'));self.assertEqual(b[1][2]['origin'][1],-a[1][2]['origin'][1])
 def test_radial_angle_explicit(self):self.assertAlmostEqual(G.section_frames(dict(layout='Spiral'),0)[0][2]['u'][0],1)
 def test_frame_orthographic_coordinates(self):self.assertEqual(G.project(G.frame((2,3,4),(0,1,0),(0,0,1)),(7,5,8)),(2,4))
 def test_scale_choices(self):
  v=dict(title='test',lines=[dict(a=(0,0),b=(1,0))],dims=[],texts=[],levels=[])
  for n in G.SCALES:
   _,f=G.paper_view(v,G.options(scale=n));self.assertAlmostEqual(math.dist(f((0,0)),f((1,0))),1000/n)
 def test_exact_paper_sizes(self):self.assertEqual(G.PAPERS['A1'],(841,594))
 def test_clip_rejected_not_silently_fit(self):
  v=dict(title='test',lines=[dict(a=(0,0),b=(20,0))],dims=[],texts=[],levels=[])
  with self.assertRaises(ValueError):G.paper_view(v,G.options(scale=20))
 def test_larger_sheet_accepts_requested_scale(self):
  v=dict(title='test',lines=[dict(a=(0,0),b=(10,0))],dims=[],texts=[],levels=[]);G.paper_view(v,G.options(paper='A0',scale=20))
 def test_unknown_scale_rejected(self):
  with self.assertRaises(ValueError):G.options(scale=40)
 def test_unknown_paper_rejected(self):
  with self.assertRaises(ValueError):G.options(paper='Letter')
 def test_empty_project_rejected(self):
  with self.assertRaises(ValueError):G.options(name='')
 def test_nonfinite_angle_rejected(self):
  with self.assertRaises(ValueError):G.options(angle=math.inf)
 def test_native_mark_counts_preserved(self):
  a=sample_bar();b=dict(a,uid='bar2');r=G.grouped_bars([a,b]);self.assertEqual(r[0]['mark'],'B-A');self.assertEqual(r[0]['uids'],['bar','bar2'])
 def test_descriptor_roundoff_does_not_split_identical_marks(self):
  a=sample_bar();b=copy.deepcopy(a);b['bbs']['length_m']+=1e-14;self.assertEqual(len(G.grouped_bars([a,b])[0]['uids']),2)
 def test_conflicting_mark_descriptor_rejected(self):
  a=sample_bar();b=copy.deepcopy(a);b['bbs']['length_m']=2
  with self.assertRaises(ValueError):G.grouped_bars([a,b])
 def test_planar_bar_true_shape_plane(self):
  b=G.grouped_bars([sample_bar()])[0];v=G.detail_views([b]);self.assertEqual(len(v),1);self.assertAlmostEqual(math.dist(v[0]['lines'][0]['a'],v[0]['lines'][0]['b']),1)
 def test_spatial_bar_two_views(self):
  b=sample_bar();b['path']=[(0,0,0),(1,0,0),(1,1,0),(0,1,1)];v=G.detail_views(G.grouped_bars([b]));self.assertEqual(len(v),2);self.assertTrue(all(q['spatial'] for q in v))
 def test_landing_dimensions_and_step_numbering(self):
  p=S.defaults();sp=S.spec(**p);faces=sp['faces'];tri=[[f[0],f[i],f[i+1]] for f in faces for i in range(1,len(f)-1)];v=G.concrete_views(p,faces,tri);self.assertEqual(len(v[0]['texts']),18+1+2);self.assertGreaterEqual(len(v[0]['dims']),4)
 def test_level_uses_base_elevation(self):
  f,t=box();v=G.concrete_views(S.defaults(),f,t,base_z=3.75);self.assertEqual([r['z'] for r in v[1]['levels']],[3.75,6.75])
if __name__=='__main__':unittest.main()
