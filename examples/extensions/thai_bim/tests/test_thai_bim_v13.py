import copy,importlib,sys,types,unittest
from pathlib import Path
p=types.ModuleType('tb13pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
G=importlib.import_module('tb13pure.selected_geometry');E=importlib.import_module('tb13pure.engine');P=importlib.import_module('tb13pure.path_geometry');S=importlib.import_module('tb13pure.structures')
class InstanceGeometryTests(unittest.TestCase):
    def test_footing_and_column_centres_fixed(self):
        for kind in ('Footing','Column'):
            rec=E.box_spec(kind,2,3,-.4,1,1,3);sp=G.edit_spec(rec,dict(width=2,depth=3,height=4));q=sp['params']
            self.assertEqual((q['x']+q['width']/2,q['y']+q['depth']/2,q['z']),(2.5,3.5,-.4))
    def test_two_point_and_legacy_beam_keep_span_and_width_axis(self):
        for y in (0,-.1):
            r=E.box_spec('Beam',1,y,3,5,.2,.4);sp=G.edit_spec(r,dict(depth=.4,height=.6));q=sp['params']
            self.assertEqual((q['x'],q['width'],q['y']+q['depth']/2,q['z']),(1,5,y+.1,3))
    def test_rectangular_slab_only_thickness_changes(self):
        r=E.box_spec('Slab',2,3,4,6,5,.15);q=G.edit_spec(r,dict(height=.2))['params']
        self.assertEqual({k:q[k] for k in ('x','y','z','width','depth')},{k:r['params'][k] for k in ('x','y','z','width','depth')})
    def test_concave_slab_preserves_negative_local_outline(self):
        r,_=P.polygon([(5,5),(2,5),(2,2),(4,2),(4,4),(5,4)],3,dict(height=.15))
        sp=G.edit_spec(r,dict(height=.3));self.assertEqual(sp['params']['footprint'],r['params']['footprint']);self.assertAlmostEqual(sp['quantity'],r['quantity']*2)
    def test_stair_origin_kept_and_run_updates(self):
        r=S.stair_spec(x=2,y=3,z=4);v={k:r['stair_params'][k] for k in G.editable('Stair')};v['risers']=20
        q=G.edit_spec(r,v)['stair_params'];self.assertEqual((q['x'],q['y'],q['z']),(2,3,4));self.assertEqual(q['risers'],20)
    def test_invalid_dimensions_rejected_and_source_untouched(self):
        r=E.box_spec('Column',0,0,0,.2,.2,3);before=copy.deepcopy(r)
        for values in (dict(width=-1,depth=.2,height=3),dict(width=.2,depth=.2,height=float('nan')),dict(width=.2,depth=.2,height=3,unexpected=1)):
            with self.assertRaises(ValueError):G.edit_spec(r,values)
        self.assertEqual(r,before)
