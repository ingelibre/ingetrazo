import importlib,sys,types,unittest,math,copy
from pathlib import Path
p=types.ModuleType('tb20pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
G=importlib.import_module('tb20pure.member_drawing_geometry');D=importlib.import_module('tb20pure.stair_drawing_geometry');E=importlib.import_module('tb20pure.engine');P=importlib.import_module('tb20pure.path_geometry')
def sample(kind='Footing',x=0,y=0,z=-.4,w=1.2,d=1.2,h=.4):
 f=E.box_spec(kind,x,y,z,w,d,h)['faces'];t=[[a[0],a[i],a[i+1]] for a in f for i in range(1,len(a)-1)];return f,t
class MemberDrawingTests(unittest.TestCase):
 def test_four_member_kinds_have_plan_and_two_cuts(self):
  for k in G.KINDS:
   f,t=sample(k);v=G.concrete_views(k,f,t);self.assertEqual(len(v),3);self.assertTrue(all(q['cut'] for q in v))
 def test_footing_exact_width_depth_height(self):
  f,t=sample(w=1.4,d=1.8);v=G.concrete_views('Footing',f,t)
  self.assertEqual([round(math.dist(d['a'],d['b']),6) for d in v[0]['dims']],[1.4,1.8]);self.assertAlmostEqual(math.dist(v[1]['dims'][1]['a'],v[1]['dims'][1]['b']),.4)
 def test_column_exact_levels_and_height(self):
  f,t=sample('Column',z=.25,w=.3,d=.4,h=3);v=G.concrete_views('Column',f,t,base_z=3.5)
  self.assertEqual([q['z'] for q in v[1]['levels']],[3.75,6.75])
 def test_beam_local_length_and_cross_section(self):
  f,t=sample('Beam',y=-.15,z=0,w=4.5,d=.3,h=.6);v=G.concrete_views('Beam',f,t)
  self.assertAlmostEqual(math.dist(v[1]['dims'][0]['a'],v[1]['dims'][0]['b']),4.5);self.assertAlmostEqual(math.dist(v[2]['dims'][0]['a'],v[2]['dims'][0]['b']),.3)
 def test_negative_coordinate_geometry_measured(self):
  f,t=sample(x=-10,y=-8);self.assertAlmostEqual(math.dist(*[G.concrete_views('Footing',f,t)[0]['dims'][0][k] for k in ('a','b')]),1.2)
 def test_polygon_plan_preserves_reentrant_corner(self):
  sp,_=P.polygon([(0,0),(3,0),(3,1),(1,1),(1,3),(0,3)],0,dict(height=.2));f=sp['faces'];t=[[a[0],a[i],a[i+1]] for a in f for i in range(1,len(a)-1)]
  v=G.concrete_views('Slab',f,t);pts=[p for l in v[0]['lines'] if l.get('weight')==.4 for p in (l['a'],l['b'])]
  self.assertTrue(any(math.dist(p,(1,1))<1e-6 for p in pts))
 def test_outlines_no_coplanar_diagonals(self):
  f,t=sample();self.assertEqual(len(D.edges(f)),12)
 def test_empty_source_rejected(self):
  with self.assertRaises(ValueError):G.extents([])
 def test_invalid_kind_rejected(self):
  with self.assertRaises(ValueError):G.concrete_views('Wall',*sample())
 def test_plan_references_two_section_pages(self):
  v=G.concrete_views('Footing',*sample());self.assertEqual({q['text'] for q in v[0]['texts']},{'SEC-A / S002','SEC-B / S003'})
 def test_exact_three_physical_scales(self):
  v=G.concrete_views('Footing',*sample())[0]
  for n in D.SCALES:
   paper,pp=D.paper_view(v,D.options(scale=n));self.assertAlmostEqual(math.dist(pp((0,0)),pp((1,0))),1000/n)
 def test_oversize_beam_rejected_without_fit(self):
  v=G.concrete_views('Beam',*sample(w=20))[0]
  with self.assertRaises(ValueError):D.paper_view(v,D.options(scale=20))
 def test_vertical_representative_is_nominal_section_ring(self):
  bar=dict(uid='b',role='Main Z',path=[(0,0,0),(0,0,1)],bbs=dict(mark='B-1',diameter_mm=12,shape='Straight',length_m=1))
  rows=D.grouped_bars([bar]);v=G.concrete_views('Column',*sample('Column'));n=len(v[0]['lines']);G.add_representatives(v,rows,'A3',[bar]);self.assertEqual(len(v[0]['lines'])-n,12)
 def test_equal_marks_preserve_distinct_axis_representatives(self):
  a=dict(uid='x',role='Main X',path=[(0,0,0),(1,0,0)],bbs=dict(mark='B-1',diameter_mm=12,shape='Straight',length_m=1));b=dict(a,uid='y',role='Main Y',path=[(0,0,0),(0,1,0)])
  rows=D.grouped_bars([a,b]);v=G.concrete_views('Footing',*sample());G.add_representatives(v,rows,'A3',[a,b]);self.assertEqual(len(v[0]['labels']),2);self.assertNotEqual(v[0]['labels'][0]['point'],v[0]['labels'][1]['point']);self.assertEqual(len(rows),1)
if __name__=='__main__':unittest.main()
