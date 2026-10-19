import importlib,sys,types,unittest,copy,math
from pathlib import Path
p=types.ModuleType('tb21pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
G=importlib.import_module('tb21pure.shape_geometry');E=importlib.import_module('tb21pure.engine');P=importlib.import_module('tb21pure.placement');R=importlib.import_module('tb21pure.slab_rebar');S=importlib.import_module('tb21pure.stairs');SE=importlib.import_module('tb21pure.selected_geometry')
def slab():return E.box_spec('Slab',0,0,3,4,3,.2)['params']
def rec(kind='Slab',params=None):return dict(kind=kind,params=params or slab())
HOLE=[(1,1),(2,1),(2,2),(1,2)]
class ShapeTests(unittest.TestCase):
 def test_net_opening_concrete_volume(self):self.assertAlmostEqual(G.slab_spec(slab(),holes=[HOLE])['quantity'],2.2)
 def test_caps_have_native_hole_loops_and_internal_walls(self):
  sp=G.slab_spec(slab(),holes=[HOLE]);self.assertEqual(len(sp['face_holes'][0]),1);self.assertEqual(len(sp['faces']),10)
 def test_touching_opening_rejected(self):
  with self.assertRaises(ValueError):G.slab_spec(slab(),holes=[[(0,0),(1,0),(1,1),(0,1)]])
 def test_crossing_opening_rejected(self):
  with self.assertRaises(ValueError):G.slab_spec(slab(),holes=[[(-1,1),(1,1),(1,2),(-1,2)]])
 def test_nested_openings_rejected(self):
  with self.assertRaises(ValueError):G.slab_spec(slab(),holes=[HOLE,[(1.2,1.2),(1.8,1.2),(1.8,1.8),(1.2,1.8)]])
 def test_overlapping_openings_rejected(self):
  with self.assertRaises(ValueError):G.slab_spec(slab(),holes=[HOLE,[(1.5,1.5),(2.5,1.5),(2.5,2.5),(1.5,2.5)]])
 def test_disjoint_openings_allowed(self):self.assertEqual(len(G.slab_spec(slab(),holes=[HOLE,[(2.5,.5),(3.5,.5),(3.5,1.5),(2.5,1.5)]])['params']['holes']),2)
 def test_hole_crossing_concave_notch_rejected_even_corners_inside(self):
  poly=[(0,0),(4,0),(4,4),(3,4),(3,1),(1,1),(1,4),(0,4)]
  with self.assertRaises(ValueError):G.slab_spec(slab(),poly=poly,holes=[[(.5,2),(3.5,2),(3.5,3),(.5,3)]])
 def test_world_local_inverse_yaw_translation(self):
  m=P.matrix((5,7,3.75),37);q=(2,-3,4);r=G.inverse(m,P.point(m,q));self.assertTrue(all(abs(a-b)<1e-8 for a,b in zip(q,r)))
 def test_beam_end_changed_other_end_exactly_fixed(self):
  r=rec('Beam',E.box_spec('Beam',1,-.1,0,3,.2,.4)['params']);m=P.matrix((2,4,3.65),30);fixed=P.point(m,(1,0,0));new=(8,9,3.65);sp,pose=G.change(r,m,('beam',1),new)
  self.assertLess(math.dist(P.point(pose,(0,0,0)),fixed),1e-7);self.assertLess(math.dist(P.point(pose,(sp['params']['width'],0,0)),new),1e-7)
 def test_beam_start_changed_preserves_old_end(self):
  r=rec('Beam',E.box_spec('Beam',0,-.15,0,3,.3,.5)['params']);sp,m=G.change(r,None,('beam',0),(-1,1,0));self.assertLess(math.dist(P.point(m,(sp['params']['width'],0,0)),(3,0,0)),1e-7)
 def test_zero_length_beam_rejected(self):
  with self.assertRaises(ValueError):G.change(rec('Beam',E.box_spec('Beam',0,-.1,0,3,.2,.4)['params']),None,('beam',1),(0,0,0))
 def test_slab_vertex_moves_in_original_local_frame(self):
  sp,m=G.change(rec(),None,('vertex',0,0),(-1,-1,3.2));self.assertEqual(tuple(sp['params']['footprint'][0]),(-1,-1));self.assertEqual(m,P.IDENTITY)
 def test_slab_edge_translates_both_ends(self):
  sp,_=G.change(rec(),None,('edge',0,0),(2,-1,3.2));self.assertEqual(sp['params']['footprint'][:2],[(0,-1),(4,-1)])
 def test_slab_edit_keeps_other_vertices(self):
  sp,_=G.change(rec(),None,('vertex',0,1),(5,0,3.2));self.assertEqual(sp['params']['footprint'][2:],[(4,3),(0,3)])
 def test_slab_self_intersection_edit_rejected(self):
  with self.assertRaises(ValueError):G.change(rec(),None,('vertex',0,1),(-1,2,3.2))
 def test_opening_from_world_points_at_yaw_pose(self):
  m=P.matrix((5,4,.75),45);sp,_=G.add_opening(rec(),m,P.point(m,(1,1,3.2)),P.point(m,(2,2,3.2)));self.assertAlmostEqual(sp['quantity'],2.2)
 def test_opening_handle_ring_index(self):
  p=G.slab_spec(slab(),holes=[HOLE])['params'];h=G.handles(rec(params=p));self.assertEqual(sum(row['key'][1]==1 for row in h),8)
 def test_move_hole_vertex_keeps_outer_boundary(self):
  p=G.slab_spec(slab(),holes=[HOLE])['params'];sp,_=G.change(rec(params=p),None,('vertex',1,0),(.8,.8,3.2));self.assertEqual(sp['params']['footprint'],G.outline(p))
 def test_height_edit_preserves_holes_and_coordinate_frame(self):
  p=G.slab_spec(slab(),poly=[(-1,-1),(4,0),(4,3),(0,3)],holes=[HOLE])['params'];sp=SE.edit_spec(rec(params=p),dict(height=.3));self.assertEqual(sp['params']['footprint'],p['footprint']);self.assertEqual(sp['params']['holes'],p['holes'])
 def test_all_supported_landing_hands_change_shared_depth(self):
  for kind in ('Straight','L','U','Spiral','Circular'):
   for hand in ('Left','Right'):
    p=S.validated(dict(layout=kind,hand=hand));h=G.landing_handle(p);point=E.add(h['origin'],E.mul(h['axis'],1.7));sp,_=G.change(dict(kind='Stair',stair_params=p),None,h['key'],point);self.assertAlmostEqual(sp['stair_params']['landing_depth'],1.7)
 def test_floating_without_landing_rejected(self):
  with self.assertRaises(ValueError):G.landing_handle(dict(layout='Floating',risers=8,height=1.3))
 def test_landing_depth_below_width_rejected(self):
  p=S.defaults();h=G.landing_handle(p)
  with self.assertRaises(ValueError):G.change(dict(kind='Stair',stair_params=p),None,h['key'],E.add(h['origin'],E.mul(h['axis'],.3)))
 def test_one_way_two_way_and_mesh_paths_avoid_opening_with_cover(self):
  host=G.slab_spec(slab(),holes=[HOLE])['params']
  for mode in R.MODES:
   bars=R.generate(host,dict(mode=mode))
   for bar in bars:
    for a,b in zip(bar['bar_path'],bar['bar_path'][1:]):
     for i in range(21):
      point=E.add(a,E.mul(E.sub(b,a),i/20));self.assertFalse(G.inside(point[:2],HOLE));self.assertGreaterEqual(min(G.distance(point[:2],c,d) for c,d in zip(HOLE,HOLE[1:]+HOLE[:1])),.025-1e-7)
 def test_opening_shortens_net_bar_quantity(self):
  base=R.generate(slab(),{});opened=R.generate(G.slab_spec(slab(),holes=[HOLE])['params'],{});self.assertLess(sum(b['quantity'] for b in opened),sum(b['quantity'] for b in base))
 def test_precast_dowels_with_openings_rejected(self):
  with self.assertRaises(ValueError):R.generate(G.slab_spec(slab(),holes=[HOLE])['params'],dict(mode='Precast',dowels=True))
 def test_scaled_pose_rejected(self):
  m=list(P.IDENTITY);m[0]=2
  with self.assertRaises(ValueError):G.upright(m)
 def test_empty_boundary_rejected(self):
  with self.assertRaises(ValueError):G.slab_spec(slab(),poly=[])
if __name__=='__main__':unittest.main()
