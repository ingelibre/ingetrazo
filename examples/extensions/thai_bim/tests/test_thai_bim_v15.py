import copy,importlib,math,sys,types,unittest
from pathlib import Path
p=types.ModuleType('tb15pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
S=importlib.import_module('tb15pure.stairs');E=importlib.import_module('tb15pure.engine');C=importlib.import_module('tb15pure.steel')
G=importlib.import_module('tb15pure.selected_geometry')
class StairFormsTests(unittest.TestCase):
    def test_all_layouts_have_closed_positive_volume(self):
        for layout in S.LAYOUTS:
            with self.subTest(layout=layout):
                s=S.spec(layout=layout);self.assertGreater(s['quantity'],0);self.assertTrue(s['faces']);self.assertEqual(s['ifc'],'IfcStair')
    def test_straight_has_landing_parts(self):
        parts=S.parts({});self.assertEqual([p['kind'] for p in parts],['Flight','Landing','Landing'])
    def test_l_has_two_flights_and_turn(self):
        parts=S.parts(dict(layout='L'));fl=[p for p in parts if p['kind']=='Flight'];self.assertEqual([p['risers'] for p in fl],[9,9]);self.assertEqual(fl[1]['direction'],(0,1))
    def test_u_two_parallel_flights_and_gap(self):
        parts=S.parts(dict(layout='U'));fl=[p for p in parts if p['kind']=='Flight'];self.assertEqual(fl[1]['direction'],(-1,0));self.assertAlmostEqual(fl[1]['origin'][1],2.15)
    def test_right_hand_mirrors_volume_and_geometry(self):
        for layout in S.LAYOUTS:
            a=S.spec(layout=layout);b=S.spec(layout=layout,hand='Right');self.assertAlmostEqual(a['quantity'],b['quantity']);self.assertEqual(b['faces'][0],[(x,-y,z) for x,y,z in reversed(a['faces'][0])])
    def test_floating_tread_count_and_gaps(self):
        parts=S.parts(dict(layout='Floating'));self.assertEqual(len(parts),18);self.assertAlmostEqual(sum(S.volume(p['faces']) for p in parts),18*.28*.9*.12)
    def test_curved_shell_has_expected_inner_outer_radii(self):
        p=S.parts(dict(layout='Circular',inner_radius=1.5,sweep=180))[0]
        self.assertAlmostEqual(min(math.hypot(v[0],v[1]) for f in p['faces'] for v in f),1.5);self.assertAlmostEqual(max(math.hypot(v[0],v[1]) for f in p['faces'] for v in f),2.5)
    def test_landing_volume_sum_matches_host(self):
        p=S.parts(dict(layout='U'));self.assertAlmostEqual(sum(S.volume(v['faces']) for v in p),S.spec(layout='U')['quantity'])
    def test_inputs_immutable(self):
        p=S.defaults();r=S.rebar_defaults();a=copy.deepcopy(p);b=copy.deepcopy(r);S.spec(**p);S.reinforcement(p,r);self.assertEqual(p,a);self.assertEqual(r,b)
    def test_rc_straight_l_u_reinforcement_roles(self):
        for layout in ('Straight','L','U'):
            rs=S.reinforcement(dict(layout=layout),{});self.assertTrue(any('landing' in r['bbs']['stair_role'] for r in rs));self.assertTrue(any(r['bbs']['bend_degrees'] for r in rs));self.assertTrue(all(r['bbs']['stair_layout']==layout for r in rs))
    def test_one_flight_without_landings_no_outside_extensions(self):
        rs=S.reinforcement(dict(bottom_landing=False,top_landing=False),{});self.assertTrue(all(0<=p[0]<=18*.28 for r in rs for p in r['bar_path']))
    def test_helix_analytic_length_and_metadata(self):
        rs=S.reinforcement(dict(layout='Circular',inner_radius=1.5,sweep=180),dict(connection=0));r=next(r for r in rs if r['bbs']['shape']=='3D helix');b=r['bbs'];self.assertAlmostEqual(b['length_m'],b['helix_angle_rad']*math.sqrt(b['helix_radius_m']**2+b['helix_rise_per_radian']**2))
    def test_floating_bars_per_tread(self):
        rs=S.reinforcement(dict(layout='Floating'),{});self.assertEqual(len({r['bbs']['stair_role'].split(' Cantilever')[0] for r in rs if 'Cantilever' in r['bbs']['stair_role']}),18);self.assertTrue(any(p[1]<0 for r in rs for p in r['bar_path']))
    def test_right_bars_mirror(self):
        a=S.reinforcement(dict(layout='L'),{});b=S.reinforcement(dict(layout='L',hand='Right'),{});self.assertEqual([r['bar_path'] for r in b],[[(x,-y,z) for x,y,z in r['bar_path']] for r in a]);self.assertEqual([r['bbs'] for r in a],[r['bbs'] for r in b])
    def test_representations_preserve_bbs(self):
        for layout in ('L','Circular','Floating'):
            p=dict(layout=layout,inner_radius=1.5,sweep=180);a=S.reinforcement(p,dict(connection=0));b=S.reinforcement(p,dict(connection=0,representation='Full'));self.assertEqual([r['bbs'] for r in a],[r['bbs'] for r in b]);self.assertTrue(all(r['faces'] for r in b));self.assertTrue(all(not r['faces'] for r in a))
    def test_catalogue_nominal_diameter_guard(self):
        steel=C.selection(C.TIS_DB,'DB12','SD40');rs=S.reinforcement({},dict(main_steel=steel));self.assertTrue(any(r.get('steel')==steel for r in rs))
        with self.assertRaises(ValueError):S.reinforcement({},dict(main_steel=steel,diameter=.01))
    def test_invalid_geometry_rejected(self):
        for p in (dict(layout='bad'),dict(material_system='Steel'),dict(risers=2.5),dict(height=float('nan')),dict(layout='L',first_risers=1),dict(layout='U',first_risers=8),dict(landing_depth=.5),dict(landing_thickness=.1),dict(layout='Floating',tread_thickness=.2)):
            with self.subTest(p=p),self.assertRaises(ValueError):S.spec(**p)
    def test_curved_automatic_connection_blocked(self):
        with self.assertRaises(ValueError):S.reinforcement(dict(layout='Circular'),dict(connection=.2))
    def test_curved_thin_radial_space_rejected(self):
        with self.assertRaises(ValueError):S.reinforcement(dict(layout='Spiral',inner_radius=.1,waist=.08),dict(connection=0))
    def test_connection_does_not_fit_rejected(self):
        with self.assertRaises(ValueError):S.reinforcement(dict(layout='L'),dict(connection=1))
    def test_schema_and_material_system_persisted(self):
        p=S.spec(layout='L')['stair_params'];self.assertEqual(p['stair_schema'],2);self.assertEqual(p['material_system'],'RC')
    def test_advanced_geometry_adapter_preserves_layout(self):
        rec=S.spec(layout='U');p=rec['stair_params'];values={k:p[k] for k in G.editable('Stair')};values['height']=3.12;r=G.edit_spec(rec,values);self.assertEqual(r['stair_params']['layout'],'U');self.assertEqual(r['stair_params']['height'],3.12)
    def test_curved_has_tangent_landing_geometry_and_mats(self):
        parts=S.parts(dict(layout='Circular',inner_radius=1.5,sweep=180));self.assertEqual([p['kind'] for p in parts],['Curved','Landing','Landing']);bars=S.reinforcement(dict(layout='Circular',inner_radius=1.5,sweep=180),dict(connection=0));self.assertTrue(any('Top landing' in b['bbs']['stair_role'] for b in bars))
    def test_explicit_connections_repeated_and_leg_signed(self):
        row=dict(name='Wall joint',x=0,y=0,z=.5,angle=90,length=.4,leg=-.1,count=3,spacing=.15)
        rs=S.reinforcement(dict(layout='Circular',inner_radius=1.5,sweep=180),dict(connection=0,extra_connections=[row]));extra=[r for r in rs if r['slot'].startswith('explicit-')];self.assertEqual(len(extra),3);self.assertTrue(all(r['bbs']['bend_degrees']==[90] for r in extra));self.assertAlmostEqual(extra[1]['bar_path'][0][0],-.15)
    def test_invalid_explicit_pattern_rejected(self):
        row=dict(name='x',x=0,y=0,z=0,angle=0,length=.4,leg=.1,count=0,spacing=.15)
        with self.assertRaises(ValueError):S.reinforcement({},dict(extra_connections=[row]))
    def test_two_mat_thickness_guard(self):
        with self.assertRaises(ValueError):S.reinforcement({},dict(mats=2))
        self.assertTrue(S.reinforcement(dict(waist=.2,landing_thickness=.25),dict(mats=2)))
    def test_curve_topology_each_edge_has_two_faces(self):
        for layout in ('Spiral','Circular'):
            faces=S.parts(dict(layout=layout))[0]['faces'];edges={}
            for f in faces:
                for a,b in zip(f,f[1:]+f[:1]):
                    key=tuple(sorted(tuple(round(v,7) for v in p) for p in (a,b)));edges[key]=edges.get(key,0)+1
            self.assertEqual(set(edges.values()),{2})
